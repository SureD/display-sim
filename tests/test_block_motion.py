"""M14 P proxy: correspondence, visibility, safe holds and bounded budgets."""

from fractions import Fraction

import numpy as np
import pytest

from tv_sim.block_motion import (
    REASON_CODES,
    BlockMotionConfig,
    PairEstimate,
    estimate_pair,
    reconstruct_block,
)
from tv_sim.frame import Frame
from tv_sim.motion import _sample


def textured_pair(dx=4.0, dy=0.0, shape=(40, 56)):
    random = np.random.default_rng(7)
    left = Frame(random.uniform(20, 500, (*shape, 3)))
    return left, Frame(_sample(left.rgb, dx, dy)[0])


def known_estimate(shape, vector=(0, 0), block=8):
    grid = tuple((v + block - 1) // block for v in shape)
    flow = np.broadcast_to(np.asarray(vector, np.float32), (*grid, 2)).copy()
    confidence, visible, reasons = (
        np.ones(grid, np.float32),
        np.ones(grid, bool),
        np.zeros(grid, np.uint8),
    )
    return PairEstimate(
        flow,
        -flow,
        confidence,
        confidence.copy(),
        visible,
        visible.copy(),
        reasons,
        reasons.copy(),
        shape,
        shape,
        block,
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"schema_version": 1.0},
        {"parameter_status": "measured"},
        {"block_size": 4},
        {"estimation_width": 321},
        {"estimation_height": 181},
        {"pyramid_levels": 1000000},
        {"search_radius": 1000000},
        {"refinement_radius": 1000000},
        {"cut_histogram_bins": 1000000},
        {"subpixel_steps": (0.5,) * 1000},
        {"subpixel_steps": (float("nan"),)},
        {"texture_threshold": 0},
        {"confidence_threshold": 2},
        {"max_displacement_px": float("nan")},
        {"luma_reference_nits": True},
    ],
)
def test_config_rejects_invalid_or_unbounded_policy(settings):
    with pytest.raises(ValueError):
        BlockMotionConfig(**settings)


def test_static_pairs_skip_matching_and_return_exact_content():
    left, _ = textured_pair()
    for source in (left, Frame(np.full((9, 17, 3), 37.5, np.float32))):
        config = BlockMotionConfig()
        estimate = estimate_pair(source, source.copy(), config)
        result = reconstruct_block(source, source.copy(), Fraction(2, 5), estimate, config)
        assert estimate.static and not estimate.scene_cut
        assert not np.any(estimate.forward)
        assert result.frame is source and result.frame.rgb is source.rgb
        assert result.fallback_fraction == 0


@pytest.mark.parametrize("phase", [0, 1])
def test_original_endpoints_are_exact_even_for_a_declared_cut(phase):
    left, right = textured_pair()
    config = BlockMotionConfig()
    estimate = estimate_pair(left, right, config, declared_cut=True)
    result = reconstruct_block(left, right, Fraction(phase), estimate, config)
    assert result.frame is (left, right)[phase]
    assert result.kind == "original" and result.scene_cut
    assert result.fallback_fraction == 0


@pytest.mark.parametrize("vector", [(4, 0), (-4, 0), (0, 4), (4, -4)])
def test_integer_bidirectional_estimation_and_interpolation_have_known_interior(vector):
    left, right = textured_pair(*vector)
    config = BlockMotionConfig()
    estimate = estimate_pair(left, right, config)
    interior = np.s_[2:-2, 2:-2]
    assert np.allclose(estimate.forward[interior], vector, atol=0.25, rtol=0)
    assert np.allclose(estimate.backward[interior], -np.array(vector), atol=0.25, rtol=0)
    assert np.all(estimate.forward_confidence[interior] >= config.confidence_threshold)
    result = reconstruct_block(left, right, Fraction(1, 2), estimate, config)
    truth = _sample(left.rgb, vector[0] / 2, vector[1] / 2)[0]
    assert np.allclose(result.frame.rgb[12:-12, 12:-12], truth[12:-12, 12:-12], atol=1e-4, rtol=0)
    assert result.frame.rgb.dtype == np.float32 and np.isfinite(result.frame.rgb).all()


@pytest.mark.parametrize("vector", [(2.5, -1.5), (-2.5, 1.5)])
@pytest.mark.parametrize("phase", [Fraction(1, 100), Fraction(2, 5), Fraction(99, 100)])
def test_known_signed_subpixel_splats_preserve_linear_plane(vector, phase):
    yy, xx = np.indices((32, 40), dtype=float)

    def plane(dx, dy):
        return Frame(np.repeat((50 + 0.5 * (xx - dx) + 0.25 * (yy - dy))[..., None], 3, axis=-1))

    left, right = plane(0, 0), plane(*vector)
    estimate = known_estimate(left.shape[:2], vector)
    result = reconstruct_block(left, right, phase, estimate, BlockMotionConfig())
    truth = plane(*(float(phase) * np.array(vector)))
    assert np.allclose(result.frame.rgb[4:-4, 4:-4], truth.rgb[4:-4, 4:-4], atol=1e-5, rtol=0)
    assert np.array_equal(result.frame.rgb[result.fallback_mask], left.rgb[result.fallback_mask])


@pytest.mark.parametrize("vector", [(4, 0), (-4, 0), (0, 4), (4, -4)])
def test_rational_phase_texture_splats_do_not_treat_image_contrast_as_collision(vector):
    left, right = textured_pair(*vector)
    estimate = known_estimate(left.shape[:2], vector)
    result = reconstruct_block(left, right, Fraction(2, 5), estimate, BlockMotionConfig())
    truth, _ = _sample(left.rgb, vector[0] * 0.4, vector[1] * 0.4)
    assert not np.any(result.fallback_mask[8:-8, 8:-8])
    # The fixture's clamped border is deliberately outside this supported
    # interior; its unrelated border samples may correctly be rejected.
    assert not np.any(result.reason_map[8:-8, 8:-8] == REASON_CODES["collision"])
    assert np.allclose(result.frame.rgb[8:-8, 8:-8], truth[8:-8, 8:-8], atol=1e-4, rtol=0)


def test_reduced_estimation_never_upscales_and_vectors_use_output_pixels():
    left, right = textured_pair(8, 0, shape=(64, 96))
    config = BlockMotionConfig(estimation_width=48, estimation_height=32)
    estimate = estimate_pair(left, right, config)
    assert estimate.estimation_shape == (32, 48)
    assert np.allclose(estimate.forward[1:-1, 2:-2], (8, 0), atol=0.5, rtol=0)
    assert estimate.dense_field(estimate.forward).shape == (64, 96, 2)
    small = Frame(np.full((5, 7, 3), 20, np.float32))
    assert estimate_pair(small, small, config).estimation_shape == (5, 7)


def test_zero_confidence_returns_source_with_partitioned_reason_fractions():
    left, right = textured_pair()
    estimate = known_estimate(left.shape[:2], (4, 0))
    estimate.forward_confidence.fill(0)
    estimate.backward_confidence.fill(0)
    estimate.forward_reasons.fill(REASON_CODES["ambiguous_match"])
    result = reconstruct_block(left, right, 0.5, estimate, BlockMotionConfig())
    assert result.frame is left and result.fallback_mask.all()
    assert result.fallback_reasons == ["ambiguous_match"]
    assert result.reason_fractions == {"ambiguous_match": 1.0}
    assert result.diagnostics["whole_frame_hold"]


@pytest.mark.parametrize("declared", [True, False])
def test_cut_holds_old_shot_and_does_not_reuse_history(declared):
    left, moving = textured_pair()
    config = BlockMotionConfig()
    previous = estimate_pair(left, moving, config)
    new = Frame(np.full_like(left.rgb, 1000))
    estimate = estimate_pair(left, new, config, declared_cut=declared, previous=previous)
    assert estimate.scene_cut and not estimate.diagnostics["history_reused"]
    assert not np.any(estimate.forward) and not np.any(estimate.backward)
    reason = "scene_cut_declared" if declared else "scene_cut_detected"
    for phase in (Fraction(1, 100), Fraction(1, 2), Fraction(999, 1000)):
        result = reconstruct_block(left, new, phase, estimate, config)
        assert result.frame is left and result.fallback_reasons == [reason]
    assert reconstruct_block(left, new, 1, estimate, config).frame is new


def test_exposure_flash_is_held_without_declaring_a_scene_cut():
    left, _ = textured_pair()
    flash = Frame(left.rgb + 200)
    config = BlockMotionConfig()
    estimate = estimate_pair(left, flash, config)
    result = reconstruct_block(left, flash, 0.5, estimate, config)
    assert not estimate.scene_cut and result.frame is left
    assert result.fallback_reasons == ["exposure_change"]


def test_periodic_texture_is_ambiguous_even_with_neighbor_regularization():
    yy, xx = np.indices((32, 48))
    left = Frame(np.repeat(((xx % 4) < 2)[..., None] * 400, 3, axis=-1))
    right = Frame(_sample(left.rgb, 1, 0)[0])
    config = BlockMotionConfig()
    estimate = estimate_pair(left, right, config)
    assert np.any(estimate.forward_reasons == REASON_CODES["ambiguous_match"])
    result = reconstruct_block(left, right, 0.5, estimate, config)
    assert result.frame is left and result.fallback_fraction == 1


def test_declared_motion_limit_falls_back_and_records_out_of_range():
    left, right = textured_pair()
    config = BlockMotionConfig(max_displacement_px=2)
    estimate = estimate_pair(left, right, config)
    result = reconstruct_block(left, right, 0.5, estimate, config)
    assert np.any(estimate.forward_reasons == REASON_CODES["motion_out_of_range"])
    assert result.frame is left and "motion_out_of_range" in result.fallback_reasons


def test_conflicting_visible_trajectories_hold_collision_pixels():
    left = Frame(np.full((24, 32, 3), 100, np.float32))
    right = Frame(np.full((24, 32, 3), 500, np.float32))
    estimate = known_estimate(left.shape[:2])
    result = reconstruct_block(left, right, 0.5, estimate, BlockMotionConfig())
    assert result.frame is left and result.fallback_fraction == 1
    assert result.fallback_reasons == ["collision"]
    assert result.diagnostics["collision_fraction"] == 1


def test_disagreeing_trajectories_hold_even_when_endpoint_luma_agrees():
    left = Frame(np.full((24, 32, 3), 100, np.float32))
    right = left.copy()
    estimate = known_estimate(left.shape[:2], (4, 0))
    estimate.backward[:] = (4, 0)  # Opposing physical trajectories collide.
    result = reconstruct_block(left, right, 0.5, estimate, BlockMotionConfig())
    assert result.frame is left and result.fallback_fraction == 1
    assert result.diagnostics["collision_fraction"] > 0
    assert "collision" in result.fallback_reasons


def test_visibility_and_generic_confidence_are_separate_maps():
    left, right = textured_pair()
    estimate = known_estimate(left.shape[:2], (4, 0))
    estimate.forward_visibility[:] = False
    # The visible right endpoint alone can supply supported content.
    result = reconstruct_block(left, right, 0.5, estimate, BlockMotionConfig())
    assert result.kind == "interpolated"
    assert result.fallback_fraction < 1
    assert np.array_equal(result.frame.rgb[result.fallback_mask], left.rgb[result.fallback_mask])


def test_estimation_and_reconstruction_are_deterministic_and_debuggable():
    left, right = textured_pair()
    config = BlockMotionConfig()
    estimates = [estimate_pair(left, right, config) for _ in range(2)]
    for name, value in estimates[0].debug_arrays().items():
        assert np.array_equal(value, estimates[1].debug_arrays()[name]), name
    assert estimates[0].diagnostics == estimates[1].diagnostics
    outputs = [reconstruct_block(left, right, Fraction(2, 5), e, config) for e in estimates]
    assert np.array_equal(outputs[0].frame.rgb, outputs[1].frame.rgb)
    assert np.array_equal(outputs[0].reason_map, outputs[1].reason_map)
    assert outputs[0].to_dict() == outputs[1].to_dict()


def test_low_confidence_history_requires_stronger_evidence_to_reenable():
    left, right = textured_pair()
    config = BlockMotionConfig(confidence_threshold=0.95, confidence_hysteresis=0.1)
    previous = known_estimate(left.shape[:2])
    previous.forward_confidence.fill(0)
    previous.backward_confidence.fill(0)
    estimate = estimate_pair(left, right, config, previous=previous)
    assert estimate.diagnostics["history_reused"]
    assert not np.any(estimate.forward_confidence)
    # Independent clips start without the confidence history.
    fresh = estimate_pair(left, right, config)
    assert np.any(fresh.forward_confidence)


def test_nonfinite_sources_safely_stop_estimation():
    left, right = textured_pair()
    right.rgb[0, 0, 0] = np.nan
    config = BlockMotionConfig()
    estimate = estimate_pair(left, right, config)
    result = reconstruct_block(left, right, 0.5, estimate, config)
    assert result.frame is left and result.fallback_reasons == ["nonfinite_source"]


def test_invalid_alpha_or_geometry_is_rejected():
    left, right = textured_pair()
    estimate = known_estimate(left.shape[:2])
    with pytest.raises(ValueError, match="alpha"):
        reconstruct_block(left, right, -0.1, estimate, BlockMotionConfig())
    with pytest.raises(ValueError, match="shapes"):
        reconstruct_block(left, Frame(np.zeros((2, 2, 3))), 0.5, estimate, BlockMotionConfig())
