"""Static pre-MEMC goldens protect the default/off display path.

Captured before the M7 implementation, rather than deriving expected outputs
from a second execution of the implementation under test. Arrays are hashed as
contiguous bytes with their shape/dtype so float32 parity is exact. PNG parity
uses decoded pixels, independent of compression/metadata. The original M4
harness is exercised at its full 384x216 defaults, including its historic load
state convention. Gallery comparisons retain every pre-M7 sheet and setting;
an additional baseline captured from committed pre-M9 HEAD protects M7's
gallery additions, full manifest, and motion trace.
All checks run after an M9 fit has been saved, loaded, and replayed, so opting
into a separate fitting experiment cannot change later default rendering.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from sim.gallery import PROFILE_NAMES, generate_gallery
from sim.patterns import white_window
from sim.pipeline import Pipeline
import sim.profile as profiles
from sim.profile import load_profile
from sim.stages.encode import encode_frame
from sim.validate import run_validation

BASELINE = Path(__file__).parent / "fixtures" / "memc_off_baseline.json"
WINDOW_BASELINE = Path(__file__).parent / "fixtures" / "window_replay_off_baseline.json"


@pytest.fixture(scope="module", autouse=True)
def after_window_fit(tmp_path_factory):
    """Use an isolated fit before reusing all expensive, static golden checks.

    The copied runtime YAMLs retain the original bytes and profile identity.
    No fitted result is installed as a default profile, and the fitter must
    leave its caller's profile untouched as well as the files on disk.
    """
    from sim.provenance import load_provenance
    from sim.window_replay import (
        ReplayConditions, fit_windows, load_fit, replay_fit, save_fit,
    )

    root = tmp_path_factory.mktemp("m9-default-parity")
    profile_dir = root / "profiles"
    profile_dir.mkdir()
    original_files = {
        path.name: path.read_bytes() for path in profiles.PROFILES_DIR.glob("*.yaml")
    }
    for name, contents in original_files.items():
        (profile_dir / name).write_bytes(contents)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(profiles, "PROFILES_DIR", profile_dir)
        original_names = profiles.available_profiles()
        baseline = load_profile("generic_woled")
        original_profile = deepcopy(baseline)
        fit = fit_windows(
            baseline,
            load_provenance("generic_woled"),
            "c2_42_hdr_standard_peak",
            "m9_parity_exploratory_fit",
            fractions=[1.0],
            conditions=ReplayConditions(
                level_nits=1000.0,
                color_rgb=(1.0, 1.0, 1.0),
                settle_ms=0.0,
                hold_ms=1000.0 / 60.0,
                frame_time_ms=1000.0 / 60.0,
                pre_roll_ms=1000.0 / 60.0,
            ),
            exploratory=True,
        )
        artifact = root / "datasets" / "m9_parity.fit.json"
        save_fit(artifact, fit)
        restored = load_fit(artifact)
        assert restored == json.loads(json.dumps(fit))
        assert replay_fit(baseline, restored)
        assert baseline == original_profile
        assert profiles.available_profiles() == original_names
        assert {path.name: path.read_bytes() for path in profile_dir.glob("*.yaml")} == original_files
        yield artifact
        assert baseline == original_profile
        assert profiles.available_profiles() == original_names
        assert {path.name: path.read_bytes() for path in profile_dir.glob("*.yaml")} == original_files


def _array_digest(array: np.ndarray | None) -> dict | None:
    if array is None:
        return None
    array = np.ascontiguousarray(array)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "sha256": sha256(array.tobytes()).hexdigest(),
    }


def _inputs() -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Fixed encoded test pictures, independent of the motion implementation."""
    height, width = 48, 96
    y, x = np.indices((height, width), dtype=np.int32)
    pattern = np.stack(((3*x + 5*y) % 256, (11*x + y) % 256,
                        (x + 13*y) % 256), axis=-1).astype(np.uint8)
    stills = [white_window(height, width, fraction=.1), pattern]
    sequence = [np.zeros_like(pattern), pattern,
                np.roll(pattern, 7, axis=1), np.full_like(pattern, 255),
                np.roll(pattern, -5, axis=1), np.zeros_like(pattern)]
    return stills, sequence


def _frame_digest(frame, profile) -> dict:
    return {
        "rgb": _array_digest(frame.rgb),
        "backlight": _array_digest(frame.backlight),
        "preview": _array_digest(encode_frame(frame, profile.output)),
    }


def _state_digest(pipeline: Pipeline) -> dict:
    return {
        "panel_previous": _array_digest(pipeline.state.previous),
        "load_apl_nits_hex": (
            None if pipeline.load_state.apl_nits is None
            else float(pipeline.load_state.apl_nits).hex()
        ),
    }


def _pipeline_snapshot(profile) -> dict:
    stills, sequence = _inputs()
    still_results = []
    for source in stills:
        pipeline = Pipeline(profile)
        frame = pipeline.run_linear(source)
        still_results.append(dict(_frame_digest(frame, profile),
                                  final_state=_state_digest(pipeline)))
        # Exercise the public preview entry point with an independent history.
        assert _array_digest(Pipeline(profile).run(source)) == still_results[-1]["preview"]
    pipeline = Pipeline(profile)
    frames = [_frame_digest(pipeline.run_linear(source), profile) for source in sequence]
    previews = Pipeline(profile)
    assert [_array_digest(previews.run(source)) for source in sequence] == [
        frame["preview"] for frame in frames
    ]
    return {"stills": still_results, "sequence": frames,
            "final_state": _state_digest(pipeline)}


def _png_digests(out: Path, names: list[str] | None = None) -> dict:
    paths = sorted(out.glob("*.png")) if names is None else [out / name for name in names]
    return {path.name: _array_digest(np.asarray(Image.open(path).convert("RGB")))
            for path in paths}


def _validation_snapshot(out: Path) -> dict:
    run_validation(list(PROFILE_NAMES), out)
    return {
        "metrics_json_sha256": sha256((out / "metrics.json").read_bytes()).hexdigest(),
        "metrics_csv_sha256": sha256((out / "metrics.csv").read_bytes()).hexdigest(),
        "decoded_previews": _png_digests(out),
    }


def _gallery_snapshot(out: Path) -> dict:
    manifest = generate_gallery(out, width=160, height=96)
    return {
        "manifest": manifest,
        "decoded_previews": _png_digests(out),
        "manifest_json_sha256": sha256((out / "manifest.json").read_bytes()).hexdigest(),
        "memc_trace_json_sha256": sha256((out / "memc_trace.json").read_bytes()).hexdigest(),
    }


@pytest.fixture(scope="module")
def memc_off_baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def window_replay_off_baseline():
    return json.loads(WINDOW_BASELINE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_default_pipeline_matches_pre_memc_golden(name, memc_off_baseline):
    assert _pipeline_snapshot(load_profile(name)) == memc_off_baseline["pipeline"][name]


def test_original_validation_harness_matches_pre_memc_golden(tmp_path, memc_off_baseline):
    assert _validation_snapshot(tmp_path / "validate") == memc_off_baseline["validation"]


def test_existing_gallery_matches_pre_memc_golden(
    tmp_path, memc_off_baseline, window_replay_off_baseline,
):
    current = _gallery_snapshot(tmp_path / "gallery")
    expected = memc_off_baseline["gallery"]
    expected_m9 = window_replay_off_baseline["gallery"]
    legacy_ids = {sheet["id"] for sheet in expected["manifest"]["sheets"]}
    current_manifest = current["manifest"]
    # The second static capture includes M7's opt-in demonstrations. It was
    # generated by isolated committed HEAD code, never this implementation.
    assert current["manifest_json_sha256"] == expected_m9["manifest_json_sha256"]
    assert current["memc_trace_json_sha256"] == expected_m9["memc_trace_json_sha256"]
    assert [sheet for sheet in current_manifest["sheets"] if sheet["id"] not in legacy_ids] == expected_m9["additional_sheets"]
    assert {name: current["decoded_previews"][name] for name in expected_m9["decoded_previews"]} == expected_m9["decoded_previews"]
    # Retain every older sheet, row, exposure, profile setting and pixel too.
    current_manifest["sheets"] = [sheet for sheet in current_manifest["sheets"]
                                  if sheet["id"] in legacy_ids]
    assert {key: current_manifest[key] for key in expected["manifest"]} == expected["manifest"]
    assert {name: current["decoded_previews"][name] for name in expected["decoded_previews"]} == expected["decoded_previews"]


def _sequence_api_snapshot(profile, *, explicit_off: bool) -> dict:
    from sim.sequence import MotionConfig

    stills, sequence = _inputs()
    config = MotionConfig(mode="off") if explicit_off else None
    still_results = []
    for source in stills:
        pipeline = Pipeline(profile)
        outputs = list(pipeline.run_sequence([source], config))
        assert len(outputs) == 1
        still_results.append(dict(_frame_digest(outputs[0].frame, profile),
                                  final_state=_state_digest(pipeline)))
    pipeline = Pipeline(profile)
    outputs = list(pipeline.run_sequence(sequence, config))
    assert len(outputs) == len(sequence)
    return {"stills": still_results,
            "sequence": [_frame_digest(output.frame, profile) for output in outputs],
            "final_state": _state_digest(pipeline)}


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("explicit_off", [False, True], ids=["default", "explicit-off"])
def test_sequence_bypass_matches_pre_memc_golden(name, explicit_off, memc_off_baseline):
    assert _sequence_api_snapshot(load_profile(name), explicit_off=explicit_off) == memc_off_baseline["pipeline"][name]
