"""Static pre-MEMC goldens protect the default/off display path.

Captured before the M7 implementation, rather than deriving expected outputs
from a second execution of the implementation under test. Arrays are hashed as
contiguous bytes with their shape/dtype so float32 parity is exact. PNG parity
uses decoded pixels, independent of compression/metadata. The original M4
harness is exercised at its full 384x216 defaults, including its historic load
state convention. Gallery comparisons retain every pre-M7 sheet and setting;
new opt-in motion demonstrations may add sheets without changing these goldens.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from sim.gallery import PROFILE_NAMES, generate_gallery
from sim.patterns import white_window
from sim.pipeline import Pipeline
from sim.profile import load_profile
from sim.stages.encode import encode_frame
from sim.validate import run_validation

BASELINE = Path(__file__).parent / "fixtures" / "memc_off_baseline.json"


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
    return {"manifest": manifest, "decoded_previews": _png_digests(out)}


@pytest.fixture(scope="module")
def memc_off_baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_default_pipeline_matches_pre_memc_golden(name, memc_off_baseline):
    assert _pipeline_snapshot(load_profile(name)) == memc_off_baseline["pipeline"][name]


def test_original_validation_harness_matches_pre_memc_golden(tmp_path, memc_off_baseline):
    assert _validation_snapshot(tmp_path / "validate") == memc_off_baseline["validation"]


def test_existing_gallery_matches_pre_memc_golden(tmp_path, memc_off_baseline):
    current = _gallery_snapshot(tmp_path / "gallery")
    expected = memc_off_baseline["gallery"]
    # New M7 demonstrations can be appended. Every existing sheet, row,
    # exposure, profile setting and decoded contact-sheet pixel is immutable.
    legacy_ids = {sheet["id"] for sheet in expected["manifest"]["sheets"]}
    current_manifest = current["manifest"]
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
