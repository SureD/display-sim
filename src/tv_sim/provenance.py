"""Versioned, offline profile evidence. This module is never read by the pipeline.

Lists are atomic profile values; nested dataclasses use dotted field paths.
Measurement lookup is exploratory inspection of a named sample's table, not
condition-matched replay or a calibration of the associated generic preset.
"""

from __future__ import annotations

import argparse
import math
import sys
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeGuard, cast, get_args, get_type_hints

import yaml

from tv_sim import profile as profiles

SCHEMA_VERSION = 1
EVIDENCE = {"M", "D", "P", "NR"}
CONDITIONS = (
    "picture_mode",
    "dynamic_tone_mapping",
    "input_mode",
    "local_dimming",
    "refresh_hz",
    "vrr",
    "white_xy",
    "source_encoding",
    "requested_window_nits",
    "source_rgb_primaries",
    "stimulus",
    "stimulus_rgb_code",
    "pattern_aspect_ratio",
    "position_xy_fraction",
    "warmup_s",
    "dwell_s",
    "prior_pattern_and_duration",
    "ambient_lux",
    "temperature_C",
    "viewing_angle_deg",
    "meter_geometry_and_spot",
    "instrument_and_correction",
)


class ProvenanceError(ValueError):
    """Missing, invalid, unknown-support or out-of-support evidence."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Keep YAML anchors/merges, but never silently overwrite explicit keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise ProvenanceError(f"duplicate YAML key {key!r}")
                seen.add(key)
            except TypeError as exc:
                raise ProvenanceError("YAML mapping keys must be scalar") from exc
        return super().construct_mapping(node, deep=deep)


def _read_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError, ProvenanceError) as exc:
        raise ProvenanceError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProvenanceError(f"{path}: expected a YAML mapping")
    return data


def load_provenance(name: str) -> dict:
    """Read a sidecar explicitly; loading a runtime profile never calls this."""
    profiles.profile_path(name)
    return _read_yaml(profiles.PROFILES_DIR / f"{name}.provenance.yaml")


def profile_values(profile: profiles.TVProfile) -> dict:
    """Return every effective value, including defaults, without list indexing."""
    result = {}

    def visit(value, prefix):
        if is_dataclass(value):
            for field in fields(value):
                path = f"{prefix}.{field.name}" if prefix else field.name
                visit(getattr(value, field.name), path)
        else:
            result[prefix] = deepcopy(value)

    visit(profile, "")
    return result


def _number(value: object) -> TypeGuard[int | float]:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(cast(int | float, value))
    except OverflowError:
        return False


def _same_value(left, right) -> bool:
    # bool is a subclass of int: a switch must not match a numeric snapshot.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if _number(left) and _number(right):
        return left == right
    return type(left) is type(right) and left == right


def _profile_key_errors(data: dict, cls=profiles.TVProfile, prefix="") -> list[str]:
    """Catch unknown runtime YAML keys even where the legacy loader ignores them."""
    errors = []
    hints = get_type_hints(cls)
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in hints:
            errors.append(f"unsupported profile key {path}")
            continue
        nested = next((t for t in (hints[key], *get_args(hints[key])) if is_dataclass(t)), None)
        if nested is not None and isinstance(value, dict):
            errors.extend(_profile_key_errors(value, nested, path))
    return errors


def _context_value(value, active=None) -> bool:
    """Unknown metadata uses NR, never empty containers or nonfinite numbers."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool) or _number(value):
        return True
    if not isinstance(value, (list, dict)) or not value:
        return False
    active = set() if active is None else active
    if id(value) in active:
        return False
    active.add(id(value))
    if isinstance(value, dict):
        valid = all(
            isinstance(k, str) and k.strip() and _context_value(v, active) for k, v in value.items()
        )
    else:
        valid = all(_context_value(v, active) for v in value)
    active.remove(id(value))
    return valid


def _conditions_errors(value, where: str, *, complete=False) -> list[str]:
    if not isinstance(value, dict) or not value:
        return [f"{where}: conditions must be a nonempty mapping (unknowns are NR)"]
    errors = []
    if complete:
        for key in CONDITIONS:
            if key not in value:
                errors.append(f"{where}: missing condition {key}; use NR when unknown")
    for key, item in value.items():
        if not _context_value(item):
            errors.append(f"{where}: condition {key} must be finite/nonempty; use NR for unknown")
    return errors


def _source_errors(value, where: str, *, dataset=False) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: source must be a mapping"]
    keys = (
        ("url", "locator", "extraction", "source_check_date", "uncertainty_nits", "repeat_count")
        if dataset
        else ("locator", "sample")
    )
    errors = []
    for key in keys:
        if key not in value or value[key] is None or value[key] == "":
            errors.append(f"{where}: source.{key} is required (unknowns are NR)")
    text_keys = (
        ("url", "locator", "extraction", "source_check_date") if dataset else ("locator", "sample")
    )
    for key in text_keys:
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            errors.append(f"{where}: source.{key} must be nonempty text")
    for key in ("locator", "url") if dataset else ("locator",):
        if key in value and (not isinstance(value[key], str) or value[key] == "NR"):
            errors.append(f"{where}: source.{key} must identify the raw source")
    if dataset:
        uncertainty = value.get("uncertainty_nits")
        if uncertainty != "NR" and not (_number(uncertainty) and uncertainty >= 0):
            errors.append(f"{where}: source.uncertainty_nits must be NR or finite nonnegative nits")
        count = value.get("repeat_count")
        if count != "NR" and not (type(count) is int and count > 0 and _number(count)):
            errors.append(f"{where}: source.repeat_count must be NR or a positive integer")
    return errors


def _interpolation_errors(value, where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: interpolation must be a mapping"]
    method = value.get("method")
    if method == "none" and value.get("evidence") == "not_applicable":
        return []
    if method == "piecewise_linear" and value.get("evidence") == "P":
        return []
    return [f"{where}: interpolation must be none/not_applicable or piecewise_linear/P"]


def _support_errors(value, where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: support must be a mapping"]
    errors = []
    bounds = value.get("range")
    if not (isinstance(bounds, str) and bounds in {"NR", "not_applicable"}):
        if not (
            isinstance(bounds, list)
            and len(bounds) == 2
            and all(_number(v) for v in bounds)
            and bounds[0] <= bounds[1]
        ):
            errors.append(f"{where}: support.range must be [finite min, max], NR or not_applicable")
    if not isinstance(value.get("unit"), str) or not value["unit"]:
        errors.append(f"{where}: support.unit is required")
    if value.get("outside") != "reject":
        errors.append(
            f"{where}: support.outside must be reject; extrapolation/clamping is forbidden"
        )
    return errors


def _dataset_errors(dataset_id: str, data) -> list[str]:
    where = f"dataset {dataset_id}"
    if not isinstance(data, dict):
        return [f"{where}: expected a mapping"]
    errors = []
    kind = data.get("kind")
    if kind not in ("window_curve", "unlocated_peak"):
        errors.append(f"{where}: kind must be window_curve or unlocated_peak")
    specimen = data.get("specimen")
    if not isinstance(specimen, dict):
        errors.append(f"{where}: specimen must be a mapping")
    else:
        for key in ("manufacturer", "model", "diagonal_in", "region_panel_variant", "firmware"):
            if key not in specimen or specimen[key] is None or specimen[key] == "":
                errors.append(f"{where}: missing specimen.{key} (unknowns are NR)")
    errors.extend(_source_errors(data.get("source"), where, dataset=True))
    errors.extend(_conditions_errors(data.get("conditions"), where, complete=True))
    errors.extend(_interpolation_errors(data.get("interpolation"), where))
    errors.extend(_support_errors(data.get("support"), where))
    if data.get("axis") != {"kind": "window_fraction", "unit": "screen_area_fraction"}:
        errors.append(f"{where}: axis must declare window_fraction in screen_area_fraction")
    if data.get("metric") != "peak_center_luminance_nits":
        errors.append(f"{where}: metric must be peak_center_luminance_nits")
    if data.get("calibrated_profile_fit") != "NR":
        errors.append(f"{where}: calibrated_profile_fit must be NR; no generic calibration exists")
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        errors.append(f"{where}: nodes must be a list")
        nodes = []
    last = 0.0
    numeric = []
    for i, node in enumerate(nodes):
        loc = f"{where} node {i}"
        if not isinstance(node, dict):
            errors.append(f"{loc}: expected a mapping")
            continue
        fraction = node.get("fraction")
        if not _number(fraction) or not 0 < fraction <= 1 or fraction <= last:
            errors.append(f"{loc}: fractions must be unique, increasing and in (0, 1]")
        else:
            last = fraction
        luminance = node.get("luminance_nits")
        evidence = node.get("evidence")
        if luminance == "NR":
            if evidence != "NR":
                errors.append(f"{loc}: NR luminance requires NR evidence")
        elif not _number(luminance) or luminance < 0 or evidence not in ("M", "D", "P"):
            errors.append(f"{loc}: numeric luminance must be finite, nonnegative and M/D/P")
        elif _number(fraction):
            numeric.append(node)
    support = data.get("support")
    bounds = support.get("range") if isinstance(support, dict) else None
    interpolation = data.get("interpolation")
    method = interpolation.get("method") if isinstance(interpolation, dict) else None
    if isinstance(support, dict) and support.get("unit") != "screen_area_fraction":
        errors.append(f"{where}: support.unit must be screen_area_fraction")
    if kind == "window_curve":
        if len(numeric) < 2:
            errors.append(f"{where}: window curve needs at least two numeric nodes")
        elif bounds != [numeric[0]["fraction"], numeric[-1]["fraction"]]:
            errors.append(f"{where}: support range must equal the numeric node endpoints")
        if method != "piecewise_linear":
            errors.append(f"{where}: window curve interpolation must be piecewise_linear/P")
    if kind == "unlocated_peak":
        if nodes or bounds != "NR" or method != "none":
            errors.append(
                f"{where}: unlocated peak requires empty nodes, NR support and no interpolation"
            )
        peak = data.get("unlocated_peak")
        if not isinstance(peak, dict):
            errors.append(f"{where}: unlocated_peak must be a mapping")
        elif not (
            _number(peak.get("luminance_nits"))
            and peak["luminance_nits"] >= 0
            and peak.get("evidence") == "M"
            and peak.get("fraction") == "NR"
            and peak.get("dwell_s") == "NR"
        ):
            errors.append(
                f"{where}: unlocated peak needs measured luminance with NR fraction/dwell"
            )
    return errors


def validate_provenance(name: str, data: dict | None = None) -> list[str]:
    """Check schema, supported keys, coverage and snapshots; return all errors.

    Invalid/unreadable YAML raises ProvenanceError. No runtime settings change.
    """
    if data is None:
        data = load_provenance(name)
    if not isinstance(data, dict):
        return ["sidecar must be a mapping"]
    errors = []
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("profile") != name:
        errors.append(f"profile must be {name!r}")
    raw = _read_yaml(profiles.profile_path(name))
    errors.extend(_profile_key_errors(raw))
    try:
        values = profile_values(profiles.load_profile(name))
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(f"{name}: cannot load runtime profile: {exc}")
        return errors
    entries = data.get("entries")
    if not isinstance(entries, dict):
        errors.append("entries must be a mapping")
        entries = {}
    for key in sorted(values.keys() - entries.keys()):
        errors.append(f"missing provenance entry {key}")
    for key in sorted(entries.keys() - values.keys(), key=str):
        errors.append(f"unsupported profile key {key}")
    for key, entry in entries.items():
        where = f"entry {key}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: expected a mapping")
            continue
        if key in values and ("value" not in entry or not _same_value(entry["value"], values[key])):
            errors.append(f"{where}: value snapshot does not match the effective profile value")
        if not isinstance(entry.get("evidence"), str) or entry["evidence"] not in EVIDENCE:
            errors.append(f"{where}: evidence must be M, D, P or NR")
        errors.extend(_source_errors(entry.get("source"), where))
        errors.extend(_conditions_errors(entry.get("conditions"), where, complete=True))
        errors.extend(_interpolation_errors(entry.get("interpolation"), where))
        errors.extend(_support_errors(entry.get("support"), where))
        interpolation = entry.get("interpolation")
        if (
            isinstance(interpolation, dict)
            and interpolation.get("method") == "piecewise_linear"
            and entry.get("evidence") != "P"
        ):
            errors.append(f"{where}: an interpolated value must have P evidence")
        source = entry.get("source")
        if (
            entry.get("evidence") == "M"
            and isinstance(source, dict)
            and source.get("sample") == "NR"
        ):
            errors.append(f"{where}: M evidence requires an identified sample")
    datasets = data.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        errors.append("datasets must be a nonempty mapping")
    else:
        for dataset_id, dataset in datasets.items():
            errors.extend(_dataset_errors(dataset_id, dataset))
    return errors


@dataclass(frozen=True)
class Measurement:
    """A named-sample table query; unknown conditions remain in the result."""

    fraction: float
    luminance_nits: float
    evidence: str
    interpolated: bool
    conditions: dict
    source: dict


def lookup_measurement(data: dict, dataset_id: str, fraction: float) -> Measurement:
    """Inspect a table within support, preserving M nodes and labeling fits P.

    This does not waive NR conditions, activate runtime replay, or claim a
    match to any requested amplitude, timing or TV. No extrapolation or clamp.
    """
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != SCHEMA_VERSION
    ):
        raise ProvenanceError(f"schema_version must be {SCHEMA_VERSION}")
    datasets = data.get("datasets")
    if not isinstance(datasets, dict) or dataset_id not in datasets:
        raise ProvenanceError(f"unknown dataset {dataset_id!r}")
    dataset = datasets[dataset_id]
    errors = _dataset_errors(dataset_id, dataset)
    if errors:
        raise ProvenanceError("; ".join(errors))
    bounds = dataset["support"]["range"]
    if not isinstance(bounds, list):
        raise ProvenanceError(f"{dataset_id}: support range is NR; lookup is unsupported")
    if not _number(fraction) or not bounds[0] <= fraction <= bounds[1]:
        raise ProvenanceError(f"{dataset_id}: fraction {fraction!r} outside support {bounds}")
    numeric = [n for n in dataset["nodes"] if _number(n["luminance_nits"])]

    def result(value, evidence, interpolated):
        return Measurement(
            float(fraction),
            float(value),
            evidence,
            interpolated,
            deepcopy(dataset["conditions"]),
            deepcopy(dataset["source"]),
        )

    for node in numeric:
        if fraction == node["fraction"]:
            return result(node["luminance_nits"], node["evidence"], False)
    for left, right in zip(numeric, numeric[1:]):
        if left["fraction"] < fraction < right["fraction"]:
            weight = (fraction - left["fraction"]) / (right["fraction"] - left["fraction"])
            value = left["luminance_nits"] + weight * (
                right["luminance_nits"] - left["luminance_nits"]
            )
            return result(value, "P", True)
    raise ProvenanceError(f"{dataset_id}: no supported interval at {fraction!r}")


def main(argv: list[str] | None = None) -> None:
    from tv_sim.angular_provenance import validate_angular_provenance
    from tv_sim.colorimetry_provenance import validate_colorimetry_provenance
    from tv_sim.motion_provenance import validate_motion_provenance
    from tv_sim.motion_validate import validate_motion_validation_provenance
    from tv_sim.oled_dynamics_provenance import validate_oled_dynamics_provenance
    from tv_sim.zone_temporal_provenance import validate_zone_temporal_provenance

    parser = argparse.ArgumentParser(
        description="Check offline profile provenance and measurement sidecars."
    )
    parser.add_argument(
        "--check", action="store_true", required=True, help="Validate all selected sidecars"
    )
    parser.add_argument("--profiles", nargs="+", default=None, help="Profile names (default: all)")
    args = parser.parse_args(argv)
    names = args.profiles if args.profiles is not None else profiles.available_profiles()
    failures = []
    if args.profiles is None:
        for suffix in (".provenance.yaml", ".angular.yaml", ".colorimetry.yaml"):
            for path in sorted(profiles.PROFILES_DIR.glob(f"*{suffix}")):
                stem = path.name.removesuffix(suffix)
                if stem not in names:
                    failures.append(f"{path.name}: no runtime profile {stem!r}")
    if not names:
        failures.append("no runtime profiles found")
    for name in names:
        for validate in (
            validate_provenance,
            validate_angular_provenance,
            validate_colorimetry_provenance,
        ):
            try:
                errors = validate(name)
            except (ProvenanceError, FileNotFoundError) as exc:
                errors = [str(exc)]
            failures.extend(f"{name}: {error}" for error in errors)
    failures.extend(validate_oled_dynamics_provenance())
    failures.extend(validate_motion_provenance())
    failures.extend(validate_motion_validation_provenance())
    failures.extend(validate_zone_temporal_provenance())
    if failures:
        for error in failures:
            print(error, file=sys.stderr)
        raise SystemExit(1)
    print(
        f"Provenance OK: {len(names)} profile(s), baseline/angular/colorimetry/OLED-dynamics/motion/zone-temporal schema_version {SCHEMA_VERSION}"
    )


if __name__ == "__main__":
    main()
