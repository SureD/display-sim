"""Opt-in window fits preserve experiment support and the forward pipeline."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sim.color import luminance, pq_oetf
from sim.frame import Frame
from sim.pipeline import Pipeline
from sim import pipeline as pipeline_module, profile as profiles
from sim.profile import load_profile
from sim.provenance import ProvenanceError, load_provenance
from sim import window_replay as windows
from sim.window_replay import (
    ReplayConditions, drive_profile, fit_windows, load_fit,
    measurement_conditions, replay_fit, replay_window, save_fit,
)


WIDTH, HEIGHT = 32, 24
SOURCE = "synthetic_placeholder_windows"
FITTED = "synthetic_placeholder_drive_fit"


@pytest.fixture
def conditions():
    return ReplayConditions(3000.0, settle_ms=30.0, hold_ms=20.0,
                            frame_time_ms=10.0, pre_roll_ms=20.0)


@pytest.fixture
def profile():
    original = load_profile("generic_va_fald_miniled")
    return replace(
        original,
        processing=replace(original.processing, sharpen_amount=0.0),
        backlight=replace(original.backlight, zones_x=4, zones_y=3),
        hdr=replace(original.hdr, abl_source="demand", abl_reference_nits=1800.0,
                    abl_full_field_nits=550.0, abl_power_budget_nits=180.0,
                    abl_response_ms=25.0, abl_backlight_tracking=0.8),
        temporal=replace(original.temporal, response_time_ms=14.0,
                         overdrive_gain=0.4, overdrive_ms=2.0,
                         overdrive_ceiling_nits=2200.0, bfi_duty=0.75,
                         integration_samples=4),
    )


def synthetic_source(profile, conditions, scales=(0.6, 1.7)):
    """Synthetic output targets are P, even though their numbers are exact."""
    data = load_provenance("generic_va_fald_miniled")
    dataset = deepcopy(data["datasets"]["x955_98_theatre_hdr_peak"])
    dataset["specimen"] = {
        "manufacturer": "synthetic", "model": "placeholder forward model",
        "diagonal_in": "NR", "region_panel_variant": "NR", "firmware": "NR",
    }
    dataset["source"].update(url="test://synthetic", locator="Synthetic test targets",
                             extraction="placeholder_forward_simulation")
    dataset["conditions"].update(measurement_conditions(profile, conditions, WIDTH, HEIGHT))
    dataset["nodes"] = [
        {"fraction": fraction,
         "luminance_nits": replay_window(profile, fraction, conditions, scale,
                                         width=WIDTH, height=HEIGHT).luminance_nits,
         "evidence": "P"}
        for fraction, scale in zip((0.25, 1.0), scales)
    ]
    dataset["support"]["range"] = [0.25, 1.0]
    dataset["notes"] = "P placeholder targets, not measured device readings"
    data["datasets"] = {SOURCE: dataset}
    return data


def fit(profile, data, conditions, **kwargs):
    return fit_windows(profile, data, SOURCE, FITTED, conditions=conditions,
                       width=WIDTH, height=HEIGHT, **kwargs)


def assert_identical(first, second):
    assert first.dtype == second.dtype
    assert first.shape == second.shape
    assert first.tobytes() == second.tobytes()


@pytest.mark.parametrize("abl_source", ["demand", "emitted"])
def test_fit_recovers_synthetic_drive_with_active_limits(profile, conditions, abl_source):
    profile = replace(profile, hdr=replace(profile.hdr, abl_source=abl_source))
    source = synthetic_source(profile, conditions)
    original = deepcopy(source)
    result = fit(profile, source, conditions, atol_nits=1e-4, rtol=1e-6)
    assert source == original
    assert result["assumptions"] == {}
    assert result["calibrated_profile_fit"] == result["timed_sustained_trace"] == "NR"
    assert result["model"]["evidence"] == "P"
    for node, expected in zip(result["nodes"], (0.6, 1.7)):
        assert node["drive_scale"]["value"] == pytest.approx(expected, rel=1e-5)
        assert node["drive_scale"]["evidence"] == "P"
        assert node["target"]["evidence"] == "P"
        assert node["simulation"]["evidence"] == "D"
        assert abs(node["simulation"]["residual_nits"]) <= 1e-4
    for node, replay in zip(result["nodes"], replay_fit(profile, result)):
        assert replay.luminance_nits == node["simulation"]["luminance_nits"]
        assert replay.center_trace_nits == node["simulation"]["center_trace_nits"]


@pytest.mark.parametrize("abl_source", ["demand", "emitted"])
def test_replay_limits_once_per_tick_and_matches_manual_history(
    monkeypatch, profile, conditions, abl_source
):
    profile = replace(profile, hdr=replace(profile.hdr, abl_source=abl_source))
    scale = 1.3
    # Construct a 25% centered window independently of replay's raster helper.
    rgb = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    rgb[6:18, 8:24] = conditions.level_nits
    manual = Pipeline(drive_profile(profile, scale))
    prepared = manual.prepare_content(pq_oetf(rgb))
    drive = Frame(prepared.rgb * np.float32(scale))
    black = manual.prepare_content(np.zeros_like(rgb))
    for _ in range(conditions.ticks("pre_roll_ms")):
        manual.display_content(black, frame_time_ms=conditions.frame_time_ms)
    trace = []
    for tick in range(conditions.ticks("settle_ms") + conditions.ticks("hold_ms")):
        expected = manual.display_content(drive, frame_time_ms=conditions.frame_time_ms)
        if tick >= conditions.ticks("settle_ms"):
            trace.append(float(np.mean(luminance(expected.rgb[11:13, 15:17]), dtype=np.float64)))

    counts = {}
    for name in ("simulate_backlight", "simulate_panel", "tone_map", "add_ambient",
                 "apply_temporal", "smooth_apl", "backlight_derate"):
        original = getattr(pipeline_module, name)

        def counted(*args, _name=name, _original=original, **kwargs):
            counts[_name] = counts.get(_name, 0) + 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(pipeline_module, name, counted)

    pipelines = []

    class RecordingPipeline(Pipeline):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            pipelines.append(self)

    monkeypatch.setattr(windows, "Pipeline", RecordingPipeline)
    actual = replay_window(profile, 0.25, conditions, scale, width=WIDTH, height=HEIGHT)
    ticks = sum(conditions.ticks(field) for field in ("pre_roll_ms", "settle_ms", "hold_ms"))
    assert len(pipelines) == 1
    assert set(counts.values()) == {ticks}
    assert actual.center_trace_nits == trace
    assert actual.luminance_nits == max(trace)
    assert actual.area_fraction_actual == 0.25
    assert actual.requested_apl_nits == pytest.approx(750.0)
    assert actual.drive_apl_nits == pytest.approx(actual.processed_request_apl_nits * scale)
    assert_identical(actual.frame.rgb, expected.rgb)
    assert_identical(actual.frame.backlight, expected.backlight)
    assert_identical(pipelines[0].state.previous, manual.state.previous)
    assert pipelines[0].load_state.apl_nits.hex() == manual.load_state.apl_nits.hex()
    # The output has passed real active limits; it is not the requested drive.
    assert actual.luminance_nits < conditions.level_nits * scale / 2


def test_shipped_nr_conditions_require_explicit_exploratory_mode(conditions):
    profile = load_profile("generic_woled")
    source = load_provenance(profile.name)
    kwargs = dict(conditions=conditions, fractions=[0.25], width=WIDTH, height=HEIGHT)
    with pytest.raises(ProvenanceError, match="NR.*exploratory"):
        fit_windows(profile, source, "c2_42_hdr_standard_peak", "c2_experiment", **kwargs)
    result = fit_windows(profile, source, "c2_42_hdr_standard_peak", "c2_experiment",
                         exploratory=True, **kwargs)
    assert result["condition_policy"] == "exploratory"
    assert result["assumptions"]["requested_window_nits"] == {
        "recorded": "NR", "value": 3000.0, "evidence": "P"}
    assert result["assumptions"]["settling_s"]["recorded"] == "NR"
    assert result["source_provenance"]["datasets"]["c2_42_hdr_standard_peak"]["conditions"]["dwell_s"] == "NR"
    assert result["nodes"][0]["target"]["evidence"] == "M"


@pytest.mark.parametrize("exploratory", [False, True])
@pytest.mark.parametrize("change", [
    {"requested_window_nits": 1000.0},
    {"source_encoding": "srgb"},
    {"source_rgb_primaries": "bt2020"},
    {"stimulus": "rgb_window_on_black"},
    {"stimulus_rgb_code": [1.0, 0.0, 0.0]},
    {"settling_s": 0.2},
    {"hold_s": 0.2},
    {"hold_statistic": "mean_over_hold"},
    {"refresh_hz": 60.0},
    {"prior_pattern_and_duration": {"stimulus": "white", "duration_s": 0.02}},
])
def test_known_amplitude_color_and_time_mismatches_always_fail(
    profile, conditions, change, exploratory
):
    source = synthetic_source(profile, conditions)
    source["datasets"][SOURCE]["conditions"].update(change)
    with pytest.raises(ProvenanceError, match="mismatch"):
        fit(profile, source, conditions, exploratory=exploratory)


def test_colored_window_requires_matching_color(profile, conditions):
    colored = replace(conditions, color_rgb=(1.0, 0.5, 0.25))
    source = synthetic_source(profile, colored)
    result = fit(profile, source, colored)
    assert result["matching_fields"]["stimulus"] == "rgb_window_on_black"
    assert result["conditions"]["color_rgb"] == [1.0, 0.5, 0.25]
    with pytest.raises(ProvenanceError, match="mismatch"):
        fit(profile, source, conditions, exploratory=True)


def test_strict_lookup_rejects_x955_below_two_percent_before_forward_run(monkeypatch, conditions):
    profile = load_profile("generic_va_fald_miniled")
    source = load_provenance(profile.name)

    def unexpected(*args, **kwargs):
        pytest.fail("out-of-support data reached the forward model")

    monkeypatch.setattr(windows, "replay_window", unexpected)
    with pytest.raises(ProvenanceError, match="outside support"):
        fit_windows(profile, source, "x955_98_theatre_hdr_peak", "invalid_small_window",
                    conditions=conditions, fractions=[0.01], exploratory=True,
                    width=WIDTH, height=HEIGHT)


@pytest.mark.parametrize("fractions", [None, [0.1]])
def test_unlocated_ips_peak_cannot_be_fitted(conditions, fractions):
    profile = load_profile("generic_ips_edge")
    with pytest.raises(ProvenanceError, match="unlocated|support range is NR"):
        fit_windows(profile, load_provenance(profile.name), "uh770v_55_hdr_peak_unlocated",
                    "unlocated_fit", conditions=conditions, fractions=fractions,
                    exploratory=True, width=WIDTH, height=HEIGHT)


def test_raw_nr_nodes_survive_and_interpolated_targets_stay_p(conditions):
    profile = load_profile("generic_va_fald_miniled")
    source = load_provenance(profile.name)
    result = fit_windows(profile, source, "x955_98_theatre_hdr_peak", "x955_gap_experiment",
                         conditions=conditions, fractions=[0.02, 0.035], exploratory=True,
                         width=WIDTH, height=HEIGHT)
    embedded = result["source_provenance"]["datasets"]["x955_98_theatre_hdr_peak"]
    assert embedded == source["datasets"]["x955_98_theatre_hdr_peak"]
    assert embedded["nodes"][0] == {"fraction": 0.01, "luminance_nits": "NR", "evidence": "NR"}
    assert result["nodes"][0]["target"]["evidence"] == "M"
    assert result["nodes"][1]["target"] == {
        "luminance_nits": 2337.5, "evidence": "P", "interpolated": True}
    assert result["support"]["interpolation"] == "none"


def test_raster_rounding_requires_exploratory_assumption(profile, conditions):
    source = synthetic_source(profile, conditions)
    with pytest.raises(ProvenanceError, match="rasterized fraction differs"):
        fit(profile, source, conditions, fractions=[0.5])
    result = fit(profile, source, conditions, fractions=[0.5], exploratory=True)
    node = result["nodes"][0]
    assert node["raster_assumption"] == {
        "nominal_fraction": 0.5, "actual_fraction": 23 * 17 / (WIDTH * HEIGHT), "evidence": "P"}
    assert node["simulation"]["area_fraction_actual"] == node["raster_assumption"]["actual_fraction"]
    assert node["target"]["evidence"] == "P"


@pytest.mark.parametrize("dataset_id", [SOURCE, "generic_va_fald_miniled", "", "../fit"])
def test_fitted_dataset_id_must_be_new_and_separate(profile, conditions, dataset_id):
    with pytest.raises(ProvenanceError, match="dataset ID"):
        fit_windows(profile, synthetic_source(profile, conditions), SOURCE, dataset_id,
                    conditions=conditions, width=WIDTH, height=HEIGHT)


def test_fit_file_is_separate_new_artifact_and_preserves_p_targets(
    tmp_path, monkeypatch, profile, conditions
):
    source = synthetic_source(profile, conditions)
    result = fit(profile, source, conditions)
    baseline = profiles.PROFILES_DIR / f"{profile.name}.yaml"
    baseline_bytes = baseline.read_bytes()
    destination = tmp_path / "fits" / "placeholder.fit.json"
    save_fit(destination, result)
    loaded = load_fit(destination)
    assert loaded["dataset_id"] == FITTED
    assert loaded["source_dataset_id"] == SOURCE
    assert all(node["target"]["evidence"] == "P" for node in loaded["nodes"])
    assert baseline.read_bytes() == baseline_bytes
    assert replay_fit(profile, loaded)[0].luminance_nits == result["nodes"][0]["simulation"]["luminance_nits"]
    with pytest.raises(FileExistsError):
        save_fit(destination, result)
    with pytest.raises(ProvenanceError, match=".fit.json"):
        save_fit(tmp_path / "baseline.yaml", result)
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path / "profiles")
    with pytest.raises(ProvenanceError, match="outside sim/profiles"):
        save_fit(profiles.PROFILES_DIR / "separate.fit.json", result)


def test_stale_baseline_and_modified_matching_record_are_rejected(profile, conditions):
    result = fit(profile, synthetic_source(profile, conditions), conditions)
    changed = replace(profile, hdr=replace(profile.hdr, abl_gamma=2.0))
    with pytest.raises(ProvenanceError, match="baseline profile changed"):
        replay_fit(changed, result)
    changed_artifact = deepcopy(result)
    changed_artifact["matching_fields"]["requested_window_nits"] = 500.0
    with pytest.raises(ProvenanceError, match="condition.*changed"):
        replay_fit(profile, changed_artifact)


def test_load_rejects_changed_target_evidence_and_drive_evidence(tmp_path, profile, conditions):
    result = fit(profile, synthetic_source(profile, conditions), conditions)
    for category, field, value in (("target", "evidence", "M"),
                                   ("drive_scale", "evidence", "M"),
                                   ("simulation", "evidence", "M"),
                                   ("drive_scale", "value", 0.0)):
        changed = deepcopy(result)
        changed["nodes"][0][category][field] = value
        path = tmp_path / f"{category}_{field}.fit.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ProvenanceError, match="evidence|scale"):
            load_fit(path)


def test_replay_rejects_a_changed_drive_that_misses_target(profile, conditions):
    result = fit(profile, synthetic_source(profile, conditions), conditions)
    result["nodes"][0]["drive_scale"]["value"] *= 1.5
    with pytest.raises(ProvenanceError, match="no longer matches target"):
        replay_fit(profile, result)


@pytest.mark.parametrize(("path", "value"), [
    (("raster", "height"), 0),
    (("matching_fields",), None),
    (("assumptions",), None),
    (("condition_policy",), None),
    (("solver", "atol_nits"), float("nan")),
    (("dataset_id",), "../source"),
    (("nodes", 0, "raster_assumption"), {"evidence": "P", "actual_fraction": 0.5}),
])
def test_malformed_persisted_records_raise_provenance_errors(
    tmp_path, profile, conditions, path, value
):
    record = fit(profile, synthetic_source(profile, conditions), conditions)
    parent = record
    for key in path[:-1]:
        parent = parent[key]
    if value is None:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    destination = tmp_path / "malformed.fit.json"
    destination.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ProvenanceError):
        load_fit(destination)


@pytest.mark.parametrize("kwargs", [
    {"level_nits": 0.0}, {"level_nits": float("nan")}, {"level_nits": 10001.0},
    {"level_nits": True}, {"color_rgb": (0.5, 0.5, 0.5)},
    {"color_rgb": (1.0, -0.1, 0.0)}, {"frame_time_ms": 0.0},
    {"settle_ms": -10.0}, {"settle_ms": 1.5}, {"hold_ms": 0.0},
    {"pre_roll_ms": 0.0}, {"pre_roll_ms": 15.0},
])
def test_invalid_replay_conditions_are_rejected(kwargs):
    parameters = dict(level_nits=1000.0, frame_time_ms=10.0, settle_ms=20.0,
                      hold_ms=20.0, pre_roll_ms=10.0)
    parameters.update(kwargs)
    with pytest.raises(ProvenanceError):
        ReplayConditions(**parameters)


@pytest.mark.parametrize("kwargs", [
    {"atol_nits": 0.0}, {"rtol": -1.0}, {"max_iterations": 0},
    {"max_iterations": True}, {"fractions": []}, {"fractions": [1.0, 0.25]},
    {"fractions": [0.25, 0.25]},
])
def test_invalid_fit_options_are_rejected(profile, conditions, kwargs):
    with pytest.raises(ProvenanceError):
        fit(profile, synthetic_source(profile, conditions), conditions, **kwargs)


def test_static_replay_rejects_resizing_motion_and_invalid_rasters(profile, conditions):
    profiles_to_reject = [
        replace(profile, processing=replace(profile.processing, scale_factor=2.0)),
        replace(profile, temporal=replace(profile.temporal, motion_px_per_frame=1.0)),
    ]
    for unsupported in profiles_to_reject:
        with pytest.raises(ProvenanceError, match="static replay"):
            replay_window(unsupported, 0.25, conditions, width=WIDTH, height=HEIGHT)
    for width in (3, 32.0, True):
        with pytest.raises(ProvenanceError, match="raster"):
            replay_window(profile, 0.25, conditions, width=width, height=HEIGHT)
    with pytest.raises(ProvenanceError, match="two pixels per axis"):
        replay_window(profile, 0.0001, conditions, width=WIDTH, height=HEIGHT)


def test_iteration_exhaustion_is_reported_instead_of_saving_partial_fit(profile, conditions):
    source = synthetic_source(profile, conditions)
    with pytest.raises(ProvenanceError, match="did not converge"):
        fit(profile, source, conditions, max_iterations=1, atol_nits=1e-8, rtol=0.0)


def test_zero_response_time_and_zero_targets_use_finite_absolute_tolerance(profile, conditions):
    profile = replace(profile, temporal=replace(profile.temporal, response_time_ms=0.0))
    source = synthetic_source(profile, conditions)
    for node in source["datasets"][SOURCE]["nodes"]:
        node["luminance_nits"] = 0.0
    result = fit(profile, source, conditions)
    assert all(0 <= node["simulation"]["luminance_nits"] <= 0.01 for node in result["nodes"])
    assert all(np.isfinite(node["drive_scale"]["value"]) for node in result["nodes"])


def test_black_preroll_exposes_onset_and_longer_settling_raises_hold_luminance():
    profile = load_profile("generic_woled")
    profile = replace(profile, temporal=replace(profile.temporal, response_time_ms=100.0),
                      processing=replace(profile.processing, sharpen_amount=0.0),
                      hdr=replace(profile.hdr, abl_enabled=False))
    onset = ReplayConditions(100.0, settle_ms=0.0, hold_ms=10.0,
                             frame_time_ms=10.0, pre_roll_ms=10.0)
    settled = replace(onset, settle_ms=200.0)
    immediate = replay_window(profile, 0.25, onset, width=WIDTH, height=HEIGHT)
    delayed = replay_window(profile, 0.25, settled, width=WIDTH, height=HEIGHT)
    instantaneous_profile = replace(profile, temporal=replace(profile.temporal, response_time_ms=0.0))
    steady = replay_window(instantaneous_profile, 0.25, onset, width=WIDTH, height=HEIGHT)
    assert immediate.luminance_nits == pytest.approx(steady.luminance_nits * (1 - np.exp(-0.1)), rel=1e-6)
    assert delayed.luminance_nits == pytest.approx(steady.luminance_nits * (1 - np.exp(-2.1)), rel=1e-6)
    assert 0 < immediate.luminance_nits < delayed.luminance_nits < steady.luminance_nits


def test_non_scalable_ambient_offset_rejects_unreachable_black_target(profile, conditions):
    profile = replace(profile, ambient=replace(profile.ambient, lux=1000.0))
    source = synthetic_source(profile, conditions)
    source["datasets"][SOURCE]["nodes"][0]["luminance_nits"] = 0.0
    with pytest.raises(ProvenanceError, match="unreachable"):
        fit(profile, source, conditions)


@pytest.mark.parametrize("exploratory", [False, True])
def test_cli_fit_windows_requires_opt_in_for_shipped_unknowns(tmp_path, exploratory):
    output = tmp_path / "cli.fit.json"
    command = [sys.executable, "-m", "sim", "fit-windows", "--profile", "generic_woled",
               "--source-dataset", "c2_42_hdr_standard_peak", "--dataset-id", "cli_experiment",
               "--out", str(output), "--fractions", "0.25", "--level-nits", "3000",
               "--settle-ms", "20", "--hold-ms", "20", "--frame-time-ms", "10",
               "--pre-roll-ms", "10", "--width", str(WIDTH), "--height", str(HEIGHT)]
    if exploratory:
        command.append("--exploratory")
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, check=False)
    if exploratory:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "cli_experiment" in result.stdout
        assert "calibration NR" in result.stdout
        assert load_fit(output)["nodes"][0]["target"]["evidence"] == "M"
    else:
        assert result.returncode != 0
        assert "NR" in result.stderr and "exploratory" in result.stderr
        assert not output.exists()
