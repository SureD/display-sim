"""Synthetic zone clips retain clocks, honest metrics and inspectable artifacts."""

import json
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest
from PIL import Image

from tv_sim.cli import main as cli_main
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile, profile_path
from tv_sim.stages.encode import encode_frame
from tv_sim.zone_temporal import MODEL, ZoneTemporalConfig
from tv_sim.zone_temporal_experiment import _fixture, build_parser, run_experiment
from tv_sim.zone_temporal_provenance import load_protocol


def protocol():
    data = load_protocol()
    data["settings"].update(width=32, height=24, output_fps="30", duration_s="4/5")
    return data


def profile():
    value = load_profile("generic_va_fald_miniled")
    return replace(value, backlight=replace(value.backlight, zones_x=4, zones_y=3))


def config(**kwargs):
    return ZoneTemporalConfig(model=MODEL, attack_s=0.05, release_s=0.15, **kwargs)


def test_fixture_content_is_repeatable_and_saved_geometry_matches():
    settings = protocol()["settings"]
    for name in load_protocol()["fixtures"]:
        first, mask, details = _fixture(name, settings)
        second, second_mask, second_details = _fixture(name, settings)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(mask, second_mask)
        assert details == second_details
        assert first.shape == (24, 24, 32, 3)
        if name != "apl_step":
            assert np.all(first[mask] == settings["level_nits"])
        if name == "moving_object":
            for i, bounds in enumerate(details["foreground_bounds_yxyx"]):
                if bounds is None:
                    assert not mask[i].any()
                else:
                    y0, y1, x0, x1 = bounds
                    assert mask[i, y0:y1, x0:x1].all()
                    assert np.sum(mask[i]) == (y1 - y0) * (x1 - x0)
    with pytest.raises(ValueError, match="unknown fixture"):
        _fixture("unknown", settings)


def test_artifacts_retain_rational_pts_zone_grids_and_shared_exposure(tmp_path):
    source = profile()
    original = deepcopy(source)
    out = tmp_path / "clips"
    manifest = run_experiment(source, config(), protocol(), out)
    assert source == original
    assert manifest["profile"]["temporal"]["response_time_ms"] == 0
    assert manifest["preview"]["reference_nits"] == 1000
    assert manifest["preview"]["shadow_reference_nits"] == 1
    assert [c["fixture"] for c in manifest["clips"]] == load_protocol()["fixtures"]
    assert "P placeholders" in (out / "index.html").read_text()
    for clip in manifest["clips"]:
        saved = np.load(out / clip["linear_file"])
        traces = json.loads((out / clip["trace_file"]).read_text())["arms"]
        assert clip["ticks"] == 24
        expected_files = {"off", "on", "foreground_mask", "content"}
        if clip["fixture"] == "moving_object":
            expected_files |= {"black_off", "black_on"}
        assert set(saved.files) == expected_files
        assert len(traces["on"]) == len(traces["off"]) == 24
        for i, row in enumerate(traces["on"]):
            assert Fraction(row["pts"]) == Fraction(i, 30)
            assert Fraction(row["right_pts"]) == Fraction(i + 1, 30)
            assert Fraction(row["duration_s"]) == Fraction(1, 30)
            assert row["zone"]["ticks"] == i + 1
            assert np.array(row["zone"]["targets_nits"]).shape == (3, 4)
            assert np.array(row["zone"]["after_nits"]).shape == (3, 4)
        sheet = np.array(Image.open(out / clip["contact_sheet"]))
        i = clip["samples"][0]
        expected = encode_frame(
            Frame(saved["off"][i]), replace(source.output, eotf="srgb", reference_nits=1000)
        )
        np.testing.assert_array_equal(sheet[44:92:2, :64:2], expected)
        assert (out / clip["shadow_sheet"]).is_file()
        assert (out / clip["trace_plot"]).is_file()
        assert (
            (out / clip["fixture"] / "probes.csv")
            .read_text()
            .startswith("arm,index,pts,right_pts,duration_s")
        )
        metrics = clip["metrics"]
        assert metrics["evidence"].startswith("D under P")
        assert metrics["arms"]["on"]["zone_total_variation_nits"] >= 0
        assert metrics["arms"]["on"]["probe_peak_to_peak_nits"] >= 0
    apl = next(c for c in manifest["clips"] if c["fixture"] == "apl_step")
    for event in ("rise", "fall"):
        assert apl["metrics"]["transitions"][event]["on"]["zone_overshoot_nits"] == 0
        assert apl["metrics"]["transitions"][event]["off"]["zone"]["settling_s"] == "1/30"
    moving = manifest["clips"][0]
    assert set(moving["metrics"]["trails"]) == {"off", "on", "positive_on_minus_off"}
    assert moving["metrics"]["trails"]["positive_on_minus_off"]["energy_nit_pixel_s"] > 0


def test_saved_off_arm_is_exact_independent_legacy_pipeline(tmp_path):
    out = tmp_path / "independent"
    run_experiment(profile(), config(), protocol(), out, fixtures=["moving_object"])
    arrays = np.load(out / "moving_object/linear.npz")
    p = profile()
    p = replace(
        p,
        ambient=replace(p.ambient, lux=0),
        temporal=replace(
            p.temporal,
            response_time_ms=0,
            frame_time_ms=1000 / 30,
            motion_px_per_frame=0,
            overdrive_gain=0,
            bfi_duty=1,
            bfi_preserve_mean=False,
            integration_samples=1,
        ),
    )
    pipeline = Pipeline(p)
    for i, content in enumerate(arrays["content"]):
        expected = pipeline.display_content(
            Frame(content), frame_time_ms=1000 / 30, timestamp_ms=float(Fraction(i, 30) * 1000)
        )
        np.testing.assert_array_equal(expected.rgb, arrays["off"][i])


def test_repeated_artifact_outputs_and_traces_are_exact(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    left = run_experiment(profile(), config(), protocol(), first, fixtures=["flashing_highlight"])
    right = run_experiment(profile(), config(), protocol(), second, fixtures=["flashing_highlight"])
    assert left == right
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()


def test_profile_pixel_response_is_identified_separately(tmp_path):
    manifest = run_experiment(
        profile(),
        config(),
        protocol(),
        tmp_path / "pixel",
        fixtures=["subtitle"],
        pixel_response="profile",
    )
    assert manifest["pixel_response"] == "profile"
    assert (
        manifest["profile"]["temporal"]["response_time_ms"] == profile().temporal.response_time_ms
    )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"fixtures": []}, "unique known"),
        ({"fixtures": ["subtitle", "subtitle"]}, "unique known"),
        ({"fixtures": ["unknown"]}, "unique known"),
        ({"pixel_response": "unknown"}, "pixel_response"),
    ],
)
def test_rejects_ambiguous_runner_options_without_writing(tmp_path, change, match):
    out = tmp_path / "invalid"
    with pytest.raises(ValueError, match=match):
        run_experiment(profile(), config(), protocol(), out, **change)
    assert not out.exists()


def test_rejects_oled_inactive_conflicts_and_resume_without_writing(tmp_path):
    for p, conf, match in (
        (load_profile("generic_woled"), config(), "LCD"),
        (profile(), ZoneTemporalConfig(), "explicit active"),
        (profile(), config(initial="resume"), "resume"),
        (replace(profile(), hdr=replace(profile().hdr, abl_response_ms=10)), config(), "conflicts"),
    ):
        out = tmp_path / match.replace(" ", "_")
        with pytest.raises(ValueError, match=match):
            run_experiment(p, conf, protocol(), out)
        assert not out.exists()


def test_exclusive_output_and_no_profile_tree_writes(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "keep.txt"
    sentinel.write_text("old")
    with pytest.raises(ValueError, match="new experiment"):
        run_experiment(profile(), config(), protocol(), out)
    assert sentinel.read_text() == "old"
    with pytest.raises(ValueError, match="outside profiles"):
        run_experiment(
            profile(), config(), protocol(), profile_path("generic_va_fald_miniled").parent / "new"
        )
    outer = tmp_path / "outer"
    outer.mkdir()
    (outer / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="nested"):
        run_experiment(profile(), config(), protocol(), outer / "nested")


def test_cli_requires_explicit_taus_and_dispatches(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args([])
    assert error.value.code == 2
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol()))
    out = tmp_path / "cli"
    cli_main(
        [
            "zone-temporal",
            "--protocol",
            str(path),
            "--attack-s",
            "0.05",
            "--release-s",
            "0.15",
            "--fixtures",
            "moving_object",
            "--out",
            str(out),
        ]
    )
    assert "Saved 1 P LCD zone temporal clips" in capsys.readouterr().out
    assert (out / "index.html").is_file()


def test_cli_invalid_config_does_not_create_output(tmp_path):
    out = tmp_path / "bad"
    with pytest.raises(SystemExit) as error:
        cli_main(["zone-temporal", "--attack-s", "-1", "--release-s", "0.15", "--out", str(out)])
    assert error.value.code == 2
    assert not out.exists()


def test_trail_metric_subtracts_matched_black_and_retains_positive_residual():
    from tv_sim.zone_temporal_experiment import _metrics

    background = np.ones((1, 3, 6, 3), dtype=np.float32)
    content = np.zeros_like(background)
    content[:, 1, 2] = 10
    mask = np.zeros((1, 3, 6), dtype=bool)
    mask[:, 1, 2] = True
    off, on = background.copy(), background.copy()
    off[:, 1, :2] += 0.2
    on[:, 1, :2] += 0.5
    off[:, 1, 2] = on[:, 1, 2] = 10
    traces = {
        arm: [{"zone": {"after_nits": [[10]], "targets_nits": [[10]]}}] for arm in ("off", "on")
    }
    details = {"probe_yx": [0, 0], "foreground_bounds_yxyx": [[1, 2, 2, 3]]}
    result = _metrics(
        "moving_object",
        {"off": off, "on": on},
        mask,
        content,
        details,
        traces,
        protocol()["settings"],
        {"off": background, "on": background},
    )
    assert result["trails"]["off"]["max_length_px"] == 2
    assert result["trails"]["on"]["energy_nit_pixel_s"] == pytest.approx(1 / 30)
    assert result["trails"]["off"]["energy_nit_pixel_s"] == pytest.approx(0.4 / 30)
    assert result["trails"]["positive_on_minus_off"]["energy_nit_pixel_s"] == pytest.approx(
        0.6 / 30
    )


def test_settling_needs_to_remain_in_band_through_hold():
    from tv_sim.zone_temporal_experiment import _settling

    result = _settling(np.array([0, 9.9, 8, 10, 10]), 10, 0, 5, 0.2, Fraction(10))
    assert result["settling_s"] == "2/5"
    assert result["reached"]
    short = _settling(np.array([0, 8]), 10, 0, 2, 0.2, Fraction(10))
    assert short["settling_s"] is None
    assert not short["reached"]


def test_explicit_grid_geometry_rejected_before_creating_artifact(tmp_path):
    out = tmp_path / "grid"
    with pytest.raises(ValueError, match="grid does not match"):
        run_experiment(
            profile(), config(initial="explicit", initial_zones_nits=((0.0,),)), protocol(), out
        )
    assert not out.exists()
