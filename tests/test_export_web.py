"""The web transport preserves absolute units, pipeline history and evidence."""

import json
from hashlib import sha256

import numpy as np
import pytest

from tv_sim.cli import main
from tv_sim.color import pq_oetf
from tv_sim.export_web import generate_web_export
from tv_sim.gallery import (
    INTEGRATION_SAMPLES,
    PAN_SPEED,
    PRE_ROLL,
    PROFILE_NAMES,
    _gallery_profile,
    render_still,
    scenes,
)
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile, profile_path

pytestmark = [pytest.mark.slow, pytest.mark.e2e]


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("web-export")
    baseline = {}
    for name in PROFILE_NAMES:
        for suffix in (".yaml", ".provenance.yaml", ".angular.yaml"):
            path = profile_path(name).with_name(name + suffix)
            baseline[path] = path.read_bytes()
    main(
        [
            "export-web",
            "--out",
            str(out),
            "--width",
            "160",
            "--height",
            "96",
            "--motion-frames",
            "3",
        ]
    )
    assert all(path.read_bytes() == contents for path, contents in baseline.items())
    return out, json.loads((out / "manifest.json").read_text())


def _scene(manifest, identifier):
    return next(scene for scene in manifest["scenes"] if scene["id"] == identifier)


def _frames(out, asset):
    return np.fromfile(out / asset["file"], dtype="<f2").reshape(
        asset["frame_count"],
        asset["height"],
        asset["width"],
        3,
    )


def test_export_cli_preserves_settings_and_ships_complete_profile_evidence(exported):
    out, manifest = exported
    assert manifest["schema_version"] == 1
    assert [profile["id"] for profile in manifest["profiles"]] == list(PROFILE_NAMES)
    assert manifest["resolution"] == [160, 96]
    assert "PLACEHOLDER" in manifest["disclaimer"]
    assert manifest["format"]["dtype"] == "float16"
    assert manifest["format"]["byte_order"] == "little"
    assert manifest["format"]["units"] == "linear-nit"
    assert manifest["format"]["primaries"] == "BT.709 / sRGB"
    assert "does not imply BT.2020" in manifest["format"]["pq_source_note"]
    assert "no calibrated gamut" in manifest["format"]["colorimetry_status"]
    assert set(manifest["implementation_sha256"]) >= {
        "src/tv_sim/export_web.py",
        "src/tv_sim/pipeline.py",
    }
    for profile in manifest["profiles"]:
        assert profile["settings"]["input"]["eotf"] == "srgb"
        assert profile["settings"]["temporal"]["integration_samples"] == 1
        for kind in ("still", "motion"):
            settings = profile["effective_settings"][kind]
            assert settings["input"]["eotf"] == "pq"
            assert settings["ambient"]["lux"] == 0
            assert settings["temporal"]["integration_samples"] == INTEGRATION_SAMPLES
        assert profile["effective_settings"]["still"]["temporal"]["motion_px_per_frame"] == 0
        assert (
            profile["effective_settings"]["motion"]["temporal"]["motion_px_per_frame"] == PAN_SPEED
        )
        assert set(profile["snapshots"]) == {"profile", "provenance", "angular"}
        assert profile["yaml_sha256"] == profile["snapshots"]["profile"]["sha256"]
        for snapshot in profile["snapshots"].values():
            payload = (out / snapshot["file"]).read_bytes()
            assert len(payload) == snapshot["byte_length"]
            assert sha256(payload).hexdigest() == snapshot["sha256"]
            assert (
                payload
                == profile_path(profile["id"])
                .with_name(snapshot["file"].split("/")[-1])
                .read_bytes()
            )


def test_every_scene_has_valid_headerless_absolute_nit_fp16_for_all_four_profiles(exported):
    out, manifest = exported
    assert {scene["id"] for scene in manifest["scenes"]} == {
        "starfield",
        "subtitles",
        "bright_window",
        "wide_window",
        "gradients",
        "macro_subpixel",
        "macro_apertures",
        "motion_pan",
    }
    total_bytes = 0
    for scene in manifest["scenes"]:
        assert set(scene["assets"]) == set(PROFILE_NAMES)
        for asset in scene["assets"].values():
            payload = (out / asset["file"]).read_bytes()
            assert sha256(payload).hexdigest() == asset["sha256"]
            assert (
                len(payload)
                == asset["byte_length"]
                == asset["frame_count"] * asset["frame_stride_bytes"]
            )
            assert asset["frame_stride_bytes"] == asset["width"] * asset["height"] * 3 * 2
            assert [asset["width"], asset["height"], asset["frame_count"]] == [
                scene["width"],
                scene["height"],
                scene["frame_count"],
            ]
            rgb = _frames(out, asset)
            assert np.isfinite(rgb).all() and np.all(rgb >= 0)
            assert rgb.max() > 1  # unencoded nits, no 0–1 or per-TV normalization
            assert asset["statistics"]["peak_channel_nits"] == float(rgb.max())
            total_bytes += len(payload)
    assert total_bytes == manifest["asset_bytes"]
    window = _scene(manifest, "bright_window")
    peaks = [window["assets"][name]["statistics"]["peak_channel_nits"] for name in PROFILE_NAMES]
    assert peaks[0] > peaks[3] > peaks[2] > peaks[1]


def test_stills_are_ordinary_gallery_linear_outputs_with_only_fp16_quantization(exported):
    out, manifest = exported
    sources = scenes(160, 96)
    for name in PROFILE_NAMES:
        for identifier in ("bright_window", "gradients"):
            asset = _scene(manifest, identifier)["assets"][name]
            expected = render_still(load_profile(name), sources[identifier])
            actual = _frames(out, asset)[0]
            assert np.array_equal(actual, expected.astype("<f2"))
            assert np.max(np.abs(actual.astype(np.float32) - expected)) == pytest.approx(
                asset["statistics"]["float16_max_absolute_error_nits"],
                abs=1e-6,
            )


def test_pan_transports_real_persistent_history_and_correct_frame_timing(exported):
    out, manifest = exported
    scene = _scene(manifest, "motion_pan")
    protocol = manifest["temporal_protocol"]
    assert protocol["pre_roll_frames"] == PRE_ROLL
    assert scene["frame_source_indices"] == [1, 2, 3]
    assert scene["fps"] == pytest.approx(1000 / 16.666)
    assert scene["pts_seconds"] == pytest.approx([0, 0.016666, 0.033332])
    assert "Not a continuous loop" in scene["loop_boundary"]
    encoded = pq_oetf(scenes(160, 96)["motion_pan"])
    for name in PROFILE_NAMES:
        configured = _gallery_profile(load_profile(name), motion=PAN_SPEED)
        pipeline = Pipeline(configured)
        for _ in range(PRE_ROLL):
            pipeline.run_linear(encoded)
        expected = []
        for frame_index in range(1, 4):
            source = np.roll(encoded, int(frame_index * PAN_SPEED), axis=1)
            expected.append(pipeline.run_linear(source).rgb)
        actual = _frames(out, scene["assets"][name])
        assert np.array_equal(actual, np.asarray(expected, dtype="<f2"))
        if name == "generic_va_fald_miniled":
            cold = Pipeline(configured).run_linear(np.roll(encoded, 8, axis=1)).rgb
            assert np.max(np.abs(actual[0].astype(np.float32) - cold)) > 1


def test_macro_apertures_keep_logical_cell_energy_and_disclose_synthetic_peaks(exported):
    out, manifest = exported
    scene = _scene(manifest, "macro_apertures")
    assert scene["kind"] == "macro"
    assert "P synthetic" in scene["macro"]["geometry_status"]
    assert "not physical" in scene["macro"]["statistics_note"]
    scale = scene["macro"]["scale"]
    cy, cx, height, width = scene["macro"]["crop_yxhw"]
    for name in PROFILE_NAMES:
        logical = _frames(out, _scene(manifest, "macro_subpixel")["assets"][name])[0].astype(
            np.float32
        )
        apertures = _frames(out, scene["assets"][name])[0].astype(np.float32)
        recovered = apertures.reshape(height, scale, width, scale, 3).mean(axis=(1, 3))
        np.testing.assert_allclose(
            recovered, logical[cy : cy + height, cx : cx + width], rtol=0.001, atol=0.02
        )
        assert apertures.max() > recovered.max()
        assert np.count_nonzero(apertures.sum(axis=-1) == 0) > 0  # black matrix


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 159},
        {"height": 95},
        {"width": 160.0},
        {"motion_frames": 0},
        {"motion_frames": -1},
        {"motion_frames": True},
    ],
)
def test_invalid_export_dimensions_and_duration_fail_before_writing(tmp_path, kwargs):
    out = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        generate_web_export(out, **kwargs)
    assert not out.exists()


def test_export_cli_rejects_zero_motion_frames(tmp_path):
    with pytest.raises(SystemExit, match="2"):
        main(["export-web", "--out", str(tmp_path / "invalid"), "--motion-frames", "0"])
    assert not (tmp_path / "invalid").exists()
