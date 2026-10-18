"""Opt-in P LCD zone commands, filtered once per display tick before optics.

Attack increases backlight drive; release decreases it. Time constants use
seconds and the optional slew bound uses nits per tick. Neither setting is a
measured television parameter. The ordinary backlight stage remains unchanged.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, cast

import numpy as np

from tv_sim.abl_dynamics import finite_number
from tv_sim.frame import Frame
from tv_sim.profile import BacklightParams, TVProfile
from tv_sim.stages.backlight import (
    apply_light_spread,
    pool_zones,
    psf_axis_kernels,
    upsample_zones,
    zone_edges,
)

MODEL = "zone_attack_release_v1"


@dataclass(frozen=True)
class ZoneTemporalConfig:
    """Separate P runtime policy; active taus must be explicitly supplied."""

    model: str = "off"
    attack_s: float | None = None
    release_s: float | None = None
    slew_nits_per_tick: float | None = None
    reset_on_scene_cut: bool = True
    cut_detection_threshold: float | None = None
    initial: str = "cold"
    initial_zones_nits: tuple[tuple[float, ...], ...] | None = None
    parameter_status: str = "placeholder"

    def __post_init__(self) -> None:
        if self.model not in ("off", MODEL):
            raise ValueError(f"unsupported zone temporal model {self.model!r}")
        if self.parameter_status != "placeholder":
            raise ValueError("zone temporal parameter_status must be placeholder (P)")
        if type(self.reset_on_scene_cut) is not bool:
            raise ValueError("reset_on_scene_cut must be bool")
        if self.initial not in ("cold", "settled_first_tick", "explicit", "resume"):
            raise ValueError("unknown zone initialization policy")
        if not self.active:
            if (
                self.attack_s is not None
                or self.release_s is not None
                or self.slew_nits_per_tick is not None
                or not self.reset_on_scene_cut
                or self.cut_detection_threshold is not None
                or self.initial != "cold"
                or self.initial_zones_nits is not None
            ):
                raise ValueError("zone temporal options require an active model, not off")
            return
        for name in ("attack_s", "release_s"):
            if finite_number(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.slew_nits_per_tick is not None:
            if finite_number(self.slew_nits_per_tick, "slew_nits_per_tick") <= 0:
                raise ValueError("slew_nits_per_tick must be positive")
        if self.cut_detection_threshold is not None:
            threshold = finite_number(self.cut_detection_threshold, "cut_detection_threshold")
            if not self.reset_on_scene_cut or not 0 < threshold <= 1:
                raise ValueError(
                    "cut detection requires reset_on_scene_cut and threshold in (0, 1]"
                )
        if self.initial == "explicit":
            grid = self.initial_zones_nits
            if (
                not isinstance(grid, tuple)
                or not grid
                or any(not isinstance(row, tuple) or not row for row in grid)
                or any(len(row) != len(grid[0]) for row in grid)
            ):
                raise ValueError(
                    "explicit initialization requires an immutable rectangular zone grid"
                )
            for row in grid:
                for value in row:
                    if finite_number(value, "initial_zones_nits") < 0:
                        raise ValueError("initial_zones_nits must be nonnegative")
        elif self.initial_zones_nits is not None:
            raise ValueError(
                "initial_zones_nits requires explicit initialization; resume owns history"
            )

    @property
    def active(self) -> bool:
        return self.model != "off"


@dataclass
class ZoneBacklightState:
    """Exact float64 commands/detector input and the last successful tick clock."""

    zones_nits: np.ndarray | None = None
    previous_targets: np.ndarray | None = None
    elapsed_ms: float = 0.0
    ticks: int = 0


def evolution(config: ZoneTemporalConfig) -> dict[str, Any]:
    """Initialization is recorded separately from the continuation identity."""
    return {
        key: value
        for key, value in asdict(config).items()
        if key not in ("initial", "initial_zones_nits")
    }


def bounds(params: BacklightParams) -> tuple[float, float]:
    floor = finite_number(params.floor_nits, "floor_nits")
    peak = finite_number(params.peak_nits, "peak_nits")
    if not 0 <= floor <= peak or peak <= 0:
        raise ValueError("zone bounds require 0 <= floor_nits <= peak_nits and positive peak")
    return floor, peak


def validate_path(profile: TVProfile, config: ZoneTemporalConfig) -> None:
    """Reject ambiguous controller ownership before mutating any display state."""
    if not config.active:
        return
    if profile.technology not in ("va_lcd", "ips_lcd") or profile.self_emissive:
        raise ValueError("zone temporal dynamics supports only LCD profiles")
    params = profile.backlight
    if params.mode not in ("fald", "edge"):
        raise ValueError("zone temporal dynamics requires a zoned fald/edge backlight")
    for name in ("zones_x", "zones_y"):
        if type(getattr(params, name)) is not int or getattr(params, name) < 1:
            raise ValueError(f"{name} must be a positive integer")
    if not 0 <= finite_number(params.zone_percentile, "zone_percentile") <= 100:
        raise ValueError("zone_percentile must be in [0, 100]")
    if params.psf_shape not in ("gaussian", "exponential_tail"):
        raise ValueError("unknown zone PSF shape")
    if params.psf_boundary not in ("reflect", "zero", "calibrated_zero"):
        raise ValueError("unknown zone PSF boundary")
    if not 0 <= finite_number(params.psf_tail_weight, "psf_tail_weight") <= 1:
        raise ValueError("psf_tail_weight must be in [0, 1]")
    floor, peak = bounds(params)
    for name in ("abl_response_ms", "abl_backlight_tracking", "abl_power_budget_nits"):
        if finite_number(getattr(profile.hdr, name), name) != 0:
            raise ValueError(f"zone temporal dynamics conflicts with nonzero {name}")
    if config.initial_zones_nits is not None:
        initial = np.asarray(config.initial_zones_nits, dtype=np.float64)
        if np.any(initial < floor) or np.any(initial > peak):
            raise ValueError("initial_zones_nits outside declared zone bounds")


def validate_grid(value: np.ndarray, params: BacklightParams, name: str) -> None:
    floor, peak = bounds(params)
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.float64
        or value.ndim != 2
        or min(value.shape) < 1
        or not np.isfinite(value).all()
        or np.any(value < floor)
        or np.any(value > peak)
    ):
        raise ValueError(f"{name} must be a finite float64 zone grid within declared bounds")


def validate_state(state: ZoneBacklightState, params: BacklightParams) -> None:
    """Check a history without changing its arrays or clock."""
    if not isinstance(state, ZoneBacklightState):
        raise ValueError("zone_state must be a ZoneBacklightState")
    if finite_number(state.elapsed_ms, "elapsed_ms") < 0:
        raise ValueError("elapsed_ms must be nonnegative")
    if type(state.ticks) is not int or state.ticks < 0:
        raise ValueError("ticks must be a nonnegative integer")
    if (state.ticks == 0) != (state.elapsed_ms == 0):
        raise ValueError("zone clock and tick history are inconsistent")
    if state.zones_nits is None:
        if state.ticks or state.previous_targets is not None:
            raise ValueError("uninitialized zones cannot have elapsed or detector history")
    else:
        validate_grid(state.zones_nits, params, "zones_nits")
        if state.previous_targets is not None:
            validate_grid(state.previous_targets, params, "previous_targets")
            if state.previous_targets.shape != state.zones_nits.shape:
                raise ValueError("zone and detector grids must have matching shapes")
        elif state.ticks:
            raise ValueError("continued zone state requires its previous detector input")


def zone_targets(frame: Frame, params: BacklightParams) -> np.ndarray:
    """Bound pooled panel-domain demand before optics on the active P path."""
    zones, _, _ = pool_zones(
        np.max(frame.rgb, axis=-1).astype(np.float32),
        params.zones_y,
        params.zones_x,
        params.zone_percentile,
    )
    floor, peak = bounds(params)
    return np.clip(zones.astype(np.float64), floor, peak)


def render_backlight(frame: Frame, params: BacklightParams, zones: np.ndarray) -> Frame:
    """Cast commands only at optical transport; use the existing PSF once."""
    height, width = frame.rgb.shape[:2]
    y_edges = zone_edges(height, params.zones_y)
    x_edges = zone_edges(width, params.zones_x)
    if zones.shape != (len(y_edges) - 1, len(x_edges) - 1):
        raise ValueError("zone history does not match the effective rasterized grid")
    backlight = upsample_zones(zones, y_edges, x_edges, (height, width))
    kernels = psf_axis_kernels(
        params,
        zone_pitch_y=height / zones.shape[0],
        zone_pitch_x=width / zones.shape[1],
        per_pixel=False,
    )
    if any(kernel.size > 1 for kernel in kernels[:2]) or (
        kernels[4] > 1e-8 and any(kernel.size > 1 for kernel in kernels[2:4])
    ):
        backlight = apply_light_spread(backlight, kernels, params.psf_boundary)
    floor, peak = bounds(params)
    return Frame(frame.rgb, np.clip(np.maximum(backlight, np.float32(floor)), 0, np.float32(peak)))


def update_zones(
    state: ZoneBacklightState,
    targets: np.ndarray,
    params: BacklightParams,
    dt_ms: float,
    config: ZoneTemporalConfig,
    *,
    scene_cut: bool = False,
) -> dict[str, Any]:
    """One bounded asymmetric e-fold update; validation failures do not mutate."""
    if not config.active:
        raise ValueError("zone update requires active dynamics")
    if type(scene_cut) is not bool:
        raise ValueError("scene_cut must be bool")
    validate_state(state, params)
    validate_grid(targets, params, "targets")
    dt = finite_number(dt_ms, "frame_time_ms")
    if dt <= 0 or not math.isfinite(state.elapsed_ms + dt):
        raise ValueError("frame_time_ms must be positive with a finite elapsed clock")
    floor, peak = bounds(params)
    if state.zones_nits is not None:
        before = state.zones_nits.copy()
    elif config.initial == "resume":
        raise ValueError("resume requires a complete validated zone checkpoint")
    elif config.initial == "explicit":
        before = np.asarray(config.initial_zones_nits, dtype=np.float64)
    elif config.initial == "settled_first_tick":
        before = targets.copy()
    else:
        before = np.full(targets.shape, floor, dtype=np.float64)
    if before.shape != targets.shape:
        raise ValueError("initial/history zone grid does not match effective rasterized grid")
    validate_grid(before, params, "initial zones")
    score = (
        None
        if state.previous_targets is None
        else float(np.mean(np.abs(targets - state.previous_targets), dtype=np.float64) / peak)
    )
    detected = bool(
        config.cut_detection_threshold is not None
        and score is not None
        and score > config.cut_detection_threshold
    )
    reset = config.reset_on_scene_cut and (scene_cut or detected)
    rising, falling = targets > before, targets < before
    after = before.copy()
    for mask, tau in ((rising, config.attack_s), (falling, config.release_s)):
        tau = cast(float, tau)
        if tau == 0:
            after[mask] = targets[mask]
        else:
            after[mask] += (-math.expm1(-(dt / 1000) / tau)) * (targets[mask] - before[mask])
    slew_limited = np.zeros(targets.shape, dtype=bool)
    if reset:
        after = targets.copy()
    elif config.slew_nits_per_tick is not None:
        difference = after - before
        slew_limited = np.abs(difference) > config.slew_nits_per_tick
        after = before + np.clip(difference, -config.slew_nits_per_tick, config.slew_nits_per_tick)
    after = np.clip(after, floor, peak)
    trace = {
        "model": config.model,
        "targets_nits": targets.tolist(),
        "before_nits": before.tolist(),
        "after_nits": after.tolist(),
        "branch": np.where(rising, "attack", np.where(falling, "release", "equal")).tolist(),
        "slew_limited": slew_limited.tolist(),
        "scene_cut_declared": scene_cut,
        "scene_cut_detected": detected,
        "scene_cut_reset": reset,
        "cut_detection_score": score,
        "cut_detection_threshold": config.cut_detection_threshold,
        "detector_domain": "mean_absolute_bounded_zone_target_delta_divided_by_peak",
        "attack_s": config.attack_s,
        "release_s": config.release_s,
        "slew_nits_per_tick": config.slew_nits_per_tick,
        "dt_ms": dt,
        "elapsed_ms": float(state.elapsed_ms + dt),
        "ticks": state.ticks + 1,
        "parameter_evidence": "P",
        "trace_evidence": "D",
    }
    state.zones_nits = after
    state.previous_targets = targets.copy()
    state.elapsed_ms = float(state.elapsed_ms + dt)
    state.ticks += 1
    return trace
