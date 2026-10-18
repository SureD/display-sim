"""Authenticated pre-M15 captures supplement the M7/M9/M13/M14 goldens.

The existing fixtures cover default pipelines, the full M4 validation harness,
the default/M10 galleries, M9 replay, M7 scheduling, M13 enabled experiments,
and every web-export asset. This fixture adds M14's inferred MCI sequence and
CLI outputs plus its complete synthetic validation/gallery artifacts, including
an enabled M13 display tail. Captures precede all M15 runtime edits. Historical
rendered values use golden_support's declared tolerances; stable JSON metadata
and rational traces remain exact. Implementation fingerprints are excluded.
"""

from __future__ import annotations

import importlib
import json
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from golden_support import array_digest as _array_digest
from golden_support import assert_historical_snapshot, legacy_labels, rendered_file_digest
from PIL import Image

from tv_sim.abl_dynamics import ABLDynamicsConfig
from tv_sim.block_motion import BlockMotionConfig
from tv_sim.gallery import PROFILE_NAMES
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.sequence import MotionConfig
from tv_sim.stages.encode import encode_frame

pytestmark = [pytest.mark.slow, pytest.mark.golden]

BASELINE = Path(__file__).parent / "fixtures" / "colorimetry_off_baseline.json"


def _inputs():
    y, x = np.indices((24, 40), dtype=np.int32)
    picture = np.stack(
        ((3 * x + 5 * y) % 256, (11 * x + y) % 256, (x + 13 * y) % 256), axis=-1
    ).astype(np.uint8)
    return (
        picture,
        np.roll(picture, 3, axis=1),
        np.full_like(picture, 255),
        np.zeros_like(picture),
    )


def _block_config():
    return BlockMotionConfig(
        estimation_width=40,
        estimation_height=24,
        pyramid_levels=2,
        search_radius=2,
        refinement_radius=1,
        subpixel_steps=(),
    )


def _sequence_snapshot(name, *, pipeline_kwargs=None):
    pipeline = Pipeline(load_profile(name), **(pipeline_kwargs or {}))
    config = MotionConfig(
        mode="mci", source_fps="24000/1001", output_fps="60000/1001", block=_block_config()
    )
    records = []
    for output in pipeline.run_sequence(_inputs(), config, cuts=[2]):
        records.append(
            {
                "rgb": _array_digest(output.frame.rgb),
                "backlight": _array_digest(output.frame.backlight),
                "preview": _array_digest(
                    encode_frame(output.frame, pipeline.profile.output), preview=True
                ),
                "diagnostics": output.diagnostics,
                "motion_maps": None
                if output.motion_maps is None
                else {key: _array_digest(value) for key, value in output.motion_maps.items()},
                "panel_previous": _array_digest(pipeline.state.previous),
                "load_apl_nits_hex": (
                    None
                    if pipeline.load_state.apl_nits is None
                    else float(pipeline.load_state.apl_nits).hex()
                ),
            }
        )
    return records


def _substantive_json(value):
    if isinstance(value, dict):
        return {
            key: _substantive_json(item)
            for key, item in value.items()
            if key not in ("code_sha256", "implementation_sha256", "checkpoint_sha256")
        }
    if isinstance(value, list):
        return [_substantive_json(item) for item in value]
    return legacy_labels(value)


def _artifact_snapshot(out):
    files = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            if path.name.endswith(".state.json"):
                from tv_sim.abl_dynamics import digest

                assert value["checkpoint_sha256"] == digest(
                    {key: item for key, item in value.items() if key != "checkpoint_sha256"}
                )
            if path.name == "manifest.json" and "sources" in value:
                for source in value["sources"]:
                    source["file"] = Path(source["file"]).name
            payload = json.dumps(_substantive_json(value), sort_keys=True, allow_nan=False).encode()
        else:
            payload = path.read_bytes()
        files[path.relative_to(out).as_posix()] = rendered_file_digest(
            path, {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}, payload=payload
        )
    return files


def _motion_cli_snapshot(root, name):
    from tv_sim.motion_cli import main
    from tv_sim.motion_provenance import block_config_record

    sources = root / "sources"
    sources.mkdir(parents=True)
    for index, frame in enumerate(_inputs()):
        Image.fromarray(frame).save(sources / f"source_{index:03d}.png")
    config_path = root / "motion.json"
    config_path.write_text(json.dumps(block_config_record(_block_config())))
    out = root / "motion"
    main(
        [
            "--profile",
            name,
            "--input-frames",
            str(sources / "source_*.png"),
            "--source-fps",
            "24000/1001",
            "--output-fps",
            "60000/1001",
            "--memc",
            "mci",
            "--motion-config",
            str(config_path),
            "--cut-before",
            "2",
            "--preview-reference-nits",
            "1000",
            "--out",
            str(out),
        ]
    )
    return _artifact_snapshot(out)


def _validation_snapshot(out, name=None):
    from tv_sim.motion_validate import run_validation

    kwargs = (
        {}
        if name is None
        else {
            "profile": load_profile(name),
            "abl_dynamics": ABLDynamicsConfig(
                model="capacity_attack_release_v1", attack_ms=100, release_ms=1000
            ),
        }
    )
    run_validation(
        out,
        width=40,
        height=24,
        source_count=4,
        block_config=_block_config(),
        gallery=True,
        **kwargs,
    )
    return _artifact_snapshot(out)


def _force_explicit_off(monkeypatch):
    """Pass the public disabled config through every legacy adapter."""
    from tv_sim.colorimetry import ColorimetryConfig

    class ExplicitOffPipeline(Pipeline):
        def __init__(self, *args, **kwargs):
            kwargs["colorimetry"] = ColorimetryConfig(enabled=False)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "Pipeline", ExplicitOffPipeline)
    for name in (
        "tv_sim.pipeline",
        "tv_sim.export_web",
        "tv_sim.gallery",
        "tv_sim.validate",
        "tv_sim.window_replay",
        "tv_sim.motion_cli",
        "tv_sim.oled_dynamics_experiment",
        "test_memc_parity",
        "test_oled_dynamics_parity",
        "test_m14_parity",
    ):
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "Pipeline", ExplicitOffPipeline, raising=False)


def _legacy_baseline(filename):
    return json.loads((BASELINE.parent / filename).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", autouse=True)
def after_enabled_colorimetry():
    """A new opt-in history must never contaminate later disabled rendering."""
    from tv_sim.colorimetry import ColorimetryConfig
    from tv_sim.viewing_angle import ViewingAngleConfig

    for name in PROFILE_NAMES:
        profile = load_profile(name)
        dynamics = (
            ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
            if profile.self_emissive
            else None
        )
        pipeline = Pipeline(
            profile,
            colorimetry=ColorimetryConfig(enabled=True),
            viewing_angle=ViewingAngleConfig(enabled=True, horizontal_deg=35),
            abl_dynamics=dynamics,
        )
        for source in _inputs():
            assert np.isfinite(pipeline.run_linear(source).rgb).all()


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_m14_mci_sequence_matches_pre_m15(name, explicit_off, monkeypatch, baseline):
    if explicit_off:
        _force_explicit_off(monkeypatch)
    assert_historical_snapshot(_sequence_snapshot(name), baseline["mci_sequence"][name])


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_m14_mci_cli_assets_match_pre_m15(tmp_path, name, explicit_off, monkeypatch, baseline):
    if explicit_off:
        _force_explicit_off(monkeypatch)
    assert_historical_snapshot(_motion_cli_snapshot(tmp_path, name), baseline["mci_cli"][name])


@pytest.mark.parametrize(
    "name",
    [None, "generic_woled", "generic_qdoled"],
    ids=["content-only", "M13-WOLED", "M13-QDOLED"],
)
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_m14_validation_and_gallery_assets_match_pre_m15(
    tmp_path, name, explicit_off, monkeypatch, baseline
):
    if explicit_off:
        _force_explicit_off(monkeypatch)
    assert_historical_snapshot(
        _validation_snapshot(tmp_path / "validation", name),
        baseline["motion_validation"][str(name)],
    )


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("angular", [False, True], ids=["default-angle", "M10-active"])
def test_explicit_off_pipeline_and_m10_match_pre_m13(name, angular, monkeypatch):
    legacy = importlib.import_module("test_oled_dynamics_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("oled_dynamics_off_baseline.json")
    assert_historical_snapshot(
        legacy._pipeline_snapshot(name, angular=angular), expected["pipeline"][name][str(angular)]
    )


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("mode", ["off", "repeat", "analytic"])
def test_explicit_off_m7_sequences_match_pre_m13(name, mode, monkeypatch):
    legacy = importlib.import_module("test_oled_dynamics_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("oled_dynamics_off_baseline.json")
    assert_historical_snapshot(
        legacy._sequence_snapshot(name, mode), expected["sequence"][name][mode]
    )


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_explicit_off_m9_replay_matches_pre_m13(name, monkeypatch):
    legacy = importlib.import_module("test_oled_dynamics_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("oled_dynamics_off_baseline.json")
    assert_historical_snapshot(legacy._window_snapshot(name), expected["m9_replay"][name])


@pytest.mark.parametrize("angular", [False, True], ids=["default", "M10-angular"])
def test_explicit_off_galleries_match_pre_m13(tmp_path, angular, monkeypatch):
    legacy = importlib.import_module("test_oled_dynamics_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("oled_dynamics_off_baseline.json")
    legacy._assert_gallery_snapshot(
        tmp_path / "gallery", expected["gallery"][str(angular)], angular=angular
    )


def test_explicit_off_web_assets_match_pre_m13(tmp_path, monkeypatch):
    legacy = importlib.import_module("test_oled_dynamics_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("oled_dynamics_off_baseline.json")
    assert_historical_snapshot(legacy._export_snapshot(tmp_path / "web"), expected["export"])


def test_explicit_off_validation_matches_pre_m7(tmp_path, monkeypatch):
    legacy = importlib.import_module("test_memc_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("memc_off_baseline.json")
    legacy._assert_validation_snapshot(tmp_path / "validation", expected["validation"])


@pytest.mark.parametrize("name", ["generic_woled", "generic_qdoled"])
def test_explicit_off_m13_enabled_experiments_match_pre_m14(tmp_path, name, monkeypatch):
    legacy = importlib.import_module("test_m14_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("m14_current_baseline.json")
    assert_historical_snapshot(
        legacy._oled_dynamics_snapshot(tmp_path, name), expected["oled_dynamics"][name]
    )


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("mode", ["off", "repeat", "analytic"])
def test_explicit_off_m7_cli_matches_pre_m14(tmp_path, name, mode, monkeypatch):
    legacy = importlib.import_module("test_m14_parity")
    _force_explicit_off(monkeypatch)
    expected = _legacy_baseline("m14_current_baseline.json")
    assert_historical_snapshot(
        legacy._motion_cli_snapshot(tmp_path, name, mode), expected["motion_cli"][name][mode]
    )
