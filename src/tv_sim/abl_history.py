"""Version-1 full OLED display checkpoints; float hex and exact array bytes.

Capacity-only explicit initialization is intentionally a different API. It
does not promise the pixel/history parity provided by these checkpoints.
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
from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import DTypeLike

from tv_sim.abl_dynamics import (
    ABLCapacityState,
    ABLDynamicsConfig,
    digest,
    evolution,
    finite_number,
    target_semantics,
    validate_dynamics,
    validate_state,
)
from tv_sim.colorimetry import PanelColorimetry

if TYPE_CHECKING:
    from tv_sim.pipeline import Pipeline

EVIDENCE = {
    "model_and_initialization": "P",
    "states_and_clock": "D",
    "measured_prior_thermal_condition": "NR",
}


@lru_cache(maxsize=1)
def _implementation() -> str:
    root = Path(__file__).resolve().parent
    names = [
        "abl_dynamics.py",
        "abl_history.py",
        "pipeline.py",
        "load.py",
        "color.py",
        "frame.py",
        "filters.py",
        "viewing_angle.py",
    ]
    names += [
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


def identity(pipeline: Pipeline) -> dict:
    if not pipeline._dynamics_active:
        raise ValueError("capacity identity requires active ABL dynamics")
    result = {
        "model": cast(ABLDynamicsConfig, pipeline.abl_dynamics).model,
        "evolution_version": 1,
        "profile_sha256": digest(asdict(pipeline.profile)),
        "evolution_sha256": digest(evolution(cast(ABLDynamicsConfig, pipeline.abl_dynamics))),
        "target_map": target_semantics(pipeline.profile.hdr),
        "angle_sha256": digest(
            {
                "config": asdict(pipeline.viewing_angle),
                "parameters": None
                if pipeline.angular_params is None
                else asdict(pipeline.angular_params),
            }
        ),
        "implementation_sha256": _implementation(),
        "numpy_version": np.__version__,
    }
    if pipeline._colorimetry_active:
        result["colorimetry"] = {
            "config_sha256": digest(asdict(pipeline.colorimetry)),
            "panel_sha256": digest(asdict(cast(PanelColorimetry, pipeline.panel_colorimetry))),
            "implementation_sha256": sha256(
                (Path(__file__).resolve().parent / "colorimetry.py").read_bytes()
            ).hexdigest(),
        }
    return result


def _hex(value):
    return None if value is None else float(value).hex()


def boundary(pipeline: Pipeline) -> str:
    """Detect edits to a live history that bypassed a declared display tick."""
    state, previous = cast(ABLCapacityState, pipeline.capacity_state), pipeline.state.previous
    return digest(
        {
            "capacity": _hex(state.capacity_nits),
            "elapsed": _hex(state.elapsed_ms),
            "ticks": state.ticks,
            "legacy_load": _hex(pipeline.load_state.apl_nits),
            "previous": None
            if previous is None
            else {
                "shape": list(previous.shape),
                "dtype": previous.dtype.str,
                "sha256": sha256(np.ascontiguousarray(previous).tobytes()).hexdigest(),
            },
        }
    )


def checkpoint(pipeline: Pipeline) -> dict:
    if not pipeline._dynamics_active or cast(ABLCapacityState, pipeline.capacity_state).ticks == 0:
        raise ValueError("checkpoint requires a successful active display tick")
    if pipeline.identity() != pipeline._capacity_identity:
        raise ValueError("display identity changed before checkpoint")
    if boundary(pipeline) != pipeline._capacity_boundary:
        raise ValueError(
            "display history was edited outside a tick; restart or restore a checkpoint"
        )
    state = cast(ABLCapacityState, pipeline.capacity_state)
    validate_state(
        state, pipeline.profile.hdr.panel_peak_nits, pipeline.profile.hdr.abl_full_field_nits
    )
    apl = pipeline.load_state.apl_nits
    if apl is not None and finite_number(apl, "load APL") < 0:
        raise ValueError("checkpoint load APL must be nonnegative")
    previous = pipeline.state.previous
    if (
        previous is None
        or not np.isfinite(previous).all()
        or {"shape": list(previous.shape), "dtype": previous.dtype.str}
        != pipeline._capacity_geometry
    ):
        raise ValueError("panel history does not match capacity geometry")
    raw = np.ascontiguousarray(previous).tobytes()
    data = {
        "schema_version": 1,
        "kind": "oled_capacity_full_history",
        "identity": deepcopy(pipeline._capacity_identity),
        "geometry": deepcopy(pipeline._capacity_geometry),
        "capacity_state": {
            "capacity_nits_hex": _hex(state.capacity_nits),
            "elapsed_ms_hex": _hex(state.elapsed_ms),
            "ticks": state.ticks,
        },
        "load_state": {"apl_nits_hex": _hex(pipeline.load_state.apl_nits)},
        "temporal_state": {
            "previous_base64": base64.b64encode(raw).decode("ascii"),
            "previous_sha256": sha256(raw).hexdigest(),
        },
        "initialization": deepcopy(pipeline._capacity_initialization),
        "history_sha256": pipeline._capacity_history_hash,
        "last_source_sha256": pipeline._capacity_source_hash,
        "evidence": dict(EVIDENCE),
    }
    data["checkpoint_sha256"] = digest(data)
    return data


def _scalar(value, name):
    if not isinstance(value, str):
        raise ValueError(f"checkpoint {name} must be an exact float hex string")
    result = float.fromhex(value)
    if not math.isfinite(result):
        raise ValueError(f"checkpoint {name} must be finite")
    return result


def restore_checkpoint(
    pipeline: Pipeline,
    data: dict,
    *,
    shape: tuple[int, ...] | None = None,
    dtype: DTypeLike | None = None,
    elapsed_ms: float | None = None,
) -> None:
    """Validate everything into local values; failures cannot advance history."""
    config = cast(ABLDynamicsConfig, pipeline.abl_dynamics)
    if not pipeline._dynamics_active or config.initial != "resume":
        raise ValueError("state input requires resume as the sole initialization owner")
    if (
        cast(ABLCapacityState, pipeline.capacity_state).ticks
        or pipeline.state.previous is not None
        or pipeline._capacity_resumed
    ):
        raise ValueError("resume requires a fresh Pipeline; cannot overwrite live history")
    validate_dynamics(pipeline.profile, config)
    try:
        if not isinstance(data, dict):
            raise ValueError("checkpoint must be a mapping")
        payload = {key: value for key, value in data.items() if key != "checkpoint_sha256"}
        if data["checkpoint_sha256"] != digest(payload):
            raise ValueError("checkpoint integrity hash mismatch")
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["kind"] != "oled_capacity_full_history"
        ):
            raise ValueError("unsupported checkpoint schema/model")
        if data["identity"] != pipeline.identity():
            raise ValueError("checkpoint profile/config/angle/model identity mismatch")
        if data["evidence"] != EVIDENCE:
            raise ValueError("checkpoint must preserve P/D/NR evidence")
        geometry = data["geometry"]
        stored_shape = geometry["shape"]
        if (
            not isinstance(stored_shape, list)
            or len(stored_shape) != 3
            or stored_shape[-1] != 3
            or any(type(n) is not int or n <= 0 for n in stored_shape)
            or geometry["dtype"] != np.dtype(np.float32).str
        ):
            raise ValueError("invalid checkpoint geometry/dtype")
        if shape is not None and list(shape) != stored_shape:
            raise ValueError("checkpoint geometry mismatch")
        if dtype is not None and np.dtype(dtype).str != geometry["dtype"]:
            raise ValueError("checkpoint dtype mismatch")
        saved = data["capacity_state"]
        state = ABLCapacityState(
            _scalar(saved["capacity_nits_hex"], "capacity"),
            _scalar(saved["elapsed_ms_hex"], "elapsed_ms"),
            saved["ticks"],
        )
        validate_state(
            state, pipeline.profile.hdr.panel_peak_nits, pipeline.profile.hdr.abl_full_field_nits
        )
        if state.ticks < 1:
            raise ValueError("checkpoint must be a successful tick boundary")
        if elapsed_ms is not None and not math.isclose(
            finite_number(elapsed_ms, "elapsed_ms"), state.elapsed_ms, rel_tol=1e-12, abs_tol=1e-9
        ):
            raise ValueError("checkpoint timestamp gap; replay every elapsed interval")
        load_hex = data["load_state"]["apl_nits_hex"]
        apl = None if load_hex is None else _scalar(load_hex, "load APL")
        if apl is not None and apl < 0:
            raise ValueError("checkpoint load APL must be nonnegative")
        temporal = data["temporal_state"]
        raw = base64.b64decode(temporal["previous_base64"], validate=True)
        if len(raw) != math.prod(stored_shape) * np.dtype(np.float32).itemsize:
            raise ValueError("checkpoint panel byte count/geometry mismatch")
        if sha256(raw).hexdigest() != temporal["previous_sha256"]:
            raise ValueError("checkpoint panel hash mismatch")
        previous = np.frombuffer(raw, dtype=np.float32).reshape(stored_shape).copy()
        if not np.isfinite(previous).all() or np.any(previous < 0):
            raise ValueError("checkpoint panel history must be finite nonnegative nits")
        for key in ("history_sha256", "last_source_sha256"):
            if not isinstance(data[key], str) or not re.fullmatch(r"[0-9a-f]{64}", data[key]):
                raise ValueError(f"invalid checkpoint {key}")
        initialization = data["initialization"]
        if (
            initialization["policy"] not in ("cold", "settled_first_tick", "explicit")
            or initialization["evidence"] != "P"
        ):
            raise ValueError("checkpoint must preserve original P initialization")
        if initialization["policy"] == "explicit":
            initial = finite_number(initialization["capacity_nits"], "initial_capacity_nits")
            if (
                not pipeline.profile.hdr.abl_full_field_nits
                <= initial
                <= pipeline.profile.hdr.panel_peak_nits
            ):
                raise ValueError("checkpoint original initialization outside bounds")
        elif initialization["capacity_nits"] is not None:
            raise ValueError("checkpoint has competing initialization owners")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid OLED checkpoint: {exc}") from exc
    cast(ABLCapacityState, pipeline.capacity_state).capacity_nits = state.capacity_nits
    cast(ABLCapacityState, pipeline.capacity_state).elapsed_ms = state.elapsed_ms
    cast(ABLCapacityState, pipeline.capacity_state).ticks = state.ticks
    pipeline.load_state.apl_nits = apl
    pipeline.state.previous = previous
    pipeline._capacity_geometry = deepcopy(geometry)
    pipeline._capacity_initialization = deepcopy(initialization)
    pipeline._capacity_history_hash = data["history_sha256"]
    pipeline._capacity_source_hash = data["last_source_sha256"]
    pipeline._capacity_resumed = True
    pipeline._capacity_boundary = boundary(pipeline)
