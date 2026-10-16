"""Provenance is complete, honest about unknowns, and outside the runtime path."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import yaml

import sim.profile as profiles
from sim.pipeline import Pipeline
from sim.profile import PsfProfile, load_profile
from sim.provenance import (
    ProvenanceError,
    load_provenance,
    lookup_measurement,
    profile_values,
    validate_provenance,
)
from sim.stages.encode import encode_frame


PROFILES = (
    "generic_ips_edge",
    "generic_qdoled",
    "generic_va_fald_miniled",
    "generic_woled",
)
PROFILE_DIR = profiles.PROFILES_DIR


@pytest.fixture
def woled_data():
    return deepcopy(load_provenance("generic_woled"))


def _set_path(data, path, value):
    keys = path.split("/")
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


def _copy_profiles(destination):
    destination.mkdir()
    for name in PROFILES:
        (destination / f"{name}.yaml").write_bytes(
            (PROFILE_DIR / f"{name}.yaml").read_bytes()
        )


@pytest.mark.parametrize("name", PROFILES)
def test_bundled_sidecars_cover_effective_values_without_claiming_calibration(name):
    data = load_provenance(name)
    assert data["schema_version"] == 1
    assert data["profile"] == name
    assert validate_provenance(name) == []
    values = profile_values(load_profile(name))
    assert set(data["entries"]) == set(values)
    assert {key: entry["value"] for key, entry in data["entries"].items()} == values
    assert {entry["evidence"] for entry in data["entries"].values()} <= {"P", "NR"}
    # These effective defaults are absent from some raw YAML profiles.
    assert "hdr.abl_source" in values
    assert "temporal.integration_samples" in values
    assert "backlight.psf_profile" in values
    assert isinstance(values["panel.color_matrix"], list)
    assert "panel.color_matrix.0" not in values


def test_profile_values_recurse_dataclasses_but_keep_optional_arrays_atomic():
    original = load_profile("generic_woled")
    profile = replace(
        original,
        backlight=replace(
            original.backlight,
            psf_profile=PsfProfile(step_zones=0.25, x=[1.0, 0.5, 0.0]),
        ),
    )
    values = profile_values(profile)
    assert values["backlight.psf_profile.step_zones"] == 0.25
    assert values["backlight.psf_profile.x"] == [1.0, 0.5, 0.0]
    assert values["backlight.psf_profile.y"] is None
    assert "backlight.psf_profile" not in values
    assert "backlight.psf_profile.x.0" not in values


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("profile", "generic_qdoled"),
        ("entries", []),
        ("entries/hdr.panel_peak_nits/value", 717),
        ("entries/hdr.abl_enabled/value", 1),
        ("entries/hdr.panel_peak_nits/evidence", "measured"),
        ("entries/hdr.panel_peak_nits/evidence", []),
        ("entries/hdr.panel_peak_nits/evidence", {}),
        ("entries/hdr.panel_peak_nits/source", {}),
        ("entries/hdr.panel_peak_nits/source/locator", ""),
        ("entries/hdr.panel_peak_nits/source/sample", 42),
        ("entries/hdr.panel_peak_nits/conditions", "NR"),
        ("entries/hdr.panel_peak_nits/interpolation", {}),
        ("entries/hdr.panel_peak_nits/interpolation/method", "spline"),
        ("entries/hdr.panel_peak_nits/support", {}),
        ("entries/hdr.panel_peak_nits/support/range", [0.9, 0.1]),
        ("entries/hdr.panel_peak_nits/support/range", [0.0, float("inf")]),
        pytest.param(
            "entries/hdr.panel_peak_nits/support/range",
            [0.0, 10**400],
            id="entry-support-oversized-integer",
        ),
        ("entries/hdr.panel_peak_nits/support/outside", "clamp"),
    ],
)
def test_validator_reports_malformed_or_stale_values(woled_data, path, value):
    _set_path(woled_data, path, value)
    errors = validate_provenance("generic_woled", woled_data)
    assert errors, (path, value)
    assert all(isinstance(error, str) and error for error in errors)


def test_validator_reports_missing_and_unsupported_profile_keys(woled_data):
    del woled_data["entries"]["hdr.abl_source"]
    woled_data["entries"]["hdr.window_curve"] = deepcopy(
        woled_data["entries"]["hdr.panel_peak_nits"]
    )
    errors = validate_provenance("generic_woled", woled_data)
    assert any("hdr.abl_source" in error for error in errors)
    assert any("hdr.window_curve" in error for error in errors)


@pytest.mark.parametrize("missing", ["value", "evidence", "source", "conditions", "interpolation", "support"])
def test_each_profile_entry_requires_all_provenance_fields(woled_data, missing):
    del woled_data["entries"]["hdr.panel_peak_nits"][missing]
    assert validate_provenance("generic_woled", woled_data)


def test_entry_conditions_require_explicit_unknown_fields(woled_data):
    del woled_data["entries"]["hdr.panel_peak_nits"]["conditions"]["dwell_s"]
    errors = validate_provenance("generic_woled", woled_data)
    assert any("dwell_s" in error for error in errors)


@pytest.mark.parametrize("unknown", [None, ""])
def test_unknown_conditions_must_use_nr(woled_data, unknown):
    woled_data["entries"]["hdr.panel_peak_nits"]["conditions"]["dwell_s"] = unknown
    assert validate_provenance("generic_woled", woled_data)


@pytest.mark.parametrize(
    "condition",
    [{}, [], float("nan"), float("inf"), {"distance_m": [2.0, None]}],
)
def test_conditions_reject_empty_nonfinite_or_nested_unknown_values(woled_data, condition):
    woled_data["entries"]["hdr.panel_peak_nits"]["conditions"]["dwell_s"] = condition
    assert validate_provenance("generic_woled", woled_data)


def test_measured_evidence_requires_identified_sample(woled_data):
    woled_data["entries"]["hdr.panel_peak_nits"]["evidence"] = "M"
    errors = validate_provenance("generic_woled", woled_data)
    assert any("sample" in error for error in errors)


@pytest.mark.parametrize("evidence", ["M", "D", "NR"])
def test_interpolated_profile_value_must_have_proposed_evidence(woled_data, evidence):
    entry = woled_data["entries"]["hdr.panel_peak_nits"]
    entry["source"]["sample"] = "LG 42C2"
    entry["interpolation"] = {"method": "piecewise_linear", "evidence": "P"}
    # An identified measured source cannot turn an interpolated value into M.
    entry["evidence"] = "P"
    assert validate_provenance("generic_woled", woled_data) == []
    entry["evidence"] = evidence
    assert validate_provenance("generic_woled", woled_data)


def test_sidecars_are_excluded_from_runtime_profile_discovery(tmp_path, monkeypatch):
    _copy_profiles(tmp_path / "profiles")
    for name in PROFILES:
        (tmp_path / "profiles" / f"{name}.provenance.yaml").write_text("[broken yaml")
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path / "profiles")
    assert profiles.available_profiles() == list(PROFILES)
    for name in PROFILES:
        assert load_profile(name).name == name


@pytest.mark.parametrize("contents", ["[unclosed", "- not\n- a mapping\n", "schema_version: 1\nschema_version: 2\n"])
def test_load_rejects_malformed_yaml_and_duplicate_explicit_keys(tmp_path, monkeypatch, contents):
    (tmp_path / "generic_woled.yaml").write_bytes((PROFILE_DIR / "generic_woled.yaml").read_bytes())
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    (tmp_path / "generic_woled.provenance.yaml").write_text(contents)
    with pytest.raises(ProvenanceError):
        load_provenance("generic_woled")


def test_load_missing_sidecar_has_an_actionable_error(tmp_path, monkeypatch):
    (tmp_path / "generic_woled.yaml").write_bytes((PROFILE_DIR / "generic_woled.yaml").read_bytes())
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    with pytest.raises(ProvenanceError, match="generic_woled"):
        load_provenance("generic_woled")


def test_yaml_merge_defaults_keep_explicit_overrides_legal(tmp_path, monkeypatch):
    (tmp_path / "generic_woled.yaml").write_bytes((PROFILE_DIR / "generic_woled.yaml").read_bytes())
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    (tmp_path / "generic_woled.provenance.yaml").write_text(
        "defaults: &defaults\n  schema_version: 0\n"
        "<<: *defaults\nschema_version: 1\nprofile: generic_woled\n"
    )
    assert load_provenance("generic_woled")["schema_version"] == 1


@pytest.mark.parametrize("section", [None, "hdr"])
def test_validator_rejects_unsupported_raw_profile_keys(tmp_path, monkeypatch, section):
    _copy_profiles(tmp_path / "profiles")
    raw = yaml.safe_load((tmp_path / "profiles" / "generic_woled.yaml").read_text())
    if section is None:
        raw["unsupported_measurement_setting"] = 123
    else:
        raw[section]["unsupported_measurement_setting"] = 123
    (tmp_path / "profiles" / "generic_woled.yaml").write_text(yaml.safe_dump(raw))
    (tmp_path / "profiles" / "generic_woled.provenance.yaml").write_bytes(
        (PROFILE_DIR / "generic_woled.provenance.yaml").read_bytes()
    )
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path / "profiles")
    errors = validate_provenance("generic_woled")
    assert any("unsupported_measurement_setting" in error for error in errors)


def test_named_sample_records_preserve_documented_measurements_and_unknowns():
    expected = {
        "generic_woled": (
            "c2_42_hdr_standard_peak",
            [717, 717, 717, 717, 396, 243, 192, 152],
        ),
        "generic_qdoled": (
            "s95b_65_hdr10_filmmaker_peak",
            [1000, "NR", "NR", 1000, 600, 300, "NR", 200],
        ),
        "generic_va_fald_miniled": (
            "x955_98_theatre_hdr_peak",
            ["NR", 1675, 3000, 3200, 3200, 1800, 1100, 896],
        ),
    }
    for name, (dataset_id, luminances) in expected.items():
        data = load_provenance(name)
        assert set(data["datasets"]) == {dataset_id}
        dataset = data["datasets"][dataset_id]
        assert [node["fraction"] for node in dataset["nodes"]] == [
            0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0
        ]
        assert [node["luminance_nits"] for node in dataset["nodes"]] == luminances
        assert [node["evidence"] for node in dataset["nodes"]] == [
            "NR" if value == "NR" else "M" for value in luminances
        ]
        assert dataset["conditions"]["dwell_s"] == "NR"
        assert dataset["conditions"]["requested_window_nits"] == "NR"
        assert dataset["timed_sustained_trace"] == "NR"
        assert dataset["calibrated_profile_fit"] == "NR"
        assert dataset["source"]["url"].startswith("https://")
        assert dataset["source"]["locator"]


@pytest.mark.parametrize(
    ("name", "dataset_id", "fraction", "luminance"),
    [
        ("generic_woled", "c2_42_hdr_standard_peak", 0.01, 717),
        ("generic_woled", "c2_42_hdr_standard_peak", 1.0, 152),
        ("generic_qdoled", "s95b_65_hdr10_filmmaker_peak", 0.01, 1000),
        ("generic_qdoled", "s95b_65_hdr10_filmmaker_peak", 1.0, 200),
        ("generic_va_fald_miniled", "x955_98_theatre_hdr_peak", 0.02, 1675),
        ("generic_va_fald_miniled", "x955_98_theatre_hdr_peak", 1.0, 896),
    ],
)
def test_exact_measured_endpoints_remain_measured(name, dataset_id, fraction, luminance):
    result = lookup_measurement(load_provenance(name), dataset_id, fraction)
    assert result.fraction == fraction
    assert result.luminance_nits == luminance
    assert result.evidence == "M"
    assert result.interpolated is False


@pytest.mark.parametrize("fraction, expected", [(0.02, 1000), (0.05, 1000), (0.75, 250)])
def test_interpolation_is_proposed_and_does_not_replace_nr_samples(fraction, expected):
    data = load_provenance("generic_qdoled")
    before = deepcopy(data)
    dataset_id = "s95b_65_hdr10_filmmaker_peak"
    result = lookup_measurement(data, dataset_id, fraction)
    assert result.fraction == fraction
    assert result.luminance_nits == expected
    assert result.evidence == "P"
    assert result.interpolated is True
    assert data == before
    node = next(node for node in data["datasets"][dataset_id]["nodes"] if node["fraction"] == fraction)
    assert node["luminance_nits"] == node["evidence"] == "NR"


def test_x955_interpolation_preserves_small_window_suppression():
    data = load_provenance("generic_va_fald_miniled")
    result = lookup_measurement(data, "x955_98_theatre_hdr_peak", 0.035)
    assert result.luminance_nits == pytest.approx((1675 + 3000) / 2)
    assert result.evidence == "P" and result.interpolated


@pytest.mark.parametrize(
    "fraction",
    [
        0.0, 0.01, -0.01, 1.001,
        float("nan"), float("inf"), -float("inf"), True,
        pytest.param(10**400, id="oversized-integer"),
    ],
)
def test_out_of_support_or_nonfinite_lookup_fails_loudly(fraction):
    data = load_provenance("generic_va_fald_miniled")
    with pytest.raises(ProvenanceError):
        lookup_measurement(data, "x955_98_theatre_hdr_peak", fraction)


def test_unlocated_ips_peak_does_not_create_window_support():
    data = load_provenance("generic_ips_edge")
    dataset_id = "uh770v_55_hdr_peak_unlocated"
    dataset = data["datasets"][dataset_id]
    assert dataset["nodes"] == []
    assert dataset["support"]["range"] == "NR"
    assert dataset["unlocated_peak"]["luminance_nits"] == 455
    assert dataset["unlocated_peak"]["evidence"] == "M"
    assert dataset["unlocated_peak"]["fraction"] == "NR"
    for fraction in (0.01, 0.1, 1.0):
        with pytest.raises(ProvenanceError):
            lookup_measurement(data, dataset_id, fraction)


def test_unknown_measurement_dataset_is_an_error(woled_data):
    with pytest.raises(ProvenanceError):
        lookup_measurement(woled_data, "nonexistent_dataset", 0.1)


def test_lookup_retains_unknown_conditions_and_returns_independent_metadata(woled_data):
    result = lookup_measurement(woled_data, "c2_42_hdr_standard_peak", 0.1)
    assert result.conditions["picture_mode"] == "HDR Standard"
    assert result.conditions["dynamic_tone_mapping"] == "disabled"
    assert result.conditions["dwell_s"] == "NR"
    assert result.conditions["requested_window_nits"] == "NR"
    dataset = woled_data["datasets"]["c2_42_hdr_standard_peak"]
    assert result.source == dataset["source"]
    result.conditions["dwell_s"] = 60
    result.source["locator"] = "modified inspection result"
    assert dataset["conditions"]["dwell_s"] == "NR"
    assert dataset["source"]["locator"] != result.source["locator"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("conditions", {}),
        ("source/url", ""),
        ("source/locator", ""),
        ("axis/kind", "requested_apl"),
        ("interpolation/method", "cubic"),
        ("interpolation/evidence", "M"),
        ("support/range", [0.0, 1.0]),
        ("support/outside", "clamp"),
        ("nodes", []),
    ],
)
def test_validator_rejects_invalid_dataset_metadata(woled_data, path, value):
    dataset = woled_data["datasets"]["c2_42_hdr_standard_peak"]
    _set_path(dataset, path, value)
    assert validate_provenance("generic_woled", woled_data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uncertainty_nits", {}),
        ("uncertainty_nits", -1),
        ("repeat_count", float("inf")),
        ("repeat_count", 1.5),
    ],
)
def test_measurement_uncertainty_and_repeat_count_are_numbers_or_nr(woled_data, field, value):
    woled_data["datasets"]["c2_42_hdr_standard_peak"]["source"][field] = value
    assert validate_provenance("generic_woled", woled_data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fraction", 0.0),
        ("fraction", 1.1),
        ("fraction", float("nan")),
        ("fraction", True),
        ("luminance_nits", -1),
        ("luminance_nits", float("inf")),
        ("luminance_nits", "NR"),
        ("evidence", "NR"),
        ("evidence", "unknown"),
        ("evidence", []),
        ("evidence", {}),
    ],
)
def test_validator_rejects_invalid_measurement_nodes(woled_data, field, value):
    woled_data["datasets"]["c2_42_hdr_standard_peak"]["nodes"][0][field] = value
    assert validate_provenance("generic_woled", woled_data)


@pytest.mark.parametrize("field", ["fraction", "luminance_nits", "support"])
def test_oversized_measurement_integers_fail_as_provenance_errors(woled_data, field):
    dataset_id = "c2_42_hdr_standard_peak"
    dataset = woled_data["datasets"][dataset_id]
    if field == "support":
        dataset["support"]["range"] = [0.01, 10**400]
    else:
        dataset["nodes"][0][field] = 10**400
    assert validate_provenance("generic_woled", woled_data)
    with pytest.raises(ProvenanceError):
        lookup_measurement(woled_data, dataset_id, 0.1)


@pytest.mark.parametrize("reverse", [False, True])
def test_measurement_fractions_must_be_strictly_increasing(woled_data, reverse):
    nodes = woled_data["datasets"]["c2_42_hdr_standard_peak"]["nodes"]
    if reverse:
        nodes.reverse()
    else:
        nodes[1]["fraction"] = nodes[0]["fraction"]
    assert validate_provenance("generic_woled", woled_data)


def test_python_module_provenance_command_checks_all_profiles():
    result = subprocess.run(
        [sys.executable, "-m", "sim", "provenance", "--check"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 profile(s)" in result.stdout


def test_provenance_cli_rejects_missing_entries(tmp_path, monkeypatch, woled_data, capsys):
    from sim.cli import main

    _copy_profiles(tmp_path / "profiles")
    del woled_data["entries"]["temporal.integration_samples"]
    (tmp_path / "profiles" / "generic_woled.provenance.yaml").write_text(
        yaml.safe_dump(woled_data)
    )
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path / "profiles")
    with pytest.raises(SystemExit) as raised:
        main(["provenance", "--check", "--profiles", "generic_woled"])
    assert raised.value.code != 0
    captured = capsys.readouterr()
    assert "temporal.integration_samples" in captured.out + captured.err


def test_provenance_cli_default_check_rejects_orphan_sidecars_but_allows_targeted_check(
    tmp_path, monkeypatch, capsys
):
    from sim.cli import main

    _copy_profiles(tmp_path / "profiles")
    for name in PROFILES:
        (tmp_path / "profiles" / f"{name}.provenance.yaml").write_bytes(
            (PROFILE_DIR / f"{name}.provenance.yaml").read_bytes()
        )
    orphan = tmp_path / "profiles" / "retired_profile.provenance.yaml"
    orphan.write_bytes((PROFILE_DIR / "generic_woled.provenance.yaml").read_bytes())
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path / "profiles")
    with pytest.raises(SystemExit) as raised:
        main(["provenance", "--check"])
    assert raised.value.code != 0
    captured = capsys.readouterr()
    assert "retired_profile" in captured.out + captured.err
    main(["provenance", "--check", "--profiles", "generic_woled"])


def _assert_array_identical(first, second):
    assert first.dtype == second.dtype
    assert first.shape == second.shape
    assert first.tobytes() == second.tobytes()


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("sidecar_state", ["present", "malformed"])
def test_pipeline_outputs_and_history_are_bit_identical_with_or_without_sidecars(
    tmp_path, monkeypatch, name, sidecar_state
):
    plain_dir, sidecar_dir = tmp_path / "plain", tmp_path / "sidecar"
    _copy_profiles(plain_dir)
    _copy_profiles(sidecar_dir)
    sidecar_path = sidecar_dir / f"{name}.provenance.yaml"
    if sidecar_state == "present":
        sidecar_path.write_bytes((PROFILE_DIR / sidecar_path.name).read_bytes())
    else:
        # Ordinary loading and rendering must not even parse the sidecar.
        sidecar_path.write_text("[unclosed, deliberately invalid provenance")
    monkeypatch.setattr(profiles, "PROFILES_DIR", plain_dir)
    plain = load_profile(name)
    monkeypatch.setattr(profiles, "PROFILES_DIR", sidecar_dir)
    with_sidecar = load_profile(name)
    assert plain == with_sidecar
    plain_pipeline, sidecar_pipeline = Pipeline(plain), Pipeline(with_sidecar)
    plain_encoded_pipeline, sidecar_encoded_pipeline = Pipeline(plain), Pipeline(with_sidecar)
    rng = np.random.default_rng(20261016)
    pattern = rng.integers(0, 256, size=(24, 32, 3), dtype=np.uint8)
    sequence = [
        np.zeros_like(pattern),
        pattern,
        np.full_like(pattern, 255),
        np.roll(pattern, 5, axis=1),
        np.zeros_like(pattern),
    ]
    previous = None
    for source in sequence:
        first = plain_pipeline.run_linear(source)
        second = sidecar_pipeline.run_linear(source)
        _assert_array_identical(first.rgb, second.rgb)
        _assert_array_identical(first.backlight, second.backlight)
        _assert_array_identical(encode_frame(first, plain.output), encode_frame(second, with_sidecar.output))
        _assert_array_identical(
            plain_encoded_pipeline.run(source), sidecar_encoded_pipeline.run(source)
        )
        _assert_array_identical(plain_pipeline.state.previous, sidecar_pipeline.state.previous)
        assert plain_pipeline.load_state.apl_nits.hex() == sidecar_pipeline.load_state.apl_nits.hex()
        if previous is not None:
            assert first.rgb.tobytes() != previous
        previous = first.rgb.tobytes()
