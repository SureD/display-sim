"""M18 ownership, rational sequence composition, rejection and disabled parity."""

import base64
import math
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from tv_sim import ABLDynamicsConfig, Frame, MotionConfig, Pipeline, SubframeConfig, load_profile
from tv_sim.block_motion import BlockMotionConfig
from tv_sim.profile import TemporalParams
from tv_sim.stages.temporal import TemporalState
from tv_sim.viewing_angle import ViewingAngleConfig
from tv_sim.zone_temporal import ZoneTemporalConfig


def profile(name="generic_va_fald_miniled"):
    """Explicit ideal spatial/legacy-temporal controls for a synthetic M18 run."""
    p = load_profile(name)
    return replace(
        p,
        temporal=TemporalParams(response_time_ms=0, sample_and_hold=False),
        processing=replace(p.processing, sharpen_amount=0),
        ambient=replace(p.ambient, lux=0),
        backlight=replace(p.backlight, psf_sigma_zones=0, psf_tail_weight=0),
    )


def config(**kwargs):
    return SubframeConfig(model="subframe_emission_v1", rise_tau_ms=3, fall_tau_ms=7, **kwargs)


@pytest.mark.parametrize(
    "name", ["generic_va_fald_miniled", "generic_ips_edge", "generic_woled", "generic_qdoled"]
)
def test_disabled_exact_images_and_histories(name):
    p = load_profile(name)
    baseline, disabled = Pipeline(p), Pipeline(p, subframe=SubframeConfig())
    rng = np.random.default_rng(18)
    for _ in range(4):
        image = rng.random((5, 9, 3), dtype=np.float32)
        a, b = baseline.run_linear(image), disabled.run_linear(image)
        assert a.rgb.tobytes() == b.rgb.tobytes()
        assert baseline.state.previous.tobytes() == disabled.state.previous.tobytes()
        assert baseline.load_state.apl_nits == disabled.load_state.apl_nits
        assert disabled.last_subframe_result is None


@pytest.mark.parametrize(
    "name", ["generic_va_fald_miniled", "generic_ips_edge", "generic_woled", "generic_qdoled"]
)
def test_rational_samples_and_independent_state(name):
    pipe = Pipeline(profile(name), subframe=config(substeps=7, initial="cold"))
    start, step = Fraction(17, 19), Fraction(1001, 60000)
    for i, level in enumerate((1, 150, 40)):
        result = pipe.display_subframes(
            Frame(np.full((4, 6, 3), level)), pts=start + i * step, duration=step
        )
        assert len(result.samples) == 7
        for j, sample in enumerate(result.samples):
            assert sample.pts == start + i * step + j * step / 7
            assert sample.duration == step / 7
        np.testing.assert_array_equal(
            result.mean, np.mean([s.rgb for s in result.samples], axis=0).astype(np.float32)
        )
        endpoint = pipe.subframe_state.previous.copy()
        result.endpoint[:] = 0
        result.samples[-1].panel[:] = 0
        np.testing.assert_array_equal(pipe.subframe_state.previous, endpoint)
        assert pipe.state.previous is None
        assert pipe.load_state.apl_nits is None


@pytest.mark.parametrize("mode", ["off", "repeat", "analytic", "mci"])
@pytest.mark.parametrize("owner", ["none", "zone", "capacity"])
def test_all_sequence_modes_update_each_owner_once(mode, owner):
    name = "generic_woled" if owner == "capacity" else "generic_va_fald_miniled"
    kwargs = {}
    if owner == "zone":
        kwargs["zone_temporal"] = ZoneTemporalConfig(
            model="zone_attack_release_v1", attack_s=0.04, release_s=0.08
        )
    if owner == "capacity":
        kwargs["abl_dynamics"] = ABLDynamicsConfig(
            model="capacity_attack_release_v1", attack_ms=20, release_ms=60
        )
    pipe = Pipeline(profile(name), subframe=config(substeps=3), **kwargs)
    settings = MotionConfig(
        mode=mode,
        source_fps="24",
        output_fps=None if mode == "off" else "60000/1001",
        translation_px=(1, 0) if mode == "analytic" else None,
        block=BlockMotionConfig(block_size=8) if mode == "mci" else None,
    )
    frames = [np.full((8, 16, 3), v, dtype=np.float32) for v in (0.2, 0.4, 0.8)]
    outputs = list(pipe.run_sequence(frames, settings, cuts=[1]))
    assert pipe.subframe_state.ticks == len(outputs)
    if pipe.zone_state is not None:
        assert pipe.zone_state.ticks == len(outputs)
    if pipe.capacity_state is not None:
        assert pipe.capacity_state.ticks == len(outputs)
    for out in outputs:
        assert out.subframes is not None
        assert out.subframes.samples[0].pts == Fraction(out.diagnostics["output_pts"])
        assert out.frame.rgb.tobytes() == out.subframes.mean.tobytes()
    if mode != "off":
        assert outputs[0].subframes.samples[0].duration == Fraction(1001, 60000) / 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_time_ms", 1),
        ("overdrive_gain", 1),
        ("overdrive_ms", 1),
        ("overdrive_ceiling_nits", 100),
        ("motion_px_per_frame", 2),
        ("bfi_duty", 0.5),
        ("bfi_preserve_mean", True),
        ("integration_samples", 2),
    ],
)
def test_legacy_temporal_conflicts(field, value):
    p = profile()
    p = replace(p, temporal=replace(p.temporal, **{field: value}))
    with pytest.raises(ValueError, match="legacy"):
        Pipeline(p, subframe=config())


@pytest.mark.parametrize(
    "field", ["abl_response_ms", "abl_backlight_tracking", "abl_power_budget_nits"]
)
def test_load_conflicts(field):
    p = profile()
    with pytest.raises(ValueError, match=field):
        Pipeline(replace(p, hdr=replace(p.hdr, **{field: 1})), subframe=config())


def test_m10_m15_and_partial_histories_reject():
    from tv_sim import ColorimetryConfig

    with pytest.raises(ValueError, match="M10"):
        Pipeline(
            profile(),
            subframe=config(),
            viewing_angle=ViewingAngleConfig(enabled=True, horizontal_deg=20),
        )
    with pytest.raises(ValueError, match="M15"):
        Pipeline(profile(), subframe=config(), colorimetry=ColorimetryConfig(enabled=True))
    with pytest.raises(ValueError, match="fresh Pipeline"):
        Pipeline(
            profile(), subframe=config(), state=TemporalState(np.ones((2, 3, 3), dtype=np.float32))
        )


def test_zone_cut_does_not_reset_lc_history():
    pipe = Pipeline(
        profile(),
        subframe=config(),
        zone_temporal=ZoneTemporalConfig(
            model="zone_attack_release_v1", attack_s=0.1, release_s=0.2
        ),
    )
    for i, level in enumerate((100, 0)):
        result = pipe.display_subframes(
            Frame(np.full((4, 6, 3), level)),
            pts=Fraction(i, 60),
            duration=Fraction(1, 60),
            scene_cut=i == 1,
        )
    assert pipe.last_zone_trace["scene_cut_reset"]
    assert pipe.subframe_state.ticks == pipe.zone_state.ticks == 2
    assert np.any(result.endpoint > 1 / pipe.profile.panel.native_contrast)


@pytest.mark.parametrize(
    "bad", ["gap", "negative", "nan", "geometry", "scene_cut", "mutable_state", "config", "profile"]
)
def test_rejection_is_atomic(bad):
    pipe = Pipeline(
        profile(),
        subframe=config(),
        zone_temporal=ZoneTemporalConfig(
            model="zone_attack_release_v1", attack_s=0.01, release_s=0.02
        ),
    )
    frame = Frame(np.full((3, 4, 3), 100))
    pipe.display_subframes(frame, pts=Fraction(0), duration=Fraction(1, 60))
    before = pipe.checkpoint()
    next_pts = Fraction(1, 60)
    kwargs = {}
    if bad == "gap":
        next_pts += 1
    if bad == "negative":
        frame.rgb[:] = -1
    if bad == "nan":
        frame.rgb[:] = np.nan
    if bad == "geometry":
        frame = Frame(np.zeros((2, 2, 3)))
    if bad == "scene_cut":
        kwargs["scene_cut"] = 1
    if bad == "mutable_state":
        pipe.subframe_state.previous[:] = 0.5
    if bad == "config":
        pipe.subframe = replace(pipe.subframe, substeps=2)
    if bad == "profile":
        pipe.profile = replace(pipe.profile, description="changed")
    with pytest.raises(ValueError):
        pipe.display_subframes(frame, pts=next_pts, duration=Fraction(1, 60), **kwargs)
    # Every owner stays at the last successful tick even for candidate-zone failures.
    assert pipe.zone_state.ticks == pipe.subframe_state.ticks == 1
    assert pipe.zone_state.zones_nits.tobytes() == base64.b64decode(
        before["states"]["zones"]["zones"]["base64"]
    )
    if bad not in ("mutable_state", "config", "profile"):
        assert pipe.checkpoint() == before


def test_m9_admission():
    from tv_sim.window_replay import ReplayConditions, fit_windows, replay_fit, replay_window

    for func, args, kwargs in [
        (replay_window, (profile(), 0.1, ReplayConditions(100)), {}),
        (fit_windows, (profile(), {}, "source", "fit"), {"conditions": ReplayConditions(100)}),
        (replay_fit, (profile(), {}), {}),
    ]:
        with pytest.raises(ValueError, match="M9.*subframe"):
            func(*args, subframe=config(), **kwargs)


def test_unrealizable_hdr_leakage_target_rejects_atomically():
    p = profile()
    p = replace(
        p,
        backlight=replace(p.backlight, floor_nits=1000, peak_nits=1000),
        panel=replace(p.panel, native_contrast=1000),
        hdr=replace(p.hdr, panel_peak_nits=0.1, abl_enabled=False),
    )
    pipe = Pipeline(p, subframe=config())
    with pytest.raises(ValueError, match="HDR steady target"):
        pipe.display_subframes(
            Frame(np.zeros((2, 3, 3))), pts=Fraction(0), duration=Fraction(1, 60)
        )
    assert pipe.subframe_state.ticks == 0


def test_zero_tau_lcd_uses_filtered_zone_illumination_leakage_and_ungated_ambient():
    """An independent optical calculation checks every owner in the cascade."""
    p = profile()
    p = replace(
        p,
        backlight=replace(p.backlight, zones_x=1, zones_y=1, floor_nits=10, peak_nits=1000),
        panel=replace(p.panel, native_contrast=1000),
        hdr=replace(p.hdr, abl_enabled=False, panel_peak_nits=1000),
        ambient=replace(p.ambient, lux=math.pi, reflectance=1),
    )
    settings = SubframeConfig(
        model="subframe_emission_v1",
        substeps=3,
        rise_tau_ms=0,
        fall_tau_ms=0,
        initial="cold",
        pwm_hz="60",
        pwm_duty="1/4",
        strobe_duty="1/2",
    )
    zones = ZoneTemporalConfig(model="zone_attack_release_v1", attack_s=0.1, release_s=0.2)
    pipe = Pipeline(p, subframe=settings, zone_temporal=zones)
    duration = Fraction(1, 60)
    bright = pipe.display_subframes(
        Frame(np.full((2, 3, 3), 100)), pts=Fraction(0), duration=duration
    )
    illumination = 10 + (100 - 10) * (-math.expm1(-float(duration) / 0.1))
    np.testing.assert_allclose(pipe.zone_state.zones_nits, illumination, rtol=2e-15)
    assert np.all(bright.endpoint == 1)
    # Illumination crosses into existing float32 optics once before the
    # float64 emission model. The independent mean retains that explicit cast.
    expected_bright = np.float32(illumination) * 0.25 + 1
    np.testing.assert_allclose(bright.mean, expected_bright, rtol=1e-7)
    dark = pipe.display_subframes(Frame(np.zeros((2, 3, 3))), pts=duration, duration=duration)
    illumination = 10 + (illumination - 10) * math.exp(-float(duration) / 0.2)
    np.testing.assert_allclose(pipe.zone_state.zones_nits, illumination, rtol=2e-15)
    assert np.all(dark.endpoint == 0.001)
    np.testing.assert_allclose(dark.mean, np.float32(illumination) * 0.001 * 0.25 + 1, rtol=1e-7)
    assert pipe.zone_state.ticks == pipe.subframe_state.ticks == 2
    assert any(np.all(sample.rgb == 1) for sample in dark.samples)


def test_oled_bfi_only_reduces_emission_after_single_m13_capacity_update():
    p = profile("generic_woled")
    p = replace(p, ambient=replace(p.ambient, lux=0))
    capacity = ABLDynamicsConfig(
        model="capacity_attack_release_v1",
        attack_ms=20,
        release_ms=60,
        initial="cold",
    )
    hold = SubframeConfig(model="subframe_emission_v1", substeps=3, rise_tau_ms=0, fall_tau_ms=0)
    baseline = Pipeline(p, subframe=hold, abl_dynamics=capacity)
    inserted = Pipeline(
        p, subframe=replace(hold, bfi_duty="1/4", bfi_phase="3/4"), abl_dynamics=capacity
    )
    duration = Fraction(1001, 60000)
    for index, level in enumerate((500, 50, 400, 100)):
        frame = Frame(np.full((2, 3, 3), level))
        a = baseline.display_subframes(frame, pts=index * duration, duration=duration)
        b = inserted.display_subframes(frame, pts=index * duration, duration=duration)
        assert a.endpoint.tobytes() == b.endpoint.tobytes()
        assert baseline.capacity_state == inserted.capacity_state
        assert inserted.capacity_state.ticks == inserted.subframe_state.ticks == index + 1
        np.testing.assert_array_equal(b.mean, a.mean * np.float32(0.25))
