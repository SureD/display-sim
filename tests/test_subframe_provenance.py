"""Strict independent P-only sub-frame protocol admission and packaging tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tv_sim.subframe_provenance import (
    PROTOCOL_PATH,
    load_protocol,
    validate_protocol,
    validate_subframe_provenance,
)


def test_packaged_subframe_protocol_is_strict_p_only():
    data = load_protocol()
    assert validate_subframe_provenance() == []
    assert data["evidence"] == "P"
    assert all(value == "NR" for value in data["unavailable"].values())
    validate_protocol(json.loads(json.dumps(data, allow_nan=False)))


@pytest.mark.parametrize(
    "section,field,value",
    [
        (None, "schema_version", True),
        (None, "schema_version", 2),
        (None, "protocol_id", "vendor"),
        (None, "evidence", "M"),
        (None, "parameter_status", "measured"),
        (None, "notes", ""),
        (None, "fixtures", ["moving_edge"]),
        ("settings", "width", True),
        ("settings", "height", 0),
        ("settings", "substeps", 1),
        ("settings", "output_fps", 60),
        ("settings", "output_fps", "nan"),
        ("settings", "output_fps", "0"),
        ("settings", "motion_duration_s", "1/7"),
        ("settings", "step_duration_s", "1/60"),
        ("settings", "flash_duration_s", "100"),
        ("settings", "level_nits", float("nan")),
        ("settings", "level_nits", True),
        ("settings", "dark_nits", 300),
        ("settings", "dark_nits", -1),
        ("settings", "preview_reference_nits", 0),
        ("settings", "speeds_px_s", [20, 10]),
        ("settings", "gray_levels_nits", [20, 20]),
        ("settings", "speeds_px_s", [1]),
        ("settings", "flash_hz", 30),
        ("settings", "settling_fraction", 0),
        ("settings", "settling_fraction", 1),
        ("demonstration", "rise_tau_ms", -1),
        ("demonstration", "fall_tau_ms", None),
        ("demonstration", "overdrive_gain", True),
        ("demonstration", "strobe_duty", "0"),
        ("demonstration", "bfi_duty", "2"),
        ("demonstration", "strobe_phase", "1"),
        ("demonstration", "bfi_phase", "-1/2"),
        ("demonstration", "pwm_hz", "960"),
        ("unavailable", "measured_overdrive_lut", [1, 2]),
    ],
)
def test_rejects_ambiguous_promoted_or_invalid_parameters(section, field, value):
    data = load_protocol()
    (data if section is None else data[section])[field] = value
    assert validate_subframe_provenance(data)


@pytest.mark.parametrize("section", [None, "settings", "demonstration", "unavailable"])
@pytest.mark.parametrize("operation", ["extra", "missing"])
def test_exact_fields_are_required(section, operation):
    data = load_protocol()
    target = data if section is None else data[section]
    if operation == "extra":
        target["surprise"] = 1
    else:
        del target[next(iter(target))]
    with pytest.raises(ValueError):
        validate_protocol(data)


def test_duplicate_json_keys_reject(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(
        PROTOCOL_PATH.read_text().replace(
            '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,'
        )
    )
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_protocol(path)


def test_provenance_subcommand_is_package_relative_and_always_checks_subframe(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "tv_sim", "provenance", "--check", "--profiles", "generic_ips_edge"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr
    assert "subframe" in result.stdout


def test_gray_reference_below_declared_lcd_extinction_floor_rejects():
    data = load_protocol()
    data["settings"]["gray_levels_nits"] = [0.01, 100]
    with pytest.raises(ValueError, match="extinction floor"):
        validate_protocol(data)
