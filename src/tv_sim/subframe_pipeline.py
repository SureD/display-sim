"""M18 tick orchestration: one zone/capacity owner before resolved emission.

HDR defines the steady target once per tick. LCD history is dimensionless
transmission, multiplied by that tick's illumination at each emission interval.
Transient OD can exceed the steady HDR target within physical transmission
bounds. OLED capacity limits the steady emission target before duty gating.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from typing import TYPE_CHECKING, cast

import numpy as np

from tv_sim.abl_dynamics import (
    ABLCapacityState,
    ABLDynamicsConfig,
    digest,
    target_trace,
    update_capacity,
    validate_dynamics,
)
from tv_sim.frame import Frame
from tv_sim.load import demand_apl
from tv_sim.stages.ambient import reflected_nits
from tv_sim.stages.backlight import simulate_backlight
from tv_sim.stages.panel import emission_psf, simulate_panel
from tv_sim.stages.tonemap import tone_map
from tv_sim.zone_temporal import (
    ZoneBacklightState,
    ZoneTemporalConfig,
    render_backlight,
    update_zones,
    zone_targets,
)
from tv_sim.zone_temporal import (
    validate_path as validate_zones,
)

if TYPE_CHECKING:
    from tv_sim.pipeline import Pipeline
    from tv_sim.subframe import SubframeConfig, SubframeResult


def initialize(pipeline: Pipeline, config: SubframeConfig | None) -> None:
    """Attach a separate history only for an explicitly active configuration."""
    from tv_sim.subframe import SubframeConfig, SubframeState

    pipeline.subframe = config if config is not None else SubframeConfig()
    pipeline._initial_subframe = pipeline.subframe
    pipeline._subframe_active = pipeline.subframe.active
    pipeline.last_subframe_result = None
    if not pipeline._subframe_active:
        return
    from tv_sim.subframe_history import boundary, identity

    validate(pipeline)
    if pipeline.state.previous is not None or pipeline.load_state.apl_nits is not None:
        raise ValueError("subframe history requires a fresh Pipeline or a full checkpoint")
    if pipeline.zone_state is not None and (
        pipeline.zone_state.ticks or pipeline.zone_state.zones_nits is not None
    ):
        raise ValueError("subframe history cannot adopt partial zone state")
    if pipeline.capacity_state is not None and (
        pipeline.capacity_state.ticks or pipeline.capacity_state.capacity_nits is not None
    ):
        raise ValueError("subframe history cannot adopt partial capacity state")
    pipeline.subframe_state = SubframeState()
    pipeline._subframe_geometry = None
    pipeline._subframe_origin_pts = None
    pipeline._subframe_elapsed = Fraction(0)
    pipeline._subframe_resumed = False
    pipeline._subframe_initialization = {
        "pixel": pipeline.subframe.initial,
        "zone": None
        if not pipeline._zone_active
        else cast(ZoneTemporalConfig, pipeline.zone_temporal).initial,
        "capacity": None
        if not pipeline._dynamics_active
        else cast(ABLDynamicsConfig, pipeline.abl_dynamics).initial,
        "evidence": "P",
        "zone_initial_zones_nits": None
        if pipeline.zone_temporal is None or pipeline.zone_temporal.initial_zones_nits is None
        else [list(row) for row in pipeline.zone_temporal.initial_zones_nits],
        "capacity_initial_nits": None
        if pipeline.abl_dynamics is None
        else pipeline.abl_dynamics.initial_capacity_nits,
    }
    pipeline._subframe_identity = identity(pipeline)
    pipeline._subframe_boundary = boundary(pipeline)
    pipeline._subframe_history_hash = digest(pipeline._subframe_initialization)


def validate(pipeline: Pipeline) -> None:
    """Reject features whose transformed color/transmission domains are ambiguous."""
    from tv_sim.subframe import validate_path

    if not pipeline._subframe_active:
        raise ValueError("display_subframes requires active subframe emission")
    if pipeline.subframe is not pipeline._initial_subframe:
        raise ValueError("changing subframe configuration requires a fresh Pipeline")
    validate_path(pipeline.profile, pipeline.subframe)
    if pipeline._colorimetry_active or pipeline.viewing_angle.active:
        raise ValueError("M18 v1 rejects M10 viewing angle and M15 colorimetry")
    panel = pipeline.profile.panel
    if panel.viewing_angle_deg != 0 or not np.array_equal(
        np.asarray(panel.color_matrix).reshape(3, 3), np.eye(3)
    ):
        raise ValueError("M18 v1 requires on-axis identity legacy panel color transform")
    if pipeline.abl_dynamics is not pipeline._initial_abl_dynamics:
        raise ValueError("changing ABL dynamics requires a fresh Pipeline")
    if pipeline.zone_temporal is not pipeline._initial_zone_temporal:
        raise ValueError("changing zone dynamics requires a fresh Pipeline")
    if pipeline.colorimetry != pipeline._initial_colorimetry:
        raise ValueError("changing colorimetry requires a fresh Pipeline")
    for name in ("abl_response_ms", "abl_backlight_tracking", "abl_power_budget_nits"):
        if getattr(pipeline.profile.hdr, name) != 0:
            raise ValueError(f"subframe emission conflicts with nonzero {name}")
    if pipeline._zone_active:
        validate_zones(pipeline.profile, cast(ZoneTemporalConfig, pipeline.zone_temporal))
    if pipeline._dynamics_active:
        validate_dynamics(pipeline.profile, cast(ABLDynamicsConfig, pipeline.abl_dynamics))
    resume = pipeline.subframe.initial == "resume"
    for active, config in (
        (pipeline._zone_active, pipeline.zone_temporal),
        (pipeline._dynamics_active, pipeline.abl_dynamics),
    ):
        if active and config is not None and (config.initial == "resume") != resume:
            raise ValueError("subframe resume requires all active owners to select resume")


def display(
    pipeline: Pipeline,
    frame: Frame,
    *,
    pts: Fraction,
    duration: Fraction,
    scene_cut: bool = False,
) -> SubframeResult:
    """Prepare candidates and commit all physical histories after successful emission."""
    from tv_sim.subframe import simulate_tick
    from tv_sim.subframe_history import boundary, identity
    from tv_sim.zone_history import geometry

    validate(pipeline)
    if identity(pipeline) != pipeline._subframe_identity:
        raise ValueError("subframe display identity changed; restart history")
    if boundary(pipeline) != pipeline._subframe_boundary:
        raise ValueError("subframe display history changed outside a tick")
    state = pipeline.subframe_state
    if pipeline.subframe.initial == "resume" and not pipeline._subframe_resumed:
        raise ValueError("resume requires a complete validated subframe checkpoint")
    if not isinstance(pts, Fraction) or not isinstance(duration, Fraction) or duration <= 0:
        raise ValueError("subframe pts/duration must be Fraction seconds with positive duration")
    if not math.isfinite(float(duration * 1000)) or not math.isfinite(float(pts)):
        raise ValueError("subframe clock must be finite")
    if state.next_pts is not None and pts != state.next_pts:
        raise ValueError("subframe timestamp gap or out-of-order tick")
    if type(scene_cut) is not bool:
        raise ValueError("scene_cut must be bool")
    content = frame.rgb
    if min(content.shape[:2]) < 1 or not np.isfinite(content).all() or np.any(content < 0):
        raise ValueError("subframe input must be nonempty finite nonnegative float32 RGB nits")
    raster = geometry(content.shape, pipeline)
    if pipeline._subframe_geometry is not None and raster != pipeline._subframe_geometry:
        raise ValueError("subframe geometry changed; start a fresh history")
    profile = pipeline.profile
    requested_apl = demand_apl(content)
    zones = deepcopy(pipeline.zone_state)
    zone_trace = None
    dt_ms = float(duration * 1000)
    if pipeline._zone_active:
        zone_trace = update_zones(
            cast(ZoneBacklightState, zones),
            zone_targets(frame, profile.backlight),
            profile.backlight,
            dt_ms,
            cast(ZoneTemporalConfig, pipeline.zone_temporal),
            scene_cut=scene_cut,
        )
        lit = render_backlight(
            frame, profile.backlight, cast(np.ndarray, cast(ZoneBacklightState, zones).zones_nits)
        )
    else:
        lit = simulate_backlight(frame, profile.backlight)
    steady = simulate_panel(
        lit,
        profile.panel,
        self_emissive=profile.self_emissive,
        peak_nits=profile.backlight.peak_nits,
        psf=emission_psf(profile.backlight) if profile.self_emissive else None,
    )
    capacity = None
    capacity_state = None if pipeline.capacity_state is None else replace(pipeline.capacity_state)
    capacity_trace = None
    if pipeline._dynamics_active:
        apl = requested_apl if profile.hdr.abl_source == "demand" else demand_apl(steady.rgb)
        capacity_trace = target_trace(apl, profile.hdr)
        capacity = update_capacity(
            cast(ABLCapacityState, capacity_state),
            capacity_trace["target_nits"],
            profile.hdr.panel_peak_nits,
            profile.hdr.abl_full_field_nits,
            dt_ms,
            cast(ABLDynamicsConfig, pipeline.abl_dynamics),
        )
        capacity_trace.update(
            after_nits=capacity, ticks=cast(ABLCapacityState, capacity_state).ticks
        )
    mapped = tone_map(steady, profile.hdr, demand_apl_nits=requested_apl, capacity_nits=capacity)
    if profile.self_emissive:
        target = mapped.rgb.astype(np.float64)
        illumination = None
        floor = 0.0
    else:
        illumination = np.asarray(lit.backlight, dtype=np.float64)
        floor = 1 / profile.panel.native_contrast
        transmission = mapped.rgb / np.maximum(illumination[..., None], 1e-8)
        tolerance = 8 * np.finfo(np.float32).eps
        if np.any(transmission < floor - tolerance) or np.any(transmission > 1 + tolerance):
            raise ValueError(
                "HDR steady target is outside physical LCD transmission/leakage bounds"
            )
        target = np.clip(transmission, floor, 1)
    result = simulate_tick(
        target,
        illumination,
        reflected_nits(profile.ambient),
        state,
        pts,
        duration,
        pipeline.subframe,
        self_emissive=profile.self_emissive,
        floor=floor,
    )
    if not np.isfinite(result.mean).all() or np.any(result.mean < 0):
        raise ValueError("subframe produced invalid emission")
    # No mutable transport array is allowed to alias persistent history.
    state.previous = result.endpoint.copy()
    state.next_pts = pts + duration
    state.ticks += 1
    if pipeline._subframe_origin_pts is None:
        pipeline._subframe_origin_pts = pts
    pipeline._subframe_elapsed += duration
    pipeline.zone_state = zones
    pipeline.capacity_state = capacity_state
    pipeline._subframe_geometry = raster
    pipeline._subframe_history_hash = digest(
        {
            "previous": pipeline._subframe_history_hash,
            "source": sha256(content.tobytes()).hexdigest(),
            "pts": str(pts),
            "duration": str(duration),
            "scene_cut": scene_cut,
        }
    )
    pipeline.last_subframe_result = result
    pipeline.last_zone_trace = zone_trace
    pipeline.last_capacity_trace = capacity_trace
    pipeline.last_pre_temporal = mapped
    pipeline._subframe_boundary = boundary(pipeline)
    return result
