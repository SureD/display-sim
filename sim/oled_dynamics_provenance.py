"""Offline validation of the separate M13 synthetic protocol/config evidence.

The ordinary pipeline never discovers this file or supplies demonstration taus.
Every setting is P; calculated traces are D under that model and device fits NR.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = 1
PROTOCOL_PATH = (Path(__file__).resolve().parents[1] / "research" / "measurements"
                 / "oled_dynamics_synthetic_v1.json")


def validate_oled_dynamics_provenance(data: dict | None = None) -> list[str]:
    """Check the versioned, P-only experiment independently of runtime profiles."""
    from sim.oled_dynamics_experiment import load_protocol, validate_protocol

    try:
        if data is None:
            data = load_protocol(PROTOCOL_PATH)
        validate_protocol(data)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [f"OLED dynamics protocol: {exc}"]
    return []
