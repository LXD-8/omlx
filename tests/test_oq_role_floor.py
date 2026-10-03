# SPDX-License-Identifier: Apache-2.0
"""Tests for the small-but-critical role floor.

Roles that decide something discrete - a sparse-attention top-k selection, a
gated residual write, an attention read pattern - do not average their
quantization error away. On a fine-grained MoE they are a rounding error of the
checkpoint, so they stay in full precision (hard selectors) or are pinned to a
fixed 8-bit affine format (attention, gated residual, PLE key/value, MTP). The
attention and gated-residual roles only apply while they stay a small share of
the checkpoint, so a dense model keeps the per-level allocator's choice.
"""

import pytest

from omlx.oq import (
    _build_quant_plan,
    _role_floor,
    _role_floor_gated_overrides,
    universal_quant_predicate,
)

# Hard top-k selectors stay in full precision, across family spellings.
HARD_SELECTOR_PATHS = [
    "language_model.model.layers.11.self_attn.indexer.index_qk_proj",
    "language_model.model.layers.11.self_attn.indexer.wk",
    "language_model.model.layers.11.self_attn.indexer.wq_b",
    "language_model.model.layers.11.self_attn.indexer.weights_proj",
    "mtp.layers.0.self_attn.indexer.index_qk_proj",
]

# Unconditionally pinned to 8-bit: tiny by construction.
UNCONDITIONAL_Q8_PATHS = [
    "mtp.fc_embedding",
    "mtp.fc_hidden",
    "language_model.model.layers.11.ple.key_proj",
    "language_model.model.layers.11.ple.value_proj",
    # MTP copies of the backbone roles stay on the same format.
    "mtp.layers.0.self_attn.q_proj",
    "mtp.layers.0.self_attn.k_proj",
    "mtp.layers.0.self_attn.v_proj",
    "mtp.layers.0.self_attn.o_proj",
    "mtp.layers.0.attn_hyper_connection.input_mix_weight_up",
    "mtp.layers.0.mlp_hyper_connection.input_mix_weight_down",
    "mtp.hyper_connection_mixer.input_mix_weight_up",
]

# Paths the floor must not touch.
UNCOVERED_PATHS = [
    "language_model.model.layers.11.mlp.gate",
    "language_model.model.layers.11.mlp.switch_mlp.gate_proj",
    "language_model.model.layers.11.mlp.switch_mlp.down_proj",
    # DeltaNet / linear attention stays on the per-level policy, as do MLA
    # low-rank pairs.
    "language_model.model.layers.11.linear_attn.in_proj_qkv",
    "language_model.model.layers.11.linear_attn.out_proj",
    "language_model.model.layers.11.self_attn.q_a_proj",
    "language_model.model.layers.11.self_attn.kv_b_proj",
    "language_model.model.layers.11.ple.ple_embedding.ngram_embedding.shards.7",
    "language_model.model.layers.11.mlp.shared_expert.down_proj",
    "language_model.model.layers.11.self_attn.q_norm",
    "lm_head",
    "language_model.model.embed_tokens",
]

Q8_SPEC = {"bits": 8, "group_size": 64, "mode": "affine"}

# A fine-grained MoE: attention is a rounding error, experts dominate.
MOE_SHAPES = {
    "model.layers.0.self_attn.q_proj": (12288, 2560),
    "model.layers.0.self_attn.k_proj": (512, 2560),
    "model.layers.0.attn_hyper_connection.input_mix_weight_up": (10240, 2560),
    "model.layers.0.mlp.switch_mlp.gate_proj": (512, 640, 2560),
    "model.layers.0.mlp.switch_mlp.up_proj": (512, 640, 2560),
    "model.layers.0.mlp.switch_mlp.down_proj": (512, 2560, 640),
    "model.layers.0.mlp.gate": (512, 2560),
}

# A dense model: attention is a large share, so the gate must not fire.
DENSE_SHAPES = {
    "model.layers.0.self_attn.q_proj": (4096, 4096),
    "model.layers.0.self_attn.k_proj": (4096, 4096),
    "model.layers.0.self_attn.v_proj": (4096, 4096),
    "model.layers.0.self_attn.o_proj": (4096, 4096),
    "model.layers.0.mlp.down_proj": (11008, 4096),
    "model.embed_tokens": (32000, 4096),
}


def _numel(shape):
    n = 1
    for dim in shape:
        n *= dim
    return n


class TestRoleFloorUnconditional:
    """Roles that are tiny by construction, at any level and model."""

    @pytest.mark.parametrize("path", HARD_SELECTOR_PATHS)
    def test_hard_selectors_stay_full_precision(self, path):
        assert _role_floor(path, {}) is False

    @pytest.mark.parametrize("path", UNCONDITIONAL_Q8_PATHS)
    def test_tiny_roles_are_q8(self, path):
        assert _role_floor(path, {}) == Q8_SPEC

    @pytest.mark.parametrize("path", UNCOVERED_PATHS)
    def test_uncovered_paths_get_no_opinion(self, path):
        assert _role_floor(path, {}) is None

    def test_weight_suffix_is_normalized(self):
        assert (
            _role_floor("model.layers.0.self_attn.indexer.index_qk_proj", {}) is False
        )
        assert _role_floor("mtp.fc_embedding.scales", {}) == Q8_SPEC

    def test_fused_family_invariants_are_left_to_their_own_rules(self):
        # Inkling fuses Q/K/V/R and its loader requires Q8, so the floor must
        # not claim it as a full-precision hard selector.
        assert _role_floor("model.layers.0.self_attn.qkvr_proj", {}) is None
        assert (
            universal_quant_predicate(
                "model.layers.0.self_attn.qkvr_proj",
                None,
                {"model_type": "inkling"},
                4,
            )
            == Q8_SPEC
        )

    def test_gated_roles_are_not_unconditional(self):
        # These need the size gate, so the unconditional half must not claim
        # them.
        assert _role_floor("model.layers.0.self_attn.q_proj", {}) is None
        assert (
            _role_floor("model.layers.0.attn_hyper_connection.block_inject_weight", {})
            is None
        )


class TestRoleFloorInPredicate:
    """The floor must win over the per-level policy and the boost map."""

    @pytest.mark.parametrize("level", [2, 2.5, 2.7, 3, 3.5, 4, 5, 6, 8])
    def test_floor_holds_at_every_level(self, level):
        for path in HARD_SELECTOR_PATHS:
            assert universal_quant_predicate(path, None, {}, level) is False
        for path in UNCONDITIONAL_Q8_PATHS:
            assert universal_quant_predicate(path, None, {}, level) == Q8_SPEC

    def test_floor_beats_base_bits_at_oq2(self):
        path = "model.layers.11.self_attn.indexer.index_qk_proj"
        assert universal_quant_predicate(path, None, {}, 2) is False

    def test_floor_beats_boost_map(self):
        path = "mtp.fc_embedding"
        config = {"_oq_boost_map": {path: {"bits": 2, "group_size": 64}}}
        assert universal_quant_predicate(path, None, config, 4) == Q8_SPEC

    def test_glm_indexer_invariant_still_wins(self):
        # GLM must keep Q8 (fused loader), not the floor's full precision.
        path = "model.layers.11.self_attn.indexer.wk"
        config = {"model_type": "glm5_next"}
        assert universal_quant_predicate(path, None, config, 4) == {
            "bits": 8,
            "group_size": 64,
            "mode": "affine",
        }


class TestRoleFloorSizeGate:
    """Attention and gated-residual roles are pinned only while they are small."""

    def test_moe_pins_attention_and_mixer(self):
        overrides = _role_floor_gated_overrides(MOE_SHAPES)
        total = sum(_numel(s) for s in MOE_SHAPES.values())
        attention = sum(
            _numel(s)
            for p, s in MOE_SHAPES.items()
            if p.endswith(("q_proj", "k_proj", "v_proj", "o_proj"))
        )
        assert attention / total < 0.02  # the premise of the test
        assert overrides["model.layers.0.self_attn.q_proj"] == Q8_SPEC
        assert overrides["model.layers.0.self_attn.k_proj"] == Q8_SPEC
        assert (
            overrides["model.layers.0.attn_hyper_connection.input_mix_weight_up"]
            == Q8_SPEC
        )
        # Routed experts and the MoE gate are never touched.
        assert "model.layers.0.mlp.switch_mlp.gate_proj" not in overrides
        assert "model.layers.0.mlp.gate" not in overrides

    def test_dense_model_is_left_to_the_allocator(self):
        overrides = _role_floor_gated_overrides(DENSE_SHAPES)
        total = sum(_numel(s) for s in DENSE_SHAPES.values())
        attention = sum(
            _numel(s)
            for p, s in DENSE_SHAPES.items()
            if p.endswith(("q_proj", "k_proj", "v_proj", "o_proj"))
        )
        assert attention / total > 0.02  # the premise of the test
        assert overrides == {}

    def test_mtp_paths_are_left_to_the_unconditional_half(self):
        shapes = {
            "mtp.layers.0.self_attn.q_proj": (12288, 2560),
            "model.layers.0.self_attn.q_proj": (12288, 2560),
            "model.layers.0.mlp.switch_mlp.gate_proj": (512, 640, 2560),
            "model.layers.0.mlp.switch_mlp.up_proj": (512, 640, 2560),
            "model.layers.0.mlp.switch_mlp.down_proj": (512, 2560, 640),
        }
        overrides = _role_floor_gated_overrides(shapes)
        assert "mtp.layers.0.self_attn.q_proj" not in overrides
        assert "model.layers.0.self_attn.q_proj" in overrides

    def test_empty_shapes_is_a_noop(self):
        assert _role_floor_gated_overrides({}) == {}


class TestRoleFloorInBudgetPlan:
    """The plan must price the floor up front instead of letting the cap drop it."""

    @pytest.mark.parametrize("level", [2, 4, 6])
    def test_plan_seeds_the_floor(self, level):
        plan = _build_quant_plan(
            MOE_SHAPES,
            {},
            level,
            target_bpw={2: 2.9, 4: 4.6, 6: 6.5}[level],
            hard_cap_bpw={2: 3.0, 4: 4.7, 6: 6.6}[level],
        )
        assert plan.boost_map["model.layers.0.self_attn.q_proj"] == Q8_SPEC
        assert (
            plan.boost_map["model.layers.0.attn_hyper_connection.input_mix_weight_up"]
            == Q8_SPEC
        )

    def test_plan_leaves_a_dense_model_alone(self):
        plan = _build_quant_plan(DENSE_SHAPES, {}, 4, target_bpw=4.6, hard_cap_bpw=4.7)
        for path in DENSE_SHAPES:
            # The sensitivity allocator may still boost these to 5/6 bits; the
            # floor must not pin them to Q8 the way it does for a checkpoint
            # where attention is a rounding error.
            assert plan.boost_map.get(path, {}).get("bits", 0) != 8
