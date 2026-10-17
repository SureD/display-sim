"""Angular evidence stays complete and explicit about synthetic placeholders."""

from copy import deepcopy

import pytest
import yaml

import sim.profile as profiles
from sim.angular_provenance import (
    angular_values,
    load_angular_provenance,
    validate_angular_provenance,
)
from sim.provenance import ProvenanceError, main as provenance_main


PROFILES = (
    "generic_ips_edge", "generic_qdoled", "generic_va_fald_miniled", "generic_woled",
)
PROFILE_DIR = profiles.PROFILES_DIR


@pytest.fixture
def ips_data():
    return deepcopy(load_angular_provenance("generic_ips_edge"))


def _set_path(data, path, value):
    parts = path.split("/")
    target = data
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _copy_records(destination):
    for name in PROFILES:
        for suffix in (".yaml", ".provenance.yaml", ".angular.yaml"):
            (destination / f"{name}{suffix}").write_bytes(
                (PROFILE_DIR / f"{name}{suffix}").read_bytes()
            )


@pytest.mark.parametrize("name", PROFILES)
def test_bundled_angular_parameters_are_complete_synthetic_placeholders(name):
    data = load_angular_provenance(name)
    profile = profiles.load_profile(name)
    assert validate_angular_provenance(name) == []
    assert data["parameter_status"] == "placeholder"
    assert data["full_angular_fit"] == data["calibrated_profile_fit"] == "NR"
    assert {key: entry["value"] for key, entry in data["entries"].items()} == angular_values(profile)
    assert {entry["evidence"] for entry in data["entries"].values()} == {"P"}
    assert all(entry["source"]["sample"] == "NR" for entry in data["entries"].values())
    if profile.self_emissive:
        assert data["model"] == "emissive_gain"
        assert data["angular_spectra"] == "NR"
        assert data["black_leakage_fit"] == "not_applicable"
        assert set(data["entries"]) == {"max_angle_deg", "emission_gain_45"}
    else:
        assert data["model"] == "lcd_transmission"
        assert data["black_leakage_fit"] == "NR"
        assert set(data["entries"]) == {
            "max_angle_deg", "white_gain_45", "black_gain_45", "gray_exponent_45",
        }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("profile", "generic_woled"),
        ("model", "emissive_gain"),
        ("parameter_status", "calibrated"),
        ("full_angular_fit", "M"),
        ("calibrated_profile_fit", "M"),
        ("black_leakage_fit", "M"),
        ("entries", []),
        ("entries/white_gain_45/value", [0.9, 0.9, 0.9]),
        ("entries/white_gain_45/value", [float("nan"), 0.8, 0.8]),
        ("entries/white_gain_45/value", [float("inf"), 0.8, 0.8]),
        ("entries/white_gain_45/value", [True, 0.8, 0.8]),
        ("entries/white_gain_45/evidence", "M"),
        ("entries/white_gain_45/evidence", "NR"),
        ("entries/white_gain_45/evidence", []),
        ("entries/white_gain_45/source/sample", "A named television"),
        ("entries/white_gain_45/conditions/dwell_s", float("inf")),
        ("entries/white_gain_45/conditions/dwell_s", None),
        ("entries/white_gain_45/interpolation/method", "piecewise_linear"),
        ("entries/white_gain_45/support/range", [0.0, 60.0]),
        ("entries/white_gain_45/support/range", [0.0, float("inf")]),
        ("entries/white_gain_45/support/unit", "measured_angle_deg"),
        ("entries/white_gain_45/support/outside", "clamp"),
        ("entries/white_gain_45/notes", ""),
    ],
)
def test_angular_validator_rejects_stale_unlabeled_and_misleading_records(ips_data, path, value):
    _set_path(ips_data, path, value)
    assert validate_angular_provenance("generic_ips_edge", ips_data)


@pytest.mark.parametrize(
    "missing", ["value", "evidence", "source", "conditions", "interpolation", "support", "notes"],
)
def test_each_angular_parameter_requires_all_provenance_fields(ips_data, missing):
    del ips_data["entries"]["black_gain_45"][missing]
    assert validate_angular_provenance("generic_ips_edge", ips_data)


def test_angular_validator_rejects_missing_and_unknown_parameters(ips_data):
    del ips_data["entries"]["white_gain_45"]
    ips_data["entries"]["lcd_leakage_alias"] = deepcopy(ips_data["entries"]["black_gain_45"])
    errors = validate_angular_provenance("generic_ips_edge", ips_data)
    assert any("white_gain_45" in error for error in errors)
    assert any("lcd_leakage_alias" in error for error in errors)


@pytest.mark.parametrize("path", ["invented", "entries/white_gain_45/invented", "entries/white_gain_45/source/invented", "entries/white_gain_45/conditions/invented", "entries/white_gain_45/support/invented"])
def test_angular_validator_rejects_unknown_fields(ips_data, path):
    _set_path(ips_data, path, "P")
    assert validate_angular_provenance("generic_ips_edge", ips_data)


def test_angular_conditions_require_explicit_unknowns(ips_data):
    del ips_data["entries"]["black_gain_45"]["conditions"]["dwell_s"]
    assert any("dwell_s" in error for error in validate_angular_provenance("generic_ips_edge", ips_data))


@pytest.mark.parametrize("contents", ["[unclosed", "schema_version: 1\nschema_version: 1\n"])
def test_angular_load_rejects_invalid_yaml_or_duplicate_keys(tmp_path, monkeypatch, contents):
    _copy_records(tmp_path)
    (tmp_path / "generic_ips_edge.angular.yaml").write_text(contents)
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    with pytest.raises(ProvenanceError):
        load_angular_provenance("generic_ips_edge")


def test_angular_sidecars_never_become_runtime_profiles(tmp_path, monkeypatch):
    _copy_records(tmp_path)
    (tmp_path / "generic_ips_edge.angular.yaml").write_text("[broken yaml")
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    assert profiles.available_profiles() == list(PROFILES)
    assert profiles.load_profile("generic_ips_edge").technology == "ips_lcd"
    with pytest.raises(FileNotFoundError):
        profiles.profile_path("generic_ips_edge.angular")


def test_provenance_cli_checks_angular_records_and_profile_selection(tmp_path, monkeypatch, capsys):
    _copy_records(tmp_path)
    ips = load_angular_provenance("generic_ips_edge")
    ips["entries"]["black_gain_45"]["evidence"] = "M"
    (tmp_path / "generic_ips_edge.angular.yaml").write_text(yaml.safe_dump(ips))
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    provenance_main(["--check", "--profiles", "generic_woled"])
    with pytest.raises(SystemExit) as raised:
        provenance_main(["--check", "--profiles", "generic_ips_edge"])
    assert raised.value.code == 1
    assert "black_gain_45" in capsys.readouterr().err


@pytest.mark.parametrize("state", ["missing", "orphan"])
def test_provenance_cli_rejects_missing_or_orphan_angular_records(tmp_path, monkeypatch, capsys, state):
    _copy_records(tmp_path)
    if state == "missing":
        (tmp_path / "generic_ips_edge.angular.yaml").unlink()
    else:
        (tmp_path / "retired.angular.yaml").write_bytes((PROFILE_DIR / "generic_ips_edge.angular.yaml").read_bytes())
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    with pytest.raises(SystemExit) as raised:
        provenance_main(["--check"])
    assert raised.value.code == 1
    assert "angular.yaml" in capsys.readouterr().err
    provenance_main(["--check", "--profiles", "generic_woled"])
