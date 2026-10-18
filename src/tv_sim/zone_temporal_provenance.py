"""Strict P-only M17 protocol ledger, independent of runtime profile loading.

Numeric experiment choices inherit P evidence; generated traces are D under
that model and device parameters remain NR. Demonstration taus never become
implicit runtime defaults. JSON duplicate keys and unknown fields reject.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PROTOCOL_PATH = (
    Path(__file__).resolve().parent / "data/measurements/zone_temporal_synthetic_v1.json"
)
FIXTURES = ("moving_object", "apl_step", "flashing_highlight", "subtitle")
_TOP = {
    "schema_version",
    "protocol_id",
    "evidence",
    "parameter_status",
    "settings",
    "demonstration",
    "fixtures",
    "unavailable",
    "notes",
}
_SETTINGS = {
    "width",
    "height",
    "output_fps",
    "duration_s",
    "level_nits",
    "dark_scene_nits",
    "preview_reference_nits",
    "halo_threshold_nits",
    "settling_fraction",
}
_UNAVAILABLE = {
    "measured_attack_s",
    "measured_release_s",
    "measured_slew",
    "vendor_cut_policy",
    "measured_psf",
    "pixel_backlight_synchronization",
    "calibrated_profile_fit",
}


def _keys(value: Any, expected: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{name} requires exactly {', '.join(sorted(expected))}")


def _number(value: Any, name: str) -> float:
    try:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite numeric data")
        return float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite numeric data") from exc


def _rational(value: Any, name: str) -> Fraction:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an explicit positive rational string")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"{name} must be an explicit positive rational string") from exc
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def validate_protocol(data: dict) -> None:
    """Validate exact versioned schema and synthetic evidence without rendering."""
    _keys(data, _TOP, "zone temporal protocol")
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("zone temporal schema_version must be 1")
    if data["protocol_id"] != "zone_temporal_synthetic_v1":
        raise ValueError("unsupported zone temporal protocol_id")
    if data["evidence"] != "P" or data["parameter_status"] != "placeholder":
        raise ValueError("zone temporal settings require P/placeholder evidence")
    if not isinstance(data["notes"], str) or not data["notes"].strip():
        raise ValueError("protocol notes must explain the synthetic choices")
    settings = data["settings"]
    _keys(settings, _SETTINGS, "settings")
    for name in ("width", "height"):
        if type(settings[name]) is not int or settings[name] < 16:
            raise ValueError(f"{name} must be an integer >= 16")
    fps = _rational(settings["output_fps"], "output_fps")
    duration = _rational(settings["duration_s"], "duration_s")
    if (fps * duration).denominator != 1 or fps * duration < 12:
        raise ValueError("duration must contain an integral number of at least 12 display ticks")
    for name in ("level_nits", "preview_reference_nits", "halo_threshold_nits"):
        if _number(settings[name], name) <= 0:
            raise ValueError(f"{name} must be positive")
    if not 0 <= _number(settings["dark_scene_nits"], "dark_scene_nits") < settings["level_nits"]:
        raise ValueError("dark_scene_nits must be nonnegative and below level_nits")
    if not 0 < _number(settings["settling_fraction"], "settling_fraction") < 1:
        raise ValueError("settling_fraction must be in (0, 1)")
    demo = data["demonstration"]
    _keys(
        demo,
        {
            "model",
            "attack_s",
            "release_s",
            "initial",
            "reset_on_scene_cut",
            "slew_nits_per_tick",
            "cut_detection_threshold",
        },
        "demonstration",
    )
    if demo["model"] != "zone_attack_release_v1" or demo["initial"] != "cold":
        raise ValueError("demonstration requires zone_attack_release_v1 and cold initialization")
    for name in ("attack_s", "release_s"):
        if _number(demo[name], name) < 0:
            raise ValueError(f"{name} must be nonnegative seconds")
    if type(demo["reset_on_scene_cut"]) is not bool:
        raise ValueError("reset_on_scene_cut must be boolean")
    slew = demo["slew_nits_per_tick"]
    if slew is not None and _number(slew, "slew_nits_per_tick") <= 0:
        raise ValueError("slew_nits_per_tick must be positive or null")
    threshold = demo["cut_detection_threshold"]
    if threshold is not None:
        if (
            not demo["reset_on_scene_cut"]
            or not 0 < _number(threshold, "cut_detection_threshold") <= 1
        ):
            raise ValueError("cut detection requires scene reset and a threshold in (0, 1]")
    if data["fixtures"] != list(FIXTURES):
        raise ValueError("fixtures must preserve the four versioned synthetic clips in order")
    _keys(data["unavailable"], _UNAVAILABLE, "unavailable")
    if any(value != "NR" for value in data["unavailable"].values()):
        raise ValueError("measured/controller/calibration data must remain NR")


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_protocol(path: Path = PROTOCOL_PATH) -> dict:
    """Load a supplied or packaged protocol; reject ambiguous duplicate keys."""
    data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique)
    validate_protocol(data)
    return data


def validate_zone_temporal_provenance(data: dict | None = None) -> list[str]:
    """Report all-or-nothing admission of the separate M17 P-only record."""
    try:
        validate_protocol(load_protocol() if data is None else data)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [f"zone temporal protocol: {exc}"]
    return []
