"""Pre-M14 artifact goldens supplement the existing M7/M9/M13 parity suite.

The older captures already cover all default profiles, complete M4 reports,
default/angular galleries, M9 replay, phase-1 sequence diagnostics and physical
histories, and web-export assets. This capture adds the phase-1 motion CLI's
saved artifacts and M13's enabled experiment artifacts. Expected values were
saved before any M14 runtime changes. Historical images/arrays use authenticated
decoded references and declared tolerances; HTML and substantive checkpoint
state remain exact. Implementation fingerprints are excluded, actual checkpoint
checksums are validated, and NumPy environment identity must match this host.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from golden_support import assert_historical_snapshot, legacy_labels, rendered_file_digest
from PIL import Image

from tv_sim.gallery import PROFILE_NAMES
from tv_sim.profile import load_profile

pytestmark = [pytest.mark.slow, pytest.mark.golden]

BASELINE = Path(__file__).parent / "fixtures" / "m14_current_baseline.json"


def _substantive_json(value):
    """Strip implementation fingerprints, retaining source/profile identities."""
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

                # The enclosing checksum changes with implementation identity,
                # but must still cover the entire actual checkpoint exactly.
                assert value["checkpoint_sha256"] == digest(
                    {key: item for key, item in value.items() if key != "checkpoint_sha256"}
                )
            if path.name == "manifest.json" and "sources" in value:
                # Temporary input directory differs between capture/test runs.
                for source in value["sources"]:
                    source["file"] = Path(source["file"]).name
            payload = json.dumps(_substantive_json(value), sort_keys=True, allow_nan=False).encode()
        else:
            payload = path.read_bytes()
        files[path.relative_to(out).as_posix()] = rendered_file_digest(
            path,
            {"bytes": len(payload), "sha256": sha256(payload).hexdigest()},
            payload=payload,
            artifact_root=out,
        )
    return files


def _motion_cli_snapshot(root, name, mode):
    from tv_sim.motion_cli import main

    sources = root / "sources"
    sources.mkdir(parents=True)
    y, x = np.indices((24, 40), dtype=np.int32)
    picture = np.stack(
        ((3 * x + 5 * y) % 256, (11 * x + y) % 256, (x + 13 * y) % 256), axis=-1
    ).astype(np.uint8)
    for index, frame in enumerate(
        (picture, np.roll(picture, 7, axis=1), np.full_like(picture, 255), np.zeros_like(picture))
    ):
        Image.fromarray(frame).save(sources / f"source_{index:03d}.png")
    out = root / "motion"
    args = [
        "--profile",
        name,
        "--input-frames",
        str(sources / "source_*.png"),
        "--source-fps",
        "24000/1001",
        "--memc",
        mode,
        "--cut-before",
        "2",
        "--preview-reference-nits",
        "1000",
        "--out",
        str(out),
    ]
    if mode != "off":
        args.extend(["--output-fps", "60000/1001", "--translation-px", "7", "0"])
    main(args)
    return _artifact_snapshot(out)


def _oled_dynamics_snapshot(root, name):
    from tv_sim.abl_dynamics import ABLDynamicsConfig
    from tv_sim.oled_dynamics_experiment import load_protocol, run_experiment

    protocol = load_protocol()
    protocol["protocol_id"] = "m14_prechange_capacity_artifacts"
    protocol["settings"].update(
        width=40, height=24, output_fps="100", onset_interval_s="1/100", late_interval_s="1/100"
    )
    protocol["trials"] = [
        {
            "trial_id": "small_full_recovery",
            "family": "parity",
            "segments": [
                {"label": label, "fraction": fraction, "duration_s": duration}
                for label, fraction, duration in (
                    ("black_preroll", 0.0, ".02"),
                    ("small", 0.01, ".02"),
                    ("full", 1.0, ".04"),
                    ("recovery", 0.01, ".04"),
                    ("black", 0.0, ".02"),
                )
            ],
        }
    ]
    config = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    out = root / "oled-dynamics"
    run_experiment(load_profile(name), config, protocol, out, gallery=True)
    return _artifact_snapshot(out)


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("mode", ["off", "repeat", "analytic"])
def test_phase1_motion_cli_artifacts_match_pre_m14(tmp_path, name, mode, baseline):
    assert_historical_snapshot(
        _motion_cli_snapshot(tmp_path, name, mode), baseline["motion_cli"][name][mode]
    )


@pytest.mark.parametrize("name", ["generic_woled", "generic_qdoled"])
def test_oled_dynamics_artifacts_match_pre_m14(tmp_path, name, baseline):
    assert_historical_snapshot(
        _oled_dynamics_snapshot(tmp_path, name), baseline["oled_dynamics"][name]
    )
