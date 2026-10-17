"""Versioned P-only block motion parameters, outside runtime TV profiles.

The default snapshot is checked against the dataclass. Custom experiments may
change values within the proxy's declared support, retaining P/placeholder and
NR device calibration. Legacy rendering never loads these records.
"""

from __future__ import annotations

from dataclasses import asdict, fields
import json
from pathlib import Path

SCHEMA_VERSION = 1
CONFIG_PATH = (Path(__file__).resolve().parents[1] / "research" / "measurements"
               / "motion_block_synthetic_v1.json")
UNAVAILABLE = {"vendor_algorithm": "NR", "measured_thresholds": "NR",
               "calibrated_profile_fit": "NR", "measured_latency": "NR"}


def _unit(name: str) -> str:
    if name.endswith("_px"):
        return "output_pixels"
    if name.endswith("_nits"):
        return "nits"
    if name in ("estimation_width", "estimation_height", "block_size", "search_radius", "refinement_radius", "subpixel_steps"):
        return "estimation_pixels"
    if name in ("schema_version", "pyramid_levels", "cut_histogram_bins"):
        return "count"
    if name == "parameter_status":
        return "label"
    return "dimensionless"


def block_config_record(config=None) -> dict:
    from sim.block_motion import BlockMotionConfig

    parameters = asdict(config if config is not None else BlockMotionConfig())
    return {
        "schema_version": SCHEMA_VERSION, "kind": "block_motion_proxy_v1",
        "evidence": "P", "parameter_status": "placeholder",
        "source": {"locator": "research/m7-memc-motion.md sections 3, 6–9; sim/block_motion.py",
                   "sample": "NR"},
        "parameters": {key: {"value": value, "evidence": "P", "unit": _unit(key)}
                       for key, value in parameters.items()},
        "unavailable": UNAVAILABLE.copy(),
    }


def validate_block_config(data, *, require_defaults=False) -> list[str]:
    from sim.block_motion import BlockMotionConfig

    if not isinstance(data, dict):
        return ["motion config must be a mapping"]
    errors = []
    required = {"schema_version", "kind", "evidence", "parameter_status", "source", "parameters", "unavailable"}
    if set(data) != required:
        errors.append("motion config has missing or unknown fields")
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        errors.append("motion config schema_version must be 1")
    if data.get("kind") != "block_motion_proxy_v1":
        errors.append("motion config kind must be block_motion_proxy_v1")
    if data.get("evidence") != "P" or data.get("parameter_status") != "placeholder":
        errors.append("motion config must retain P/placeholder; calibration is NR")
    source = data.get("source")
    if (not isinstance(source, dict) or set(source) != {"locator", "sample"}
            or not isinstance(source.get("locator"), str) or not source["locator"].strip()
            or source.get("sample") != "NR"):
        errors.append("motion config source requires a locator and sample NR")
    if data.get("unavailable") != UNAVAILABLE:
        errors.append("motion config must retain the complete NR ledger")
    parameters = data.get("parameters")
    names = {field.name for field in fields(BlockMotionConfig)}
    if not isinstance(parameters, dict) or set(parameters) != names:
        errors.append("motion config parameters must cover exactly every BlockMotionConfig field")
        return errors
    values = {}
    for name, entry in parameters.items():
        if (not isinstance(entry, dict) or set(entry) != {"value", "evidence", "unit"}
                or entry.get("evidence") != "P" or entry.get("unit") != _unit(name)):
            errors.append(f"motion config {name}: requires value, P evidence and unit {_unit(name)}")
        else:
            values[name] = entry["value"]
    if len(values) == len(names):
        try:
            config = BlockMotionConfig(**values)
            if require_defaults and asdict(config) != asdict(BlockMotionConfig()):
                errors.append("motion config default snapshot is stale")
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append(f"motion config parameters: {exc}")
    return errors


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_block_record(path=None) -> dict:
    with Path(CONFIG_PATH if path is None else path).open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_unique_pairs)


def load_block_config(path=None):
    from sim.block_motion import BlockMotionConfig

    data = load_block_record(path)
    errors = validate_block_config(data)
    if errors:
        raise ValueError("; ".join(errors))
    return BlockMotionConfig(**{key: entry["value"] for key, entry in data["parameters"].items()})


def validate_motion_provenance(data=None) -> list[str]:
    try:
        return validate_block_config(load_block_record() if data is None else data, require_defaults=True)
    except (OSError, ValueError, TypeError) as exc:
        return [f"motion config: {exc}"]
