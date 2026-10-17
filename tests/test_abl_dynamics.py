"""M13 synthetic controller correctness, history, and admission boundaries.

All numeric choices here are P test stimuli; computed expectations are D under
the M11 capacity-domain model. They do not calibrate an OLED or identify watts.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import json
import math

import numpy as np
import pytest

from sim.abl_dynamics import ABLDynamicsConfig, ABLCapacityState, digest, update_capacity
from sim.frame import Frame
from sim.load import LoadState
from sim.pipeline import Pipeline
from sim.profile import load_profile
from sim.sequence import MotionConfig
from sim.stages.temporal import TemporalState
from sim.viewing_angle import ViewingAngleConfig


MODEL = "capacity_attack_release_v1"


def config(**kwargs):
    return ABLDynamicsConfig(model=MODEL, attack_ms=100.0, release_ms=1000.0, **kwargs)


def profile(name="generic_woled", source="emitted"):
    original = load_profile(name)
    return replace(original, hdr=replace(original.hdr, abl_source=source))


def picture(level, shape=(12, 20, 3), fraction=1.0):
    rgb = np.zeros(shape, dtype=np.float32)
    h, w = max(1, round(shape[0] * math.sqrt(fraction))), max(1, round(shape[1] * math.sqrt(fraction)))
    y, x = (shape[0] - h) // 2, (shape[1] - w) // 2
    rgb[y:y+h, x:x+w] = level
    return Frame(rgb)


def snapshot(pipeline):
    """Save complete mutable history without allowing ndarray equality coercion."""
    return (None if pipeline.state.previous is None else pipeline.state.previous.tobytes(),
            pipeline.load_state.apl_nits,
            None if pipeline.capacity_state is None else asdict(pipeline.capacity_state))


@pytest.mark.parametrize("start,target,tau", [(850.0, 170.0, 100.0), (170.0, 850.0, 1000.0)])
def test_constant_target_e_fold_closed_form_and_bounds(start, target, tau):
    state = ABLCapacityState(capacity_nits=start)
    previous = start
    dt = tau / 10
    for index in range(1, 101):
        result = update_capacity(state, target, 850.0, 170.0, dt, config())
        expected = target + (start - target) * math.exp(-index * dt / tau)
        assert result == pytest.approx(expected, rel=1e-12, abs=1e-9)
        assert 170.0 <= result <= 850.0
        assert min(previous, target) <= result <= max(previous, target)
        assert state.capacity_nits == result
        assert state.ticks == index
        assert state.elapsed_ms == pytest.approx(index * dt)
        previous = result


def test_equal_target_has_no_capacity_drift_but_advances_clock():
    state = ABLCapacityState(capacity_nits=425.125)
    assert update_capacity(state, 425.125, 850.0, 170.0, 17.0, config()) == 425.125
    assert state == ABLCapacityState(capacity_nits=425.125, elapsed_ms=17.0, ticks=1)


@pytest.mark.parametrize("start,target,attack,release", [
    (850.0, 170.0, 0.0, 1e8), (170.0, 850.0, 1e8, 0.0),
])
def test_zero_tau_assigns_target_exactly_only_for_selected_direction(start, target, attack, release):
    settings = ABLDynamicsConfig(model=MODEL, attack_ms=attack, release_ms=release)
    state = ABLCapacityState(capacity_nits=start)
    assert update_capacity(state, target, 850.0, 170.0, 1e-15, settings) == target


@pytest.mark.parametrize("dt,tau", [(1e-300, 1e300), (1e300, 1e-300), (1e-6, 1e-3)])
def test_extreme_positive_dt_tau_stays_finite_and_bounded(dt, tau):
    settings = ABLDynamicsConfig(model=MODEL, attack_ms=tau, release_ms=tau)
    state = ABLCapacityState(capacity_nits=850.0)
    value = update_capacity(state, 170.0, 850.0, 170.0, dt, settings)
    assert math.isfinite(value) and 170.0 <= value <= 850.0


@pytest.mark.parametrize("target,start", [(170.0, 850.0), (850.0, 170.0)])
def test_split_duration_preserves_final_capacity(target, start):
    whole = ABLCapacityState(capacity_nits=start)
    divided = ABLCapacityState(capacity_nits=start)
    update_capacity(whole, target, 850.0, 170.0, 1000.0, config())
    for dt in (13.0, 27.0, 160.0, 300.0, 500.0):
        update_capacity(divided, target, 850.0, 170.0, dt, config())
    assert divided.capacity_nits == pytest.approx(whole.capacity_nits, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("changes", [
    {"model": "wrong"}, {"model": MODEL},
    {"model": MODEL, "attack_ms": 100},
    {"model": MODEL, "release_ms": 100},
    {"model": MODEL, "attack_ms": -1, "release_ms": 100},
    {"model": MODEL, "attack_ms": math.nan, "release_ms": 100},
    {"model": MODEL, "attack_ms": 100, "release_ms": math.inf},
    {"model": MODEL, "attack_ms": True, "release_ms": 100},
    {"model": MODEL, "attack_ms": 100, "release_ms": 100, "initial": "wrong"},
    {"model": MODEL, "attack_ms": 100, "release_ms": 100, "initial": "explicit"},
    {"model": MODEL, "attack_ms": 100, "release_ms": 100, "initial_capacity_nits": 500},
    {"model": MODEL, "attack_ms": 100, "release_ms": 100, "initial": "resume", "initial_capacity_nits": 500},
    {"model": MODEL, "attack_ms": 100, "release_ms": 100, "parameter_status": "measured"},
])
def test_invalid_config_rejected(changes):
    with pytest.raises(ValueError):
        ABLDynamicsConfig(**changes)


@pytest.mark.parametrize("field,value", [
    ("target", math.nan), ("target", math.inf), ("target", 0),
    ("target", 169), ("target", 851),
    ("peak", 0), ("peak", math.inf), ("floor", 0), ("floor", 851),
    ("dt", 0), ("dt", -1), ("dt", math.nan), ("dt", math.inf),
    ("capacity", 169), ("capacity", 851), ("capacity", math.nan),
    ("elapsed", -1), ("elapsed", math.inf), ("ticks", -1), ("ticks", 0.5),
])
def test_update_rejects_invalid_inputs_before_state_mutation(field, value):
    values = {"target": 500.0, "peak": 850.0, "floor": 170.0, "dt": 10.0}
    state = ABLCapacityState(capacity_nits=700.0)
    if field in values:
        values[field] = value
    else:
        setattr(state, {"capacity": "capacity_nits", "elapsed": "elapsed_ms", "ticks": "ticks"}[field], value)
    before = deepcopy(state)
    with pytest.raises(ValueError):
        update_capacity(state, values["target"], values["peak"], values["floor"], values["dt"], config())
    for key, original in asdict(before).items():
        actual = getattr(state, key)
        assert actual == original or (isinstance(actual, float) and math.isnan(actual) and math.isnan(original))


def test_cold_settled_first_and_explicit_onsets_are_distinct():
    cold = Pipeline(profile(), abl_dynamics=config())
    settled = Pipeline(profile(), abl_dynamics=config(initial="settled_first_tick"))
    explicit = Pipeline(profile(), abl_dynamics=config(initial="explicit", initial_capacity_nits=500))
    outputs = [p.display_content(picture(1000), frame_time_ms=10).rgb for p in (cold, settled, explicit)]
    assert cold.capacity_state.capacity_nits > explicit.capacity_state.capacity_nits > settled.capacity_state.capacity_nits
    assert outputs[0].mean() > outputs[2].mean() > outputs[1].mean()


@pytest.mark.parametrize("initial", [169.0, 851.0, math.nan, math.inf, -1.0])
def test_explicit_initial_capacity_must_fit_profile(initial):
    with pytest.raises(ValueError):
        Pipeline(profile(), abl_dynamics=config(initial="explicit", initial_capacity_nits=initial))


def test_black_pre_roll_recovers_capacity_analytically_and_sets_pixel_history():
    pipe = Pipeline(profile(), abl_dynamics=config(initial="explicit", initial_capacity_nits=200))
    for _ in range(10):
        rendered = pipe.display_content(picture(0), frame_time_ms=100)
        assert np.count_nonzero(rendered.rgb) == 0
    assert pipe.capacity_state.capacity_nits == pytest.approx(850 + (200 - 850) * math.exp(-1), rel=1e-12, abs=1e-9)
    assert np.count_nonzero(pipe.state.previous) == 0
    assert pipe.capacity_state.ticks == 10


@pytest.mark.parametrize("name", ["generic_woled", "generic_qdoled"])
@pytest.mark.parametrize("source", ["demand", "emitted"])
def test_zero_tau_images_and_pixel_history_match_legacy_exactly(name, source):
    baseline = Pipeline(profile(name, source))
    active = Pipeline(profile(name, source), abl_dynamics=ABLDynamicsConfig(model=MODEL, attack_ms=0, release_ms=0))
    for level, fraction, dt in [(0, 1, 13), (1000, .1, 17), (1000, 1, 11), (1000, .01, 21), (0, 1, 30)]:
        target = picture(level, fraction=fraction)
        expected = baseline.display_content(target, frame_time_ms=dt)
        actual = active.display_content(target, frame_time_ms=dt)
        assert actual.rgb.tobytes() == expected.rgb.tobytes()
        assert actual.backlight.tobytes() == expected.backlight.tobytes()
        assert active.state.previous.tobytes() == baseline.state.previous.tobytes()
    assert active.load_state.apl_nits is None


def test_active_mode_does_not_read_or_mutate_legacy_apl_state():
    one = Pipeline(profile(), load_state=LoadState(1.0), abl_dynamics=config())
    two = Pipeline(profile(), load_state=LoadState(123456.0), abl_dynamics=config())
    assert one.display_content(picture(1000)).rgb.tobytes() == two.display_content(picture(1000)).rgb.tobytes()
    assert one.load_state.apl_nits == 1.0 and two.load_state.apl_nits == 123456.0


def test_one_target_update_and_shoulder_per_tick_preserves_attack(monkeypatch):
    import sim.pipeline as runtime
    import sim.stages.tonemap as tonemap

    calls = {"target": 0, "update": 0, "shoulder": 0}
    original_update, original_shoulder, original_target = runtime.update_capacity, tonemap.soft_shoulder, runtime.target_trace
    def target(*args, **kwargs):
        calls["target"] += 1
        return original_target(*args, **kwargs)
    def update(*args, **kwargs):
        calls["update"] += 1
        return original_update(*args, **kwargs)
    def shoulder(*args, **kwargs):
        calls["shoulder"] += 1
        return original_shoulder(*args, **kwargs)
    monkeypatch.setattr(runtime, "update_capacity", update)
    monkeypatch.setattr(runtime, "target_trace", target)
    monkeypatch.setattr(tonemap, "soft_shoulder", shoulder)
    pipe = Pipeline(profile(), abl_dynamics=config())
    result = pipe.display_content(picture(1000), frame_time_ms=1)
    trace = pipe.last_capacity_trace
    assert trace["after_nits"] > trace["target_nits"]
    assert float(result.rgb.mean()) > trace["target_nits"] + 100
    assert calls["target"] == calls["update"] == calls["shoulder"] == 1


@pytest.mark.parametrize("field,value", [
    ("abl_response_ms", 1), ("abl_response_ms", -1),
    ("abl_backlight_tracking", 0.1), ("abl_power_budget_nits", 500),
    ("abl_enabled", False), ("tone_map", "clip"), ("abl_source", "final"),
    ("abl_reference_nits", -1), ("abl_reference_nits", math.nan),
    ("panel_peak_nits", math.inf), ("abl_full_field_nits", 0),
    ("abl_gamma", 0), ("abl_gamma", math.inf),
])
def test_profile_conflicts_rejected_without_mutating_supplied_histories(field, value):
    original = profile()
    conflicting = replace(original, hdr=replace(original.hdr, **{field: value}))
    capacity, load = ABLCapacityState(), LoadState(15)
    with pytest.raises(ValueError):
        Pipeline(conflicting, load_state=load, abl_dynamics=config(), capacity_state=capacity)
    assert capacity == ABLCapacityState() and load.apl_nits == 15


@pytest.mark.parametrize("name", ["generic_ips_edge", "generic_va_fald_miniled"])
def test_non_oled_profiles_rejected(name):
    with pytest.raises(ValueError, match="OLED|woled|technology"):
        Pipeline(load_profile(name), abl_dynamics=config())


@pytest.mark.parametrize("dt", [0, -1, math.nan, math.inf])
def test_invalid_tick_duration_changes_no_history(dt):
    pipe = Pipeline(profile(), abl_dynamics=config())
    pipe.display_content(picture(1000))
    before = snapshot(pipe)
    with pytest.raises(ValueError):
        pipe.display_content(picture(0), frame_time_ms=dt)
    assert snapshot(pipe) == before


def test_preparation_and_inspection_do_not_advance_history():
    pipe = Pipeline(profile(), abl_dynamics=config())
    before = snapshot(pipe)
    pipe.prepare_content(np.zeros((12, 20, 3), dtype=np.uint8))
    assert snapshot(pipe) == before


@pytest.mark.parametrize("mode", ["repeat", "analytic"])
def test_output_ticks_own_capacity_clock_even_for_repeated_pictures_and_cuts(mode):
    pipe = Pipeline(profile(), abl_dynamics=config())
    sources = [np.ones((12, 20, 3), dtype=np.float32)] * 3
    motion = MotionConfig(mode=mode, source_fps=24, output_fps=120,
                          translation_px=(0, 0) if mode == "analytic" else None)
    outputs = list(pipe.run_sequence(sources, motion, cuts=[1]))
    assert len(outputs) == pipe.capacity_state.ticks == 15
    assert pipe.capacity_state.elapsed_ms == pytest.approx(125)
    assert any(output.diagnostics["scene_cut"] for output in outputs)
    target = pipe.last_capacity_trace["target_nits"]
    expected = target + (850 - target) * math.exp(-125 / 100)
    assert pipe.capacity_state.capacity_nits == pytest.approx(expected, rel=1e-12, abs=1e-9)


def test_memc_off_uses_profile_clock_despite_irregular_source_pts():
    pipe = Pipeline(profile(), abl_dynamics=config())
    images = [np.zeros((12, 20, 3), dtype=np.uint8)] * 3
    outputs = list(pipe.run_sequence(images, MotionConfig(), source_pts=["0", "1/10", "3"], last_duration="2"))
    assert len(outputs) == pipe.capacity_state.ticks == 3
    assert pipe.capacity_state.elapsed_ms == 3 * pipe.profile.temporal.frame_time_ms


def test_temporal_integration_samples_and_bfi_do_not_add_capacity_updates():
    plain = Pipeline(profile(), abl_dynamics=config())
    original = profile()
    sampled = Pipeline(replace(original, temporal=replace(original.temporal, integration_samples=31, bfi_duty=.25)),
                       abl_dynamics=config())
    for level in (0, 1000, 1000, 0, 1000):
        for pipe in (plain, sampled):
            pipe.display_content(picture(level), frame_time_ms=10)
        assert asdict(plain.capacity_state) == asdict(sampled.capacity_state)


def test_different_prehistories_change_same_probe_and_recovery_brightens():
    fresh, loaded = (Pipeline(profile(), abl_dynamics=config()) for _ in range(2))
    for _ in range(60):
        fresh.display_content(picture(0), frame_time_ms=100)
        loaded.display_content(picture(1000), frame_time_ms=100)
    probe = picture(1000, fraction=.1)
    first_fresh = fresh.display_content(probe, frame_time_ms=10)
    first_loaded = loaded.display_content(probe, frame_time_ms=10)
    assert first_fresh.rgb.max() > first_loaded.rgb.max()
    capacities, centers = [], []
    for _ in range(200):
        frame = loaded.display_content(probe, frame_time_ms=100)
        capacities.append(loaded.capacity_state.capacity_nits)
        centers.append(float(frame.rgb.max()))
    assert all(b >= a for a, b in zip(capacities, capacities[1:]))
    assert all(b >= a for a, b in zip(centers, centers[1:]))
    assert capacities[-1] == pytest.approx(loaded.last_capacity_trace["target_nits"], abs=1e-5)


@pytest.mark.parametrize("changes", [
    {"attack_ms": 0}, {"release_ms": 0}, {"initial": "settled_first_tick"},
    {"initial": "explicit", "initial_capacity_nits": 500}, {"initial": "resume"},
])
def test_off_config_rejects_explicit_dynamic_options(changes):
    with pytest.raises(ValueError, match="off|active"):
        ABLDynamicsConfig(**changes)


@pytest.mark.parametrize("state", [
    ABLCapacityState(500, 100, 1), ABLCapacityState(500, 0, 1),
    ABLCapacityState(None, 100, 1), ABLCapacityState(500),
])
def test_stale_or_unowned_capacity_state_rejected(state):
    before = deepcopy(state)
    with pytest.raises(ValueError):
        Pipeline(profile(), abl_dynamics=config(), capacity_state=state)
    assert state == before


@pytest.mark.parametrize("mutation", ["profile", "config", "angle", "geometry", "dtype", "gap", "past"])
def test_mid_history_identity_or_unknown_time_change_rejected_atomically(mutation):
    pipe = Pipeline(profile(), abl_dynamics=config())
    pipe.display_content(picture(1000), frame_time_ms=10)
    before = snapshot(pipe)
    target, arguments = picture(0), {"frame_time_ms": 10}
    if mutation == "profile":
        pipe.profile = replace(pipe.profile, hdr=replace(pipe.profile.hdr, abl_gamma=3))
    elif mutation == "config":
        pipe.abl_dynamics = ABLDynamicsConfig()
    elif mutation == "angle":
        pipe.viewing_angle = ViewingAngleConfig(enabled=True, horizontal_deg=10)
    elif mutation == "geometry":
        target = picture(0, shape=(13, 20, 3))
    elif mutation == "dtype":
        target.rgb = target.rgb.astype(np.float64)
    else:
        arguments["timestamp_ms"] = 11 if mutation == "gap" else 9
    with pytest.raises(ValueError):
        pipe.display_content(target, **arguments)
    assert snapshot(pipe) == before


@pytest.mark.parametrize("value", [math.nan, math.inf, -1])
def test_invalid_requested_pixels_rejected_before_history_changes(value):
    pipe = Pipeline(profile(), abl_dynamics=config())
    pipe.display_content(picture(1000))
    target = picture(0)
    target.rgb[0, 0, 0] = value
    before = snapshot(pipe)
    with pytest.raises(ValueError):
        pipe.display_content(target)
    assert snapshot(pipe) == before


def test_demand_and_emitted_sources_stay_explicit_with_angular_gain():
    angle = ViewingAngleConfig(enabled=True, horizontal_deg=45)
    demand = Pipeline(profile(source="demand"), abl_dynamics=config(), viewing_angle=angle)
    emitted = Pipeline(profile(source="emitted"), abl_dynamics=config(), viewing_angle=angle)
    for pipe in (demand, emitted):
        pipe.display_content(picture(1000, fraction=.25), frame_time_ms=10)
    assert demand.last_capacity_trace["source"] == "demand"
    assert emitted.last_capacity_trace["source"] == "emitted"
    assert demand.last_capacity_trace["apl_nits"] > emitted.last_capacity_trace["apl_nits"]
    assert demand.last_capacity_trace["target_nits"] < emitted.last_capacity_trace["target_nits"]


def test_run_and_run_linear_each_advance_one_tick():
    pipe = Pipeline(profile(), abl_dynamics=config())
    encoded = np.full((12, 20, 3), 255, dtype=np.uint8)
    pipe.run(encoded)
    assert pipe.capacity_state.ticks == 1
    pipe.run_linear(encoded)
    assert pipe.capacity_state.ticks == 2
    assert pipe.capacity_state.elapsed_ms == 2 * pipe.profile.temporal.frame_time_ms


def _history_profile():
    original = profile()
    return replace(original, temporal=replace(original.temporal, response_time_ms=75, integration_samples=7))


def _checkpoint_source():
    source = Pipeline(_history_profile(), abl_dynamics=config(), load_state=LoadState(25.123))
    for level, fraction, dt in [(0, 1, 5), (1000, 1, 20), (1000, .1, 17), (0, 1, 13)]:
        source.display_content(picture(level, fraction=fraction), frame_time_ms=dt)
    return source


def test_full_checkpoint_json_roundtrip_resumes_images_and_histories_byte_for_byte():
    uninterrupted = _checkpoint_source()
    original = uninterrupted.checkpoint()
    saved = json.loads(json.dumps(original, allow_nan=False))
    resumed = Pipeline(_history_profile(), abl_dynamics=config(initial="resume"))
    resumed.restore_checkpoint(saved, shape=(12, 20, 3), dtype=np.float32,
                               elapsed_ms=uninterrupted.capacity_state.elapsed_ms)
    assert resumed.identity() == uninterrupted.identity()
    assert resumed.checkpoint() == original
    assert snapshot(resumed) == snapshot(uninterrupted)
    for level, fraction, dt in [(1000, .1, 7), (1000, 1, 21), (0, 1, 100), (1000, .25, 15)]:
        target = picture(level, fraction=fraction)
        expected = uninterrupted.display_content(target, frame_time_ms=dt)
        actual = resumed.display_content(target, frame_time_ms=dt)
        assert actual.rgb.tobytes() == expected.rgb.tobytes()
        assert actual.backlight.tobytes() == expected.backlight.tobytes()
        assert resumed.last_capacity_trace == uninterrupted.last_capacity_trace
        assert resumed.checkpoint() == uninterrupted.checkpoint()
    assert saved == original  # Restoring never mutates the caller's artifact.
    assert resumed.checkpoint()["initialization"]["policy"] == "cold"


def test_capacity_only_explicit_initialization_does_not_restore_pixel_history():
    source = _checkpoint_source()
    partial = Pipeline(_history_profile(), abl_dynamics=config(initial="explicit",
                       initial_capacity_nits=source.capacity_state.capacity_nits))
    target = picture(1000, fraction=.1)
    complete = source.display_content(target, frame_time_ms=10)
    incomplete = partial.display_content(target, frame_time_ms=10)
    assert partial.capacity_state.capacity_nits == source.capacity_state.capacity_nits
    assert complete.rgb.tobytes() != incomplete.rgb.tobytes()


@pytest.mark.parametrize("difference", ["profile", "config", "angle", "domain", "geometry", "dtype", "gap"])
def test_checkpoint_identity_shape_and_unknown_gap_rejected_before_mutation(difference):
    saved = _checkpoint_source().checkpoint()
    original = _history_profile()
    settings, kwargs, restore = config(initial="resume"), {}, {}
    if difference == "profile":
        original = replace(original, backlight=replace(original.backlight, peak_nits=800))
    elif difference == "config":
        settings = ABLDynamicsConfig(model=MODEL, attack_ms=101, release_ms=1000, initial="resume")
    elif difference == "angle":
        kwargs["viewing_angle"] = ViewingAngleConfig(enabled=True, horizontal_deg=1)
    elif difference == "domain":
        original = replace(original, hdr=replace(original.hdr, abl_source="demand"))
    elif difference == "geometry":
        restore["shape"] = (13, 20, 3)
    elif difference == "dtype":
        restore["dtype"] = np.float64
    else:
        restore["elapsed_ms"] = 56
    resumed = Pipeline(original, abl_dynamics=settings, **kwargs)
    before = snapshot(resumed)
    with pytest.raises(ValueError):
        resumed.restore_checkpoint(saved, **restore)
    assert snapshot(resumed) == before


@pytest.mark.parametrize("path,value", [
    ("schema_version", 2), ("identity/model", "wrong"),
    ("capacity_state/capacity_nits_hex", float(169).hex()),
    ("capacity_state/capacity_nits_hex", "nan"),
    ("capacity_state/elapsed_ms_hex", float(-1).hex()),
    ("capacity_state/ticks", 0), ("capacity_state/ticks", True),
    ("load_state/apl_nits_hex", "inf"),
    ("geometry/shape", [12, 21, 3]), ("geometry/dtype", "<f8"),
    ("temporal_state/previous_base64", "broken!"),
    ("temporal_state/previous_sha256", "0" * 64),
    ("history_sha256", "invalid"), ("last_source_sha256", "invalid"),
    ("initialization/policy", "resume"), ("initialization/capacity_nits", 500),
    ("evidence/model_and_initialization", "M"), ("evidence/states_and_clock", "M"),
    ("evidence/measured_prior_thermal_condition", "M"),
])
def test_checkpoint_semantic_validation_rejects_corruption_atomically(path, value):
    saved = _checkpoint_source().checkpoint()
    parts = path.split("/")
    destination = saved
    for part in parts[:-1]:
        destination = destination[part]
    destination[parts[-1]] = value
    # Re-sign the envelope to exercise semantic validation independently of
    # accidental-corruption detection. This is not a security signature.
    saved["checkpoint_sha256"] = digest({k: v for k, v in saved.items() if k != "checkpoint_sha256"})
    resumed = Pipeline(_history_profile(), abl_dynamics=config(initial="resume"))
    before = snapshot(resumed)
    with pytest.raises(ValueError):
        resumed.restore_checkpoint(saved)
    assert snapshot(resumed) == before


def test_checkpoint_checksum_geometry_on_next_tick_and_resume_ownership():
    source = _checkpoint_source()
    saved = source.checkpoint()
    corrupted = deepcopy(saved)
    corrupted["capacity_state"]["ticks"] += 1
    resumed = Pipeline(_history_profile(), abl_dynamics=config(initial="resume"))
    with pytest.raises(ValueError, match="integrity"):
        resumed.restore_checkpoint(corrupted)
    with pytest.raises(ValueError, match="resume"):
        source.restore_checkpoint(saved)
    resumed.restore_checkpoint(saved)
    before = snapshot(resumed)
    with pytest.raises(ValueError, match="geometry"):
        resumed.display_content(picture(0, shape=(10, 20, 3)))
    assert snapshot(resumed) == before
    with pytest.raises(ValueError, match="fresh|overwrite"):
        resumed.restore_checkpoint(saved)


def test_resume_requires_checkpoint_and_checkpoint_requires_successful_tick():
    resumed = Pipeline(profile(), abl_dynamics=config(initial="resume"))
    before = snapshot(resumed)
    with pytest.raises(ValueError, match="checkpoint"):
        resumed.display_content(picture(0))
    assert snapshot(resumed) == before
    with pytest.raises(ValueError, match="tick"):
        resumed.checkpoint()
    with pytest.raises(ValueError):
        Pipeline(profile()).checkpoint()


@pytest.fixture(scope="module")
def existing_m9_fit(tmp_path_factory):
    from sim.provenance import load_provenance
    from sim.window_replay import ReplayConditions, fit_windows, load_fit, save_fit

    conditions = ReplayConditions(level_nits=1000, settle_ms=0,
                                  hold_ms=1000/60, pre_roll_ms=1000/60)
    fit = fit_windows(profile(), load_provenance("generic_woled"), "c2_42_hdr_standard_peak",
                      "m13_rejection_fit", conditions=conditions, fractions=[1.0],
                      exploratory=True, width=20, height=12)
    path = tmp_path_factory.mktemp("m13-fit") / "synthetic.fit.json"
    save_fit(path, fit)
    return load_fit(path), conditions


@pytest.mark.parametrize("tau", [0, 100])
def test_existing_m9_fit_rejects_every_active_composition(existing_m9_fit, tau):
    from sim.provenance import load_provenance
    from sim.window_replay import fit_windows, replay_fit, replay_window

    saved, conditions = existing_m9_fit
    before = deepcopy(saved)
    active = ABLDynamicsConfig(model=MODEL, attack_ms=tau, release_ms=tau)
    with pytest.raises(ValueError, match="M9|schema-1|fit.json"):
        replay_fit(profile(), saved, abl_dynamics=active)
    with pytest.raises(ValueError, match="M9|schema-1|fit.json"):
        replay_window(profile(), 1.0, conditions, abl_dynamics=active)
    with pytest.raises(ValueError, match="M9|schema-1|fit.json"):
        fit_windows(profile(), load_provenance("generic_woled"), "c2_42_hdr_standard_peak",
                    "m13_must_reject", conditions=conditions, exploratory=True, abl_dynamics=active)
    assert saved == before


def test_existing_m9_fit_explicit_off_replay_is_exact(existing_m9_fit):
    from sim.window_replay import replay_fit

    saved, _ = existing_m9_fit
    omitted = replay_fit(profile(), saved)
    explicit = replay_fit(profile(), saved, abl_dynamics=ABLDynamicsConfig())
    assert [item.frame.rgb.tobytes() for item in omitted] == [item.frame.rgb.tobytes() for item in explicit]
    assert [item.center_trace_nits for item in omitted] == [item.center_trace_nits for item in explicit]


def test_long_contiguous_rational_timestamps_do_not_become_false_gaps():
    """Float64 elapsed summation must coexist with exact output PTS beyond 1 min."""
    pipe = Pipeline(profile(), abl_dynamics=config())
    target = picture(0, shape=(2, 2, 3))
    dt = Fraction(1000, 60)
    for tick in range(3601):
        pipe.display_content(target, frame_time_ms=float(dt), timestamp_ms=float(tick * dt))
    assert pipe.capacity_state.ticks == 3601
    checkpoint = pipe.checkpoint()
    resumed = Pipeline(profile(), abl_dynamics=config(initial="resume"))
    resumed.restore_checkpoint(checkpoint, elapsed_ms=float(3601 * dt))


@pytest.mark.parametrize("field,value", [("capacity_nits", 500), ("elapsed_ms", 100), ("ticks", 5)])
def test_external_valid_capacity_state_edits_cannot_invent_history(field, value):
    pipe = Pipeline(profile(), abl_dynamics=config())
    pipe.display_content(picture(1000), frame_time_ms=10)
    setattr(pipe.capacity_state, field, value)
    before = snapshot(pipe)
    with pytest.raises(ValueError, match="state|history|stale"):
        pipe.display_content(picture(0), frame_time_ms=10)
    assert snapshot(pipe) == before


def test_two_pipelines_cannot_silently_share_a_mutated_capacity_history():
    shared = ABLCapacityState()
    first = Pipeline(profile(), abl_dynamics=config(), capacity_state=shared)
    second = Pipeline(profile(), abl_dynamics=config(), capacity_state=shared)
    first.display_content(picture(1000), frame_time_ms=10)
    before = snapshot(second)
    with pytest.raises(ValueError, match="state|history|stale"):
        second.display_content(picture(0), frame_time_ms=10)
    assert snapshot(second) == before


@pytest.mark.parametrize("mutation", ["capacity_replacement", "panel_pixels", "panel_replacement", "load"])
def test_external_full_history_edits_reject_render_and_checkpoint(mutation):
    pipe = _checkpoint_source()
    if mutation == "capacity_replacement":
        original = pipe.capacity_state
        pipe.capacity_state = ABLCapacityState(500, original.elapsed_ms, original.ticks)
    elif mutation == "panel_pixels":
        pipe.state.previous[0, 0, 0] += 1
    elif mutation == "panel_replacement":
        pipe.state.previous = np.zeros_like(pipe.state.previous)
    else:
        pipe.load_state.apl_nits = 50
    before = snapshot(pipe)
    with pytest.raises(ValueError, match="state|history|stale"):
        pipe.display_content(picture(0))
    assert snapshot(pipe) == before
    with pytest.raises(ValueError, match="state|history|stale"):
        pipe.checkpoint()
    assert snapshot(pipe) == before


def test_supplied_initial_panel_history_is_distinct_recorded_partial_history():
    fresh = Pipeline(_history_profile(), abl_dynamics=config())
    prior = Pipeline(_history_profile(), state=TemporalState(picture(500).rgb), abl_dynamics=config())
    target = picture(0)
    assert fresh.display_content(target).rgb.tobytes() != prior.display_content(target).rgb.tobytes()
    fresh_saved, prior_saved = fresh.checkpoint(), prior.checkpoint()
    assert fresh_saved["history_sha256"] != prior_saved["history_sha256"]
    assert fresh_saved["identity"] == prior_saved["identity"]


@pytest.mark.parametrize("apl", [-1, math.inf, math.nan])
def test_unused_invalid_legacy_load_cannot_be_persisted_as_valid_checkpoint(apl):
    pipe = Pipeline(profile(), abl_dynamics=config(), load_state=LoadState(apl))
    # The active limiter does not turn unused APL history into a load input.
    pipe.display_content(picture(0))
    before = pipe.capacity_state.capacity_nits, pipe.capacity_state.elapsed_ms, pipe.capacity_state.ticks
    with pytest.raises(ValueError, match="APL|finite|nonnegative"):
        pipe.checkpoint()
    assert (pipe.capacity_state.capacity_nits, pipe.capacity_state.elapsed_ms, pipe.capacity_state.ticks) == before
