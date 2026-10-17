"""Versioned P-only panel colorimetry, loaded only by the M15 opt-in path.

These sidecars are the source of active panel parameters, unlike baseline and
angular provenance snapshots. No spectral fit or named-device calibration exists.
"""

from __future__ import annotations

import numpy as np

from sim.colorimetry import ColorimetryConfig
from sim import profile as profiles
from sim.provenance import (
    CONDITIONS, ProvenanceError, _conditions_errors, _number, _read_yaml,
    _source_errors, _support_errors,
)

SCHEMA_VERSION = 1
MODEL = "rgb_chromaticities_color_volume_v1"
MAPPING_MODEL = "neutral_axis_compress_v1"
_PARAMETERS = {
    "primaries_xy", "white_xy", "woled_rgb_peak_ratio", "woled_white_exponent",
}
_TOP_LEVEL = {
    "schema_version", "profile", "model", "parameter_status", "panel_spectra",
    "measured_color_volume", "calibrated_profile_fit", "entries", "gamut_mapping", "notes",
}
_ENTRY_FIELDS = {"value", "evidence", "source", "conditions", "interpolation", "support", "notes"}


def load_colorimetry_provenance(name: str) -> dict:
    """Read the explicit sidecar; ordinary profile loading never calls this."""
    profiles.profile_path(name)
    return _read_yaml(profiles.PROFILES_DIR / f"{name}.colorimetry.yaml")


def _unknown(data: dict, allowed: set[str], where: str) -> list[str]:
    return [f"{where}: unsupported field {key!r}" for key in data if key not in allowed]


def _xy(value) -> bool:
    return (isinstance(value, list) and len(value) == 2 and all(_number(v) for v in value)
            and 0 < value[0] < 1 and 0 < value[1] < 1
            and value[0] + value[1] <= 1 + 1e-12)


def _entry_errors(entry, key: str) -> list[str]:
    where = f"colorimetry entry {key}"
    if not isinstance(entry, dict):
        return [f"{where}: expected a mapping"]
    errors = _unknown(entry, _ENTRY_FIELDS, where)
    errors.extend(f"{where}: missing {field}" for field in sorted(_ENTRY_FIELDS - entry.keys()))
    if entry.get("evidence") != "P":
        errors.append(f"{where}: schema-1 placeholder values require P evidence")
    errors.extend(_source_errors(entry.get("source"), where))
    source = entry.get("source")
    if isinstance(source, dict):
        errors.extend(_unknown(source, {"locator", "sample", "url"}, f"{where} source"))
        if source.get("sample") != "NR":
            errors.append(f"{where}: source.sample must be NR; no named-device calibration exists")
        if not isinstance(source.get("url"), str) or not source["url"].startswith("https://"):
            errors.append(f"{where}: source.url must preserve a primary reference URL")
    errors.extend(_conditions_errors(entry.get("conditions"), where, complete=True))
    conditions = entry.get("conditions")
    if isinstance(conditions, dict):
        errors.extend(_unknown(conditions, set(CONDITIONS), f"{where} conditions"))
    if entry.get("interpolation") != {"method": "none", "evidence": "not_applicable"}:
        errors.append(f"{where}: interpolation must be none/not_applicable")
    support = entry.get("support")
    errors.extend(_support_errors(support, where))
    if isinstance(support, dict):
        errors.extend(_unknown(support, {"range", "unit", "outside"}, f"{where} support"))
        expected = {
            "primaries_xy": ([0.0, 1.0], "cie_xy"),
            "white_xy": ([0.0, 1.0], "cie_xy"),
            "woled_rgb_peak_ratio": ([0.0, 1.0], "ratio"),
            "woled_white_exponent": ("not_applicable", "positive_exponent"),
            "compression_knee": ([0.0, 1.0], "ratio"),
        }[key]
        if support.get("range") != expected[0] or support.get("unit") != expected[1]:
            errors.append(f"{where}: support must be {expected[0]} in {expected[1]}")
    if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
        errors.append(f"{where}: notes must describe the synthetic interpretation")
    return errors


def validate_colorimetry_provenance(name: str, data: dict | None = None) -> list[str]:
    """Validate complete labels, finite physical coordinates and model bounds."""
    if data is None:
        data = load_colorimetry_provenance(name)
    if not isinstance(data, dict):
        return ["colorimetry sidecar must be a mapping"]
    errors = _unknown(data, _TOP_LEVEL, "colorimetry sidecar")
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        errors.append(f"colorimetry schema_version must be {SCHEMA_VERSION}")
    if data.get("profile") != name:
        errors.append(f"colorimetry profile must be {name!r}")
    if data.get("model") != MODEL:
        errors.append(f"colorimetry model must be {MODEL}")
    if data.get("parameter_status") != "placeholder":
        errors.append("colorimetry parameter_status must be placeholder")
    for key in ("panel_spectra", "measured_color_volume", "calibrated_profile_fit"):
        if data.get(key) != "NR":
            errors.append(f"colorimetry {key} must be NR; no matched measurement or fit exists")
    if not isinstance(data.get("notes"), str) or not data["notes"].strip():
        errors.append("colorimetry notes must identify synthetic interpretation and limits")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        errors.append("colorimetry entries must be a mapping")
        entries = {}
    errors.extend(f"missing colorimetry entry {key}" for key in sorted(_PARAMETERS - entries.keys()))
    errors.extend(f"unsupported colorimetry parameter {key!r}" for key in entries if key not in _PARAMETERS)
    for key, entry in entries.items():
        if key in _PARAMETERS:
            errors.extend(_entry_errors(entry, key))
    values = {key: entry.get("value") for key, entry in entries.items() if isinstance(entry, dict)}
    primaries, white = values.get("primaries_xy"), values.get("white_xy")
    valid_primaries = isinstance(primaries, list) and len(primaries) == 3 and all(_xy(v) for v in primaries)
    if not valid_primaries:
        errors.append("colorimetry primaries_xy must be three finite physical CIE xy pairs")
    if not _xy(white):
        errors.append("colorimetry white_xy must be a finite physical CIE xy pair")
    if valid_primaries and _xy(white):
        coords = np.asarray(primaries, dtype=np.float64)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            basis = np.vstack((coords[:, 0] / coords[:, 1], np.ones(3),
                               (1 - coords.sum(axis=1)) / coords[:, 1]))
        if not np.isfinite(basis).all() or np.linalg.cond(basis) > 1e10:
            errors.append("colorimetry primaries are degenerate or numerically unstable")
        else:
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                w = np.array([white[0] / white[1], 1.0, (1 - sum(white)) / white[1]])
                scales = np.linalg.solve(basis, w)
            if not np.isfinite(scales).all() or np.any(scales <= 0):
                errors.append("colorimetry white must be strictly inside the primary triangle")
    ratio, exponent = values.get("woled_rgb_peak_ratio"), values.get("woled_white_exponent")
    if not _number(ratio) or not 0 < ratio <= 1:
        errors.append("colorimetry woled_rgb_peak_ratio must be in (0, 1]")
    if not _number(exponent) or not 0 < exponent:
        errors.append("colorimetry woled_white_exponent must be positive")
    try:
        profile = profiles.load_profile(name)
        if profile.technology != "woled" and _number(ratio) and ratio != 1:
            errors.append("colorimetry saturation penalty is only supported for WOLED; ratio must be 1")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"colorimetry cannot load profile {name}: {exc}")
    mapping = data.get("gamut_mapping")
    if not isinstance(mapping, dict):
        errors.append("colorimetry gamut_mapping must be a mapping")
    else:
        errors.extend(_unknown(mapping, {"model", "compression_knee"}, "colorimetry gamut_mapping"))
        if mapping.get("model") != MAPPING_MODEL:
            errors.append(f"colorimetry gamut_mapping.model must be {MAPPING_MODEL}")
        knee_entry = mapping.get("compression_knee")
        errors.extend(_entry_errors(knee_entry, "compression_knee"))
        knee = knee_entry.get("value") if isinstance(knee_entry, dict) else None
        if not _number(knee) or not 0 <= knee < 1:
            errors.append("colorimetry compression_knee must be in [0, 1)")
        elif knee != ColorimetryConfig.compression_knee:
            errors.append(f"colorimetry compression_knee snapshot must match the runtime default {ColorimetryConfig.compression_knee}; record overrides in runtime metadata")
    return errors


def panel_parameters(profile: profiles.TVProfile):
    """Load validated active parameters; there is no fallback to guessed values."""
    from sim.colorimetry import PanelColorimetry

    data = load_colorimetry_provenance(profile.name)
    errors = validate_colorimetry_provenance(profile.name, data)
    if errors:
        raise ProvenanceError("; ".join(errors))
    values = {key: entry["value"] for key, entry in data["entries"].items()}
    return PanelColorimetry(
        primaries_xy=tuple(tuple(v) for v in values["primaries_xy"]),
        white_xy=tuple(values["white_xy"]),
        woled_rgb_peak_ratio=values["woled_rgb_peak_ratio"],
        woled_white_exponent=values["woled_white_exponent"],
    )
