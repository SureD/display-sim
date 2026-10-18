"""Rational artifacts, real emitted-sample pursuit and isolated M18 CLI checks."""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from fractions import Fraction

import numpy as np
import pytest
from PIL import Image

from tv_sim.cli import main as cli_main
from tv_sim.frame import Frame
from tv_sim.profile import profile_path
from tv_sim.stages.encode import encode_frame
from tv_sim.subframe_experiment import ARMS, _configs, _motion_content, _profiles, run_experiment
from tv_sim.subframe_metrics import pursuit_image
from tv_sim.subframe_provenance import load_protocol


def small_protocol():
    data = load_protocol()
    data["settings"].update(
        width=48,
        height=8,
        substeps=8,
        motion_duration_s="1/15",
        step_duration_s="1/15",
        flash_duration_s="1/15",
        speeds_px_s=[120, 240],
        gray_levels_nits=[20, 100],
    )
    data["demonstration"]["pwm_hz"] = "120"
    return data


def test_motion_fixtures_are_repeatable_with_declared_subpixel_raster():
    s = small_protocol()["settings"]
    for name in ("moving_edge", "moving_bar"):
        first, second = _motion_content(name, s, 120), _motion_content(name, s, 120)
        np.testing.assert_array_equal(first, second)
        assert first.shape == (4, 8, 48, 3)
        assert first.min() == s["dark_nits"]
        assert first.max() == s["level_nits"]
    with pytest.raises(ValueError, match="unknown"):
        _motion_content("bad", s, 120)


def test_artifacts_preserve_rational_bins_shared_exposure_and_actual_pursuit(tmp_path):
    data = small_protocol()
    original = deepcopy(data)
    out = tmp_path / "experiment"
    manifest = run_experiment(data, out)
    assert data == original
    assert len(manifest["clips"]) == 4
    assert len(manifest["gray_steps"]) == 2
    assert manifest["preview"]["reference_nits"] == 500
    from tv_sim.subframe_experiment import _pipelines

    assert manifest["display_identity"] == {
        arm: pipeline.identity()
        for arm, pipeline in _pipelines(_profiles(), _configs(data)).items()
    }
    assert "P placeholders" in (out / "index.html").read_text()
    for clip in manifest["clips"]:
        arrays = np.load(out / clip["linear_file"])
        assert set(arrays.files) == {"content", *ARMS, *(f"pursuit_{arm}" for arm in ARMS)}
        rows = list(csv.DictReader((out / clip["waveform_file"]).open()))
        assert len(rows) == len(ARMS) * 4 * 8
        for arm in ARMS:
            arm_rows = [r for r in rows if r["arm"] == arm]
            for index, row in enumerate(arm_rows):
                assert Fraction(row["pts"]) == Fraction(index, 480)
                assert Fraction(row["right_pts"]) == Fraction(index + 1, 480)
                assert Fraction(row["duration_s"]) == Fraction(1, 480)
                assert float(row["panel_endpoint_probe_nits"]) >= 0
        assert Image.open(out / clip["contact_sheet"]).width == 438
        metrics = clip["metrics"]
        assert metrics["oled_bfi"]["brightness_retention"] == pytest.approx(0.25, abs=0.02)
        if clip["fixture"] == "moving_edge":
            assert (
                metrics["oled_bfi"]["edge_10_90_width_px"]
                < metrics["oled_hold"]["edge_10_90_width_px"]
            )
    cell = manifest["gray_steps"][0]
    cell_waveforms = json.loads((out / cell["waveform_file"]).with_suffix(".json").read_text())
    assert set(cell_waveforms["panel_endpoint_y_nits"]) == set(ARMS)
    cell_rows = list(csv.DictReader((out / cell["waveform_file"]).open()))
    for arm in ARMS:
        from_csv = [
            float(row["panel_endpoint_probe_nits"]) for row in cell_rows if row["arm"] == arm
        ]
        assert from_csv == cell_waveforms["panel_endpoint_y_nits"][arm]
    assert Fraction(cell_waveforms["absolute_start_pts"]) == Fraction(1, 60)
    constant = manifest["flicker"]["metrics"]
    assert constant["lcd_hold"]["constant_patch"]["flicker_percent"] == 0
    assert constant["oled_bfi"]["constant_patch"]["flicker_percent"] == 100
    assert constant["lcd_pwm"]["constant_patch"]["dominant_frequency_hz"] == 120
    assert constant["lcd_strobe"]["constant_patch"]["brightness_cost_percent"] == pytest.approx(75)
    assert constant["oled_bfi"]["constant_patch"]["brightness_cost_percent"] == pytest.approx(75)
    assert max(path.stat().st_size for path in out.rglob("*.json")) < 1_000_000


def test_pursuit_and_mean_images_reproduce_runtime_and_png_mapping(tmp_path):
    from dataclasses import replace

    from tv_sim.pipeline import Pipeline

    protocol = small_protocol()
    out = tmp_path / "reproduce"
    manifest = run_experiment(protocol, out)
    clip = manifest["clips"][0]
    arrays = np.load(out / clip["linear_file"])
    pipeline = Pipeline(_profiles()["oled"], subframe=_configs(protocol)["oled_bfi"])
    index = clip["selected_tick"]
    dt = Fraction(1, 60)
    for i, content in enumerate(arrays["content"]):
        result = pipeline.display_subframes(Frame(content), pts=i * dt, duration=dt)
        np.testing.assert_array_equal(arrays["oled_bfi"][i], result.mean)
        if i == index:
            pursuit = pursuit_image(
                [s.rgb for s in result.samples],
                [s.pts for s in result.samples],
                [s.duration for s in result.samples],
                clip["speed_px_s"],
                i * dt + dt / 2,
            )
            np.testing.assert_array_equal(pursuit, arrays["pursuit_oled_bfi"])
    output = replace(_profiles()["lcd"].output, eotf="srgb", reference_nits=500)
    expected = encode_frame(Frame(arrays["lcd_hold"][index]), output)
    sheet = np.array(Image.open(out / clip["contact_sheet"]))
    np.testing.assert_array_equal(sheet[55:79:3, 150:294:3], expected)


def test_repeated_runs_have_identical_bytes(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    assert run_experiment(small_protocol(), first) == run_experiment(small_protocol(), second)
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()


def test_exclusive_outputs_and_no_profile_tree_writes(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "keep"
    sentinel.write_text("old")
    with pytest.raises(ValueError, match="new experiment"):
        run_experiment(small_protocol(), out)
    assert sentinel.read_text() == "old"
    with pytest.raises(ValueError, match="outside profiles"):
        run_experiment(small_protocol(), profile_path("generic_woled").parent / "new")
    outer = tmp_path / "outer"
    outer.mkdir()
    (outer / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="nested"):
        run_experiment(small_protocol(), outer / "nested")


def test_invalid_protocol_rejects_before_creating_output(tmp_path):
    data = small_protocol()
    data["evidence"] = "M"
    out = tmp_path / "invalid"
    with pytest.raises(ValueError, match="P/placeholder"):
        run_experiment(data, out)
    assert not out.exists()


def test_cli_dispatches_and_rejects_bad_protocol_without_writing(tmp_path, capsys):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(small_protocol()))
    out = tmp_path / "cli"
    cli_main(["subframe", "--protocol", str(path), "--out", str(out)])
    assert "Saved 4 P sub-frame motion clips" in capsys.readouterr().out
    assert (out / "manifest.json").is_file()
    path.write_text("{}")
    with pytest.raises(SystemExit) as error:
        cli_main(["subframe", "--protocol", str(path), "--out", str(tmp_path / "bad")])
    assert error.value.code == 2
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("kind", ["lcd", "oled"])
def test_admitted_maximum_gray_is_an_identity_hdr_target(kind):
    from dataclasses import replace

    from tv_sim.pipeline import Pipeline
    from tv_sim.subframe_provenance import validate_protocol

    protocol = small_protocol()
    protocol["settings"].update(level_nits=1000, gray_levels_nits=[100, 1000])
    validate_protocol(protocol)
    config = replace(_configs(protocol)[f"{kind}_hold"], rise_tau_ms=0, fall_tau_ms=0)
    pipeline = Pipeline(_profiles()[kind], subframe=config)
    pipeline.display_subframes(
        Frame(np.full((8, 8, 3), 100, dtype=np.float32)), pts=Fraction(0), duration=Fraction(1, 60)
    )
    result = pipeline.display_subframes(
        Frame(np.full((8, 8, 3), 1000, dtype=np.float32)),
        pts=Fraction(1, 60),
        duration=Fraction(1, 60),
    )
    for sample in result.samples:
        np.testing.assert_array_equal(
            sample.panel, np.full((8, 8, 3), 1 if kind == "lcd" else 1000)
        )
        np.testing.assert_allclose(sample.rgb, np.full((8, 8, 3), 1000), rtol=0, atol=2e-12)
    np.testing.assert_array_equal(result.mean, np.full((8, 8, 3), 1000))


def test_exact_lcd_extinction_floor_is_an_admitted_gray_endpoint():
    from dataclasses import replace

    from tv_sim.pipeline import Pipeline
    from tv_sim.subframe_provenance import (
        LCD_GRAY_FLOOR_NITS,
        LCD_NATIVE_CONTRAST,
        validate_protocol,
    )

    protocol = small_protocol()
    protocol["settings"]["gray_levels_nits"] = [LCD_GRAY_FLOOR_NITS, 1000]
    validate_protocol(protocol)
    profile = _profiles()["lcd"]
    assert profile.panel.native_contrast == LCD_NATIVE_CONTRAST
    config = replace(_configs(protocol)["lcd_hold"], rise_tau_ms=0, fall_tau_ms=0)
    pipeline = Pipeline(profile, subframe=config)
    result = pipeline.display_subframes(
        Frame(np.full((8, 8, 3), LCD_GRAY_FLOOR_NITS, dtype=np.float32)),
        pts=Fraction(0),
        duration=Fraction(1, 60),
    )
    np.testing.assert_array_equal(result.mean, np.full((8, 8, 3), LCD_GRAY_FLOOR_NITS))
    for sample in result.samples:
        np.testing.assert_array_equal(sample.panel, np.full((8, 8, 3), 1 / LCD_NATIVE_CONTRAST))
