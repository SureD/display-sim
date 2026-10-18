"""Strict versioned P-only ledger for the M18 synthetic emission experiment."""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LCD_ILLUMINATION_NITS = 1000.0
LCD_NATIVE_CONTRAST = 4000.0
LCD_GRAY_FLOOR_NITS = LCD_ILLUMINATION_NITS / LCD_NATIVE_CONTRAST
PROTOCOL_PATH = Path(__file__).resolve().parent / "data/measurements/subframe_synthetic_v1.json"
FIXTURES = ("moving_edge", "moving_bar", "gray_steps", "flashing_patch")
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
    "motion_duration_s",
    "substeps",
    "level_nits",
    "dark_nits",
    "preview_reference_nits",
    "speeds_px_s",
    "gray_levels_nits",
    "step_duration_s",
    "flash_duration_s",
    "flash_hz",
    "settling_fraction",
}
_DEMO = {
    "rise_tau_ms",
    "fall_tau_ms",
    "overdrive_gain",
    "overdrive_fraction",
    "strobe_duty",
    "strobe_phase",
    "bfi_duty",
    "bfi_phase",
    "pwm_hz",
    "pwm_duty",
}
_UNKNOWN = {
    "measured_gray_to_gray_table",
    "measured_overdrive_lut",
    "measured_pwm_waveform",
    "measured_scanout",
    "measured_strobe_crosstalk",
    "device_calibration",
    "certification",
}


def _keys(value: Any, fields: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} requires exactly {', '.join(sorted(fields))}")


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        valid = (
            type(value) in (int, float)
            and math.isfinite(value)
            and value >= 0
            and (not positive or value > 0)
        )
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(
            f"{name} requires finite {'positive' if positive else 'nonnegative'} numeric data"
        )
    return float(value)


def _rational(value: Any, name: str, *, zero: bool = False) -> Fraction:
    if not isinstance(value, str):
        raise ValueError(f"{name} requires a rational string")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"{name} requires a rational string") from exc
    if result < 0 or not zero and result == 0:
        raise ValueError(f"{name} requires {'nonnegative' if zero else 'positive'} rational data")
    return result


def validate_protocol(data: dict[str, Any]) -> None:
    """Reject promotions to measured evidence, ambiguity and unbounded artifacts."""
    _keys(data, _TOP, "subframe protocol")
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("subframe schema_version must be 1")
    if data["protocol_id"] != "subframe_synthetic_v1":
        raise ValueError("unsupported subframe protocol_id")
    if data["evidence"] != "P" or data["parameter_status"] != "placeholder":
        raise ValueError("subframe parameters require P/placeholder evidence")
    if not isinstance(data["notes"], str) or not data["notes"].strip():
        raise ValueError("protocol requires explanatory notes")
    if data["fixtures"] != list(FIXTURES):
        raise ValueError("fixtures must preserve the four versioned synthetic tests")
    s = data["settings"]
    _keys(s, _SETTINGS, "settings")
    for name, lower, upper in (("width", 32, 512), ("height", 8, 256), ("substeps", 4, 512)):
        if type(s[name]) is not int or not lower <= s[name] <= upper:
            raise ValueError(f"{name} must be an integer in [{lower}, {upper}]")
    fps = _rational(s["output_fps"], "output_fps")
    for name in ("motion_duration_s", "step_duration_s", "flash_duration_s"):
        ticks = fps * _rational(s[name], name)
        if ticks.denominator != 1 or ticks < 4 or ticks > 600:
            raise ValueError(f"{name} requires 4..600 integral display ticks")
    for name in ("level_nits", "preview_reference_nits", "flash_hz"):
        _number(s[name], name, positive=True)
    if _number(s["dark_nits"], "dark_nits") >= s["level_nits"]:
        raise ValueError("dark_nits must be below level_nits")
    if not 0 < _number(s["settling_fraction"], "settling_fraction") < 1:
        raise ValueError("settling_fraction must be in (0,1)")
    for name in ("speeds_px_s", "gray_levels_nits"):
        values = s[name]
        if not isinstance(values, list) or not 2 <= len(values) <= 6:
            raise ValueError(f"{name} requires 2..6 ordered unique numbers")
        for value in values:
            _number(value, name, positive=True)
        if values != sorted(set(values)):
            raise ValueError(f"{name} requires ordered unique numbers")
    if min(s["gray_levels_nits"]) < LCD_GRAY_FLOOR_NITS:
        raise ValueError(
            "gray_levels_nits must be at or above the derived 0.25-nit LCD extinction floor"
        )
    if (
        s["level_nits"] > LCD_ILLUMINATION_NITS
        or max(s["gray_levels_nits"]) > LCD_ILLUMINATION_NITS
    ):
        raise ValueError(
            "requested levels must not exceed the declared 1000-nit fixed illumination"
        )
    if s["flash_hz"] >= float(fps) / 2:
        raise ValueError("flash_hz must be below display-clock Nyquist")
    demo = data["demonstration"]
    _keys(demo, _DEMO, "demonstration")
    for name in ("rise_tau_ms", "fall_tau_ms", "overdrive_gain"):
        _number(demo[name], name)
    for name in ("overdrive_fraction", "strobe_duty", "bfi_duty", "pwm_duty"):
        if _rational(demo[name], name) > 1:
            raise ValueError(f"{name} must be in (0,1]")
    for name in ("strobe_phase", "bfi_phase"):
        if _rational(demo[name], name, zero=True) >= 1:
            raise ValueError(f"{name} must be in [0,1)")
    pwm = _rational(demo["pwm_hz"], "pwm_hz")
    if pwm >= fps * s["substeps"] / 2:
        raise ValueError("pwm_hz must be below sub-step Nyquist for diagnostic FFT")
    _keys(data["unavailable"], _UNKNOWN, "unavailable")
    if any(value != "NR" for value in data["unavailable"].values()):
        raise ValueError("measured device and certification parameters must remain NR")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    """Load package-relative or supplied data and reject duplicate JSON keys."""
    data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique)
    validate_protocol(data)
    return data


def validate_subframe_provenance(data: dict[str, Any] | None = None) -> list[str]:
    """Return strict ledger errors for the provenance CLI."""
    try:
        validate_protocol(load_protocol() if data is None else data)
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        return [f"subframe protocol: {exc}"]
    return []
