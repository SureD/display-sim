"""Synthetic acquisition protocol, history ownership and exclusive artifacts."""

import json
import math
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest
from PIL import Image

from tv_sim.abl_dynamics import MODEL, ABLDynamicsConfig
from tv_sim.cli import main as cli_main
from tv_sim.frame import Frame
from tv_sim.oled_dynamics_experiment import (
    DEFAULT_PROTOCOL,
    build_parser,
    load_protocol,
    run_experiment,
    validate_protocol,
)
from tv_sim.profile import load_profile, profile_path
from tv_sim.stages.encode import encode_frame


def config(**kwargs):
    return ABLDynamicsConfig(model=MODEL, attack_ms=100, release_ms=1000, **kwargs)


def protocol(segments=None):
    value = load_protocol()
    value["settings"].update(
        width=40, height=24, output_fps="100", onset_interval_s="0.02", late_interval_s="0.03"
    )
    if segments is None:
        segments = [
            ("black_preroll", 0, "0.01"),
            ("small", 0.01, "0.02"),
            ("full_load", 1, "0.2"),
            ("small_recovery", 0.01, "0.3"),
            ("black_release", 0, "0.02"),
        ]
    value["trials"] = [
        {
            "trial_id": "compact",
            "family": "history",
            "segments": [
                {"label": label, "fraction": fraction, "duration_s": duration}
                for label, fraction, duration in segments
            ],
        }
    ]
    return value


def trace(out, trial):
    return json.loads((out / trial["trial_id"] / trial["trace_file"]).read_text())["ticks"]


def test_shipped_protocol_covers_research_sequences():
    value = load_protocol()
    assert DEFAULT_PROTOCOL.is_file()
    assert value["parameter_status"] == "placeholder" and value["evidence"] == "P"
    assert value["demonstration"] == {"attack_ms": 100, "release_ms": 1000, "initial": "cold"}
    assert all(item == "NR" for item in value["unavailable"].values())
    assert value["settings"]["level_nits"] == 1000
    families = {t["family"] for t in value["trials"]}
    assert families == {
        "load_and_recovery",
        "black_gap_recovery",
        "small_large_small",
        "matched_probe_history",
    }
    assert {
        t["segments"][2]["fraction"] for t in value["trials"] if t["family"] == "small_large_small"
    } == {0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 0.75, 1}
    assert {
        t["segments"][2]["duration_s"]
        for t in value["trials"]
        if t["family"] == "black_gap_recovery"
    } == {"0", "0.1", "1", "5"}


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda p: p.update(schema_version=2), "schema_version"),
        (lambda p: p.update(extra=1), "exactly"),
        (lambda p: p.update(evidence="M"), "P evidence"),
        (lambda p: p.update(parameter_status="calibrated"), "placeholder"),
        (lambda p: p["unavailable"].update(measured_attack_ms=0), "remain NR"),
        (lambda p: p["settings"].update(width=True), "width"),
        (lambda p: p["settings"].update(level_nits=float("nan")), "level_nits"),
        (lambda p: p["settings"].update(output_fps="0"), "output_fps"),
        (lambda p: p["settings"].update(ambient_lux=1), "ambient_lux"),
        (lambda p: p["settings"].update(bfi_duty=0.5), "bfi_duty"),
        (lambda p: p["settings"].update(horizontal_deg=10), "horizontal_deg"),
        (lambda p: p["trials"][0]["segments"][0].update(duration_s="0.001"), "whole output ticks"),
        (lambda p: p["trials"][0]["segments"][1].update(duration_s="0"), "black gap"),
        (lambda p: p["trials"][0]["segments"][0].update(fraction=-1), "fraction"),
        (lambda p: p["trials"].append(deepcopy(p["trials"][0])), "unique"),
        (lambda p: p["trials"][0].update(trial_id="../profiles"), "trial_id"),
        (lambda p: p["demonstration"].update(attack_ms=float("inf")), "attack_ms"),
    ],
)
def test_protocol_rejections(mutate, match):
    value = protocol()
    mutate(value)
    with pytest.raises(ValueError, match=match):
        validate_protocol(value)


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_protocol(path)


def test_explicit_tick_history_trace_and_shared_exposure(tmp_path):
    profile = load_profile("generic_woled")
    original = deepcopy(profile)
    out = tmp_path / "experiment"
    manifest = run_experiment(profile, config(), protocol(), out, gallery=True)
    assert profile == original
    assert len(manifest["trials"]) == 2
    assert len({t["trial_id"] for t in manifest["trials"]}) == 2
    assert {t["load_source"] for t in manifest["trials"]} == {"demand", "emitted"}
    assert manifest["preview"]["reference_nits"] == 1000
    assert (out / "index.html").is_file()
    assert "P placeholders" in (out / "index.html").read_text()
    for trial in manifest["trials"]:
        rows = trace(out, trial)
        assert len(rows) == trial["ticks"] == 55
        assert rows[0]["pts"] == "0"
        for i, row in enumerate(rows):
            assert Fraction(row["pts"]) == Fraction(i, 100)
            assert Fraction(row["right_pts"]) == Fraction(i + 1, 100)
            assert Fraction(row["dt_s"]) == Fraction(1, 100)
            assert row["capacity"]["ticks"] == i + 1
            assert row["capacity"]["source"] == trial["load_source"]
        load = [r for r in rows if r["segment_label"] == "full_load"]
        recover = [r for r in rows if r["segment_label"] == "small_recovery"]
        assert load[0]["capacity"]["after_nits"] > load[0]["capacity"]["target_nits"]
        assert load[-1]["capacity"]["after_nits"] < load[0]["capacity"]["after_nits"]
        assert recover[-1]["capacity"]["after_nits"] > recover[0]["capacity"]["after_nits"]
        assert recover[-1]["center_y_nits"] > recover[0]["center_y_nits"]
        assert (out / trial["trial_id"] / "trace.png").is_file()
        for sample in trial["samples"]:
            rgb = np.load(out / trial["trial_id"] / sample["linear_file"])
            png = np.asarray(Image.open(out / trial["trial_id"] / sample["preview_file"]))
            expected = encode_frame(
                Frame(rgb), replace(profile.output, eotf="srgb", reference_nits=1000)
            )
            np.testing.assert_array_equal(png, expected)
            assert (out / trial["trial_id"] / sample["checkpoint_file"]).is_file()
        for segment in trial["segments"]:
            metrics = segment["metrics"]
            assert metrics["late_label"].startswith("late-interval")
            assert "output_transition" in metrics
            assert Fraction(metrics["peak_onset_pts"]) >= Fraction(metrics["onset_interval_pts"][0])


def test_zero_gap_is_adjacency_and_black_release_matches_analytic(tmp_path):
    value = protocol(
        [
            ("black", 0, "0.01"),
            ("load", 1, "0.2"),
            ("zero_black_gap", 0, "0"),
            ("black_recovery", 0, "0.1"),
            ("probe", 0.01, "0.02"),
        ]
    )
    out = tmp_path / "gap"
    manifest = run_experiment(
        load_profile("generic_woled"), config(), value, out, sources=["emitted"]
    )
    trial = manifest["trials"][0]
    rows = trace(out, trial)
    assert trial["segments"][2]["ticks"] == 0
    assert len(rows) == 33
    black = [r for r in rows if r["segment_label"] == "black_recovery"]
    start = black[0]["capacity"]["before_nits"]
    expected = 850 + (start - 850) * math.exp(-100 / 1000)
    assert black[-1]["capacity"]["after_nits"] == pytest.approx(expected, rel=1e-12, abs=1e-9)


def test_identical_probe_depends_on_prior_history(tmp_path):
    value = protocol()
    value["trials"] = [
        {
            "trial_id": "black_history",
            "family": "history",
            "segments": [
                {"label": "black", "fraction": 0, "duration_s": "0.21"},
                {"label": "probe", "fraction": 0.01, "duration_s": "0.1"},
            ],
        },
        {
            "trial_id": "load_history",
            "family": "history",
            "segments": [
                {"label": "black", "fraction": 0, "duration_s": "0.01"},
                {"label": "load", "fraction": 1, "duration_s": "0.2"},
                {"label": "probe", "fraction": 0.01, "duration_s": "0.1"},
            ],
        },
    ]
    out = tmp_path / "history"
    manifest = run_experiment(
        load_profile("generic_woled"), config(), value, out, sources=["demand"]
    )
    a, b = [trace(out, t) for t in manifest["trials"]]
    aa, bb = [[r for r in rows if r["segment_label"] == "probe"] for rows in (a, b)]
    assert aa[0]["source_sha256"] == bb[0]["source_sha256"]
    assert aa[0]["capacity"]["after_nits"] > bb[0]["capacity"]["after_nits"]
    assert aa[0]["center_y_nits"] > bb[0]["center_y_nits"]


@pytest.mark.slow
def test_all_research_trial_families_preserve_history(tmp_path):
    value = load_protocol()
    value["settings"].update(width=40, height=24, output_fps="100")
    # Scale all durations and taus together. This retains the research history
    # ordering and relative state evolution while keeping the test inexpensive.
    for trial in value["trials"]:
        for segment in trial["segments"]:
            segment["duration_s"] = str(Fraction(segment["duration_s"]) / 10)
    cfg = ABLDynamicsConfig(model=MODEL, attack_ms=10, release_ms=100)
    out = tmp_path / "families"
    manifest = run_experiment(load_profile("generic_woled"), cfg, value, out, sources=["demand"])
    assert len(manifest["trials"]) == 16
    by_id = {t["protocol_trial_id"]: t for t in manifest["trials"]}
    # A longer actual black history restores more capacity before the equal
    # final bright probe, even though black itself emits no measurable probe.
    gap_capacities = []
    for gap in ("0", "0p1", "1", "5"):
        rows = trace(out, by_id[f"black_gap_{gap}"])
        probe = next(r for r in rows if r["segment_label"] == "identical_probe")
        gap_capacities.append(probe["capacity"]["before_nits"])
    assert gap_capacities == sorted(gap_capacities)
    assert gap_capacities[-1] > gap_capacities[0]
    assert all(t["segments"][-1]["metrics"]["final_capacity_nits"] > 0 for t in manifest["trials"])


def test_complete_checkpoint_resume_matches_same_timeline(tmp_path):
    profile = load_profile("generic_woled")
    first = [("black", 0, "0.01"), ("load", 1, "0.1")]
    second = [("recovery", 0.01, "0.1")]
    whole = run_experiment(
        profile, config(), protocol(first + second), tmp_path / "whole", sources=["demand"]
    )
    state = tmp_path / "boundary.state.json"
    run_experiment(
        profile, config(), protocol(first), tmp_path / "first", sources=["demand"], state_out=state
    )
    resumed = run_experiment(
        profile,
        config(initial="resume"),
        protocol(second),
        tmp_path / "second",
        sources=["demand"],
        state_in=state,
    )
    whole_t, resumed_t = whole["trials"][0], resumed["trials"][0]
    full_rows, rows = trace(tmp_path / "whole", whole_t), trace(tmp_path / "second", resumed_t)
    assert rows[0]["pts"] == "11/100"
    assert [r["capacity"] for r in full_rows[-10:]] == [r["capacity"] for r in rows]
    a = np.load(tmp_path / "whole" / whole_t["trial_id"] / whole_t["samples"][-1]["linear_file"])
    b = np.load(
        tmp_path / "second" / resumed_t["trial_id"] / resumed_t["samples"][-1]["linear_file"]
    )
    assert a.tobytes() == b.tobytes()


@pytest.mark.slow
def test_full_35_second_protocol_at_120hz_keeps_rational_clock(tmp_path):
    value = load_protocol()
    value["settings"].update(width=8, height=6)
    out = tmp_path / "120hz"
    manifest = run_experiment(
        load_profile("generic_woled"),
        config(),
        value,
        out,
        trials=["one_full_one"],
        sources=["demand"],
        output_fps="120",
    )
    rows = trace(out, manifest["trials"][0])
    assert len(rows) == 4200
    assert rows[-1]["right_pts"] == "35"
    assert all(Fraction(r["pts"]) == Fraction(i, 120) for i, r in enumerate(rows))
    assert all(Fraction(r["dt_s"]) == Fraction(1, 120) for r in rows)
    state = json.loads((out / manifest["trials"][0]["trial_id"] / "final.state.json").read_text())
    assert state["experiment_timing"]["next_pts"] == "35"
    assert float.fromhex(state["capacity_state"]["elapsed_ms_hex"]) == pytest.approx(
        35000, abs=1e-8
    )


def test_60hz_resume_preserves_exact_rational_pts_and_rejects_gaps(tmp_path):
    from tv_sim.abl_dynamics import digest

    value = protocol([("black", 0, "1/60"), ("load", 1, "1/30")])
    value["settings"]["output_fps"] = "60"
    state = tmp_path / "rational.state.json"
    run_experiment(
        load_profile("generic_woled"),
        config(),
        value,
        tmp_path / "start",
        sources=["demand"],
        state_out=state,
    )
    continuation = protocol([("recovery", 0.01, "1/30")])
    continuation["settings"]["output_fps"] = "60"
    out = tmp_path / "continue"
    manifest = run_experiment(
        load_profile("generic_woled"),
        config(initial="resume"),
        continuation,
        out,
        sources=["demand"],
        state_in=state,
    )
    rows = trace(out, manifest["trials"][0])
    assert [r["right_pts"] for r in rows] == ["1/15", "1/12"]
    modified = json.loads(state.read_text())
    modified["experiment_timing"]["next_pts"] = "1"
    modified["checkpoint_sha256"] = digest(
        {k: v for k, v in modified.items() if k != "checkpoint_sha256"}
    )
    state.write_text(json.dumps(modified))
    rejected = tmp_path / "gap_rejected"
    with pytest.raises(ValueError, match="timestamp gap"):
        run_experiment(
            load_profile("generic_woled"),
            config(initial="resume"),
            continuation,
            rejected,
            sources=["demand"],
            state_in=state,
        )
    assert not rejected.exists()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"sources": ["demand", "demand"]}, "unique"),
        ({"sources": ["final_output"]}, "demand/emitted"),
        ({"trials": ["unknown"]}, "known"),
        ({"output_fps": "3"}, "whole output ticks"),
    ],
)
def test_runner_rejects_before_artifact_creation(tmp_path, kwargs, match):
    out = tmp_path / "invalid"
    with pytest.raises(ValueError, match=match):
        run_experiment(load_profile("generic_woled"), config(), protocol(), out, **kwargs)
    assert not out.exists()


def test_output_paths_never_overwrite_artifacts_or_profiles(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "sentinel").write_bytes(b"original")
    for out in (
        existing,
        tmp_path / "dataset.fit.json",
        profile_path("generic_woled").parent / "experiment",
    ):
        with pytest.raises(ValueError, match="new experiment directory"):
            run_experiment(
                load_profile("generic_woled"), config(), protocol(), out, sources=["demand"]
            )
    assert (existing / "sentinel").read_bytes() == b"original"
    with pytest.raises(ValueError, match="nested"):
        (existing / "manifest.json").write_text("{}")
        run_experiment(
            load_profile("generic_woled"),
            config(),
            protocol(),
            existing / "child",
            sources=["demand"],
        )


def test_fit_state_and_competing_initialization_rejected(tmp_path):
    saved = tmp_path / "old.fit.json"
    saved.write_text('{"schema_version":1,"model":"per_window_normalized_drive_v1"}')
    for cfg, kwargs, match in [
        (config(), {"state_in": saved}, "exactly one"),
        (config(), {"state_in": saved, "sources": ["demand"]}, "initial=resume"),
        (config(initial="resume"), {"state_in": saved, "sources": ["demand"]}, "M9 schema-1"),
        (config(initial="resume"), {"sources": ["demand"]}, "requires state-in"),
        (config(), {"state_out": saved, "sources": ["demand"]}, "new .json"),
    ]:
        out = tmp_path / "rejected"
        with pytest.raises(ValueError, match=match):
            run_experiment(load_profile("generic_woled"), cfg, protocol(), out, **kwargs)
        assert not out.exists()


def test_malformed_checkpoint_mapping_rejected_before_output(tmp_path):
    saved = tmp_path / "malformed.state.json"
    saved.write_text("[]")
    out = tmp_path / "rejected"
    with pytest.raises(ValueError, match="must be a mapping"):
        run_experiment(
            load_profile("generic_woled"),
            config(initial="resume"),
            protocol(),
            out,
            sources=["demand"],
            state_in=saved,
        )
    assert not out.exists()


def test_cli_default_off_requires_explicit_activation_and_taus(tmp_path, capsys):
    assert (
        build_parser()
        .parse_args(["--profile", "generic_woled", "--out", str(tmp_path / "out")])
        .abl_dynamics
        == "off"
    )
    for flags, message in [
        ([], "requires explicit"),
        (["--abl-attack-ms", "100"], "off cannot"),
        (["--abl-dynamics", MODEL], "attack_ms"),
        (["--abl-dynamics", MODEL, "--abl-attack-ms", "100"], "release_ms"),
    ]:
        with pytest.raises(SystemExit) as exc:
            cli_main(
                [
                    "oled-dynamics",
                    "--profile",
                    "generic_woled",
                    "--out",
                    str(tmp_path / "out"),
                    *flags,
                ]
            )
        assert exc.value.code == 2
        assert message in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_cli_render_dispatch(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol([("black", 0, "0.01"), ("probe", 0.01, "0.02")])))
    out = tmp_path / "render"
    cli_main(
        [
            "oled-dynamics",
            "--profile",
            "generic_woled",
            "--abl-dynamics",
            MODEL,
            "--abl-attack-ms",
            "100",
            "--abl-release-ms",
            "1000",
            "--abl-source",
            "demand",
            "--protocol",
            str(path),
            "--gallery",
            "--out",
            str(out),
        ]
    )
    saved = json.loads((out / "manifest.json").read_text())
    assert len(saved["trials"]) == 1 and saved["trials"][0]["ticks"] == 3
