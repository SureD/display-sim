"""M17 synthetic controller, physical-history ownership and continuation tests."""

import base64
import json
import math
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from tv_sim.abl_dynamics import ABLDynamicsConfig, digest
from tv_sim.block_motion import BlockMotionConfig
from tv_sim.colorimetry import ColorimetryConfig, convert_rgb, gamut_map
from tv_sim.frame import Frame
from tv_sim.load import LoadState
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.sequence import MotionConfig
from tv_sim.stages.backlight import (
    apply_light_spread,
    psf_axis_kernels,
    simulate_backlight,
    upsample_zones,
    zone_edges,
)
from tv_sim.stages.temporal import TemporalState
from tv_sim.viewing_angle import ViewingAngleConfig
from tv_sim.zone_temporal import (
    MODEL,
    ZoneBacklightState,
    ZoneTemporalConfig,
    render_backlight,
    update_zones,
    zone_targets,
)


def profile(name="generic_va_fald_miniled"):
    original = load_profile(name)
    return replace(
        original,
        processing=replace(original.processing, sharpen_amount=0),
        backlight=replace(
            original.backlight,
            zones_y=2,
            zones_x=3,
            peak_nits=1000,
            psf_sigma_zones=0,
            psf_sigma_y_zones=0,
            psf_tail_weight=0,
        ),
        hdr=replace(original.hdr, abl_enabled=False),
        temporal=replace(original.temporal, response_time_ms=0, sample_and_hold=False),
    )


def config(**changes):
    return ZoneTemporalConfig(model=MODEL, attack_s=0.1, release_s=0.4, **changes)


def picture(level, shape=(8, 12, 3)):
    return Frame(np.full(shape, level, dtype=np.float32))


def grid(level):
    return np.full((2, 3), level, dtype=np.float64)


def snapshot(pipeline):
    state = pipeline.zone_state
    return (
        None if state.zones_nits is None else state.zones_nits.tobytes(),
        None if state.previous_targets is None else state.previous_targets.tobytes(),
        state.elapsed_ms,
        state.ticks,
        None if pipeline.state.previous is None else pipeline.state.previous.tobytes(),
        pipeline.load_state.apl_nits,
        deepcopy(pipeline.last_zone_trace),
        deepcopy(getattr(pipeline, "last_colorimetry_diagnostics", None)),
    )


@pytest.mark.parametrize("start,target,tau", [(0, 1000, 0.1), (1000, 0, 0.4), (500, 500, 0.1)])
def test_asymmetric_formula_and_float64_state(start, target, tau):
    state = ZoneBacklightState(grid(start))
    for tick, dt in enumerate((7.5, 30, 100, 0.01), start=1):
        elapsed = state.elapsed_ms + dt
        trace = update_zones(state, grid(target), profile().backlight, dt, config())
        expected = target + (start - target) * math.exp(-elapsed / 1000 / tau)
        np.testing.assert_allclose(state.zones_nits, expected, rtol=2e-15, atol=1e-12)
        assert state.zones_nits.dtype == np.float64
        assert trace["ticks"] == tick
        assert trace["branch"][0][0] == (
            "attack" if start < target else "release" if start > target else "equal"
        )
        assert state.zones_nits.min() >= min(start, target)
        assert state.zones_nits.max() <= max(start, target)


def test_mixed_zone_branches_are_independent_and_equal_values_do_not_drift():
    state = ZoneBacklightState(np.array([[10, 400, 900]], dtype=np.float64))
    targets = np.array([[900, 400, 10]], dtype=np.float64)
    trace = update_zones(state, targets, profile().backlight, 100, config())
    assert trace["branch"] == [["attack", "equal", "release"]]
    assert state.zones_nits[0, 1] == 400
    assert state.zones_nits[0, 0] == pytest.approx(900 - 890 * math.exp(-1))
    assert state.zones_nits[0, 2] == pytest.approx(10 + 890 * math.exp(-0.25))


@pytest.mark.parametrize("tau", [0, 1e-300, 1e300])
@pytest.mark.parametrize("dt", [1e-15, 10, 1e200])
def test_extreme_finite_ratios_remain_bounded(tau, dt):
    state = ZoneBacklightState(grid(500))
    settings = ZoneTemporalConfig(model=MODEL, attack_s=tau, release_s=tau)
    update_zones(state, grid(1000), profile().backlight, dt, settings)
    assert np.isfinite(state.zones_nits).all()
    assert np.all((state.zones_nits >= 500) & (state.zones_nits <= 1000))
    if tau == 0:
        np.testing.assert_array_equal(state.zones_nits, grid(1000))


@pytest.mark.parametrize("start,target", [(0, 900), (900, 0)])
def test_rate_independent_e_fold_without_slew(start, target):
    whole = ZoneBacklightState(grid(start))
    split = ZoneBacklightState(grid(start))
    update_zones(whole, grid(target), profile().backlight, 1000, config())
    for _ in range(120):
        update_zones(split, grid(target), profile().backlight, 1000 / 120, config())
    np.testing.assert_allclose(split.zones_nits, whole.zones_nits, atol=1e-11, rtol=1e-12)


def test_slew_is_after_iir_per_tick_and_cut_reset_bypasses_both():
    settings = config(slew_nits_per_tick=20)
    one, two = ZoneBacklightState(grid(0)), ZoneBacklightState(grid(0))
    trace = update_zones(one, grid(1000), profile().backlight, 100, settings)
    for _ in range(2):
        update_zones(two, grid(1000), profile().backlight, 50, settings)
    np.testing.assert_array_equal(one.zones_nits, grid(20))
    np.testing.assert_array_equal(two.zones_nits, grid(40))
    assert all(all(row) for row in trace["slew_limited"])
    trace = update_zones(one, grid(900), profile().backlight, 1, settings, scene_cut=True)
    np.testing.assert_array_equal(one.zones_nits, grid(900))
    assert trace["scene_cut_declared"] and trace["scene_cut_reset"]
    assert not any(any(row) for row in trace["slew_limited"])


def test_slew_does_not_clip_release_to_target_or_apply_if_iir_change_is_small():
    state = ZoneBacklightState(grid(100))
    trace = update_zones(state, grid(0), profile().backlight, 1, config(slew_nits_per_tick=20))
    assert np.all(state.zones_nits > 99)
    assert not any(any(row) for row in trace["slew_limited"])


@pytest.mark.parametrize(
    "initial,expected", [("cold", 0), ("settled_first_tick", 800), ("explicit", 300)]
)
def test_each_initializer_is_zones_only(initial, expected):
    options = {"initial": initial}
    if initial == "explicit":
        options["initial_zones_nits"] = ((300.0,) * 3,) * 2
    pipeline = Pipeline(profile(), zone_temporal=config(**options))
    pipeline.display_content(picture(800), frame_time_ms=10)
    np.testing.assert_array_equal(pipeline.last_zone_trace["before_nits"], grid(expected))
    assert pipeline.zone_state.ticks == 1
    if initial == "settled_first_tick":
        np.testing.assert_array_equal(pipeline.zone_state.zones_nits, grid(800))


def test_detector_compares_previous_targets_once_and_reset_can_be_disabled():
    active = Pipeline(profile(), zone_temporal=config(cut_detection_threshold=0.2))
    active.display_content(picture(0))
    active.display_content(picture(200))
    assert not active.last_zone_trace["scene_cut_detected"]  # strict threshold
    active.display_content(picture(900))
    assert active.last_zone_trace["scene_cut_detected"]
    assert not active.last_zone_trace["scene_cut_declared"]
    np.testing.assert_array_equal(active.zone_state.zones_nits, grid(900))
    active.display_content(picture(900))
    assert not active.last_zone_trace["scene_cut_detected"]
    disabled = Pipeline(profile(), zone_temporal=config(reset_on_scene_cut=False))
    disabled.display_content(picture(900), scene_cut=True)
    assert disabled.last_zone_trace["scene_cut_declared"]
    assert not disabled.last_zone_trace["scene_cut_reset"]
    assert disabled.zone_state.zones_nits.max() < 900


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "unknown"},
        {"model": MODEL},
        {"model": MODEL, "attack_s": 1},
        {"attack_s": 1},
        {"release_s": 1},
        {"reset_on_scene_cut": False},
        {"initial": "resume"},
        {"initial_zones_nits": ((1.0,),)},
        {"model": MODEL, "attack_s": -1, "release_s": 1},
        {"model": MODEL, "attack_s": True, "release_s": 1},
        {"model": MODEL, "attack_s": 1, "release_s": math.nan},
        {"model": MODEL, "attack_s": math.inf, "release_s": 1},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "slew_nits_per_tick": 0},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "slew_nits_per_tick": True},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "cut_detection_threshold": 0},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "cut_detection_threshold": 1.1},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "reset_on_scene_cut": 1},
        {
            "model": MODEL,
            "attack_s": 1,
            "release_s": 1,
            "cut_detection_threshold": 0.5,
            "reset_on_scene_cut": False,
        },
        {"model": MODEL, "attack_s": 1, "release_s": 1, "parameter_status": "measured"},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "initial": "unknown"},
        {"model": MODEL, "attack_s": 1, "release_s": 1, "initial": "explicit"},
        {
            "model": MODEL,
            "attack_s": 1,
            "release_s": 1,
            "initial": "explicit",
            "initial_zones_nits": [[1]],
        },
        {
            "model": MODEL,
            "attack_s": 1,
            "release_s": 1,
            "initial": "explicit",
            "initial_zones_nits": ((1,), (1, 2)),
        },
        {
            "model": MODEL,
            "attack_s": 1,
            "release_s": 1,
            "initial": "explicit",
            "initial_zones_nits": ((math.nan,),),
        },
        {
            "model": MODEL,
            "attack_s": 1,
            "release_s": 1,
            "initial": "resume",
            "initial_zones_nits": ((1,),),
        },
    ],
)
def test_invalid_or_competing_config_rejects(changes):
    with pytest.raises(ValueError):
        ZoneTemporalConfig(**changes)


@pytest.mark.parametrize("name", ["generic_woled", "generic_qdoled"])
def test_oled_and_combined_m13_reject(name):
    with pytest.raises(ValueError, match="LCD"):
        Pipeline(load_profile(name), zone_temporal=config())
    with pytest.raises(ValueError, match="M13"):
        Pipeline(
            load_profile(name),
            zone_temporal=config(),
            abl_dynamics=ABLDynamicsConfig(
                model="capacity_attack_release_v1", attack_ms=1, release_ms=1
            ),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("abl_response_ms", 1),
        ("abl_backlight_tracking", 0.1),
        ("abl_power_budget_nits", 1),
    ],
)
def test_legacy_controller_conflicts_reject_before_supplied_history_changes(field, value):
    original = profile()
    state, load = ZoneBacklightState(), LoadState(10)
    with pytest.raises(ValueError, match=field):
        Pipeline(
            replace(original, hdr=replace(original.hdr, **{field: value})),
            zone_temporal=config(),
            zone_state=state,
            load_state=load,
        )
    assert state.zones_nits is None and state.ticks == 0 and load.apl_nits == 10


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "per_pixel"),
        ("mode", "unknown"),
        ("zones_x", 0),
        ("zones_y", True),
        ("peak_nits", 0),
        ("floor_nits", -1),
        ("floor_nits", 1001),
        ("zone_percentile", 101),
        ("psf_tail_weight", -1),
        ("psf_tail_weight", math.nan),
        ("psf_shape", "unknown"),
        ("psf_boundary", "unknown"),
    ],
)
def test_invalid_zone_profile_rejects(field, value):
    original = profile()
    with pytest.raises(ValueError):
        Pipeline(
            replace(original, backlight=replace(original.backlight, **{field: value})),
            zone_temporal=config(),
        )


def test_bounds_and_effective_tiny_grid_shape():
    original = profile()
    bounded = replace(original, backlight=replace(original.backlight, floor_nits=10))
    pipeline = Pipeline(bounded, zone_temporal=config())
    pipeline.display_content(picture(0, (1, 2, 3)))
    assert pipeline.zone_state.zones_nits.shape == (1, 2)
    np.testing.assert_array_equal(pipeline.zone_state.zones_nits, [[10, 10]])
    pipeline.display_content(picture(1e6, (1, 2, 3)))
    np.testing.assert_array_equal(pipeline.last_zone_trace["targets_nits"], [[1000, 1000]])
    saved = pipeline.checkpoint()
    assert saved["geometry"]["y_edges"] == [0, 1]
    assert saved["geometry"]["x_edges"] == [0, 1, 2]


def test_explicit_grid_must_match_effective_shape_and_bounds():
    with pytest.raises(ValueError, match="bounds"):
        Pipeline(
            profile(), zone_temporal=config(initial="explicit", initial_zones_nits=((1001.0,),))
        )
    pipeline = Pipeline(
        profile(), zone_temporal=config(initial="explicit", initial_zones_nits=((100.0,),))
    )
    before = snapshot(pipeline)
    with pytest.raises(ValueError, match="grid"):
        pipeline.display_content(picture(100))
    assert snapshot(pipeline) == before


def test_spatial_transport_follows_filtered_commands_and_leakage_exposes_release_tail():
    original = profile()
    blurred = replace(
        original, backlight=replace(original.backlight, psf_sigma_zones=0.5, psf_sigma_y_zones=0.5)
    )
    pipeline = Pipeline(blurred, zone_temporal=config(initial="settled_first_tick"))
    bright = picture(0)
    bright.rgb[2:4, 4:8] = 800
    pipeline.display_content(bright)
    output = pipeline.display_content(picture(0), frame_time_ms=100)
    zones = pipeline.zone_state.zones_nits
    raw = upsample_zones(zones, zone_edges(8, 2), zone_edges(12, 3), (8, 12))
    kernels = psf_axis_kernels(blurred.backlight, zone_pitch_y=4, zone_pitch_x=4, per_pixel=False)
    expected_map = apply_light_spread(raw, kernels, blurred.backlight.psf_boundary)
    np.testing.assert_array_equal(output.backlight, expected_map)
    np.testing.assert_allclose(
        output.rgb[..., 0], expected_map / blurred.panel.native_contrast, atol=1e-8
    )
    assert output.rgb.max() > 0


def test_active_zero_tau_matches_matched_transport_and_preserves_legacy_off_exactly():
    original = profile()
    active = Pipeline(
        original, zone_temporal=ZoneTemporalConfig(model=MODEL, attack_s=0, release_s=0)
    )
    legacy, explicit_off = (
        Pipeline(original),
        Pipeline(original, zone_temporal=ZoneTemporalConfig()),
    )
    for level in (0, 900, 100, 1e6, 0):
        target = picture(level)
        a = active.display_content(target)
        b = legacy.display_content(target)
        c = explicit_off.display_content(target)
        np.testing.assert_array_equal(
            a.backlight,
            render_backlight(
                target, original.backlight, zone_targets(target, original.backlight)
            ).backlight,
        )
        assert b.rgb.tobytes() == c.rgb.tobytes()
        assert b.backlight.tobytes() == c.backlight.tobytes()
        assert legacy.state.previous.tobytes() == explicit_off.state.previous.tobytes()
        if level <= 1000:
            assert a.rgb.tobytes() == b.rgb.tobytes()


def test_over_peak_sparse_active_clipping_boundary_is_explicit():
    original = profile()
    original = replace(
        original, backlight=replace(original.backlight, psf_sigma_zones=0.7, psf_sigma_y_zones=0.7)
    )
    target = picture(0)
    target.rgb[2, 5] = 1e6
    bounded = render_backlight(target, original.backlight, zone_targets(target, original.backlight))
    legacy = simulate_backlight(target, original.backlight)
    assert not np.array_equal(bounded.backlight, legacy.backlight)


@pytest.mark.parametrize("mode", ["off", "repeat", "analytic", "mci"])
def test_each_sequence_updates_once_per_display_tick_and_declared_cut_once(mode):
    pipeline = Pipeline(profile(), zone_temporal=config(slew_nits_per_tick=10))
    sources = [np.full((8, 12, 3), level, np.float32) for level in (0, 1, 0)]
    motion = MotionConfig(mode=mode, source_fps=24, output_fps=None if mode == "off" else 60)
    outputs = list(pipeline.run_sequence(sources, motion, cuts=[1]))
    traces = [output.diagnostics["zone_backlight"] for output in outputs]
    assert pipeline.zone_state.ticks == len(outputs)
    assert [trace["ticks"] for trace in traces] == list(range(1, len(outputs) + 1))
    resets = [i for i, trace in enumerate(traces) if trace["scene_cut_reset"]]
    expected_index = 1 if mode == "off" else 3  # first 60 Hz tick in source interval 1
    assert resets == [expected_index]
    assert outputs[expected_index].diagnostics["source_index"] == 1
    assert outputs[expected_index].diagnostics["phase"] == ("0/1" if mode == "off" else "1/5")
    assert pipeline.zone_state.elapsed_ms == pytest.approx(
        len(outputs) * (profile().temporal.frame_time_ms if mode == "off" else 1000 / 60)
    )


@pytest.mark.parametrize("mode", ["repeat", "analytic", "mci"])
def test_cut_crossed_in_skipped_source_interval_resets_first_displayed_new_shot(mode):
    pipeline = Pipeline(profile(), zone_temporal=config())
    sources = [np.full((8, 12, 3), level, np.float32) for level in (0, 1, 1, 1, 1, 1)]
    outputs = list(
        pipeline.run_sequence(
            sources, MotionConfig(mode=mode, source_fps=60, output_fps=24), cuts=[1]
        )
    )
    assert [output.diagnostics["source_index"] for output in outputs] == [0, 2, 5]
    assert [output.diagnostics["zone_backlight"]["scene_cut_reset"] for output in outputs] == [
        False,
        True,
        False,
    ]


def test_mci_estimated_cut_is_not_relabelled_declared_zone_cut():
    pipeline = Pipeline(profile(), zone_temporal=config())
    sources = [np.full((8, 12, 3), level, np.float32) for level in (0, 1, 1)]
    outputs = list(
        pipeline.run_sequence(
            sources,
            MotionConfig(
                mode="mci",
                source_fps=24,
                output_fps=60,
                block=BlockMotionConfig(luma_reference_nits=100),
            ),
        )
    )
    assert any(output.diagnostics.get("scene_cut") for output in outputs)
    assert not any(output.diagnostics["zone_backlight"]["scene_cut_declared"] for output in outputs)


def test_temporal_exposure_samples_bfi_and_overdrive_do_not_add_zone_updates():
    original = profile()
    sampled = replace(
        original,
        temporal=replace(
            original.temporal,
            integration_samples=8,
            bfi_duty=0.5,
            overdrive_gain=0.3,
            overdrive_ms=2,
            response_time_ms=8,
        ),
    )
    one, two = Pipeline(original, zone_temporal=config()), Pipeline(sampled, zone_temporal=config())
    for level in (0, 800, 0):
        one.display_content(picture(level))
        two.display_content(picture(level))
        assert one.zone_state.ticks == two.zone_state.ticks
        assert one.zone_state.zones_nits.tobytes() == two.zone_state.zones_nits.tobytes()


def test_m10_changes_panel_output_without_changing_zone_targets():
    one = Pipeline(profile(), zone_temporal=config(initial="settled_first_tick"))
    two = Pipeline(
        profile(),
        zone_temporal=config(initial="settled_first_tick"),
        viewing_angle=ViewingAngleConfig(enabled=True, horizontal_deg=30),
    )
    one.display_content(picture(900))
    two.display_content(picture(900))
    first, second = one.display_content(picture(0)), two.display_content(picture(0))
    assert one.zone_state.zones_nits.tobytes() == two.zone_state.zones_nits.tobytes()
    assert not np.array_equal(first.rgb, second.rgb)
    assert one.identity() != two.identity()


def test_m15_targets_are_panel_domain_and_joint_capacity_has_one_owner(monkeypatch):
    import tv_sim.pipeline as runtime

    original = profile()
    original = replace(original, hdr=replace(original.hdr, abl_enabled=True, abl_source="demand"))
    pipeline = Pipeline(
        original,
        zone_temporal=config(),
        colorimetry=ColorimetryConfig(enabled=True, source_primaries="bt2020"),
    )
    calls = []
    joint = runtime.joint_tone_map

    def counted(*args, **kwargs):
        calls.append(1)
        return joint(*args, **kwargs)

    monkeypatch.setattr(runtime, "joint_tone_map", counted)
    target = picture(0)
    target.rgb[..., 0] = 800
    expected, _ = gamut_map(
        convert_rgb(target.rgb, pipeline._source_to_panel),
        pipeline.panel_colorimetry,
        pipeline.colorimetry.gamut_mapping,
        pipeline.colorimetry.compression_knee,
    )
    pipeline.display_content(target)
    np.testing.assert_array_equal(
        pipeline.last_zone_trace["targets_nits"], zone_targets(Frame(expected), original.backlight)
    )
    assert calls == [1]
    assert pipeline.last_colorimetry_diagnostics["capacity_owner"] == "joint_hdr_abl_rgbw_v1"


@pytest.mark.parametrize(
    "mutation",
    [
        "profile",
        "config",
        "angle",
        "geometry",
        "dtype",
        "gap",
        "past",
        "scene_cut",
        "nan",
        "negative",
        "temporal_failure",
    ],
)
def test_invalid_tick_rejects_atomically(mutation):
    pipeline = Pipeline(profile(), zone_temporal=config())
    pipeline.display_content(picture(700), frame_time_ms=10)
    target, kwargs = picture(200), {"frame_time_ms": 10}
    if mutation == "profile":
        pipeline.profile.backlight.peak_nits = 999
    elif mutation == "config":
        pipeline.zone_temporal = config()
    elif mutation == "angle":
        pipeline.viewing_angle = ViewingAngleConfig(enabled=True, horizontal_deg=20)
    elif mutation == "geometry":
        target = picture(200, (4, 4, 3))
    elif mutation == "dtype":
        target.rgb = target.rgb.astype(np.float64)
    elif mutation in ("gap", "past"):
        kwargs["timestamp_ms"] = 11 if mutation == "gap" else 9
    elif mutation == "scene_cut":
        kwargs["scene_cut"] = 1
    elif mutation in ("nan", "negative"):
        target.rgb[0, 0] = math.nan if mutation == "nan" else -1
    else:
        pipeline.profile.temporal.bfi_duty = 0
    before = snapshot(pipeline)
    with pytest.raises(ValueError):
        pipeline.display_content(target, **kwargs)
    assert snapshot(pipeline) == before


@pytest.mark.parametrize(
    "mutation", ["zones", "detector", "elapsed", "ticks", "panel", "load", "replacement"]
)
def test_external_state_mutation_rejects_render_and_checkpoint(mutation):
    pipeline = Pipeline(profile(), zone_temporal=config())
    pipeline.display_content(picture(800))
    if mutation == "zones":
        pipeline.zone_state.zones_nits[0, 0] += 1
    elif mutation == "detector":
        pipeline.zone_state.previous_targets[0, 0] += 1
    elif mutation == "elapsed":
        pipeline.zone_state.elapsed_ms += 1
    elif mutation == "ticks":
        pipeline.zone_state.ticks += 1
    elif mutation == "panel":
        pipeline.state.previous[0, 0] += 1
    elif mutation == "load":
        pipeline.load_state.apl_nits += 1
    else:
        pipeline.zone_state = ZoneBacklightState(
            grid(500), grid(800), pipeline.zone_state.elapsed_ms, 1
        )
    before = snapshot(pipeline)
    with pytest.raises(ValueError):
        pipeline.display_content(picture(500))
    with pytest.raises(ValueError):
        pipeline.checkpoint()
    assert snapshot(pipeline) == before


def test_shared_zone_history_cannot_have_two_advancing_owners():
    shared = ZoneBacklightState()
    first, second = [
        Pipeline(profile(), zone_temporal=config(), zone_state=shared) for _ in range(2)
    ]
    first.display_content(picture(100))
    with pytest.raises(ValueError, match="outside a tick"):
        second.display_content(picture(100))


@pytest.mark.parametrize("initial", ["cold", "settled_first_tick", "explicit"])
@pytest.mark.parametrize("color", [False, True])
def test_full_checkpoint_json_continuation_is_exact(initial, color):
    options = {"initial": initial, "cut_detection_threshold": 0.5, "slew_nits_per_tick": 47}
    if initial == "explicit":
        options["initial_zones_nits"] = ((300.0, 400.0, 500.0),) * 2
    original = profile()
    original = replace(original, temporal=replace(original.temporal, response_time_ms=8))
    colorimetry = ColorimetryConfig(enabled=color, source_primaries="bt2020")
    angle = ViewingAngleConfig(enabled=True, horizontal_deg=15)
    uninterrupted = Pipeline(
        original, zone_temporal=config(**options), colorimetry=colorimetry, viewing_angle=angle
    )
    for level, dt in ((100, 7), (700, 13), (600, 10)):
        uninterrupted.display_content(picture(level), frame_time_ms=dt)
    saved = json.loads(json.dumps(uninterrupted.checkpoint()))
    resumed = Pipeline(
        original,
        zone_temporal=config(initial="resume", cut_detection_threshold=0.5, slew_nits_per_tick=47),
        colorimetry=colorimetry,
        viewing_angle=angle,
    )
    resumed.restore_checkpoint(saved, shape=(8, 12, 3), dtype=np.float32, elapsed_ms=30)
    assert resumed.checkpoint() == saved
    for level, dt, cut in ((1000, 11, False), (0, 9, True), (800, 100, False), (0, 20, False)):
        a = uninterrupted.display_content(picture(level), frame_time_ms=dt, scene_cut=cut)
        b = resumed.display_content(picture(level), frame_time_ms=dt, scene_cut=cut)
        assert a.rgb.tobytes() == b.rgb.tobytes()
        assert a.backlight.tobytes() == b.backlight.tobytes()
        assert (
            resumed.zone_state.zones_nits.tobytes() == uninterrupted.zone_state.zones_nits.tobytes()
        )
        assert resumed.last_zone_trace == uninterrupted.last_zone_trace
        assert resumed.checkpoint() == uninterrupted.checkpoint()
    assert resumed.checkpoint()["initialization"]["policy"] == initial


@pytest.mark.parametrize(
    "difference", ["profile", "tau", "slew", "detector", "angle", "color", "shape", "dtype", "time"]
)
def test_checkpoint_identity_or_restore_constraint_rejects_atomically(difference):
    original = Pipeline(profile(), zone_temporal=config())
    original.display_content(picture(800))
    saved = original.checkpoint()
    p, options, kwargs, restore = profile(), {"initial": "resume"}, {}, {}
    if difference == "profile":
        p.backlight.peak_nits = 999
    elif difference == "tau":
        options["slew_nits_per_tick"] = None
        options["attack_s"] = 1
    elif difference == "slew":
        options["slew_nits_per_tick"] = 10
    elif difference == "detector":
        options["cut_detection_threshold"] = 0.3
    elif difference == "angle":
        kwargs["viewing_angle"] = ViewingAngleConfig(enabled=True, horizontal_deg=10)
    elif difference == "color":
        kwargs["colorimetry"] = ColorimetryConfig(enabled=True)
    elif difference == "shape":
        restore["shape"] = (4, 4, 3)
    elif difference == "dtype":
        restore["dtype"] = np.float64
    else:
        restore["elapsed_ms"] = 100
    settings = {"model": MODEL, "attack_s": 0.1, "release_s": 0.4, **options}
    resumed = Pipeline(p, zone_temporal=ZoneTemporalConfig(**settings), **kwargs)
    before = snapshot(resumed)
    with pytest.raises(ValueError):
        resumed.restore_checkpoint(saved, **restore)
    assert snapshot(resumed) == before


@pytest.mark.parametrize(
    "path,value",
    [
        ("schema_version", True),
        ("kind", "oled_capacity_full_history"),
        ("zone_state/ticks", 0),
        ("zone_state/ticks", True),
        ("zone_state/elapsed_ms_hex", "nan"),
        ("zone_state/elapsed_ms_hex", (-1.0).hex()),
        ("zone_state/zones/dtype", "<f4"),
        ("zone_state/zones/shape", [1, 6]),
        ("zone_state/previous_targets/base64", "invalid"),
        ("geometry/x_edges", [0, 5, 9, 12]),
        ("load_state/apl_nits_hex", "inf"),
        ("load_state/apl_nits_hex", (-1.0).hex()),
        ("initialization/policy", "resume"),
        ("initialization/evidence", "M"),
        ("initialization/zones_nits", [[1]]),
        ("history_sha256", "invalid"),
        ("last_source_sha256", "invalid"),
        ("evidence/measured_controller", "M"),
    ],
)
def test_checkpoint_semantic_corruption_rejects_even_with_recomputed_checksum(path, value):
    original = Pipeline(profile(), zone_temporal=config())
    original.display_content(picture(800))
    saved = original.checkpoint()
    node = saved
    keys = path.split("/")
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    saved["checkpoint_sha256"] = digest(
        {key: value for key, value in saved.items() if key != "checkpoint_sha256"}
    )
    resumed = Pipeline(profile(), zone_temporal=config(initial="resume"))
    before = snapshot(resumed)
    with pytest.raises(ValueError):
        resumed.restore_checkpoint(saved)
    assert snapshot(resumed) == before


def test_checkpoint_detects_nonfinite_or_out_of_bounds_array_payloads():
    original = Pipeline(profile(), zone_temporal=config())
    original.display_content(picture(800))
    for value in (math.nan, -1, 1001):
        saved = original.checkpoint()
        raw = grid(value).tobytes()
        from hashlib import sha256

        saved["zone_state"]["zones"]["base64"] = base64.b64encode(raw).decode()
        saved["zone_state"]["zones"]["sha256"] = sha256(raw).hexdigest()
        saved["checkpoint_sha256"] = digest(
            {key: item for key, item in saved.items() if key != "checkpoint_sha256"}
        )
        resumed = Pipeline(profile(), zone_temporal=config(initial="resume"))
        before = snapshot(resumed)
        with pytest.raises(ValueError):
            resumed.restore_checkpoint(saved)
        assert snapshot(resumed) == before


def test_checkpoint_requires_successful_tick_resume_requires_full_history_and_fresh_owner():
    fresh = Pipeline(profile(), zone_temporal=config())
    with pytest.raises(ValueError, match="successful"):
        fresh.checkpoint()
    resumed = Pipeline(profile(), zone_temporal=config(initial="resume"))
    with pytest.raises(ValueError, match="checkpoint"):
        resumed.display_content(picture(800))
    fresh.display_content(picture(800))
    saved = fresh.checkpoint()
    with pytest.raises(ValueError, match="resume"):
        fresh.restore_checkpoint(saved)
    resumed.restore_checkpoint(saved)
    with pytest.raises(ValueError, match="fresh"):
        resumed.restore_checkpoint(saved)
    with pytest.raises(ValueError, match="sole"):
        Pipeline(
            profile(),
            zone_temporal=config(initial="resume"),
            state=TemporalState(np.zeros((8, 12, 3), np.float32)),
        )


def test_partial_zone_state_and_stale_history_reject():
    with pytest.raises(ValueError, match="active"):
        Pipeline(profile(), zone_state=ZoneBacklightState())
    with pytest.raises(ValueError, match="matching explicit"):
        Pipeline(profile(), zone_temporal=config(), zone_state=ZoneBacklightState(grid(100)))
    with pytest.raises(ValueError, match="stale"):
        Pipeline(
            profile(),
            zone_temporal=config(),
            zone_state=ZoneBacklightState(grid(100), grid(100), 10, 1),
        )
    fresh = Pipeline(
        profile(),
        zone_temporal=config(initial="explicit", initial_zones_nits=((100.0,) * 3,) * 2),
        zone_state=ZoneBacklightState(grid(100)),
    )
    fresh.display_content(picture(100))
    assert fresh.zone_state.ticks == 1


def test_supplied_pixel_history_is_recorded_initialization_not_resume():
    previous = np.full((8, 12, 3), 30, np.float32)
    original = profile()
    original = replace(original, temporal=replace(original.temporal, response_time_ms=100))
    pipeline = Pipeline(original, zone_temporal=config(), state=TemporalState(previous))
    pipeline.display_content(picture(0))
    assert pipeline.state.previous.max() > 0
    assert "supplied_partial_history_sha256" in pipeline.checkpoint()["initialization"]


def test_long_rational_timestamp_clock_continues_without_false_gap():
    pipeline = Pipeline(profile(), zone_temporal=config())
    dt = Fraction(1000, 120)
    for tick in range(3601):
        pipeline.display_content(picture(0), frame_time_ms=float(dt), timestamp_ms=float(tick * dt))
    saved = pipeline.checkpoint()
    resumed = Pipeline(profile(), zone_temporal=config(initial="resume"))
    resumed.restore_checkpoint(saved, elapsed_ms=float(3601 * dt))
    assert resumed.checkpoint() == saved


def test_numpy_scalar_initial_clock_normalizes_before_exact_serialization():
    state = ZoneBacklightState(elapsed_ms=np.float32(0))
    pipeline = Pipeline(profile(), zone_temporal=config(), zone_state=state)
    pipeline.display_content(picture(100), frame_time_ms=10)
    assert type(state.elapsed_ms) is float
    assert pipeline.checkpoint()["zone_state"]["elapsed_ms_hex"] == (10.0).hex()


@pytest.mark.parametrize("field,value", [("load", 123), ("elapsed", 1), ("ticks", 1)])
def test_resume_cannot_overwrite_externally_invented_fresh_history(field, value):
    original = Pipeline(profile(), zone_temporal=config())
    original.display_content(picture(100))
    resumed = Pipeline(profile(), zone_temporal=config(initial="resume"))
    if field == "load":
        resumed.load_state.apl_nits = value
    else:
        setattr(resumed.zone_state, "elapsed_ms" if field == "elapsed" else "ticks", value)
    before = snapshot(resumed)
    with pytest.raises(ValueError, match="fresh|clock"):
        resumed.restore_checkpoint(original.checkpoint())
    assert snapshot(resumed) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", -1),
        ("target", 1001),
        ("target", math.nan),
        ("target_dtype", 0),
        ("state", -1),
        ("state", 1001),
        ("state", math.inf),
        ("state_dtype", 0),
        ("dt", 0),
        ("dt", -1),
        ("dt", math.inf),
        ("dt", True),
        ("elapsed", -1),
        ("elapsed", math.nan),
        ("ticks", True),
        ("ticks", -1),
        ("scene_cut", 1),
    ],
)
def test_invalid_unit_update_rejects_without_mutation(field, value):
    state, targets, dt, cut = ZoneBacklightState(grid(500)), grid(700), 10, False
    if field == "target":
        targets[0, 0] = value
    elif field == "target_dtype":
        targets = targets.astype(np.float32)
    elif field == "state":
        state.zones_nits[0, 0] = value
    elif field == "state_dtype":
        state.zones_nits = state.zones_nits.astype(np.float32)
    elif field == "dt":
        dt = value
    elif field in ("elapsed", "ticks"):
        setattr(state, "elapsed_ms" if field == "elapsed" else "ticks", value)
    else:
        cut = value
    before = (state.zones_nits.tobytes(), state.elapsed_ms, state.ticks)
    with pytest.raises(ValueError):
        update_zones(state, targets, profile().backlight, dt, config(), scene_cut=cut)
    assert state.zones_nits.tobytes() == before[0]
    if field != "elapsed" or not math.isnan(value):
        assert state.elapsed_ms == before[1]
    assert state.ticks == before[2]


@pytest.mark.parametrize("replacement", [None, object()])
def test_invalid_replaced_zone_owner_rejects_render_and_checkpoint(replacement):
    pipeline = Pipeline(profile(), zone_temporal=config())
    pipeline.display_content(picture(100))
    pipeline.zone_state = replacement
    with pytest.raises(ValueError, match="ZoneBacklightState"):
        pipeline.display_content(picture(100))
    with pytest.raises(ValueError, match="ZoneBacklightState"):
        pipeline.checkpoint()


def test_non_array_external_pixel_history_rejects_cleanly():
    pipeline = Pipeline(profile(), zone_temporal=config())
    pipeline.display_content(picture(100))
    pipeline.state.previous = [[[100, 100, 100]]]
    with pytest.raises(ValueError, match="NumPy arrays"):
        pipeline.display_content(picture(100))
    with pytest.raises(ValueError, match="NumPy arrays"):
        pipeline.checkpoint()
