# SPDX-License-Identifier: Apache-2.0
"""Tests for omlx.neuron_steering (reversible per-neuron activation nudging)."""

import mlx.core as mx
import mlx.nn as nn
import pytest

from omlx.model_settings import ModelSettings
from omlx.neuron_steering import (
    SIGNATURE_ATTR,
    SteerOp,
    apply_neuron_steering,
    parse_steering_spec,
    remove_neuron_steering,
)

# --- spec parsing -----------------------------------------------------------


def test_parse_empty_returns_no_ops():
    assert parse_steering_spec(None) == []
    assert parse_steering_spec("") == []
    assert parse_steering_spec("   \n  ") == []


def test_parse_full_entry_and_defaults():
    ops = parse_steering_spec("14:8949:1.0, 13:7956:-2:constant")
    assert ops == [
        SteerOp(layer=14, neuron=8949, mode="scaled", value=1.0),
        SteerOp(layer=13, neuron=7956, mode="constant", value=-2.0),
    ]
    # mode is optional and defaults to scaled
    assert parse_steering_spec("3:4:0.5") == [SteerOp(3, 4, "scaled", 0.5)]
    # newlines are accepted as separators
    assert len(parse_steering_spec("1:2:1\n3:4:1")) == 2


def test_parse_accepts_l_n_prefixes_and_whitespace():
    want = [SteerOp(23, 4769, "scaled", 0.8)]
    assert parse_steering_spec("L23 N4769 +0.8") == want
    assert parse_steering_spec("l23:n4769:0.8") == want
    assert parse_steering_spec("  L23  N4769  0.8  SCALED ") == want
    assert parse_steering_spec("L23 N4769 0.8 constant, 1:2:-1") == [
        SteerOp(23, 4769, "constant", 0.8),
        SteerOp(1, 2, "scaled", -1.0),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "x:1",
        "1",
        "1:2:bogus",
        "1:2:0.5:bogus",
        "1:2:nan",
        "1:2:inf",
        "-1:2",
        "1:-2",
        "N1:L2",
        "1:2:3:scaled:4",
    ],
)
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_steering_spec(bad)


def test_parse_requires_a_value():
    with pytest.raises(ValueError, match="needs a value"):
        parse_steering_spec("L23 N4769")


def test_parse_rejects_the_mode_before_the_value():
    with pytest.raises(ValueError, match="value comes before the mode"):
        parse_steering_spec("14:8949:scaled:1.0")


# --- toy SwiGLU model mirroring the mlx_lm nesting model.model.layers[*] ----


class _MLP(nn.Module):
    def __init__(self, dim, hidden):
        super().__init__()
        self.gate_proj = nn.Linear(dim, hidden, bias=False)
        self.up_proj = nn.Linear(dim, hidden, bias=False)
        self.down_proj = nn.Linear(hidden, dim, bias=False)

    def __call__(self, x):
        return self.down_proj(nn.silu(self.gate_proj(x)) * self.up_proj(x))


class _Block(nn.Module):
    def __init__(self, dim, hidden):
        super().__init__()
        self.mlp = _MLP(dim, hidden)

    def __call__(self, x):
        return x + self.mlp(x)


class _Inner(nn.Module):
    def __init__(self, dim, hidden, n):
        super().__init__()
        self.layers = [_Block(dim, hidden) for _ in range(n)]

    def __call__(self, x):
        for layer in self.layers:
            x = layer(x)
        return x


class _Model(nn.Module):
    def __init__(self, dim=16, hidden=32, n=4):
        super().__init__()
        self.model = _Inner(dim, hidden, n)

    def __call__(self, x):
        return self.model(x)


def _count_params(model):
    return len(list(nn.utils.tree_flatten(model.parameters())))


def _fresh_input():
    mx.random.seed(0)
    return mx.random.normal((1, 5, 16))


def _make_model():
    mx.random.seed(1)
    return _Model()


# --- apply / remove ---------------------------------------------------------


def test_disabled_and_empty_are_noops():
    model = _make_model()
    assert apply_neuron_steering(model, "1:7:1", enabled=False) == 0
    assert apply_neuron_steering(model, "", enabled=True) == 0


def test_apply_changes_output_and_remove_restores_exactly():
    model = _make_model()
    x = _fresh_input()
    base = model(x)
    before = _count_params(model)

    n = apply_neuron_steering(model, "1:7:2.0, 2:3:4.0:constant", enabled=True)
    assert n == 2
    steered = model(x)
    assert not mx.allclose(base, steered, atol=1e-5).item()

    # steering state must not leak into the parameter tree
    assert _count_params(model) == before

    assert remove_neuron_steering(model) == 2
    restored = model(x)
    assert mx.allclose(base, restored, atol=1e-5).item()


def test_constant_mode_pins_the_neuron_value():
    """A constant op pins h[..., n] regardless of input, so the down_proj
    output for an all-zero input equals W_down[:, n] * value."""
    model = _make_model()
    apply_neuron_steering(model, "0:5:3.0:constant", enabled=True)
    down = model.model.layers[0].mlp.down_proj
    zeros = mx.zeros((1, 1, 32))
    out = down(zeros)  # steered: pins column 5 to 3.0, rest stay 0
    expected = down.weight[:, 5] * 3.0
    assert mx.allclose(out[0, 0], expected, atol=1e-5).item()


def test_install_on_another_thread_runs_on_the_inference_thread():
    """Engines install steering on a loader thread with its own MLX stream and
    decode on another, so the steering arrays must not stay lazy."""
    import threading

    model = _make_model()
    x = _fresh_input()
    mx.eval(model.parameters(), x)
    installed = []

    def install():
        installed.append(apply_neuron_steering(model, "1:7:2.0, 2:3:4.0:constant"))

    t = threading.Thread(target=install)
    t.start()
    t.join()
    assert installed == [2]
    mx.eval(model(x))


def test_cache_signature_tracks_the_applied_ops():
    """Engines key the prefix cache on this, so it must differ per spec and
    disappear when nothing (or nothing any more) is steered."""
    a, b, none = _make_model(), _make_model(), _make_model()
    apply_neuron_steering(a, "1:7:2.0")
    apply_neuron_steering(b, "1:7:3.0")
    apply_neuron_steering(none, "99:1:1")
    assert getattr(a, SIGNATURE_ATTR).startswith("steer-")
    assert getattr(a, SIGNATURE_ATTR) != getattr(b, SIGNATURE_ATTR)
    assert getattr(none, SIGNATURE_ATTR, None) is None
    remove_neuron_steering(a)
    assert getattr(a, SIGNATURE_ATTR, None) is None


def test_out_of_range_ops_are_skipped_not_fatal():
    model = _make_model()
    assert apply_neuron_steering(model, "99:1:1", enabled=True) == 0
    assert apply_neuron_steering(model, "1:9999:1", enabled=True) == 0


def test_quantized_down_proj_is_supported():
    mx.random.seed(2)
    model = _Model(dim=64, hidden=128, n=2)
    nn.quantize(model, group_size=64, bits=4)
    assert type(model.model.layers[0].mlp.down_proj).__name__ == "QuantizedLinear"
    x = mx.random.normal((1, 3, 64))
    base = model(x)
    assert apply_neuron_steering(model, "0:5:3.0, 1:9:1.5:constant", enabled=True) == 2
    assert not mx.allclose(base, model(x), atol=1e-4).item()
    remove_neuron_steering(model)
    assert mx.allclose(base, model(x), atol=1e-4).item()


def test_unsupported_architecture_is_noop():
    class _NoMLP(nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = [nn.Linear(4, 4)]

    assert apply_neuron_steering(_NoMLP(), "0:1:1", enabled=True) == 0


# --- settings plumbing ------------------------------------------------------


def test_model_settings_round_trip_the_fields():
    s = ModelSettings(
        neuron_steering_enabled=True,
        neuron_steering_spec="14:8949:1.0",
    )
    d = s.to_dict()
    assert d["neuron_steering_enabled"] is True
    assert d["neuron_steering_spec"] == "14:8949:1.0"
    restored = ModelSettings.from_dict(d)
    assert restored.neuron_steering_enabled is True
    assert restored.neuron_steering_spec == "14:8949:1.0"


def test_model_settings_default_off():
    s = ModelSettings()
    assert s.neuron_steering_enabled is False
    assert s.neuron_steering_spec is None
