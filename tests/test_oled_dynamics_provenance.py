"""Synthetic protocol evidence stays separate from unchanged TV records."""

from copy import deepcopy
import json

import pytest

from sim.oled_dynamics_provenance import PROTOCOL_PATH, validate_oled_dynamics_provenance
from sim.provenance import main as provenance_main


@pytest.fixture
def protocol():
    return json.loads(PROTOCOL_PATH.read_text())


def test_bundled_protocol_has_only_placeholder_choices_and_explicit_unknowns(protocol):
    assert validate_oled_dynamics_provenance() == []
    assert protocol["evidence"] == "P"
    assert protocol["parameter_status"] == "placeholder"
    assert set(protocol["unavailable"].values()) == {"NR"}
    assert protocol["demonstration"] == {"attack_ms": 100, "release_ms": 1000, "initial": "cold"}
    assert "profiles" not in PROTOCOL_PATH.parts


@pytest.mark.parametrize("path,value", [
    ("schema_version", 2), ("schema_version", True),
    ("evidence", "M"), ("parameter_status", "calibrated"),
    ("unavailable/measured_attack_ms", 100),
    ("unavailable/measured_release_ms", 0),
    ("unavailable/calibrated_profile_fit", "M"),
    ("demonstration/attack_ms", None), ("demonstration/release_ms", -1),
    ("settings/level_nits", float("inf")), ("settings/ambient_lux", 10),
    ("settings/output_fps", "0"), ("settings/invented", 1),
])
def test_provenance_rejects_unlabeled_invalid_or_unknown_constants(protocol, path, value):
    changed = deepcopy(protocol)
    parts = path.split("/")
    destination = changed
    for part in parts[:-1]:
        destination = destination[part]
    destination[parts[-1]] = value
    assert validate_oled_dynamics_provenance(changed)


def test_provenance_checks_protocol_even_with_profile_selection(protocol, tmp_path, monkeypatch, capsys):
    import sim.oled_dynamics_provenance as evidence

    protocol["evidence"] = "M"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(protocol))
    monkeypatch.setattr(evidence, "PROTOCOL_PATH", path)
    with pytest.raises(SystemExit) as error:
        provenance_main(["--check", "--profiles", "generic_woled"])
    assert error.value.code == 1
    assert "OLED dynamics protocol" in capsys.readouterr().err


def test_provenance_missing_protocol_is_actionable(tmp_path, monkeypatch):
    import sim.oled_dynamics_provenance as evidence

    monkeypatch.setattr(evidence, "PROTOCOL_PATH", tmp_path / "absent.json")
    assert "OLED dynamics protocol" in validate_oled_dynamics_provenance()[0]
