"""M15 adapters carry a declared basis, absolute units and shared exposure."""

from hashlib import sha256
import json

import numpy as np
from PIL import Image
import pytest

from sim.cli import main
from sim.color import pq_oetf
from sim.colorimetry import ColorimetryConfig, D65, RGB_SPACES, rgb_to_xyz_matrix
from sim.colorimetry_gallery import color_errors, color_volume_patterns
from sim.export_web import generate_web_export
from sim.gallery import _gallery_profile, scenes
from sim.pipeline import Pipeline
from sim.profile import load_profile


def test_synthetic_intents_cover_primaries_secondaries_neutrals_and_illustrative_patches():
    patterns = color_volume_patterns(42, 35)
    assert set(patterns) == {"saturated_ramps", "bt2020_rgb_cmy_white", "skin_foliage_like", "hue_saturation_sweep"}
    assert all(a.shape == (35, 42, 3) and a.dtype == np.float32 and np.isfinite(a).all() for a in patterns.values())
    primaries = patterns["bt2020_rgb_cmy_white"]
    for index, rgb in enumerate(((1,0,0), (0,1,0), (0,0,1), (1,1,0), (0,1,1), (1,0,1), (1,1,1))):
        assert np.any(np.all(primaries == np.array(rgb) * 2000, axis=-1))
    assert np.array_equal(color_volume_patterns(42, 35)["saturated_ramps"], patterns["saturated_ramps"])


def test_uv_metric_excludes_black_and_separates_luminance_from_chromaticity():
    intent = np.array([[[0, 0, 0], [0.4, 0.3, 0.2]]], dtype=np.float64)
    errors = color_errors(intent, intent * 0.5)
    assert errors["excluded_pixels"] == errors["valid_chromaticity_pixels"] == 1
    assert errors["max_delta_uv"] == 0
    assert errors["mean_absolute_Y_error_nits"] == pytest.approx(0.075)


@pytest.mark.parametrize("space", ["bt2020", "display_p3", "xyz", "bt709"])
def test_export_colorimetry_transports_the_declared_linear_coordinates(tmp_path, space):
    config = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    manifest = generate_web_export(tmp_path, 160, 96, motion_frames=1, colorimetry=config, output_space=space)
    format_ = manifest["format"]
    assert len(manifest["scenes"]) == 12
    assert format_["signed_components"] is True
    matrix = np.array(format_["rgb_to_xyz"])
    to709 = np.array(format_["to_linear_srgb"])
    np.testing.assert_allclose(rgb_to_xyz_matrix(RGB_SPACES["bt709"], D65) @ to709, matrix, atol=1e-14)
    record = next(s for s in manifest["scenes"] if s["id"] == "gradients")
    for name, asset in record["assets"].items():
        pipeline = Pipeline(_gallery_profile(load_profile(name)), colorimetry=config)
        frame = pipeline.run_linear(pq_oetf(scenes(160, 96)["gradients"]))
        expected = pipeline.output_in_space(frame, space).astype("<f2")
        payload = (tmp_path / asset["file"]).read_bytes()
        assert payload == expected.tobytes()
        assert sha256(payload).hexdigest() == asset["sha256"]
        decoded = expected.astype(np.float64)
        assert asset["statistics"]["mean_luminance_nits"] == pytest.approx((decoded @ matrix[1]).mean(), abs=1e-12)
    assert all("colorimetry" in p["snapshots"] for p in manifest["profiles"])
    assert json.loads((tmp_path / "manifest.json").read_text())["colorimetry"]["mastering_gamut"] == "NR"


def test_export_keeps_signed_wide_gamut_coordinates_in_p3(tmp_path):
    manifest = generate_web_export(tmp_path, 160, 96, motion_frames=1,
                                   colorimetry=ColorimetryConfig(enabled=True, source_primaries="bt2020"), output_space="display_p3")
    record = next(s for s in manifest["scenes"] if s["id"] == "bt2020_rgb_cmy_white")
    asset = record["assets"]["generic_qdoled"]
    assert np.fromfile(tmp_path / asset["file"], dtype="<f2").min() < 0


def test_colorimetry_cli_writes_shared_exposure_gallery_and_no_tracked_float_arrays(tmp_path):
    main(["colorimetry", "--out", str(tmp_path), "--width", "160", "--height", "96"])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["results"]) == 32
    assert len(manifest["sheets"]) == 4
    assert manifest["preview"]["reference_nits"] == 2000
    assert "*.npy" in (tmp_path / ".gitignore").read_text()
    assert "not Delta E" in manifest["results"][0]["intent_errors"]["metric"]
    assert all(result["intent_errors"]["valid_chromaticity_pixels"] > 0 for result in manifest["results"])
    assert all((tmp_path / result["linear_xyz_file"]).exists() for result in manifest["results"])
    for sheet in manifest["sheets"]:
        assert Image.open(tmp_path / sheet["file"]).size == (640, 386)


def test_still_cli_colorimetry_matches_explicit_pipeline(tmp_path):
    source = np.zeros((16, 24, 3), dtype=np.uint8)
    source[:, :12] = (255, 25, 10)
    source[:, 12:] = (24, 200, 40)
    Image.fromarray(source).save(tmp_path / "in.png")
    main(["--profile", "generic_woled", "--input", str(tmp_path / "in.png"), "--output", str(tmp_path / "out.png"),
          "--colorimetry", "--source-primaries", "display_p3", "--gamut-mapping", "clip"])
    expected = Pipeline(load_profile("generic_woled"), colorimetry=ColorimetryConfig(
        enabled=True, source_primaries="display_p3", gamut_mapping="clip")).run(source)
    assert np.array_equal(np.asarray(Image.open(tmp_path / "out.png")), expected)


@pytest.mark.parametrize("arguments", [["--source-primaries", "bt2020"],
                                         ["--colorimetry", "--gamut-compression-knee", "1"],
                                         ["--colorimetry", "--source-white", ".8", ".8"]])
def test_cli_rejects_undeclared_optin_and_invalid_controls(tmp_path, arguments):
    with pytest.raises(SystemExit) as exc:
        main(["--profile", "generic_woled", "--input", str(tmp_path / "unused.png"), "--output", str(tmp_path / "out.png"), *arguments])
    assert exc.value.code == 2


def test_export_cli_requires_optin_for_output_colorimetry(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["export-web", "--out", str(tmp_path), "--colorimetry-output", "xyz"])
    assert exc.value.code == 2


def test_enabled_export_cli_declares_pq_container_separately(tmp_path):
    main(["export-web", "--out", str(tmp_path), "--width", "160", "--height", "96", "--motion-frames", "1",
          "--colorimetry", "--source-primaries", "bt2020", "--colorimetry-output", "xyz"])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["format"]["color_space"] == "linear-xyz"
    assert manifest["format"]["coordinate_labels"] == ["X", "Y", "Z"]
    assert manifest["colorimetry"]["config"]["source_primaries"] == "bt2020"
