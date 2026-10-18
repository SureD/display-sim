"""Still-image CLI explicitly selects synthetic angular experiments."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tv_sim.cli import main
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.viewing_angle import ViewingAngleConfig


@pytest.fixture
def source(tmp_path):
    image = np.zeros((12, 24, 3), np.uint8)
    image[:, :8] = 255
    image[:, 8:16] = (80, 100, 140)
    path = tmp_path / "source.png"
    Image.fromarray(image).save(path)
    return path, image


@pytest.mark.parametrize(
    "options,horizontal,vertical",
    [
        (["--viewing-angle", "45"], 45.0, 0.0),
        (["--viewing-angle-horizontal", "-30"], -30.0, 0.0),
        (["--viewing-angle-vertical", "45"], 0.0, 45.0),
        (["--viewing-angle-horizontal", "20", "--viewing-angle-vertical", "25"], 20.0, 25.0),
    ],
)
def test_angle_options_select_runtime_model_without_editing_profile(
    tmp_path, source, options, horizontal, vertical
):
    path, image = source
    output = tmp_path / "angular.png"
    original = load_profile("generic_va_fald_miniled")
    main(["--profile", original.name, "--input", str(path), "--output", str(output), *options])
    expected = Pipeline(
        original,
        viewing_angle=ViewingAngleConfig(
            enabled=True,
            horizontal_deg=horizontal,
            vertical_deg=vertical,
        ),
    ).run(image)
    np.testing.assert_array_equal(np.asarray(Image.open(output)), expected)
    assert not np.array_equal(expected, Pipeline(original).run(image))
    assert load_profile(original.name) == original


def test_zero_angle_cli_is_byte_identical_to_default(tmp_path, source):
    path, _ = source
    baseline, zero = tmp_path / "baseline.png", tmp_path / "zero.png"
    common = ["--profile", "generic_qdoled", "--input", str(path)]
    main([*common, "--output", str(baseline)])
    main([*common, "--output", str(zero), "--viewing-angle", "0", "--viewing-angle-vertical", "0"])
    assert baseline.read_bytes() == zero.read_bytes()


@pytest.mark.parametrize(
    "options",
    [
        ["--viewing-angle", "46"],
        ["--viewing-angle-vertical", "-46"],
        ["--viewing-angle-horizontal", "40", "--viewing-angle-vertical", "40"],
        ["--viewing-angle", "nan"],
        ["--viewing-angle-vertical", "inf"],
    ],
)
def test_cli_rejects_invalid_angles_before_reading_or_writing_images(tmp_path, options):
    output = tmp_path / "must-not-exist.png"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sim",
            "--profile",
            "generic_woled",
            "--input",
            str(tmp_path / "missing.png"),
            "--output",
            str(output),
            *options,
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_cli_help_identifies_placeholder_and_support():
    result = subprocess.run(
        [sys.executable, "-m", "sim", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "placeholder" in result.stdout
    assert "0–45" in result.stdout
    assert "--viewing-angle-horizontal" in result.stdout
    assert "--viewing-angle-vertical" in result.stdout
