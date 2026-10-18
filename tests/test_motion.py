"""M7 P model: exact cadence, synthetic reconstruction and safe holds."""

from fractions import Fraction
from itertools import groupby

import numpy as np
import pytest

from tv_sim.frame import Frame
from tv_sim.motion import (
    AnalyticLayer,
    LayerScene,
    fixed_rate_pts,
    reconstruct,
    schedule,
)


@pytest.mark.parametrize(
    "source_fps,output_fps,runs",
    [
        (24, 60, [3, 2, 3, 2]),
        (24, 120, [5, 5, 5, 5]),
        ("24000/1001", "60000/1001", [3, 2, 3, 2]),
        ("24000/1001", "120000/1001", [5, 5, 5, 5]),
        (25, 50, [2, 2, 2, 2]),
    ],
)
def test_repeat_cadence_has_exact_source_runs(source_fps, output_fps, runs):
    ticks = schedule(fixed_rate_pts(4, source_fps), 1 / Fraction(source_fps), output_fps)
    assert [len(list(group)) for _, group in groupby(t.source_index for t in ticks)] == runs
    assert ticks[0].output_pts == ticks[0].source_pts == 0
    assert ticks[-1].next_source_index is None
    assert ticks[-1].output_pts < Fraction(4, 1) / Fraction(source_fps)


def test_phase_and_pts_diagnostics_are_rational_and_half_open():
    ticks = schedule(fixed_rate_pts(3, 24), Fraction(1, 24), 60)
    assert [t.phase for t in ticks[:5]] == [
        0,
        Fraction(2, 5),
        Fraction(4, 5),
        Fraction(1, 5),
        Fraction(3, 5),
    ]
    assert ticks[3].to_dict() == {
        "output_index": 3,
        "output_pts": "1/20",
        "source_index": 1,
        "source_pts": "1/24",
        "next_source_index": 2,
        "next_source_pts": "1/12",
        "phase": "1/5",
    }
    # Three source durations total 1/8s: no added tick at the clip endpoint.
    assert len(ticks) == 8
    assert ticks[-1].output_pts == Fraction(7, 60)


def test_fractional_rates_do_not_accumulate_drift_or_fake_five_repeats():
    pts = fixed_rate_pts(2400, "24000/1001", start="10/3")
    ticks = schedule(pts, "1001/24000", "60000/1001")
    assert len(ticks) == 6000
    assert ticks[-1].output_pts == Fraction(10, 3) + Fraction(5999 * 1001, 60000)
    assert ticks[-1].phase == Fraction(3, 5)
    # True 120 Hz is a different ratio from 120000/1001 Hz.
    true_120 = schedule(fixed_rate_pts(200, "24000/1001"), "1001/24000", 120)
    assert len(true_120) == 1001
    assert any(len(list(group)) != 5 for _, group in groupby(t.source_index for t in true_120))


def test_irregular_pts_and_single_frame_hold():
    ticks = schedule(["5/2", "8/3", 3], Fraction(1, 2), 6)
    assert [t.source_index for t in ticks] == [0, 1, 1, 2, 2, 2]
    assert ticks[1].phase == 0
    one = schedule([Fraction(7, 3)], Fraction(1, 24), 60)
    assert len(one) == 3
    assert all(t.source_index == 0 and t.next_source_pts is None for t in one)


@pytest.mark.parametrize(
    "pts,duration,fps",
    [
        ([], 1, 60),
        ([0, 0], 1, 60),
        ([1, 0], 1, 60),
        ([0, float("nan")], 1, 60),
        ([0], 0, 60),
        ([0], 1, 0),
    ],
)
def test_scheduler_rejects_invalid_timing(pts, duration, fps):
    with pytest.raises(ValueError):
        schedule(pts, duration, fps)


def _plane(dx=0.0, dy=0.0):
    yy, xx = np.indices((16, 20), dtype=np.float64)
    values = 50 + 0.5 * (xx - dx) + 0.25 * (yy - dy)
    return Frame(np.repeat(values[..., None], 3, axis=-1))


@pytest.mark.parametrize("translation", [(2.5, -1.5), (-2.5, 1.5), (0, 2.25), (-1.25, 0)])
@pytest.mark.parametrize("alpha", [0.01, 0.4, 0.99])
def test_signed_subpixel_2d_translation_matches_known_interior(translation, alpha):
    dx, dy = translation
    left, right = _plane(), _plane(dx, dy)
    result = reconstruct(left, right, alpha, translation=translation)
    truth = _plane(alpha * dx, alpha * dy)
    assert result.kind == "interpolated"
    assert np.allclose(
        result.frame.rgb[~result.fallback_mask], truth.rgb[~result.fallback_mask], atol=1e-5, rtol=0
    )
    assert result.frame.rgb.dtype == np.float32
    assert np.isfinite(result.frame.rgb).all()
    assert result.evidence == "P"


def test_translation_holes_hold_source_instead_of_reflecting_content():
    left, right = _plane(), _plane(4, 4)
    result = reconstruct(left, right, 0.5, translation=(4, 4))
    assert 0 < result.fallback_fraction < 1
    assert result.fallback_reasons == ["out_of_bounds"]
    assert np.array_equal(result.frame.rgb[result.fallback_mask], left.rgb[result.fallback_mask])
    assert result.fallback_mask[-1, 0]


def test_endpoints_return_original_frame_and_array_without_resampling():
    left, right = _plane(), _plane(2, 0)
    first = reconstruct(left, right, Fraction(0), translation=(float("nan"), 0), cut=True)
    last = reconstruct(left, right, Fraction(1), translation=(float("nan"), 0), cut=True)
    assert first.frame is left and first.frame.rgb is left.rgb
    assert last.frame is right and last.frame.rgb is right.rgb
    assert first.kind == last.kind == "original"
    assert first.scene_cut and last.scene_cut
    assert first.fallback_fraction == last.fallback_fraction == 0


def test_identical_pairs_and_dc_are_exact_noops():
    for left in (_plane(), Frame(np.full((4, 6, 3), 37.5, np.float32))):
        result = reconstruct(left, left.copy(), Fraction(2, 5), translation=(17.5, -2.25))
        assert result.frame is left
        assert result.fallback_fraction == 0
        assert np.array_equal(result.frame.rgb, left.rgb)


def test_cut_holds_old_shot_until_the_declared_cut_pts():
    old = Frame(np.full((8, 8, 3), 10, np.float32))
    new = Frame(np.full((8, 8, 3), 100, np.float32))
    for alpha in (0.001, 0.5, 0.999999):
        result = reconstruct(old, new, alpha, translation=(1, 0), cut=True)
        assert result.frame is old
        assert result.scene_cut and result.kind == "repeated"
        assert result.fallback_reasons == ["scene_cut"]
        assert result.fallback_fraction == 1
    assert reconstruct(old, new, 1, cut=True).frame is new


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({}, "missing_motion_model"),
        ({"translation": (float("nan"), 0)}, "nonfinite_motion"),
        ({"translation": (257, 0)}, "motion_out_of_range"),
        ({"translation": (30, 0)}, "out_of_bounds"),
        ({"translation": (0, 0)}, "model_endpoint_mismatch"),
    ],
)
def test_unsafe_or_missing_translation_reports_whole_frame_hold(kwargs, reason):
    left, right = _plane(), _plane(2, 0)
    result = reconstruct(left, right, 0.5, **kwargs)
    assert result.frame is left and result.kind == "repeated"
    assert result.fallback_reasons == [reason]
    assert result.fallback_mask.all() and result.fallback_fraction == 1


def test_tail_has_no_extrapolation_and_invalid_dimensions_are_rejected():
    left = _plane()
    result = reconstruct(left, None, 0.7, translation=(2, 0))
    assert result.frame is left and result.fallback_reasons == ["last_frame_hold"]
    with pytest.raises(ValueError, match="shapes"):
        reconstruct(left, Frame(np.zeros((2, 2, 3))), 0.5)
    with pytest.raises(ValueError, match="alpha"):
        reconstruct(left, left, -0.01)


def _layer_scene():
    background = _plane().rgb
    rear_mask = np.zeros(background.shape[:2], bool)
    rear_mask[3:12, 7:15] = True
    front_mask = np.zeros_like(rear_mask)
    front_mask[5:10, 5:9] = True
    rear = AnalyticLayer(np.full_like(background, 70), rear_mask, (-2, 0), depth=1)
    front = AnalyticLayer(np.full_like(background, 100), front_mask, (6, 0), depth=2)
    return LayerScene(background, (front, rear))


def test_known_layers_resolve_occlusion_and_reveal_background():
    scene = _layer_scene()
    left, right = scene.render(0), scene.render(1)
    result = reconstruct(left, right, 0.5, scene=scene)
    assert result.kind == "interpolated" and result.fallback_fraction == 0
    assert np.array_equal(result.frame.rgb, scene.render(0.5).rgb)
    # The top layer wins where objects cross, regardless of tuple order.
    assert result.frame.rgb[7, 9, 0] == 100
    # Previously covered background is known, so it can be revealed safely.
    assert left.rgb[7, 5, 0] == 100
    assert result.frame.rgb[7, 5, 0] == scene.background[7, 5, 0]
    assert result.frame.rgb[7, 6, 0] == 70
    assert result.frame.rgb[7, 14, 0] == scene.background[7, 14, 0]


def test_layer_subpixel_edges_use_coverage_and_return_exact_endpoints():
    scene = _layer_scene()
    left, right = scene.render(0), scene.render(1)
    result = reconstruct(left, right, Fraction(1, 4), scene=scene)
    assert np.array_equal(result.frame.rgb, scene.render(Fraction(1, 4)).rgb)
    assert reconstruct(left, right, 0, scene=scene).frame is left
    assert reconstruct(left, right, 1, scene=scene).frame is right


@pytest.mark.parametrize("dx,edge", [(1, 0), (-1, -1)])
def test_layer_at_raster_border_retains_partial_bilinear_coverage(dx, edge):
    background = np.full((4, 6, 3), 20, np.float32)
    mask = np.zeros(background.shape[:2], bool)
    mask[:, edge] = True
    scene = LayerScene(
        background, (AnalyticLayer(np.full_like(background, 100), mask, velocity=(dx, 0)),)
    )
    left, right = scene.render(0), scene.render(1)
    result = reconstruct(left, right, Fraction(1, 2), scene=scene)
    # Half of the edge texel remains visible; outside the layer is transparent.
    assert result.kind == "interpolated" and result.fallback_fraction == 0
    assert np.array_equal(result.frame.rgb[:, edge], np.full((4, 3), 60, np.float32))
    assert np.array_equal(result.frame.rgb[:, edge + dx], np.full((4, 3), 60, np.float32))
    assert np.array_equal(result.frame.rgb[:, 3], background[:, 3])


def test_wrong_scene_cannot_override_the_supplied_source_endpoints():
    scene = _layer_scene()
    left, right = scene.render(0), scene.render(1)
    wrong = LayerScene(scene.background + 1, scene.layers)
    result = reconstruct(left, right, 0.5, scene=wrong)
    assert result.frame is left
    assert result.fallback_reasons == ["model_endpoint_mismatch"]
    # A malformed mask is a safe repeated source, not an arbitrary warp.
    bad = LayerScene(scene.background, (AnalyticLayer(scene.background, np.ones((2, 2))),))
    assert reconstruct(left, right, 0.5, scene=bad).fallback_reasons == ["invalid_scene"]
