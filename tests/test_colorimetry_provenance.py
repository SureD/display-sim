"""The active M15 sidecars must stay explicit P models, with missing data NR."""

from copy import deepcopy

import pytest
import yaml

import sim.profile as profiles
from sim.colorimetry_provenance import (
    load_colorimetry_provenance, panel_parameters, validate_colorimetry_provenance,
)
from sim.provenance import ProvenanceError, main as provenance_main

PROFILES = ("generic_ips_edge", "generic_qdoled", "generic_va_fald_miniled", "generic_woled")
PROFILE_DIR = profiles.PROFILES_DIR


def records(destination):
    for name in PROFILES:
        for suffix in (".yaml", ".provenance.yaml", ".angular.yaml", ".colorimetry.yaml"):
            (destination / f"{name}{suffix}").write_bytes((PROFILE_DIR / f"{name}{suffix}").read_bytes())


@pytest.fixture
def woled_data():
    return deepcopy(load_colorimetry_provenance("generic_woled"))


def set_path(data, path, value):
    keys = path.split("/")
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


@pytest.mark.parametrize("name", PROFILES)
def test_colorimetry_sidecars_are_complete_and_explicit_placeholders(name):
    data = load_colorimetry_provenance(name)
    assert validate_colorimetry_provenance(name) == []
    assert data["panel_spectra"] == data["measured_color_volume"] == data["calibrated_profile_fit"] == "NR"
    assert {entry["evidence"] for entry in data["entries"].values()} == {"P"}
    assert all(entry["source"]["sample"] == "NR" for entry in data["entries"].values())
    params = panel_parameters(profiles.load_profile(name))
    assert params.primaries_xy == tuple(tuple(xy) for xy in data["entries"]["primaries_xy"]["value"])
    assert params.white_xy == tuple(data["entries"]["white_xy"]["value"])
    assert params.woled_rgb_peak_ratio == (0.45 if name == "generic_woled" else 1)
    stale = deepcopy(data)
    stale["gamut_mapping"]["compression_knee"]["value"] = 0.7
    assert any("runtime default" in error for error in validate_colorimetry_provenance(name, stale))


@pytest.mark.parametrize("path,value", [
    ("schema_version", True), ("schema_version", 2),
    ("profile", "generic_qdoled"), ("model", "spectral"),
    ("parameter_status", "calibrated"), ("calibrated_profile_fit", "M"),
    ("panel_spectra", "M"), ("measured_color_volume", 0.99), ("entries", []),
    ("entries/primaries_xy/value", [[0.68, 0.32]]),
    ("entries/primaries_xy/value", [[0.68, 0.32], [0.68, 0.32], [0.15, 0.06]]),
    ("entries/primaries_xy/value", [[1.1, 0.1], [0.265, 0.69], [0.15, 0.06]]),
    ("entries/primaries_xy/value", [[float("nan"), 0.32], [0.265, 0.69], [0.15, 0.06]]),
    ("entries/primaries_xy/value", [[True, 0.32], [0.265, 0.69], [0.15, 0.06]]),
    ("entries/primaries_xy/value", [[10**400, 0.32], [0.265, 0.69], [0.15, 0.06]]),
    ("entries/primaries_xy/value", [[0.5, 1e-320], [0.265, 0.69], [0.15, 0.06]]),
    ("entries/white_xy/value", [0.5, 1e-320]),
    ("entries/white_xy/value", [0.3127, 0]),
    ("entries/white_xy/value", [0.001, 0.001]),
    ("entries/white_xy/value", [float("inf"), 0.329]),
    ("entries/primaries_xy/evidence", "M"), ("entries/white_xy/evidence", "D"),
    ("entries/white_xy/evidence", []),
    ("entries/white_xy/source/sample", "Named TV"),
    ("entries/white_xy/source/url", ""),
    ("entries/white_xy/conditions/dwell_s", None),
    ("entries/white_xy/interpolation", {"method": "piecewise_linear", "evidence": "P"}),
    ("entries/white_xy/support/outside", "clamp"),
    ("entries/white_xy/support/range", [0, float("inf")]),
    ("entries/white_xy/notes", ""),
    ("entries/woled_rgb_peak_ratio/value", 0),
    ("entries/woled_rgb_peak_ratio/value", 1.1),
    ("entries/woled_rgb_peak_ratio/value", True),
    ("entries/woled_white_exponent/value", -1),
    ("entries/woled_white_exponent/value", float("inf")),
    ("gamut_mapping", {}),
    ("gamut_mapping/model", "vendor_calibrated"),
    ("gamut_mapping/compression_knee/value", -0.01),
    ("gamut_mapping/compression_knee/value", 1),
    ("gamut_mapping/compression_knee/evidence", "M"),
])
def test_colorimetry_rejects_invalid_and_misleading_records(woled_data, path, value):
    set_path(woled_data, path, value)
    assert validate_colorimetry_provenance("generic_woled", woled_data)


@pytest.mark.parametrize("field", ["value", "evidence", "source", "conditions", "interpolation", "support", "notes"])
def test_colorimetry_parameters_require_complete_evidence(woled_data, field):
    del woled_data["entries"]["primaries_xy"][field]
    assert validate_colorimetry_provenance("generic_woled", woled_data)


@pytest.mark.parametrize("path", [
    "invented", "entries/invented", "entries/white_xy/invented",
    "entries/white_xy/source/invented", "entries/white_xy/conditions/invented",
    "entries/white_xy/support/invented", "gamut_mapping/invented",
])
def test_colorimetry_schema_rejects_unknown_fields(woled_data, path):
    set_path(woled_data, path, "P")
    assert validate_colorimetry_provenance("generic_woled", woled_data)


def test_missing_parameter_and_condition_are_rejected(woled_data):
    del woled_data["entries"]["white_xy"]
    del woled_data["entries"]["primaries_xy"]["conditions"]["dwell_s"]
    errors = validate_colorimetry_provenance("generic_woled", woled_data)
    assert any("white_xy" in error for error in errors)
    assert any("dwell_s" in error for error in errors)


def test_nonwoled_profiles_cannot_claim_rgbw_capacity_penalty():
    data = load_colorimetry_provenance("generic_ips_edge")
    data["entries"]["woled_rgb_peak_ratio"]["value"] = 0.5
    assert any("WOLED" in error for error in validate_colorimetry_provenance("generic_ips_edge", data))


@pytest.mark.parametrize("contents", ["[broken", "schema_version: 1\nschema_version: 1\n"])
def test_colorimetry_read_rejects_broken_or_duplicate_yaml(tmp_path, monkeypatch, contents):
    records(tmp_path)
    (tmp_path / "generic_woled.colorimetry.yaml").write_text(contents)
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    with pytest.raises(ProvenanceError):
        load_colorimetry_provenance("generic_woled")


def test_colorimetry_sidecars_are_only_loaded_by_optin(tmp_path, monkeypatch):
    from sim.colorimetry import ColorimetryConfig
    from sim.pipeline import Pipeline

    records(tmp_path)
    (tmp_path / "generic_woled.colorimetry.yaml").write_text("[broken")
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    assert profiles.available_profiles() == list(PROFILES)
    profile = profiles.load_profile("generic_woled")
    Pipeline(profile)
    with pytest.raises(FileNotFoundError):
        profiles.profile_path("generic_woled.colorimetry")
    with pytest.raises(ProvenanceError):
        Pipeline(profile, colorimetry=ColorimetryConfig(enabled=True))


@pytest.mark.parametrize("state", ["missing", "orphan", "invalid"])
def test_provenance_cli_checks_colorimetry_records_and_profile_selection(tmp_path, monkeypatch, capsys, state):
    records(tmp_path)
    path = tmp_path / "generic_ips_edge.colorimetry.yaml"
    if state == "missing":
        path.unlink()
    elif state == "orphan":
        (tmp_path / "retired.colorimetry.yaml").write_bytes(path.read_bytes())
    else:
        data = load_colorimetry_provenance("generic_ips_edge")
        data["entries"]["white_xy"]["evidence"] = "M"
        path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    provenance_main(["--check", "--profiles", "generic_woled"])
    with pytest.raises(SystemExit) as raised:
        provenance_main(["--check"])
    assert raised.value.code == 1
    assert "colorimetry" in capsys.readouterr().err
