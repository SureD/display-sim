"""Independent synthetic truth, timing, safety and artifact provenance gates."""

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from sim.abl_dynamics import ABLDynamicsConfig
from sim.block_motion import BlockMotionConfig
from sim.motion import AnalyticLayer, LayerScene
from sim.motion_validate import (
    FIXTURE_NAMES, MotionFixture, _frame_metrics, default_validation_protocol, main, make_fixture, run_validation,
    validate_motion_validation_provenance, validate_validation_protocol,
    validate_validation_sidecar,
)
from sim.profile import load_profile


def small_config():
    return BlockMotionConfig(estimation_width=64, estimation_height=40, pyramid_levels=2,
                             search_radius=2, refinement_radius=1, subpixel_steps=())


def experiment(out, fixtures=("pan",), **kwargs):
    return run_validation(out, fixtures=fixtures, width=64, height=40, source_count=4,
                          block_config=small_config(), **kwargs)


def test_shipped_motion_protocol_is_explicitly_placeholder_and_provenance_valid():
    protocol = default_validation_protocol()
    assert protocol["evidence"] == "P"
    assert protocol["unavailable"]["vendor_memc_algorithm"] == "NR"
    assert set(protocol["fixtures"]) == set(FIXTURE_NAMES)
    assert validate_motion_validation_provenance() == []


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(evidence="M"),
    lambda p: p.update(parameter_status="calibrated"),
    lambda p: p.update(unrecognized=1),
    lambda p: p["settings"].update(seed=True),
    lambda p: p["settings"].update(output_fps="0/1"),
    lambda p: p["settings"].update(preview_reference_nits=float("nan")),
    lambda p: p["fixtures"]["pan"].update(background_velocity_px=[float("inf"), 0]),
    lambda p: p["visual"].update(marker_rect_fraction=[0.9, 0.1, 0.8, 0.1]),
    lambda p: p["unavailable"].update(named_tv_calibration="implemented"),
])
def test_protocol_rejects_unknown_or_unlabelled_or_nonfinite_parameters(mutate):
    protocol = default_validation_protocol()
    mutate(protocol)
    with pytest.raises(ValueError):
        validate_validation_protocol(protocol)


def test_protocol_file_rejects_duplicate_json_keys_and_nonfinite_values(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"evidence":"M","evidence":"P"}')
    assert "duplicate" in validate_motion_validation_provenance(path)[0]
    path.write_text('{"value":NaN}')
    assert "nonfinite" in validate_motion_validation_provenance(path)[0]


def test_selected_profile_provenance_still_checks_motion_protocol(tmp_path, monkeypatch, capsys):
    from sim import motion_validate, provenance

    protocol = default_validation_protocol()
    protocol["evidence"] = "M"
    path = tmp_path / "invalid-motion-protocol.json"
    path.write_text(json.dumps(protocol))
    monkeypatch.setattr(motion_validate, "PROTOCOL_PATH", path)
    with pytest.raises(SystemExit):
        provenance.main(["--check", "--profiles", "generic_woled"])
    assert "P placeholder" in capsys.readouterr().err


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_truth_is_finite_deterministic_and_regions_partition(name):
    fixture, again = make_fixture(name), make_fixture(name)
    assert np.array_equal(fixture.render(Fraction(2, 5)).rgb, again.render(Fraction(2, 5)).rgb)
    assert np.isfinite(fixture.render(Fraction(2, 5)).rgb).all()
    masks = fixture.regions(0.4, 0)
    assert np.array_equal(sum(mask.astype(int) for mask in masks.values()),
                          np.ones(fixture.scene.background.shape[:2], int))
    assert masks["interior"].any() and masks["boundary"].any()


def test_occlusion_has_independent_newly_visible_region_and_text_alias():
    fixture = make_fixture("occlusion")
    masks = fixture.regions(0.6, 0)
    assert masks["disoccluded"].any()
    assert not np.array_equal(fixture.render(0).rgb[masks["disoccluded"]],
                              fixture.render(0.6).rgb[masks["disoccluded"]])
    assert np.array_equal(make_fixture("thin_text").render(0.4).rgb,
                          make_fixture("text").render(0.4).rgb)


def test_disocclusion_tracks_material_visibility_on_a_moving_background():
    pan = make_fixture("pan")
    # The marker and background move together. A vacated screen coordinate is
    # backed by a background point that was already visible in the left source.
    assert not pan.regions(0.6, 0)["disoccluded"][40, 32]
    occlusion = make_fixture("occlusion")
    # A static background point under the same moving marker was hidden.
    assert occlusion.regions(0.6, 0)["disoccluded"][40, 32]


def test_hidden_fractional_layer_edges_do_not_become_visible_boundary_flags():
    base = np.zeros((48, 64, 3), np.float32)
    rear, front = np.zeros(base.shape[:2], bool), np.zeros(base.shape[:2], bool)
    rear[24:32, 24:32] = True
    front[20:40, 20:40] = True
    scene = LayerScene(base, (AnalyticLayer(base + 30, rear, (1, 0), 1),
                              AnalyticLayer(base + 100, front, (0, 0), 2)))
    protocol = default_validation_protocol()
    fixture = MotionFixture("occlusion", scene, protocol["settings"], protocol["visual"])
    _, _, fractional = fixture.labels_and_velocity(0.5)
    assert not fractional.any()


def test_cut_keeps_trackable_marker_and_event_indices_stay_inside_sources():
    fixture = make_fixture("cut")
    mask = fixture.scene.layers[-1].mask
    assert np.all(fixture.render(fixture.cut_index).rgb[..., 0][mask]
                  > fixture.render(fixture.cut_index).rgb[..., 1][mask])
    protocol = default_validation_protocol()
    protocol["visual"]["cut_source_fraction"] = 0.999
    protocol["visual"]["flash_source_fraction"] = 0.999
    assert make_fixture("cut", protocol).cut_index == protocol["settings"]["source_count"] - 1
    assert make_fixture("flash", protocol).event_index("flash_source_fraction") == protocol["settings"]["source_count"] - 1


def test_marker_metrics_record_missing_and_spurious_positions():
    fixture = make_fixture("large_motion")
    present, absent = fixture.render(0), fixture.render(4)
    masks = fixture.regions(4, 4)
    stale = _frame_metrics(present, absent, masks, fixture.settings["marker_threshold_nits"])
    missing = _frame_metrics(absent, present, masks, fixture.settings["marker_threshold_nits"])
    assert stale["spurious_visible_marker"] and not stale["missing_visible_marker"]
    assert missing["missing_visible_marker"] and not missing["spurious_visible_marker"]
    assert stale["trajectory_error_px"] is None


def test_report_compares_actual_rendered_trajectory_and_region_errors(tmp_path):
    report = experiment(tmp_path / "results", fixtures=("pan", "occlusion"))
    validate_validation_sidecar(report)
    for fixture in report["fixtures"]:
        analytic, repeat = fixture["summary"]["analytic"], fixture["summary"]["repeat"]
        assert analytic["trajectory"]["mean_error_px"] == 0
        assert repeat["trajectory"]["mean_error_px"] > 0
        assert all(region["linear_luma_mae_nits"] == 0 for region in analytic["regions"].values())
        assert repeat["regions"]["disoccluded"]["linear_luma_mae_nits"] > 0
        assert "forward vector" in fixture["pairs"][0]["vector_endpoint_error_px"]["metric"]
        mci = fixture["summary"]["mci"]
        assert 0 <= mci["fallback_fraction"] <= 1
        assert mci["temporal_fallback_switching"]["pixel_decision_changes"] >= 0
    assert not (tmp_path / "results" / "validation.json").exists()


def test_cut_is_exact_source_hold_before_cut_pts_and_tail_has_no_future(tmp_path):
    out = tmp_path / "cut"
    fixture = experiment(out, fixtures=("cut",))["fixtures"][0]
    cut_index = fixture["declared_cut_before"]
    cut_pts = Fraction(fixture["source_frames"][cut_index]["source_pts"])
    saw_intermediate = False
    for record in fixture["frames"]:
        result = record["modes"]["mci"]
        frame = np.load(out / result["linear_file"])
        source = np.load(out / fixture["source_frames"][record["source_index"]]["linear_file"])
        if record["source_index"] == cut_index - 1 and record["phase"] != "0/1":
            assert Fraction(record["output_pts"]) < cut_pts
            assert np.array_equal(frame, source)
            assert result["fallback_fraction"] == 1
            assert result["scene_cut"]
            saw_intermediate = True
        if record["next_source_index"] is None:
            assert np.array_equal(frame, source)
    assert saw_intermediate
    assert fixture["false_cut_pairs"] == 0
    declared_pair = fixture["pairs"][cut_index - 1]
    assert declared_pair["scene_cut"] and not declared_pair["detected_cut"]


def test_rational_trace_and_shared_preview_exposure_are_saved(tmp_path):
    out = tmp_path / "timing"
    report = experiment(out, source_fps="24000/1001", output_fps="60000/1001")
    fixture = report["fixtures"][0]
    assert len(fixture["frames"]) == 10
    assert [r["phase"] for r in fixture["frames"][:5]] == ["0/1", "2/5", "4/5", "1/5", "3/5"]
    assert [r["output_pts"] for r in fixture["frames"][:3]] == ["0/1", "1001/60000", "1001/30000"]
    for record in fixture["frames"]:
        for result in record["modes"].values():
            linear = np.load(out / result["linear_file"])
            assert linear.dtype == np.float32 and np.isfinite(linear).all()
            assert sha256((out / result["linear_file"]).read_bytes()).hexdigest() == result["linear_sha256"]
    record = fixture["frames"][0]
    arrays = [np.asarray(Image.open(out / record["modes"][mode]["preview_file"])) for mode in ("repeat", "analytic", "mci")]
    assert np.array_equal(arrays[0], arrays[1]) and np.array_equal(arrays[0], arrays[2])


def test_all_saved_artifact_bytes_are_deterministic_and_existing_outputs_reject(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    experiment(first)
    experiment(second)
    paths = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    assert paths == sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert all((first / path).read_bytes() == (second / path).read_bytes() for path in paths)
    with pytest.raises(ValueError, match="empty"):
        experiment(first)


def test_optional_display_advances_capacity_once_per_mode_per_tick(tmp_path):
    dynamics = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    report = experiment(tmp_path / "display", profile=load_profile("generic_woled"), abl_dynamics=dynamics)
    records = report["fixtures"][0]["frames"]
    for mode in ("repeat", "analytic", "mci"):
        assert [r["modes"][mode]["capacity_trace"]["ticks"] for r in records] == list(range(1, len(records) + 1))
        assert records[-1]["modes"][mode]["capacity_trace"]["elapsed_ms"] == pytest.approx(len(records) * 1000 / 60)
    assert report["display"]["effective_profile"]["temporal"]["motion_px_per_frame"] == 0


def test_cli_writes_offline_artifact_comparison_and_playback(tmp_path, capsys):
    out = tmp_path / "gallery"
    main(["--fixtures", "occlusion", "thin_text", "--width", "48", "--height", "32",
          "--source-count", "4", "--gallery", "--out", str(out)])
    assert "occlusion:" in capsys.readouterr().out
    html = (out / "index.html").read_text()
    assert "requestAnimationFrame" in html and "No named TV" in html
    assert (out / "occlusion/contact-sheet.png").is_file()
    assert (out / "text/contact-sheet.png").is_file()
    saved = json.loads((out / "motion-validation.json").read_text())
    validate_validation_sidecar(saved)
    invalid = deepcopy(saved)
    invalid["estimator"]["evidence"] = "M"
    with pytest.raises(ValueError, match="P evidence"):
        validate_validation_sidecar(invalid)
    invalid = deepcopy(saved)
    invalid["estimator"]["parameters"]["confidence_threshold"] = 2
    with pytest.raises(ValueError):
        validate_validation_sidecar(invalid)
    invalid = deepcopy(saved)
    invalid["surprise"] = 1
    with pytest.raises(ValueError, match="unknown"):
        validate_validation_sidecar(invalid)
