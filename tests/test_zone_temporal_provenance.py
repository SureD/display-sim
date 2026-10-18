"""Strict P-only protocol and M9 history-ownership rejection tests for M17."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from tv_sim.profile import load_profile
from tv_sim.window_replay import ReplayConditions, fit_windows, replay_fit, replay_window
from tv_sim.zone_temporal import MODEL, ZoneTemporalConfig
from tv_sim.zone_temporal_provenance import (
    PROTOCOL_PATH,
    load_protocol,
    validate_protocol,
    validate_zone_temporal_provenance,
)


def test_packaged_protocol_is_separate_p_ledger() -> None:
    data = load_protocol()
    assert validate_zone_temporal_provenance() == []
    assert data["evidence"] == "P"
    assert all(value == "NR" for value in data["unavailable"].values())
    assert ZoneTemporalConfig().model == "off"
    assert ZoneTemporalConfig().attack_s is None


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "schema_version", True),
        (None, "schema_version", 2),
        (None, "protocol_id", "unreviewed"),
        (None, "evidence", "M"),
        (None, "parameter_status", "measured"),
        (None, "notes", ""),
        (None, "fixtures", ["moving_object"]),
        ("settings", "width", True),
        ("settings", "height", 0),
        ("settings", "output_fps", 60),
        ("settings", "output_fps", "nan"),
        ("settings", "output_fps", "0"),
        ("settings", "duration_s", "0.001"),
        ("settings", "duration_s", "1/7"),
        ("settings", "level_nits", float("nan")),
        ("settings", "level_nits", True),
        ("settings", "level_nits", 0),
        ("settings", "dark_scene_nits", -1),
        ("settings", "dark_scene_nits", 800),
        ("settings", "halo_threshold_nits", 0),
        ("settings", "preview_reference_nits", float("inf")),
        ("settings", "settling_fraction", 0),
        ("settings", "settling_fraction", 1),
        ("demonstration", "attack_s", -1),
        ("demonstration", "release_s", None),
        ("demonstration", "model", "vendor"),
        ("demonstration", "initial", "resume"),
        ("demonstration", "reset_on_scene_cut", 1),
        ("demonstration", "slew_nits_per_tick", 0),
        ("demonstration", "cut_detection_threshold", 0),
        ("unavailable", "measured_attack_s", 0.05),
    ],
)
def test_protocol_rejects_ambiguous_or_promoted_values(
    section: str | None, field: str, value: object
) -> None:
    data = load_protocol()
    target = data if section is None else data[section]
    target[field] = value
    assert validate_zone_temporal_provenance(data)


@pytest.mark.parametrize("section", [None, "settings", "demonstration", "unavailable"])
@pytest.mark.parametrize("operation", ["extra", "missing"])
def test_protocol_requires_exact_fields(section: str | None, operation: str) -> None:
    data = load_protocol()
    target = data if section is None else data[section]
    if operation == "extra":
        target["unrecognized"] = 1
    else:
        del target[next(iter(target))]
    with pytest.raises(ValueError):
        validate_protocol(data)


def test_detector_cannot_silently_enable_reset() -> None:
    data = load_protocol()
    data["demonstration"].update(reset_on_scene_cut=False, cut_detection_threshold=0.5)
    with pytest.raises(ValueError, match="detection requires"):
        validate_protocol(data)


def test_protocol_duplicate_json_keys_reject(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.json"
    path.write_text(
        PROTOCOL_PATH.read_text().replace(
            '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,'
        )
    )
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_protocol(path)


def test_protocol_works_independently_of_current_directory(tmp_path: Path) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "tv_sim", "provenance", "--check", "--profiles", "generic_ips_edge"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert process.returncode == 0, process.stderr
    assert "zone-temporal" in process.stdout


def test_m9_rejects_zone_history_before_replay_or_fitting() -> None:
    config = ZoneTemporalConfig(model=MODEL, attack_s=0.05, release_s=0.15)
    profile = load_profile("generic_va_fald_miniled")
    conditions = ReplayConditions(level_nits=100)
    original = deepcopy(profile)
    with pytest.raises(ValueError, match="M9.*zone temporal"):
        replay_window(profile, 0.1, conditions, zone_temporal=config)
    with pytest.raises(ValueError, match="M9.*zone temporal"):
        fit_windows(profile, {}, "source", "fit", conditions=conditions, zone_temporal=config)
    with pytest.raises(ValueError, match="M9.*zone temporal"):
        replay_fit(profile, {}, zone_temporal=config)
    assert profile == original


def test_json_protocol_preserves_evidence_roundtrip() -> None:
    data = json.loads(json.dumps(load_protocol(), allow_nan=False))
    validate_protocol(data)
