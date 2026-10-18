"""Exact M18 full-history checkpoints, including the sole zone/capacity owners."""

from __future__ import annotations

import base64
import math
import re
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from numpy.typing import DTypeLike

from tv_sim.abl_dynamics import ABLCapacityState, ABLDynamicsConfig, digest
from tv_sim.abl_dynamics import validate_state as validate_capacity
from tv_sim.zone_temporal import ZoneBacklightState, ZoneTemporalConfig
from tv_sim.zone_temporal import validate_state as validate_zones

if TYPE_CHECKING:
    from tv_sim.pipeline import Pipeline

EVIDENCE = {"parameters": "P", "states_and_clock": "D", "matched_measured_waveforms": "NR"}


@lru_cache(maxsize=1)
def _implementation() -> str:
    root = Path(__file__).resolve().parent
    names = [
        "subframe.py",
        "subframe_pipeline.py",
        "subframe_history.py",
        "pipeline.py",
        "zone_temporal.py",
        "zone_history.py",
        "abl_dynamics.py",
        "load.py",
        "color.py",
        "filters.py",
        "frame.py",
        "profile.py",
        "stages/backlight.py",
        "stages/panel.py",
        "stages/tonemap.py",
        "stages/ambient.py",
        "stages/decode.py",
        "stages/process.py",
    ]
    return digest({name: sha256((root / name).read_bytes()).hexdigest() for name in names})


def _evolution(value: Any) -> dict | None:
    if value is None:
        return None
    return {key: val for key, val in asdict(value).items() if not key.startswith("initial")}


def identity(pipeline: Pipeline) -> dict:
    """Bind every effective setting except new-history initialization policies."""
    return {
        "model": "subframe_full_history_v1",
        "profile_sha256": digest(asdict(pipeline.profile)),
        "subframe_sha256": digest(_evolution(pipeline.subframe)),
        "zone_sha256": digest(_evolution(pipeline.zone_temporal)),
        "capacity_sha256": digest(_evolution(pipeline.abl_dynamics)),
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


def _pack(array: np.ndarray | None) -> dict | None:
    if array is None:
        return None
    if not isinstance(array, np.ndarray):
        raise ValueError("subframe history requires NumPy arrays")
    raw = np.ascontiguousarray(array).tobytes()
    return {
        "shape": list(array.shape),
        "dtype": array.dtype.str,
        "base64": base64.b64encode(raw).decode("ascii"),
        "sha256": sha256(raw).hexdigest(),
    }


def _states(pipeline: Pipeline) -> dict:
    pixel = pipeline.subframe_state
    zones, capacity = pipeline.zone_state, pipeline.capacity_state
    return {
        "pixel": {
            "previous": _pack(pixel.previous),
            "ticks": pixel.ticks,
            "next_pts": None if pixel.next_pts is None else str(pixel.next_pts),
        },
        "origin_pts": None
        if pipeline._subframe_origin_pts is None
        else str(pipeline._subframe_origin_pts),
        "elapsed": str(pipeline._subframe_elapsed),
        "zones": None
        if zones is None
        else {
            "zones": _pack(zones.zones_nits),
            "previous_targets": _pack(zones.previous_targets),
            "ticks": zones.ticks,
            "elapsed_ms_hex": float(zones.elapsed_ms).hex(),
        },
        "capacity": None
        if capacity is None
        else {
            "capacity_nits_hex": None
            if capacity.capacity_nits is None
            else float(capacity.capacity_nits).hex(),
            "ticks": capacity.ticks,
            "elapsed_ms_hex": float(capacity.elapsed_ms).hex(),
        },
        "legacy_previous": _pack(pipeline.state.previous),
        "load_apl_hex": None
        if pipeline.load_state.apl_nits is None
        else float(pipeline.load_state.apl_nits).hex(),
    }


def boundary(pipeline: Pipeline) -> str:
    """Detect external changes to persistent arrays, owners and rational clocks."""
    return digest(_states(pipeline))


def checkpoint(pipeline: Pipeline) -> dict:
    """Export only successful immutable tick boundaries with exact float bytes."""
    from tv_sim.subframe_pipeline import validate

    validate(pipeline)
    if pipeline.subframe_state.ticks < 1:
        raise ValueError("subframe checkpoint requires a successful display tick")
    if (
        identity(pipeline) != pipeline._subframe_identity
        or boundary(pipeline) != pipeline._subframe_boundary
    ):
        raise ValueError("subframe identity or history changed outside a tick")
    data = {
        "schema_version": 1,
        "kind": "subframe_full_history",
        "identity": identity(pipeline),
        "geometry": deepcopy(pipeline._subframe_geometry),
        "states": _states(pipeline),
        "initialization": deepcopy(pipeline._subframe_initialization),
        "history_sha256": pipeline._subframe_history_hash,
        "evidence": dict(EVIDENCE),
    }
    data["checkpoint_sha256"] = digest(data)
    return data


def _keys(value: Any, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid subframe checkpoint fields")


def _unpack(value: Any, shape: list[int]) -> np.ndarray:
    _keys(value, {"shape", "dtype", "base64", "sha256"})
    if value["shape"] != shape or value["dtype"] != np.dtype(np.float64).str:
        raise ValueError("checkpoint array geometry/dtype mismatch")
    raw = base64.b64decode(value["base64"], validate=True)
    if len(raw) != math.prod(shape) * 8 or sha256(raw).hexdigest() != value["sha256"]:
        raise ValueError("checkpoint array byte count/hash mismatch")
    result = np.frombuffer(raw, dtype=np.float64).reshape(shape).copy()
    if not np.isfinite(result).all() or np.any(result < 0):
        raise ValueError("checkpoint arrays require finite nonnegative values")
    return result


def _scalar(value: Any) -> float:
    if not isinstance(value, str):
        raise ValueError("checkpoint scalars require exact float hex strings")
    result = float.fromhex(value)
    if not math.isfinite(result):
        raise ValueError("checkpoint scalars must be finite")
    return result


def _fraction(value: Any) -> Fraction:
    if not isinstance(value, str):
        raise ValueError("checkpoint clock must be a rational string")
    return Fraction(value)


def restore_checkpoint(
    pipeline: Pipeline,
    data: dict,
    *,
    shape: tuple[int, ...] | None = None,
    dtype: DTypeLike | None = None,
    elapsed_ms: float | None = None,
) -> None:
    """Validate into local candidates, then restore all owners together."""
    from tv_sim.subframe import SubframeState
    from tv_sim.subframe_pipeline import validate
    from tv_sim.zone_history import geometry

    validate(pipeline)
    if (
        pipeline.subframe.initial != "resume"
        or pipeline._subframe_resumed
        or pipeline.subframe_state.ticks
    ):
        raise ValueError("subframe restore requires a fresh Pipeline with resume initialization")
    if boundary(pipeline) != pipeline._subframe_boundary:
        raise ValueError("subframe resume history changed outside a tick")
    try:
        _keys(
            data,
            {
                "schema_version",
                "kind",
                "identity",
                "geometry",
                "states",
                "initialization",
                "history_sha256",
                "evidence",
                "checkpoint_sha256",
            },
        )
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["kind"] != "subframe_full_history"
        ):
            raise ValueError("unsupported subframe checkpoint schema")
        if (
            digest({k: v for k, v in data.items() if k != "checkpoint_sha256"})
            != data["checkpoint_sha256"]
        ):
            raise ValueError("checkpoint integrity hash mismatch")
        if data["identity"] != identity(pipeline) or data["evidence"] != EVIDENCE:
            raise ValueError("checkpoint display identity or evidence mismatch")
        raster = data["geometry"]
        saved_shape = raster["shape"]
        if (
            not isinstance(saved_shape, list)
            or len(saved_shape) != 3
            or saved_shape[-1] != 3
            or any(type(n) is not int or n < 1 for n in saved_shape)
        ):
            raise ValueError("invalid checkpoint raster")
        if (
            raster != geometry(tuple(saved_shape), pipeline)
            or (shape is not None and list(shape) != saved_shape)
            or (dtype is not None and np.dtype(dtype) != np.float32)
        ):
            raise ValueError("checkpoint geometry/dtype mismatch")
        states = data["states"]
        _keys(
            states,
            {
                "pixel",
                "origin_pts",
                "elapsed",
                "zones",
                "capacity",
                "legacy_previous",
                "load_apl_hex",
            },
        )
        _keys(states["pixel"], {"previous", "ticks", "next_pts"})
        pixel = states["pixel"]
        ticks = pixel["ticks"]
        if type(ticks) is not int or ticks < 1:
            raise ValueError("checkpoint tick count must be positive")
        previous = _unpack(pixel["previous"], saved_shape)
        if not pipeline.profile.self_emissive and (
            np.any(previous > 1) or np.any(previous < 1 / pipeline.profile.panel.native_contrast)
        ):
            raise ValueError("checkpoint transmission outside physical bounds")
        next_pts, origin, elapsed = (
            _fraction(pixel["next_pts"]),
            _fraction(states["origin_pts"]),
            _fraction(states["elapsed"]),
        )
        if elapsed <= 0 or next_pts != origin + elapsed:
            raise ValueError("checkpoint rational clock mismatch")
        if elapsed_ms is not None and (
            not math.isfinite(elapsed_ms)
            or not math.isclose(elapsed_ms, float(elapsed * 1000), rel_tol=1e-12, abs_tol=1e-9)
        ):
            raise ValueError("checkpoint elapsed time mismatch")
        if states["legacy_previous"] is not None or states["load_apl_hex"] is not None:
            raise ValueError("checkpoint contains competing legacy histories")
        zones = None
        if pipeline._zone_active:
            value = states["zones"]
            _keys(value, {"zones", "previous_targets", "ticks", "elapsed_ms_hex"})
            zones = ZoneBacklightState(
                _unpack(value["zones"], raster["zone_shape"]),
                _unpack(value["previous_targets"], raster["zone_shape"]),
                _scalar(value["elapsed_ms_hex"]),
                value["ticks"],
            )
            validate_zones(zones, pipeline.profile.backlight)
            if zones.ticks != ticks or not math.isclose(
                zones.elapsed_ms, float(elapsed * 1000), rel_tol=1e-12, abs_tol=1e-9
            ):
                raise ValueError("checkpoint zone clock mismatch")
        elif states["zones"] is not None:
            raise ValueError("checkpoint has an unexpected zone owner")
        capacity = None
        if pipeline._dynamics_active:
            value = states["capacity"]
            _keys(value, {"capacity_nits_hex", "ticks", "elapsed_ms_hex"})
            capacity = ABLCapacityState(
                _scalar(value["capacity_nits_hex"]),
                _scalar(value["elapsed_ms_hex"]),
                value["ticks"],
            )
            validate_capacity(
                capacity,
                pipeline.profile.hdr.panel_peak_nits,
                pipeline.profile.hdr.abl_full_field_nits,
            )
            if capacity.ticks != ticks or not math.isclose(
                capacity.elapsed_ms, float(elapsed * 1000), rel_tol=1e-12, abs_tol=1e-9
            ):
                raise ValueError("checkpoint capacity clock mismatch")
        elif states["capacity"] is not None:
            raise ValueError("checkpoint has an unexpected capacity owner")
        initialization = data["initialization"]
        _keys(
            initialization,
            {
                "pixel",
                "zone",
                "capacity",
                "evidence",
                "zone_initial_zones_nits",
                "capacity_initial_nits",
            },
        )
        if (
            initialization["pixel"] not in ("cold", "settled_first_tick")
            or initialization["evidence"] != "P"
        ):
            raise ValueError("checkpoint original initialization must retain P evidence")
        for key, active in (
            ("zone", pipeline._zone_active),
            ("capacity", pipeline._dynamics_active),
        ):
            if (
                active and initialization[key] not in ("cold", "settled_first_tick", "explicit")
            ) or (not active and initialization[key] is not None):
                raise ValueError("checkpoint initialization owner mismatch")
        if initialization["zone"] == "explicit":
            from tv_sim.zone_temporal import validate_path

            original_grid = initialization["zone_initial_zones_nits"]
            original_zone = replace(
                cast(ZoneTemporalConfig, pipeline.zone_temporal),
                initial="explicit",
                initial_zones_nits=tuple(tuple(row) for row in original_grid),
            )
            validate_path(pipeline.profile, original_zone)
            if list(np.asarray(original_grid).shape) != raster["zone_shape"]:
                raise ValueError("checkpoint initial zone geometry mismatch")
        elif initialization["zone_initial_zones_nits"] is not None:
            raise ValueError("checkpoint unexpected initial zone grid")
        if initialization["capacity"] == "explicit":
            from tv_sim.abl_dynamics import validate_dynamics

            original_capacity = replace(
                cast(ABLDynamicsConfig, pipeline.abl_dynamics),
                initial="explicit",
                initial_capacity_nits=initialization["capacity_initial_nits"],
            )
            validate_dynamics(pipeline.profile, original_capacity)
        elif initialization["capacity_initial_nits"] is not None:
            raise ValueError("checkpoint unexpected initial capacity")
        if not isinstance(data["history_sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", data["history_sha256"]
        ):
            raise ValueError("invalid checkpoint history hash")
    except (
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        AttributeError,
        ZeroDivisionError,
    ) as exc:
        raise ValueError(f"invalid subframe checkpoint: {exc}") from exc
    pipeline.subframe_state = SubframeState(previous=previous, ticks=ticks, next_pts=next_pts)
    pipeline.zone_state, pipeline.capacity_state = zones, capacity
    pipeline._subframe_origin_pts, pipeline._subframe_elapsed = origin, elapsed
    pipeline._subframe_geometry = deepcopy(raster)
    pipeline._subframe_initialization = deepcopy(initialization)
    pipeline._subframe_history_hash = data["history_sha256"]
    pipeline._subframe_resumed = True
    pipeline._subframe_boundary = boundary(pipeline)
