# SPDX-License-Identifier: Apache-2.0
"""Neuron steering: nudge individual MLP neurons at inference time.

A playful, fully reversible interpretability knob. When enabled for a model,
the engine installs lightweight wrappers on the MLP ``down_proj`` of chosen
decoder layers that modify a single intermediate ("neuron") activation before
the down projection runs. Nothing is written to disk and no weights are
changed: the wrapper only rewrites the activation flowing through it, so a
plain reload with the toggle off restores the original model exactly.

The intermediate fed to ``down_proj`` is ``h = silu(gate(x)) * up(x)`` in a
SwiGLU MLP; coordinate ``n`` of ``h`` is neuron ``n``. Two steering schemes are
offered:

* ``constant`` -- pin ``h[..., n] = value`` at every token. Direct and strong;
  larger magnitudes can hurt coherence.
* ``scaled`` -- add ``value * ||h_token|| / ||W_down[:, n]||`` to ``h[..., n]``,
  i.e. a context-sensitive dose expressed in units of this neuron's write
  strength to the residual stream, scaled per token by the activation norm.
  Gentler on general capability than a hard pin.

Spec format (one steering op per entry, comma- or newline-separated)::

    layer:neuron:value[:mode]

Fields may also be separated by whitespace, and ``layer`` / ``neuron`` may
carry an ``L`` / ``N`` prefix, so ``23:4769:0.8`` and ``L23 N4769 +0.8`` are
the same op. ``value`` is required; ``mode`` defaults to ``scaled``.

This is a neutral activation-steering tool: the same mechanism shifts tone,
style or any other neuron-encoded behaviour. It ships with no presets.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

import mlx.core as mx

logger = logging.getLogger(__name__)

VALID_MODES = ("constant", "scaled")
_DEFAULT_MODE = "scaled"
_LAYER_RE = re.compile(r"[Ll]?(\d+)")
_NEURON_RE = re.compile(r"[Nn]?(\d+)")
_INSTALL_ATTR = "_omlx_steer_state"
# Engines append this to the prefix-cache model name, so KV computed with
# steering never serves an unsteered request (or a different spec).
SIGNATURE_ATTR = "_omlx_neuron_steering_signature"


@dataclass(frozen=True)
class SteerOp:
    """A single neuron steering instruction."""

    layer: int
    neuron: int
    mode: str  # "constant" | "scaled"
    value: float


def parse_steering_spec(spec: str | None) -> list[SteerOp]:
    """Parse a steering spec string into a list of :class:`SteerOp`.

    Entries are separated by ``,`` or newlines; the fields of an entry by
    ``:`` or whitespace, so ``23:4769:0.8`` and ``L23 N4769 +0.8`` are the
    same op. Raises ``ValueError`` with a specific message on a malformed
    entry so the admin UI can surface it, rather than silently dropping it.
    """
    if not spec or not spec.strip():
        return []

    ops: list[SteerOp] = []
    for entry in (e.strip() for e in re.split(r"[,\n]", spec)):
        if not entry:
            continue
        parts = re.split(r"[:\s]+", entry)
        if len(parts) == 2:
            raise ValueError(
                f"steering entry '{entry}' needs a value, as in 'L23 N4769 0.8'"
            )
        if len(parts) < 2 or len(parts) > 4:
            raise ValueError(
                f"steering entry '{entry}' must be 'layer:neuron:value[:mode]'"
            )
        layer = _LAYER_RE.fullmatch(parts[0])
        neuron = _NEURON_RE.fullmatch(parts[1])
        if layer is None or neuron is None:
            raise ValueError(
                f"steering entry '{entry}': layer and neuron must be "
                "non-negative integers, optionally written L23 and N4769"
            )
        if parts[2].lower() in VALID_MODES:
            raise ValueError(
                f"steering entry '{entry}': the value comes before the mode, "
                "as in 'layer:neuron:value:mode'"
            )
        try:
            value = float(parts[2])
        except ValueError:
            raise ValueError(
                f"steering entry '{entry}': value must be a number"
            ) from None
        if not math.isfinite(value):
            raise ValueError(f"steering entry '{entry}': value must be finite")
        mode = parts[3].lower() if len(parts) == 4 else _DEFAULT_MODE
        if mode not in VALID_MODES:
            raise ValueError(
                f"steering entry '{entry}': mode must be one of {VALID_MODES}"
            )
        ops.append(
            SteerOp(
                layer=int(layer.group(1)),
                neuron=int(neuron.group(1)),
                mode=mode,
                value=value,
            )
        )
    return ops


def _find_decoder_layers(model: Any) -> list | None:
    """Return the list of transformer decoder blocks across common layouts.

    Handles mlx_lm (``model.model.layers``) and mlx_vlm
    (``model.language_model.model.layers`` / ``.language_model.layers``) nests.
    A block qualifies only if it carries a SwiGLU-style ``mlp.down_proj``.
    """
    candidates = [
        model,
        getattr(model, "model", None),
        getattr(model, "language_model", None),
        getattr(getattr(model, "language_model", None), "model", None),
    ]
    for base in candidates:
        if base is None:
            continue
        layers = getattr(base, "layers", None)
        if not isinstance(layers, (list, tuple)) or not layers:
            continue
        first = layers[0]
        mlp = getattr(first, "mlp", None)
        if mlp is not None and hasattr(mlp, "down_proj"):
            return list(layers)
    return None


def _down_proj_weight_norms(down_proj: Any) -> mx.array | None:
    """Per-neuron L2 norm of ``W_down`` columns, dequantizing if needed.

    ``W_down`` has shape ``(dim, d_ff)``; neuron ``n`` is column ``n`` and its
    norm measures how strongly the neuron writes to the residual stream.
    Returns a ``(d_ff,)`` array, or ``None`` if the weight is unreadable.
    """
    weight = getattr(down_proj, "weight", None)
    if weight is None:
        return None
    if hasattr(down_proj, "bits") and hasattr(down_proj, "scales"):
        try:
            weight = mx.dequantize(
                weight,
                down_proj.scales,
                getattr(down_proj, "biases", None),
                down_proj.group_size,
                down_proj.bits,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("neuron steering: dequantize failed: %s", exc)
            return None
    if weight.ndim != 2:
        return None
    return mx.sqrt(mx.sum(weight.astype(mx.float32) ** 2, axis=0))


class _SteerState:
    """Plain (non-Module) holder so mlx never treats these as parameters."""

    __slots__ = ("orig_class", "pin_mask", "pin_vals", "scaled_vec", "has_scaled")

    def __init__(self, orig_class, pin_mask, pin_vals, scaled_vec, has_scaled):
        self.orig_class = orig_class
        self.pin_mask = pin_mask
        self.pin_vals = pin_vals
        self.scaled_vec = scaled_vec
        self.has_scaled = has_scaled


_STEERED_CLASS_CACHE: dict[type, type] = {}


def _steered_class(orig_class: type) -> type:
    """Build (once per base linear type) a subclass whose call steers input."""
    cached = _STEERED_CLASS_CACHE.get(orig_class)
    if cached is not None:
        return cached

    def __call__(self, x, *args, **kwargs):  # noqa: N807
        state: _SteerState = getattr(self, _INSTALL_ATTR)
        if state.has_scaled:
            tok_norm = mx.sqrt(mx.sum(x.astype(mx.float32) ** 2, axis=-1))
            x = x + (tok_norm[..., None] * state.scaled_vec).astype(x.dtype)
        if state.pin_mask is not None:
            x = mx.where(state.pin_mask, state.pin_vals.astype(x.dtype), x)
        return state.orig_class.__call__(self, x, *args, **kwargs)

    steered = type(
        f"Steered{orig_class.__name__}",
        (orig_class,),
        {"__call__": __call__},
    )
    _STEERED_CLASS_CACHE[orig_class] = steered
    return steered


def apply_neuron_steering(
    model: Any,
    spec: str | None,
    *,
    enabled: bool = True,
) -> int:
    """Install neuron steering on ``model`` in place. Returns neurons steered.

    No-op (returns 0) when disabled, when the spec is empty, or when the model
    has no discoverable SwiGLU decoder layers. Out-of-range or dead-neuron ops
    are skipped with a warning rather than failing the load.
    """
    if not enabled:
        return 0
    ops = parse_steering_spec(spec)
    if not ops:
        return 0
    layers = _find_decoder_layers(model)
    if layers is None:
        logger.warning(
            "neuron steering requested but no SwiGLU decoder layers were found; "
            "this model architecture is not supported"
        )
        return 0

    by_layer: dict[int, list[SteerOp]] = {}
    for op in ops:
        if op.layer >= len(layers):
            logger.warning(
                "neuron steering: layer %d out of range (model has %d layers); "
                "skipping",
                op.layer,
                len(layers),
            )
            continue
        by_layer.setdefault(op.layer, []).append(op)

    steered = 0
    applied: list[SteerOp] = []
    for layer_idx, layer_ops in by_layer.items():
        mlp = getattr(layers[layer_idx], "mlp", None)
        down_proj = getattr(mlp, "down_proj", None) if mlp is not None else None
        if down_proj is None:
            continue
        wnorm = _down_proj_weight_norms(down_proj)
        if wnorm is None:
            logger.warning(
                "neuron steering: cannot read down_proj weights at layer %d; "
                "skipping",
                layer_idx,
            )
            continue
        d_ff = int(wnorm.shape[0])

        pin_idx: list[int] = []
        pin_val: list[float] = []
        scaled = mx.zeros((d_ff,), dtype=mx.float32)
        has_scaled = False
        for op in layer_ops:
            if op.neuron >= d_ff:
                logger.warning(
                    "neuron steering: neuron %d out of range at layer %d "
                    "(d_ff=%d); skipping",
                    op.neuron,
                    layer_idx,
                    d_ff,
                )
                continue
            if op.mode == "constant":
                pin_idx.append(op.neuron)
                pin_val.append(op.value)
                applied.append(op)
                steered += 1
            else:  # scaled
                wn = float(wnorm[op.neuron])
                if wn <= 0.0:
                    logger.warning(
                        "neuron steering: neuron %d at layer %d has zero weight "
                        "norm (dead neuron); skipping",
                        op.neuron,
                        layer_idx,
                    )
                    continue
                scaled = scaled.at[mx.array([op.neuron])].add(
                    mx.array([op.value / wn], dtype=mx.float32)
                )
                has_scaled = True
                applied.append(op)
                steered += 1

        if not pin_idx and not has_scaled:
            continue

        pin_mask = None
        pin_vals = None
        if pin_idx:
            mask = mx.zeros((d_ff,), dtype=mx.bool_)
            mask = mask.at[mx.array(pin_idx)].add(
                mx.ones((len(pin_idx),), dtype=mx.bool_)
            )
            vals = mx.zeros((d_ff,), dtype=mx.float32)
            vals = vals.at[mx.array(pin_idx)].add(mx.array(pin_val, dtype=mx.float32))
            pin_mask = mask
            pin_vals = vals

        # Engines install on a loader thread and decode on another; a lazy
        # array is bound to the stream of the thread that built it.
        mx.eval([a for a in (scaled, pin_mask, pin_vals) if a is not None])

        orig_class = type(down_proj)
        state = _SteerState(orig_class, pin_mask, pin_vals, scaled, has_scaled)
        object.__setattr__(down_proj, _INSTALL_ATTR, state)
        down_proj.__class__ = _steered_class(orig_class)

    if steered:
        key = sorted((o.layer, o.neuron, o.mode, o.value) for o in applied)
        digest = hashlib.sha256(repr(key).encode()).hexdigest()
        setattr(model, SIGNATURE_ATTR, "steer-" + digest[:12])
        logger.info(
            "neuron steering active: %d neuron(s) across %d layer(s)",
            steered,
            len(by_layer),
        )
    return steered


def remove_neuron_steering(model: Any) -> int:
    """Restore any steered ``down_proj`` modules. Returns count restored."""
    if getattr(model, SIGNATURE_ATTR, None) is not None:
        delattr(model, SIGNATURE_ATTR)
    layers = _find_decoder_layers(model)
    if layers is None:
        return 0
    restored = 0
    for layer in layers:
        mlp = getattr(layer, "mlp", None)
        down_proj = getattr(mlp, "down_proj", None) if mlp is not None else None
        if down_proj is None:
            continue
        state = getattr(down_proj, _INSTALL_ATTR, None)
        if state is None:
            continue
        down_proj.__class__ = state.orig_class
        object.__delattr__(down_proj, _INSTALL_ATTR)
        restored += 1
    return restored
