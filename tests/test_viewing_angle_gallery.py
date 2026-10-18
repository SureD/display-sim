"""The opt-in angular comparison is a labeled, fixed-exposure experiment."""

import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from golden_support import assert_numeric_metadata, gallery_manifest_baseline, legacy_labels
from PIL import Image

from tv_sim.cli import main
from tv_sim.color import luminance
from tv_sim.gallery import PROFILE_NAMES, render_viewing_angle, viewing_angle_scene
from tv_sim.profile import load_profile, profile_path

pytestmark = [pytest.mark.slow, pytest.mark.golden]


def test_angular_stimulus_contains_independent_black_white_gray_and_color():
    first = viewing_angle_scene(160, 96)
    assert np.array_equal(first, viewing_angle_scene(160, 96))
    assert first.shape == (96, 160, 3) and first.dtype == np.float32
    assert np.array_equal(first[0, [0, 32, 64, 96, 128], 0], [0, 1, 10, 50, 100])
    assert np.all(np.diff(first[40, :, 0]) > 0)
    assert np.array_equal(first[40, :, 0], first[40, :, 1])
    assert np.array_equal(first[80, 10], [100, 0, 0])
    assert np.array_equal(first[80, 30], [0, 100, 0])
    assert np.array_equal(first[80, 50], [0, 0, 100])


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_angular_gallery_matches_white_before_applying_placeholder_gains(name):
    profile = load_profile(name)
    original_profile = profile_path(name).read_bytes()
    source = viewing_angle_scene(160, 96)
    on_axis = render_viewing_angle(profile, source)
    off_axis = render_viewing_angle(profile, source, 45)
    assert on_axis.dtype == off_axis.dtype == np.float32
    assert np.isfinite(on_axis).all() and np.isfinite(off_axis).all()
    # Identical white/exposure at baseline makes the subsequent gain visible;
    # neither the 850-nit OLED ceiling nor the IPS 400-nit cap sets this white.
    assert luminance(on_axis[:32, 128:]).mean() == pytest.approx(100, abs=0.005)
    assert luminance(off_axis[:32, 128:]).mean() < 100
    black_on = luminance(on_axis[:32, :32]).mean()
    black_off = luminance(off_axis[:32, :32]).mean()
    if profile.self_emissive:
        assert black_on == pytest.approx(0, abs=1e-7)
        assert black_off == pytest.approx(0, abs=1e-7)
    else:
        assert black_on == pytest.approx(100 / profile.panel.native_contrast, rel=1e-5)
        assert black_off > black_on
    assert np.array_equal(render_viewing_angle(profile, source), on_axis)
    assert profile_path(name).read_bytes() == original_profile


def test_gallery_angular_cli_appends_labeled_sheet_and_preserves_all_old_outputs(tmp_path):
    main(["gallery", "--viewing-angle", "--out", str(tmp_path), "--width", "160", "--height", "96"])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    sheet = manifest["sheets"][-1]
    assert sheet["id"] == "viewing_angle"
    assert len(sheet["rows"]) == 2
    assert all(row["reference_nits"] == 100 for row in sheet["rows"])
    assert all(len(row["statistics"]) == len(PROFILE_NAMES) for row in sheet["rows"])
    assert all("P placeholder" in caption for row in sheet["rows"] for caption in row["captions"])
    assert "+0 deg" in sheet["rows"][0]["title"]
    assert "+45 deg" in sheet["rows"][1]["title"]
    experiment = manifest["angular_experiment"]
    assert experiment["evidence"] == "P"
    assert experiment["current_profile_calibration"] == "NR"
    assert experiment["horizontal_deg"] == [0, 45] and experiment["vertical_deg"] == 0
    assert len(experiment["models"]) == len(PROFILE_NAMES)
    assert all(model["full_angular_fit"] == "NR" for model in experiment["models"])
    assert all(
        parameter["status"] == "P"
        for model in experiment["models"]
        for parameter in model["parameters"].values()
    )
    with Image.open(tmp_path / sheet["file"]) as image:
        assert image.mode == "RGB" and image.width == 700
        assert np.asarray(image).std() > 10
    html = (tmp_path / "index.html").read_text()
    assert 'href="#viewing_angle"' in html
    assert 'src="viewing_angle.png"' in html
    assert "P placeholders" in html and "OLED angular spectra/gains" in html
    assert "No named TV is calibrated" in html

    fixtures = Path(__file__).parent / "fixtures"
    legacy = json.loads((fixtures / "memc_off_baseline.json").read_text())["gallery"]
    m9 = json.loads((fixtures / "window_replay_off_baseline.json").read_text())["gallery"]
    expected_images = dict(legacy["decoded_previews"], **m9["decoded_previews"])
    for filename, expected in expected_images.items():
        pixels = np.asarray(Image.open(tmp_path / filename).convert("RGB"))
        assert sha256(pixels.tobytes()).hexdigest() == expected["sha256"]
    assert (
        sha256((tmp_path / "memc_trace.json").read_bytes()).hexdigest()
        == m9["memc_trace_json_sha256"]
    )
    # Removing the experiment recovers the entire authenticated old manifest,
    # including numeric statistics (within CPU roundoff), settings and labels.
    manifest.pop("angular_experiment")
    manifest["sheets"].pop()
    assert_numeric_metadata(
        legacy_labels(manifest), gallery_manifest_baseline(m9["manifest_json_sha256"])
    )
