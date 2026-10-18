"""Authenticated pre-M13 current-tree snapshots supplement the M7/M9 goldens.

Captured before runtime edits: M10 angular rendering, repeated/analytic display
ticks, profile identities and the web transport. No saved M4 report or older
golden is regenerated. Code hashes in export manifests necessarily describe
the current implementation. Historical rendered values and gallery statistics
allow declared numerical roundoff; stable metadata and traces remain exact.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from golden_support import (
    NumericResult,
    RenderedDigest,
    assert_historical_snapshot,
    assert_numeric_metadata,
    legacy_labels,
    link_rendered_hashes,
    rendered_file_digest,
)
from golden_support import array_digest as _array_digest
from PIL import Image

from tv_sim.export_web import generate_web_export
from tv_sim.gallery import PROFILE_NAMES, generate_gallery, scenes
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile, profile_path
from tv_sim.sequence import MotionConfig
from tv_sim.stages.encode import encode_frame
from tv_sim.viewing_angle import ViewingAngleConfig

pytestmark = [pytest.mark.slow, pytest.mark.golden]

BASELINE = Path(__file__).parent / "fixtures" / "oled_dynamics_off_baseline.json"


def _state_digest(pipeline):
    return {
        "panel_previous": _array_digest(pipeline.state.previous),
        "load_apl_nits_hex": (
            None
            if pipeline.load_state.apl_nits is None
            else float(pipeline.load_state.apl_nits).hex()
        ),
    }


def _inputs():
    y, x = np.indices((24, 40), dtype=np.int32)
    picture = np.stack(
        ((3 * x + 5 * y) % 256, (11 * x + y) % 256, (x + 13 * y) % 256), axis=-1
    ).astype(np.uint8)
    return [
        np.zeros_like(picture),
        picture,
        np.roll(picture, 7, axis=1),
        np.full_like(picture, 255),
        np.roll(picture, -5, axis=1),
        np.zeros_like(picture),
    ]


def _frame_digest(frame, pipeline):
    return {
        "rgb": _array_digest(frame.rgb),
        "backlight": _array_digest(frame.backlight),
        "preview": _array_digest(encode_frame(frame, pipeline.profile.output), preview=True),
        "history": _state_digest(pipeline),
    }


def _pipeline_snapshot(name, *, angular=False, dynamics_kwargs=None):
    kwargs = {} if dynamics_kwargs is None else dynamics_kwargs
    angle = ViewingAngleConfig(enabled=angular, horizontal_deg=45 if angular else 0)
    pipeline = Pipeline(load_profile(name), viewing_angle=angle, **kwargs)
    outputs = [_frame_digest(pipeline.run_linear(source), pipeline) for source in _inputs()]
    return {"frames": outputs, "final_history": _state_digest(pipeline)}


def _sequence_snapshot(name, mode, *, dynamics_kwargs=None):
    kwargs = {} if dynamics_kwargs is None else dynamics_kwargs
    pipeline = Pipeline(load_profile(name), **kwargs)
    config = (
        MotionConfig(mode="off")
        if mode == "off"
        else MotionConfig(
            mode=mode, source_fps="24000/1001", output_fps="60000/1001", translation_px=(7, 0)
        )
    )
    outputs = []
    for output in pipeline.run_sequence(_inputs(), config, cuts=[3]):
        outputs.append(dict(_frame_digest(output.frame, pipeline), diagnostics=output.diagnostics))
    return {"frames": outputs, "final_history": _state_digest(pipeline)}


def _profile_snapshot():
    files, effective = {}, {}
    for name in PROFILE_NAMES:
        for suffix in (".yaml", ".provenance.yaml", ".angular.yaml"):
            path = profile_path(name).with_name(name + suffix)
            payload = path.read_bytes()
            files[path.name] = {"byte_length": len(payload), "sha256": sha256(payload).hexdigest()}
        effective[name] = sha256(
            json.dumps(asdict(load_profile(name)), sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    return {"files": files, "effective_profile_sha256": effective}


def _gallery_snapshot(out, *, angular=False):
    generate_gallery(out, width=160, height=96, viewing_angle=angular)
    manifest = legacy_labels(json.loads((out / "manifest.json").read_text()))
    return {
        "manifest": manifest,
        "decoded_previews": {
            path.name: _array_digest(np.asarray(Image.open(path).convert("RGB")), preview=True)
            for path in sorted(out.glob("*.png"))
        },
        "other_files": {
            path.name: sha256(
                legacy_labels(path.read_text()).encode()
                if path.suffix == ".html"
                else path.read_bytes()
            ).hexdigest()
            for path in sorted(out.iterdir())
            if path.suffix != ".png"
        },
    }


def _assert_gallery_snapshot(out, expected, *, angular=False):
    """Compare authenticated renders numerically, retaining exact trace hashes."""
    actual = _gallery_snapshot(out, angular=angular)
    expected_manifest = expected["manifest"]
    payload = (json.dumps(expected_manifest, indent=2, allow_nan=False) + "\n").encode()
    assert_historical_snapshot(
        sha256(payload).hexdigest(), expected["other_files"]["manifest.json"]
    )
    assert_numeric_metadata(actual["manifest"], expected_manifest)
    assert_historical_snapshot(actual["decoded_previews"], expected["decoded_previews"])
    assert_historical_snapshot(
        {key: value for key, value in actual["other_files"].items() if key != "manifest.json"},
        {key: value for key, value in expected["other_files"].items() if key != "manifest.json"},
    )


def _export_snapshot(out):
    generate_web_export(out, width=160, height=96, motion_frames=3)
    return _read_export_snapshot(out)


def _read_export_snapshot(out):
    manifest = json.loads((out / "manifest.json").read_text())
    manifest.pop("implementation_sha256")
    manifest = link_rendered_hashes(manifest, out)
    sources = scenes(160, 96)
    for scene in manifest["scenes"]:
        if "source_linear_float32_sha256" in scene:
            source = sources[scene["id"]].astype("<f4")
            digest = sha256(source.tobytes()).hexdigest()
            assert digest == scene["source_linear_float32_sha256"]
            scene["source_linear_float32_sha256"] = RenderedDigest({"sha256": digest}, source)
        for asset in scene["assets"].values():
            # These fields describe rendered/quantised values, rather than
            # protocol metadata. The transport itself is checked to one FP16 ULP.
            for key, value in asset["statistics"].items():
                if isinstance(value, float):
                    rel, absolute = 1e-3, 1e-7
                    if key == "float16_max_absolute_error_nits":
                        rel, absolute = (
                            0,
                            max(1e-7, asset["statistics"]["peak_channel_nits"] * 2e-6),
                        )
                    asset["statistics"][key] = NumericResult(value, rel=rel, absolute=absolute)
    return {
        "manifest": legacy_labels(manifest),
        "files": {
            path.relative_to(out).as_posix(): rendered_file_digest(
                path, {"sha256": sha256(path.read_bytes()).hexdigest()}
            )
            if path.suffix in (".png", ".f16")
            else sha256(path.read_bytes()).hexdigest()
            for path in sorted(out.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        },
    }


def _window_snapshot(name):
    """v1 replay remains a one-owner forward model with its original history."""
    import tv_sim.window_replay as windows

    original = windows.Pipeline
    traces = []

    class RecordingPipeline(original):
        def display_content(self, *args, **kwargs):
            frame = super().display_content(*args, **kwargs)
            traces.append(_state_digest(self))
            return frame

    cases = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(windows, "Pipeline", RecordingPipeline)
        for fraction, scale in ((0.25, 0.6), (1.0, 1.7)):
            traces.clear()
            conditions = windows.ReplayConditions(
                1000.0, frame_time_ms=10.0, pre_roll_ms=20.0, settle_ms=30.0, hold_ms=40.0
            )
            replay = windows.replay_window(
                load_profile(name), fraction, conditions, scale, width=32, height=24
            )
            cases.append(
                {
                    "rgb": _array_digest(replay.frame.rgb),
                    "backlight": _array_digest(replay.frame.backlight),
                    "luminance_nits": replay.luminance_nits,
                    "center_trace_nits": replay.center_trace_nits,
                    "area_fraction_actual": replay.area_fraction_actual,
                    "requested_apl_nits": replay.requested_apl_nits,
                    "processed_request_apl_nits": replay.processed_request_apl_nits,
                    "drive_apl_nits": replay.drive_apl_nits,
                    "history": list(traces),
                }
            )
    return cases


def _force_explicit_off(monkeypatch):
    """Exercise public adapters with the same explicitly disabled config."""
    import tv_sim.export_web as export
    import tv_sim.gallery as gallery
    import tv_sim.validate as validate
    import tv_sim.window_replay as windows
    from tv_sim.abl_dynamics import ABLDynamicsConfig

    class ExplicitOffPipeline(Pipeline):
        def __init__(self, *args, **kwargs):
            kwargs["abl_dynamics"] = ABLDynamicsConfig(model="off")
            super().__init__(*args, **kwargs)

    for module in (export, gallery, validate, windows):
        monkeypatch.setattr(module, "Pipeline", ExplicitOffPipeline)


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", autouse=True)
def after_enabled_dynamics(tmp_path_factory):
    """All supplementary goldens execute after a complete enabled experiment."""
    from tv_sim.abl_dynamics import ABLDynamicsConfig
    from tv_sim.oled_dynamics_experiment import load_protocol, run_experiment

    protocol = load_protocol()
    protocol["protocol_id"] = "m13_parity_prehistory"
    protocol["settings"].update(
        width=40, height=24, output_fps="100", onset_interval_s="1/100", late_interval_s="1/100"
    )
    protocol["trials"] = [
        {
            "trial_id": "shared_history",
            "family": "parity",
            "segments": [
                {"label": label, "fraction": fraction, "duration_s": duration}
                for label, fraction, duration in (
                    ("black_preroll", 0.0, ".02"),
                    ("small", 0.1, ".02"),
                    ("full", 1.0, ".03"),
                    ("recovery", 0.1, ".04"),
                    ("black", 0.0, ".02"),
                )
            ],
        }
    ]
    config = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    root = tmp_path_factory.mktemp("m13-enabled-before-parity")
    manifest = run_experiment(
        load_profile("generic_woled"), config, protocol, root / "experiment", gallery=True
    )
    assert len(manifest["trials"]) == 2
    assert all(trial["ticks"] == 13 for trial in manifest["trials"])


def test_profile_bytes_and_effective_identities_match_pre_m13(baseline):
    assert_historical_snapshot(_profile_snapshot(), baseline["profiles"])


@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_off_allocates_no_capacity_or_discovers_history(monkeypatch, explicit_off, baseline):
    import tv_sim.pipeline as pipeline_module
    from tv_sim.abl_dynamics import ABLDynamicsConfig

    def unexpected(*args, **kwargs):
        pytest.fail("disabled dynamics entered capacity allocation/evolution/history discovery")

    monkeypatch.setattr(pipeline_module, "ABLCapacityState", unexpected)
    monkeypatch.setattr(pipeline_module, "update_capacity", unexpected)
    monkeypatch.setattr(Pipeline, "identity", unexpected)
    kwargs = {"abl_dynamics": ABLDynamicsConfig(model="off")} if explicit_off else {}
    pipeline = Pipeline(load_profile("generic_woled"), **kwargs)
    assert pipeline.capacity_state is None
    frames = [_frame_digest(pipeline.run_linear(source), pipeline) for source in _inputs()]
    assert_historical_snapshot(frames, baseline["pipeline"]["generic_woled"]["False"]["frames"])
    assert pipeline.capacity_state is None


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("angular", [False, True], ids=["default-angle", "M10-active"])
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_pipeline_off_matches_pre_m13(name, angular, explicit_off, baseline):
    from tv_sim.abl_dynamics import ABLDynamicsConfig

    kwargs = {"abl_dynamics": ABLDynamicsConfig(model="off")} if explicit_off else {}
    assert_historical_snapshot(
        _pipeline_snapshot(name, angular=angular, dynamics_kwargs=kwargs),
        baseline["pipeline"][name][str(angular)],
    )


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("mode", ["off", "repeat", "analytic"])
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_motion_and_histories_match_pre_m13(name, mode, explicit_off, baseline):
    from tv_sim.abl_dynamics import ABLDynamicsConfig

    kwargs = {"abl_dynamics": ABLDynamicsConfig(model="off")} if explicit_off else {}
    assert_historical_snapshot(
        _sequence_snapshot(name, mode, dynamics_kwargs=kwargs), baseline["sequence"][name][mode]
    )


@pytest.mark.parametrize("angular", [False, True], ids=["default", "M10-angular"])
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_gallery_after_active_experiment_matches_pre_m13(
    tmp_path,
    monkeypatch,
    angular,
    explicit_off,
    baseline,
):
    if explicit_off:
        _force_explicit_off(monkeypatch)
    _assert_gallery_snapshot(
        tmp_path / "gallery", baseline["gallery"][str(angular)], angular=angular
    )


@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_export_after_active_experiment_matches_pre_m13(
    tmp_path, monkeypatch, explicit_off, baseline
):
    if explicit_off:
        _force_explicit_off(monkeypatch)
    assert_historical_snapshot(_export_snapshot(tmp_path / "export"), baseline["export"])


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_v1_m9_replay_and_histories_match_pre_m13(name, monkeypatch, explicit_off, baseline):
    if explicit_off:
        _force_explicit_off(monkeypatch)
    assert_historical_snapshot(_window_snapshot(name), baseline["m9_replay"][name])


@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_m4_validation_after_active_experiment_matches_original_golden(
    tmp_path,
    monkeypatch,
    explicit_off,
):
    from test_memc_parity import _assert_validation_snapshot

    if explicit_off:
        _force_explicit_off(monkeypatch)
    out = tmp_path / "validation"
    legacy = json.loads((BASELINE.parent / "memc_off_baseline.json").read_text())
    _assert_validation_snapshot(out, legacy["validation"])
