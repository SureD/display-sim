"""Offline evidence for the opt-in, synthetic viewing-angle parameters.

Angular records are separate from baseline profile snapshots. Rendering never
loads them; this validator compares them against the explicit synthetic presets.
Schema 1 does not contain a calibrated device or measured angular fit.
"""

from __future__ import annotations

from dataclasses import asdict

from tv_sim import profile as profiles
from tv_sim.provenance import (
    CONDITIONS,
    EVIDENCE,
    _conditions_errors,
    _context_value,
    _number,
    _read_yaml,
    _same_value,
    _source_errors,
    _support_errors,
)

SCHEMA_VERSION = 1
_TOP_LEVEL = {
    "schema_version",
    "profile",
    "model",
    "parameter_status",
    "full_angular_fit",
    "calibrated_profile_fit",
    "angular_spectra",
    "black_leakage_fit",
    "entries",
    "notes",
}
_ENTRY_FIELDS = {
    "value",
    "evidence",
    "source",
    "conditions",
    "interpolation",
    "support",
    "notes",
}


def load_angular_provenance(name: str) -> dict:
    """Read one explicit angular sidecar without changing runtime settings."""
    profiles.profile_path(name)
    return _read_yaml(profiles.PROFILES_DIR / f"{name}.angular.yaml")


def angular_values(profile: profiles.TVProfile) -> dict:
    """Return exact angular dataclass values, with RGB tuples as atomic lists."""
    from tv_sim.viewing_angle import angular_parameters

    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in asdict(angular_parameters(profile)).items()
    }


def _unknown_fields(data: dict, supported: set[str], where: str) -> list[str]:
    return [f"{where}: unsupported field {key!r}" for key in data if key not in supported]


def validate_angular_provenance(name: str, data: dict | None = None) -> list[str]:
    """Validate angular schema, evidence labels, coverage and exact snapshots.

    As with baseline provenance, unreadable/invalid YAML raises ProvenanceError;
    valid YAML with invalid content returns actionable validation errors.
    """
    if data is None:
        data = load_angular_provenance(name)
    if not isinstance(data, dict):
        return ["angular sidecar must be a mapping"]
    errors = _unknown_fields(data, _TOP_LEVEL, "angular sidecar")
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        errors.append(f"angular schema_version must be {SCHEMA_VERSION}")
    if data.get("profile") != name:
        errors.append(f"angular profile must be {name!r}")
    try:
        profile = profiles.load_profile(name)
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(f"{name}: cannot load runtime profile: {exc}")
        return errors
    model = "emissive_gain" if profile.self_emissive else "lcd_transmission"
    if data.get("model") != model:
        errors.append(f"angular model must be {model!r}")
    if data.get("parameter_status") != "placeholder":
        errors.append(
            "angular parameter_status must be placeholder; no calibrated angular presets exist"
        )
    for key in ("full_angular_fit", "calibrated_profile_fit"):
        if data.get(key) != "NR":
            errors.append(f"angular {key} must be NR; no matched-device fit exists")
    for key, expected in (
        ("angular_spectra", "NR" if profile.self_emissive else "not_applicable"),
        ("black_leakage_fit", "not_applicable" if profile.self_emissive else "NR"),
    ):
        if data.get(key) != expected:
            errors.append(f"angular {key} must be {expected}")
    if not isinstance(data.get("notes"), str) or not data["notes"].strip():
        errors.append("angular notes must identify the synthetic interpretation and limits")

    values = angular_values(profile)
    entries = data.get("entries")
    if not isinstance(entries, dict):
        errors.append("angular entries must be a mapping")
        entries = {}
    for key in sorted(values.keys() - entries.keys()):
        errors.append(f"missing angular provenance entry {key}")
    for key in sorted(entries.keys() - values.keys(), key=str):
        errors.append(f"unsupported angular parameter {key!r}")
    for key, entry in entries.items():
        where = f"angular entry {key}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: expected a mapping")
            continue
        errors.extend(_unknown_fields(entry, _ENTRY_FIELDS, where))
        for field in sorted(_ENTRY_FIELDS - entry.keys()):
            errors.append(f"{where}: missing {field}")
        if key in values and ("value" not in entry or not _same_value(entry["value"], values[key])):
            errors.append(f"{where}: value snapshot does not match the synthetic angular parameter")
        value = entry.get("value")
        if not (
            _number(value)
            or (isinstance(value, list) and len(value) == 3 and all(_number(v) for v in value))
        ):
            errors.append(f"{where}: value must be a finite scalar or finite RGB triple")
        evidence = entry.get("evidence")
        if not isinstance(evidence, str) or evidence not in EVIDENCE:
            errors.append(f"{where}: evidence must be M, D, P or NR")
        elif evidence != "P":
            errors.append(f"{where}: schema-1 synthetic placeholder parameters require P evidence")
        errors.extend(_source_errors(entry.get("source"), where))
        source = entry.get("source")
        if isinstance(source, dict):
            errors.extend(_unknown_fields(source, {"locator", "sample", "url"}, f"{where} source"))
            if source.get("sample") != "NR":
                errors.append(f"{where}: synthetic placeholder source.sample must be NR")
            if any(not _context_value(v) for v in source.values()):
                errors.append(f"{where}: source values must be finite/nonempty")
        errors.extend(_conditions_errors(entry.get("conditions"), where, complete=True))
        if isinstance(entry.get("conditions"), dict):
            errors.extend(
                _unknown_fields(entry["conditions"], set(CONDITIONS), f"{where} conditions")
            )
        interpolation = entry.get("interpolation")
        expected_interpolation = (
            {"method": "none", "evidence": "not_applicable"}
            if key == "max_angle_deg"
            else {
                "method": "linear_sin2_v1" if key == "gray_exponent_45" else "log_gain_sin2_v1",
                "evidence": "P",
            }
        )
        if interpolation != expected_interpolation:
            errors.append(f"{where}: interpolation must be {expected_interpolation}")
        support = entry.get("support")
        errors.extend(_support_errors(support, where))
        if isinstance(support, dict):
            errors.extend(
                _unknown_fields(support, {"range", "unit", "outside"}, f"{where} support")
            )
            if (
                support.get("range") != [0.0, values["max_angle_deg"]]
                or support.get("unit") != "radial_angle_deg"
            ):
                errors.append(
                    f"{where}: support must be the synthetic radial-angle range [0, max_angle_deg]"
                )
        if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
            errors.append(f"{where}: notes must describe the placeholder parameter")
    return errors
