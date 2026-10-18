"""Versioned full LCD-zone display checkpoints with exact array byte transport.

Zone initialization alone does not restore pixel, load, detector or clock
history. This module validates a complete checkpoint before changing its owner.
"""

from __future__ import annotations

import base64
import math
import re
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from numpy.typing import DTypeLike

from tv_sim.abl_dynamics import digest, finite_number
from tv_sim.stages.backlight import zone_edges
from tv_sim.zone_temporal import (
    ZoneBacklightState,
    ZoneTemporalConfig,
    evolution,
    validate_path,
    validate_state,
)

if TYPE_CHECKING:
    from tv_sim.pipeline import Pipeline

EVIDENCE = {"model_and_initialization": "P", "states_and_clock": "D", "measured_controller": "NR"}


@lru_cache(maxsize=1)
def _implementation() -> str:
    root = Path(__file__).resolve().parent
    names = [
        "zone_temporal.py",
        "zone_history.py",
        "pipeline.py",
        "load.py",
        "color.py",
        "colorimetry.py",
        "frame.py",
        "filters.py",
        "viewing_angle.py",
    ] + [
        f"stages/{name}.py"
        for name in (
            "decode",
            "process",
            "backlight",
            "panel",
            "tonemap",
            "ambient",
            "temporal",
            "viewing_angle",
        )
    ]
    return digest({name: sha256((root / name).read_bytes()).hexdigest() for name in names})


def identity(pipeline: Pipeline) -> dict[str, Any]:
    """Effective display/controller identity, independent of initial policy."""
    if not pipeline._zone_active:
        raise ValueError("zone identity requires active zone temporal dynamics")
    return {
        "model": cast(ZoneTemporalConfig, pipeline.zone_temporal).model,
        "evolution_version": 1,
        "profile_sha256": digest(asdict(pipeline.profile)),
        "evolution_sha256": digest(evolution(cast(ZoneTemporalConfig, pipeline.zone_temporal))),
        "angle_sha256": digest(
            {
                "config": asdict(pipeline.viewing_angle),
                "parameters": None
                if pipeline.angular_params is None
                else asdict(pipeline.angular_params),
            }
        ),
        "colorimetry_sha256": digest(
            {
                "config": asdict(pipeline.colorimetry),
                "panel": None
                if pipeline.panel_colorimetry is None
                else asdict(pipeline.panel_colorimetry),
            }
        ),
        "implementation_sha256": _implementation(),
        "numpy_version": np.__version__,
    }


def geometry(shape: tuple[int, ...], pipeline: Pipeline) -> dict[str, Any]:
    """Record rasterized zone boundaries, including grids clipped to tiny images."""
    y_edges = zone_edges(shape[0], pipeline.profile.backlight.zones_y)
    x_edges = zone_edges(shape[1], pipeline.profile.backlight.zones_x)
    return {
        "shape": list(shape),
        "dtype": np.dtype(np.float32).str,
        "zone_shape": [len(y_edges) - 1, len(x_edges) - 1],
        "y_edges": y_edges.tolist(),
        "x_edges": x_edges.tolist(),
    }


def _array_summary(value: np.ndarray | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, np.ndarray):
        raise ValueError("display history must contain NumPy arrays")
    return {
        "shape": list(value.shape),
        "dtype": value.dtype.str,
        "sha256": sha256(np.ascontiguousarray(value).tobytes()).hexdigest(),
    }


def boundary(pipeline: Pipeline) -> str:
    """Detect changes to any display history made outside a validated tick."""
    state = cast(ZoneBacklightState, pipeline.zone_state)
    return digest(
        {
            "zones": _array_summary(state.zones_nits),
            "previous_targets": _array_summary(state.previous_targets),
            "elapsed_ms_hex": float(state.elapsed_ms).hex(),
            "ticks": state.ticks,
            "load_apl_hex": None
            if pipeline.load_state.apl_nits is None
            else float(pipeline.load_state.apl_nits).hex(),
            "previous": _array_summary(pipeline.state.previous),
        }
    )


def _pack(value: np.ndarray) -> dict[str, Any]:
    raw = np.ascontiguousarray(value).tobytes()
    return {
        "shape": list(value.shape),
        "dtype": value.dtype.str,
        "base64": base64.b64encode(raw).decode("ascii"),
        "sha256": sha256(raw).hexdigest(),
    }


def checkpoint(pipeline: Pipeline) -> dict[str, Any]:
    """Serialize a successful tick boundary without rounding state floats."""
    if not pipeline._zone_active:
        raise ValueError("zone checkpoint requires a successful active display tick")
    state = cast(ZoneBacklightState, pipeline.zone_state)
    validate_state(state, pipeline.profile.backlight)
    if state.ticks == 0:
        raise ValueError("zone checkpoint requires a successful active display tick")
    if identity(pipeline) != pipeline._zone_identity:
        raise ValueError("zone display identity changed before checkpoint")
    if boundary(pipeline) != pipeline._zone_boundary:
        raise ValueError("display history was edited outside a tick; restore a complete checkpoint")
    previous = pipeline.state.previous
    if previous is None or not np.isfinite(previous).all() or np.any(previous < 0):
        raise ValueError("checkpoint panel history must be finite nonnegative nits")
    if (
        previous.dtype != np.float32
        or geometry(previous.shape, pipeline) != pipeline._zone_geometry
    ):
        raise ValueError("checkpoint panel history does not match zone geometry")
    apl = pipeline.load_state.apl_nits
    if apl is not None and finite_number(apl, "load APL") < 0:
        raise ValueError("checkpoint load APL must be nonnegative")
    data = {
        "schema_version": 1,
        "kind": "lcd_zone_full_history",
        "identity": deepcopy(pipeline._zone_identity),
        "geometry": deepcopy(pipeline._zone_geometry),
        "zone_state": {
            "zones": _pack(cast(np.ndarray, state.zones_nits)),
            "previous_targets": _pack(cast(np.ndarray, state.previous_targets)),
            "elapsed_ms_hex": float(state.elapsed_ms).hex(),
            "ticks": state.ticks,
        },
        "load_state": {"apl_nits_hex": None if apl is None else float(apl).hex()},
        "temporal_state": {"previous": _pack(previous)},
        "initialization": deepcopy(pipeline._zone_initialization),
        "history_sha256": pipeline._zone_history_hash,
        "last_source_sha256": pipeline._zone_source_hash,
        "evidence": dict(EVIDENCE),
    }
    data["checkpoint_sha256"] = digest(data)
    return data


def _scalar(value: object, name: str) -> float:
    if not isinstance(value, str):
        raise ValueError(f"checkpoint {name} must be an exact float hex string")
    result = float.fromhex(value)
    if not math.isfinite(result):
        raise ValueError(f"checkpoint {name} must be finite")
    return result


def _unpack(data: dict[str, Any], shape: list[int], dtype: np.dtype) -> np.ndarray:
    if set(data) != {"shape", "dtype", "base64", "sha256"}:
        raise ValueError("invalid checkpoint array fields")
    if data["shape"] != shape or data["dtype"] != dtype.str:
        raise ValueError("checkpoint array geometry/dtype mismatch")
    raw = base64.b64decode(data["base64"], validate=True)
    if len(raw) != math.prod(shape) * dtype.itemsize or sha256(raw).hexdigest() != data["sha256"]:
        raise ValueError("checkpoint array byte count/hash mismatch")
    result = np.frombuffer(raw, dtype=dtype).reshape(shape).copy()
    if not np.isfinite(result).all() or np.any(result < 0):
        raise ValueError("checkpoint arrays must have finite nonnegative values")
    return result


def restore_checkpoint(
    pipeline: Pipeline,
    data: dict[str, Any],
    *,
    shape: tuple[int, ...] | None = None,
    dtype: DTypeLike | None = None,
    elapsed_ms: float | None = None,
) -> None:
    """Validate all fields into locals, then restore both physical histories."""
    config = cast(ZoneTemporalConfig, pipeline.zone_temporal)
    if not pipeline._zone_active or config.initial != "resume":
        raise ValueError("zone state input requires resume as the sole initialization owner")
    state = cast(ZoneBacklightState, pipeline.zone_state)
    validate_state(state, pipeline.profile.backlight)
    if (
        state.ticks
        or state.zones_nits is not None
        or pipeline.state.previous is not None
        or pipeline.load_state.apl_nits is not None
        or pipeline._zone_resumed
    ):
        raise ValueError("zone resume requires a fresh Pipeline; cannot overwrite live history")
    if boundary(pipeline) != pipeline._zone_boundary:
        raise ValueError("zone resume history changed outside a tick; requires a fresh Pipeline")
    validate_path(pipeline.profile, config)
    try:
        if not isinstance(data, dict):
            raise ValueError("checkpoint must be a mapping")
        if set(data) != {
            "schema_version",
            "kind",
            "identity",
            "geometry",
            "zone_state",
            "load_state",
            "temporal_state",
            "initialization",
            "history_sha256",
            "last_source_sha256",
            "evidence",
            "checkpoint_sha256",
        }:
            raise ValueError("invalid checkpoint fields")
        if data["checkpoint_sha256"] != digest(
            {key: value for key, value in data.items() if key != "checkpoint_sha256"}
        ):
            raise ValueError("checkpoint integrity hash mismatch")
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["kind"] != "lcd_zone_full_history"
        ):
            raise ValueError("unsupported zone checkpoint schema/model")
        if data["identity"] != identity(pipeline) or data["identity"] != pipeline._zone_identity:
            raise ValueError("checkpoint profile/config/angle/colorimetry/model identity mismatch")
        if data["evidence"] != EVIDENCE:
            raise ValueError("checkpoint must preserve P/D/NR evidence")
        saved_geometry = data["geometry"]
        saved_shape = saved_geometry["shape"]
        if (
            not isinstance(saved_shape, list)
            or len(saved_shape) != 3
            or saved_shape[-1] != 3
            or any(type(n) is not int or n <= 0 for n in saved_shape)
        ):
            raise ValueError("invalid checkpoint raster geometry")
        if saved_geometry != geometry(tuple(saved_shape), pipeline):
            raise ValueError("invalid checkpoint zone geometry/dtype")
        if shape is not None and list(shape) != saved_shape:
            raise ValueError("checkpoint geometry mismatch")
        if dtype is not None and np.dtype(dtype) != np.float32:
            raise ValueError("checkpoint dtype mismatch")
        saved = data["zone_state"]
        if set(saved) != {"zones", "previous_targets", "elapsed_ms_hex", "ticks"}:
            raise ValueError("invalid checkpoint zone state fields")
        restored = ZoneBacklightState(
            _unpack(saved["zones"], saved_geometry["zone_shape"], np.dtype(np.float64)),
            _unpack(saved["previous_targets"], saved_geometry["zone_shape"], np.dtype(np.float64)),
            _scalar(saved["elapsed_ms_hex"], "elapsed_ms"),
            saved["ticks"],
        )
        validate_state(restored, pipeline.profile.backlight)
        if restored.ticks < 1:
            raise ValueError("checkpoint must be a successful tick boundary")
        if elapsed_ms is not None and not math.isclose(
            finite_number(elapsed_ms, "elapsed_ms"),
            restored.elapsed_ms,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError("checkpoint timestamp gap; replay every elapsed interval")
        if set(data["load_state"]) != {"apl_nits_hex"} or set(data["temporal_state"]) != {
            "previous"
        }:
            raise ValueError("invalid checkpoint panel/load fields")
        apl_hex = data["load_state"]["apl_nits_hex"]
        apl = None if apl_hex is None else _scalar(apl_hex, "load APL")
        if apl is not None and apl < 0:
            raise ValueError("checkpoint load APL must be nonnegative")
        previous = _unpack(data["temporal_state"]["previous"], saved_shape, np.dtype(np.float32))
        for name in ("history_sha256", "last_source_sha256"):
            if not isinstance(data[name], str) or not re.fullmatch(r"[0-9a-f]{64}", data[name]):
                raise ValueError(f"invalid checkpoint {name}")
        initialization = data["initialization"]
        if set(initialization) - {
            "policy",
            "zones_nits",
            "evidence",
            "supplied_partial_history_sha256",
        } or not {"policy", "zones_nits", "evidence"} <= set(initialization):
            raise ValueError("invalid checkpoint initialization fields")
        if (
            initialization["policy"] not in ("cold", "settled_first_tick", "explicit")
            or initialization["evidence"] != "P"
        ):
            raise ValueError("checkpoint must preserve original P initialization")
        if initialization["policy"] == "explicit":
            original = initialization["zones_nits"]
            explicit = ZoneTemporalConfig(
                model=config.model,
                attack_s=config.attack_s,
                release_s=config.release_s,
                initial="explicit",
                initial_zones_nits=tuple(tuple(row) for row in original),
            )
            validate_path(pipeline.profile, explicit)
            if list(np.asarray(original).shape) != saved_geometry["zone_shape"]:
                raise ValueError("checkpoint explicit initialization geometry mismatch")
        elif initialization["zones_nits"] is not None:
            raise ValueError("checkpoint has competing initialization owners")
        partial = initialization.get("supplied_partial_history_sha256")
        if partial is not None and (
            not isinstance(partial, str) or not re.fullmatch(r"[0-9a-f]{64}", partial)
        ):
            raise ValueError("invalid checkpoint supplied prior history identity")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise ValueError(f"invalid LCD zone checkpoint: {exc}") from exc
    state.zones_nits = restored.zones_nits
    state.previous_targets = restored.previous_targets
    state.elapsed_ms, state.ticks = restored.elapsed_ms, restored.ticks
    pipeline.load_state.apl_nits = apl
    pipeline.state.previous = previous
    pipeline._zone_geometry = deepcopy(saved_geometry)
    pipeline._zone_initialization = deepcopy(initialization)
    pipeline._zone_history_hash = data["history_sha256"]
    pipeline._zone_source_hash = data["last_source_sha256"]
    pipeline._zone_resumed = True
    pipeline._zone_boundary = boundary(pipeline)
