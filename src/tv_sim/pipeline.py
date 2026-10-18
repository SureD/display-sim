"""Wire the display stages in plan order.

decode → image processing → backlight / local dimming → panel →
HDR tone map / ABL → ambient reflection → temporal → encode.

The opt-in runtime viewing-angle model runs inside LCD transmission, or as
RGB emission gains on emissive panels, before the panel matrix/mosaic. It
replaces the legacy chroma law only when active. Disabled and zero-angle
configurations retain the original path and arithmetic exactly.

The ABL load is read between image processing and the backlight, on the
picture the content requests: see :mod:`tv_sim.load`.

Opt-in sequence reconstruction is in :mod:`tv_sim.sequence`; the one-image
entry points retain their original timing and behavior.

Not in this pipeline: a spectral or measured subpixel model, CRT and
plasma profiles, and a GPU backend. Overdrive and BFI are optional hooks
with placeholder parameters; duty 1 and overdrive gain 0 leave lag plus
sample-and-hold. The subpixel macro view in :mod:`tv_sim.macro` is a separate
renderer, not a pipeline stage.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from numpy.typing import DTypeLike

from tv_sim.abl_dynamics import (
    ABLCapacityState,
    ABLDynamicsConfig,
    digest,
    finite_number,
    initial_capacity,
    target_trace,
    update_capacity,
    validate_dynamics,
    validate_state,
)
from tv_sim.colorimetry import (
    D65,
    RGB_SPACES,
    ColorimetryConfig,
    PanelColorimetry,
    convert_rgb,
    decode_source,
    gamut_map,
    joint_tone_map,
    panel_luminance,
    rgb_to_xyz_matrix,
    source_to_panel_matrix,
    xyz_to_rgb_matrix,
)
from tv_sim.colorimetry import (
    metadata as colorimetry_metadata,
)
from tv_sim.frame import Frame
from tv_sim.load import LoadState, backlight_derate, demand_apl, smooth_apl
from tv_sim.profile import TVProfile
from tv_sim.stages.ambient import add_ambient
from tv_sim.stages.backlight import simulate_backlight
from tv_sim.stages.decode import decode_encoded
from tv_sim.stages.encode import encode_frame
from tv_sim.stages.panel import emission_psf, simulate_panel
from tv_sim.stages.process import process_image
from tv_sim.stages.temporal import TemporalState, apply_temporal
from tv_sim.stages.tonemap import tone_map
from tv_sim.viewing_angle import (
    AngularParams,
    ViewingAngleConfig,
    angular_parameters,
    validate_angular_path,
)
from tv_sim.zone_temporal import ZoneBacklightState, ZoneTemporalConfig

if TYPE_CHECKING:
    from fractions import Fraction

    from tv_sim.sequence import MotionConfig, SequenceOutput
    from tv_sim.subframe import SubframeConfig, SubframeResult, SubframeState


class Pipeline:
    """One TV profile and the state that persists across frames.

    The legacy histories are panel level and smoothed demand APL. The
    optional capacity controller owns a separate scalar and leaves legacy
    APL history untouched. It cannot be enabled/disabled within a history.

    ``viewing_angle`` and optional synthetic ``angular_params`` are separate
    runtime controls; neither changes the profile or loads a fitted dataset.
    ``abl_dynamics`` is also separate and defaults off; its taus are explicit
    P inputs. Complete checkpoint restoration requires ``initial='resume'``.
    ``zone_temporal`` instead owns float64 LCD zone commands before optics;
    its controller is separate from the persistent emitted-RGB pixel response.
    """

    last_colorimetry_diagnostics: dict[str, Any] | None
    last_capacity_trace: dict[str, Any] | None
    last_pre_temporal: Frame | None
    _capacity_geometry: dict[str, Any] | None
    _capacity_source_hash: str | None
    last_zone_trace: dict[str, Any] | None
    _zone_geometry: dict[str, Any] | None
    _zone_source_hash: str | None
    subframe: SubframeConfig
    _initial_subframe: SubframeConfig
    subframe_state: SubframeState
    last_subframe_result: SubframeResult | None
    _subframe_geometry: dict[str, Any] | None
    _subframe_origin_pts: Fraction | None
    _subframe_elapsed: Fraction
    _subframe_resumed: bool
    _subframe_initialization: dict[str, Any]
    _subframe_identity: dict[str, Any]
    _subframe_boundary: str
    _subframe_history_hash: str

    def __init__(
        self,
        profile: TVProfile,
        state: TemporalState | None = None,
        load_state: LoadState | None = None,
        *,
        viewing_angle: ViewingAngleConfig | None = None,
        angular_params: AngularParams | None = None,
        abl_dynamics: ABLDynamicsConfig | None = None,
        capacity_state: ABLCapacityState | None = None,
        colorimetry: ColorimetryConfig | None = None,
        panel_colorimetry: PanelColorimetry | None = None,
        zone_temporal: ZoneTemporalConfig | None = None,
        zone_state: ZoneBacklightState | None = None,
        subframe: SubframeConfig | None = None,
    ) -> None:
        self._subframe_active = False
        self.profile = profile
        self.colorimetry = colorimetry if colorimetry is not None else ColorimetryConfig()
        self._initial_colorimetry = self.colorimetry
        self.panel_colorimetry = panel_colorimetry
        self._colorimetry_active = self.colorimetry.active
        self.state = state if state is not None else TemporalState()
        self.load_state = load_state if load_state is not None else LoadState()
        self.viewing_angle = viewing_angle if viewing_angle is not None else ViewingAngleConfig()
        self.angular_params = angular_params
        if self.viewing_angle.active:
            self.angular_params = (
                angular_params if angular_params is not None else angular_parameters(profile)
            )
            validate_angular_path(
                self.viewing_angle,
                self.angular_params,
                self_emissive=profile.self_emissive,
                contrast=profile.panel.native_contrast,
            )
        if self._colorimetry_active:
            if self.panel_colorimetry is None:
                from tv_sim.colorimetry_provenance import panel_parameters

                self.panel_colorimetry = panel_parameters(profile)
            matrix = np.asarray(profile.panel.color_matrix, dtype=np.float64)
            if matrix.size != 9 or not np.array_equal(matrix.reshape(3, 3), np.eye(3)):
                raise ValueError("M15 colorimetry requires an identity legacy color_matrix")
            if not self.viewing_angle.active and profile.panel.viewing_angle_deg != 0:
                raise ValueError("M15 colorimetry requires M10 for nonzero viewing angle")
            if profile.hdr.abl_power_budget_nits != 0 or profile.hdr.abl_backlight_tracking != 0:
                raise ValueError(
                    "M15 joint capacity conflicts with channel-power/backlight-tracking limiters"
                )
            if profile.hdr.tone_map != "soft_clip":
                raise ValueError("M15 colorimetry requires soft_clip tone mapper")
            self._source_to_panel = source_to_panel_matrix(self.colorimetry, self.panel_colorimetry)
            self._source_y = rgb_to_xyz_matrix(
                RGB_SPACES[self.colorimetry.source_primaries], self.colorimetry.source_white_xy
            )[1]
            self.last_colorimetry_diagnostics = None
        elif panel_colorimetry is not None:
            raise ValueError("panel_colorimetry requires active M15 colorimetry")
        self._initial_panel_colorimetry = self.panel_colorimetry
        self.abl_dynamics = abl_dynamics
        self._initial_abl_dynamics = abl_dynamics
        self._dynamics_active = abl_dynamics is not None and abl_dynamics.active
        self.zone_temporal = zone_temporal
        self._initial_zone_temporal = zone_temporal
        self._zone_active = zone_temporal is not None and zone_temporal.active
        self.zone_state: ZoneBacklightState | None = None
        if self._zone_active and self._dynamics_active:
            raise ValueError("zone temporal dynamics conflicts with active M13 capacity dynamics")
        self.capacity_state = None
        if self._dynamics_active:
            from tv_sim.abl_history import boundary

            abl_dynamics = cast(ABLDynamicsConfig, abl_dynamics)
            validate_dynamics(profile, abl_dynamics)
            candidate = capacity_state if capacity_state is not None else ABLCapacityState()
            validate_state(candidate, profile.hdr.panel_peak_nits, profile.hdr.abl_full_field_nits)
            if candidate.ticks or candidate.elapsed_ms:
                raise ValueError(
                    "stale capacity_state: restore a complete checkpoint for continuation"
                )
            if candidate.capacity_nits is not None and (
                abl_dynamics.initial != "explicit"
                or candidate.capacity_nits != abl_dynamics.initial_capacity_nits
            ):
                raise ValueError("capacity-only state requires matching explicit initialization")
            self.capacity_state = candidate
            self._capacity_geometry = None
            self._capacity_resumed = False
            self._capacity_initialization = {
                "policy": abl_dynamics.initial,
                "capacity_nits": abl_dynamics.initial_capacity_nits,
                "evidence": "P",
            }
            self._capacity_boundary = boundary(self)
            if self.state.previous is not None or self.load_state.apl_nits is not None:
                self._capacity_initialization["supplied_partial_history_sha256"] = (
                    self._capacity_boundary
                )
            self._capacity_history_hash = digest(
                {
                    "initialization": self._capacity_initialization,
                    "initial_boundary": self._capacity_boundary,
                }
            )
            self._capacity_source_hash = None
            self.last_capacity_trace = None
            self.last_pre_temporal = None
            self._capacity_identity = self.identity()
        elif capacity_state is not None:
            raise ValueError("capacity_state requires active ABL dynamics")
        if self._zone_active:
            from tv_sim.zone_history import boundary as zone_boundary
            from tv_sim.zone_temporal import validate_path
            from tv_sim.zone_temporal import validate_state as validate_zone_state

            zone_temporal = cast(ZoneTemporalConfig, zone_temporal)
            validate_path(profile, zone_temporal)
            candidate_zone = zone_state if zone_state is not None else ZoneBacklightState()
            validate_zone_state(candidate_zone, profile.backlight)
            if (
                candidate_zone.ticks
                or candidate_zone.elapsed_ms
                or candidate_zone.previous_targets is not None
            ):
                raise ValueError("stale zone_state: restore a complete checkpoint for continuation")
            if candidate_zone.zones_nits is not None and (
                zone_temporal.initial != "explicit"
                or zone_temporal.initial_zones_nits is None
                or not np.array_equal(candidate_zone.zones_nits, zone_temporal.initial_zones_nits)
            ):
                raise ValueError("zone-only state requires matching explicit initialization")
            if zone_temporal.initial == "resume" and (
                self.state.previous is not None or self.load_state.apl_nits is not None
            ):
                raise ValueError("zone resume requires a complete checkpoint as sole history owner")
            self.zone_state = candidate_zone
            self._zone_geometry = None
            self._zone_resumed = False
            self._zone_initialization: dict[str, Any] = {
                "policy": zone_temporal.initial,
                "zones_nits": None
                if zone_temporal.initial_zones_nits is None
                else [list(row) for row in zone_temporal.initial_zones_nits],
                "evidence": "P",
            }
            self._zone_boundary = zone_boundary(self)
            if self.state.previous is not None or self.load_state.apl_nits is not None:
                self._zone_initialization["supplied_partial_history_sha256"] = self._zone_boundary
            self._zone_history_hash = digest(
                {
                    "initialization": self._zone_initialization,
                    "initial_boundary": self._zone_boundary,
                }
            )
            self._zone_source_hash = None
            self.last_zone_trace = None
            self.last_pre_temporal = None
            self._zone_identity = self.identity()
        elif zone_state is not None:
            raise ValueError("zone_state requires active zone temporal dynamics")
        from tv_sim.subframe_pipeline import initialize

        initialize(self, subframe)

    def run_linear(self, encoded: np.ndarray) -> Frame:
        """Run all stages except encode; active M15 RGB uses the declared panel basis."""

        return self.display_content(self.prepare_content(encoded))

    def prepare_content(self, encoded: np.ndarray) -> Frame:
        """Decode/process in the source basis, without advancing display histories."""

        frame = (
            decode_source(encoded, self.profile.input, self.colorimetry)
            if self._colorimetry_active
            else decode_encoded(encoded, self.profile.input)
        )
        return process_image(frame, self.profile.processing)

    def display_content(
        self,
        frame: Frame,
        *,
        frame_time_ms: float | None = None,
        timestamp_ms: float | None = None,
        scene_cut: bool = False,
    ) -> Frame:
        """Display prepared linear-nit content once; never decode/sharpen it again.

        Sequence callers provide the output tick duration for both panel and
        load dynamics. The legacy entry point uses the original profile object.
        """

        if self.abl_dynamics is not self._initial_abl_dynamics:
            raise ValueError("changing ABL dynamics mode/config requires a fresh Pipeline history")
        if self.zone_temporal is not self._initial_zone_temporal:
            raise ValueError("changing zone dynamics mode/config requires a fresh Pipeline history")
        if (
            self.colorimetry != self._initial_colorimetry
            or self.panel_colorimetry != self._initial_panel_colorimetry
        ):
            raise ValueError("changing colorimetry requires a fresh Pipeline history")
        if self.subframe is not self._initial_subframe:
            raise ValueError("changing subframe configuration requires a fresh Pipeline history")
        if self._subframe_active:
            from fractions import Fraction

            from tv_sim.subframe_pipeline import display

            duration = (
                Fraction(
                    str(
                        self.profile.temporal.frame_time_ms
                        if frame_time_ms is None
                        else frame_time_ms
                    )
                )
                / 1000
            )
            pts = self.subframe_state.next_pts or Fraction(0)
            if timestamp_ms is not None:
                pts = Fraction(str(timestamp_ms)) / 1000
            result = display(self, frame, pts=pts, duration=duration, scene_cut=scene_cut)
            return Frame(result.mean)
        if self._dynamics_active:
            return self._display_capacity(
                frame, frame_time_ms=frame_time_ms, timestamp_ms=timestamp_ms
            )
        if self._zone_active:
            return self._display_zones(
                frame, frame_time_ms=frame_time_ms, timestamp_ms=timestamp_ms, scene_cut=scene_cut
            )
        profile = self.profile
        temporal = profile.temporal
        if frame_time_ms is not None:
            temporal = replace(temporal, frame_time_ms=frame_time_ms)
        # The requested picture, before the panel and before any limiting.
        # docs/research/m3-hdr-abl-params.md requires the load to be read here.
        apl = smooth_apl(
            self.load_state,
            self._source_apl(frame.rgb) if self._colorimetry_active else demand_apl(frame.rgb),
            profile.hdr,
            temporal.frame_time_ms,
        )
        if self._colorimetry_active:
            frame = self._convert_colorimetry(frame)
        frame = simulate_backlight(
            frame,
            profile.backlight,
            peak_scale=backlight_derate(apl, profile.hdr),
        )
        frame = simulate_panel(
            frame,
            profile.panel,
            self_emissive=profile.self_emissive,
            peak_nits=profile.backlight.peak_nits,
            psf=emission_psf(profile.backlight) if profile.self_emissive else None,
            viewing_angle=self.viewing_angle,
            angular_params=self.angular_params,
            defer_emissive_peak=self._colorimetry_active,
        )
        if self._colorimetry_active:
            from tv_sim.load import abl_capacity

            load = (
                apl
                if str(profile.hdr.abl_source).lower() == "demand"
                else self._panel_apl(frame.rgb)
            )
            if str(profile.hdr.abl_source).lower() not in ("demand", "emitted"):
                raise ValueError("unknown abl_source; use demand or emitted")
            frame, diagnostics = joint_tone_map(
                frame,
                profile.hdr,
                cast(PanelColorimetry, self.panel_colorimetry),
                capacity_nits=abl_capacity(load, profile.hdr),
            )
            cast(dict, self.last_colorimetry_diagnostics).update(diagnostics)
        else:
            frame = tone_map(frame, profile.hdr, demand_apl_nits=apl)
        frame = add_ambient(frame, profile.ambient)
        return apply_temporal(frame, temporal, self.state)

    def _display_zones(
        self,
        frame: Frame,
        *,
        frame_time_ms: float | None,
        timestamp_ms: float | None,
        scene_cut: bool,
    ) -> Frame:
        """One zone owner; commit zone/load/pixel history after a valid tick."""
        from hashlib import sha256

        from tv_sim.zone_history import boundary as zone_boundary
        from tv_sim.zone_history import geometry as zone_geometry
        from tv_sim.zone_temporal import render_backlight, update_zones, validate_path, zone_targets
        from tv_sim.zone_temporal import validate_state as validate_zone_state

        profile, config = self.profile, cast(ZoneTemporalConfig, self.zone_temporal)
        validate_path(profile, config)
        if type(scene_cut) is not bool:
            raise ValueError("scene_cut must be bool")
        if self.identity() != self._zone_identity:
            raise ValueError(
                "profile/config/angle/colorimetry identity changed; restart zone history"
            )
        state = cast(ZoneBacklightState, self.zone_state)
        validate_zone_state(state, profile.backlight)
        if zone_boundary(self) != self._zone_boundary:
            raise ValueError(
                "display history changed outside a tick; restore a complete checkpoint"
            )
        if config.initial == "resume" and not self._zone_resumed:
            raise ValueError("resume requires a complete validated zone checkpoint")
        dt = finite_number(
            profile.temporal.frame_time_ms if frame_time_ms is None else frame_time_ms,
            "frame_time_ms",
        )
        if dt <= 0:
            raise ValueError("frame_time_ms must be positive")
        if timestamp_ms is not None and not math.isclose(
            finite_number(timestamp_ms, "timestamp_ms"),
            state.elapsed_ms,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "timestamp gap or out-of-order tick: supply explicit held/black intervals"
            )
        if (
            frame.rgb.dtype != np.float32
            or not np.isfinite(frame.rgb).all()
            or np.any(frame.rgb < 0)
            or min(frame.rgb.shape[:2]) < 1
        ):
            raise ValueError(
                "zone input must have finite nonnegative float32 RGB nits and nonempty geometry"
            )
        geometry = zone_geometry(frame.rgb.shape, self)
        if self._zone_geometry is not None and geometry != self._zone_geometry:
            raise ValueError("geometry/dtype changed; restart zone history")
        previous = self.state.previous
        if previous is not None and (
            previous.shape != frame.rgb.shape
            or previous.dtype != np.float32
            or not np.isfinite(previous).all()
            or np.any(previous < 0)
        ):
            raise ValueError("panel history geometry/dtype/values do not match zone history")
        if (
            self.load_state.apl_nits is not None
            and finite_number(self.load_state.apl_nits, "load APL") < 0
        ):
            raise ValueError("load history must be finite nonnegative APL")
        load = LoadState(self.load_state.apl_nits)
        requested_apl = smooth_apl(
            load,
            self._source_apl(frame.rgb) if self._colorimetry_active else demand_apl(frame.rgb),
            profile.hdr,
            dt,
        )
        old_diagnostics = getattr(self, "last_colorimetry_diagnostics", None)
        panel = self._convert_colorimetry(frame) if self._colorimetry_active else frame
        diagnostics = getattr(self, "last_colorimetry_diagnostics", None)
        if self._colorimetry_active:
            self.last_colorimetry_diagnostics = old_diagnostics
        candidate = ZoneBacklightState(
            None if state.zones_nits is None else state.zones_nits.copy(),
            None if state.previous_targets is None else state.previous_targets.copy(),
            state.elapsed_ms,
            state.ticks,
        )
        trace = update_zones(
            candidate,
            zone_targets(panel, profile.backlight),
            profile.backlight,
            dt,
            config,
            scene_cut=scene_cut,
        )
        panel = render_backlight(panel, profile.backlight, cast(np.ndarray, candidate.zones_nits))
        panel = simulate_panel(
            panel,
            profile.panel,
            self_emissive=False,
            peak_nits=profile.backlight.peak_nits,
            viewing_angle=self.viewing_angle,
            angular_params=self.angular_params,
        )
        if self._colorimetry_active:
            from tv_sim.load import abl_capacity

            source = str(profile.hdr.abl_source).lower()
            if source not in ("demand", "emitted"):
                raise ValueError("unknown abl_source; use demand or emitted")
            mapped, volume_diagnostics = joint_tone_map(
                panel,
                profile.hdr,
                cast(PanelColorimetry, self.panel_colorimetry),
                capacity_nits=abl_capacity(
                    requested_apl if source == "demand" else self._panel_apl(panel.rgb), profile.hdr
                ),
            )
            cast(dict, diagnostics).update(volume_diagnostics)
        else:
            mapped = tone_map(panel, profile.hdr, demand_apl_nits=requested_apl)
        pre_temporal = add_ambient(mapped, profile.ambient)
        temporal_state = TemporalState(previous)
        result = apply_temporal(
            pre_temporal, replace(profile.temporal, frame_time_ms=dt), temporal_state
        )
        if not np.isfinite(result.rgb).all() or np.any(result.rgb < 0):
            raise ValueError("zone display produced invalid output")
        source_hash = sha256(np.ascontiguousarray(frame.rgb).tobytes()).hexdigest()
        history_hash = digest(
            {
                "previous": self._zone_history_hash,
                "source": source_hash,
                "dt_ms_hex": dt.hex(),
                "scene_cut": scene_cut,
                "geometry": geometry,
            }
        )
        state.zones_nits, state.previous_targets = candidate.zones_nits, candidate.previous_targets
        state.elapsed_ms, state.ticks = candidate.elapsed_ms, candidate.ticks
        self.state.previous = temporal_state.previous
        self.load_state.apl_nits = load.apl_nits
        self._zone_geometry = geometry
        self._zone_source_hash, self._zone_history_hash = source_hash, history_hash
        self._zone_boundary = zone_boundary(self)
        self.last_zone_trace, self.last_pre_temporal = trace, pre_temporal
        if self._colorimetry_active:
            self.last_colorimetry_diagnostics = diagnostics
        return result

    def _display_capacity(
        self, frame: Frame, *, frame_time_ms: float | None, timestamp_ms: float | None
    ) -> Frame:
        """One capacity owner; commit both histories only after a valid tick."""
        from hashlib import sha256

        from tv_sim.abl_history import boundary

        profile, config = self.profile, cast(ABLDynamicsConfig, self.abl_dynamics)
        validate_dynamics(profile, config)
        if self.identity() != self._capacity_identity:
            raise ValueError("profile/config/angle identity changed; restart the display history")
        state = cast(ABLCapacityState, self.capacity_state)
        validate_state(state, profile.hdr.panel_peak_nits, profile.hdr.abl_full_field_nits)
        if boundary(self) != self._capacity_boundary:
            raise ValueError(
                "display history changed outside a tick; restart or restore a complete checkpoint"
            )
        if config.initial == "resume" and not self._capacity_resumed:
            raise ValueError("resume requires a complete validated checkpoint")
        dt = profile.temporal.frame_time_ms if frame_time_ms is None else frame_time_ms
        dt = finite_number(dt, "frame_time_ms")
        if dt <= 0:
            raise ValueError("frame_time_ms must be positive")
        if timestamp_ms is not None:
            time = finite_number(timestamp_ms, "timestamp_ms")
            if not math.isclose(time, state.elapsed_ms, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(
                    "timestamp gap or out-of-order tick: supply explicit held/black intervals"
                )
        geometry = {"shape": list(frame.rgb.shape), "dtype": frame.rgb.dtype.str}
        if self._capacity_geometry is not None and geometry != self._capacity_geometry:
            raise ValueError("geometry/dtype changed; restart the display history")
        if (
            frame.rgb.dtype != np.float32
            or not np.isfinite(frame.rgb).all()
            or np.any(frame.rgb < 0)
            or min(frame.rgb.shape[:2]) < 1
        ):
            raise ValueError(
                "capacity input must have finite nonnegative float32 RGB nits and nonempty geometry"
            )
        if self.state.previous is not None and (
            self.state.previous.shape != frame.rgb.shape
            or self.state.previous.dtype != np.float32
            or not np.isfinite(self.state.previous).all()
            or np.any(self.state.previous < 0)
        ):
            raise ValueError("panel history geometry/dtype or values do not match capacity history")
        requested_apl = (
            self._source_apl(frame.rgb) if self._colorimetry_active else demand_apl(frame.rgb)
        )
        panel = self._convert_colorimetry(frame) if self._colorimetry_active else frame
        panel = simulate_backlight(panel, profile.backlight)
        panel = simulate_panel(
            panel,
            profile.panel,
            self_emissive=profile.self_emissive,
            peak_nits=profile.backlight.peak_nits,
            psf=emission_psf(profile.backlight),
            viewing_angle=self.viewing_angle,
            angular_params=self.angular_params,
            defer_emissive_peak=self._colorimetry_active,
        )
        emitted_apl = (
            self._panel_apl(panel.rgb) if self._colorimetry_active else demand_apl(panel.rgb)
        )
        apl = requested_apl if str(profile.hdr.abl_source).lower() == "demand" else emitted_apl
        trace = target_trace(apl, profile.hdr)
        candidate = replace(state)
        before = initial_capacity(
            candidate, trace["target_nits"], profile.hdr.panel_peak_nits, config
        )
        capacity = update_capacity(
            candidate,
            trace["target_nits"],
            profile.hdr.panel_peak_nits,
            profile.hdr.abl_full_field_nits,
            dt,
            config,
        )
        if self._colorimetry_active:
            mapped, diagnostics = joint_tone_map(
                panel,
                profile.hdr,
                cast(PanelColorimetry, self.panel_colorimetry),
                capacity_nits=capacity,
            )
            cast(dict, self.last_colorimetry_diagnostics).update(diagnostics)
        else:
            mapped = tone_map(panel, profile.hdr, capacity_nits=capacity)
        pre_temporal = add_ambient(mapped, profile.ambient)
        temporal_state = TemporalState(self.state.previous)
        temporal = replace(profile.temporal, frame_time_ms=dt)
        result = apply_temporal(pre_temporal, temporal, temporal_state)
        if not np.isfinite(result.rgb).all():
            raise ValueError("capacity display produced nonfinite output")
        source_hash = sha256(np.ascontiguousarray(frame.rgb).tobytes()).hexdigest()
        history_hash = digest(
            {
                "previous": self._capacity_history_hash,
                "source": source_hash,
                "dt_ms_hex": dt.hex(),
                "geometry": geometry,
            }
        )
        trace.update(
            before_nits=before,
            after_nits=capacity,
            branch="attack"
            if trace["target_nits"] < before
            else "release"
            if trace["target_nits"] > before
            else "equal",
            attack_ms=config.attack_ms,
            release_ms=config.release_ms,
            dt_ms=dt,
            elapsed_ms=candidate.elapsed_ms,
            ticks=candidate.ticks,
        )
        state.capacity_nits, state.elapsed_ms, state.ticks = (
            candidate.capacity_nits,
            candidate.elapsed_ms,
            candidate.ticks,
        )
        self.state.previous = temporal_state.previous
        self._capacity_geometry = geometry
        self._capacity_source_hash, self._capacity_history_hash = source_hash, history_hash
        self._capacity_boundary = boundary(self)
        self.last_capacity_trace = trace
        self.last_pre_temporal = pre_temporal
        return result

    def identity(self) -> dict:
        """Effective profile/controller/target/angle fingerprints, active only."""
        if self._subframe_active:
            from tv_sim.subframe_history import identity as subframe_identity

            return subframe_identity(self)
        if self._zone_active:
            from tv_sim.zone_history import identity as zone_identity

            return zone_identity(self)
        from tv_sim.abl_history import identity

        return identity(self)

    def checkpoint(self) -> dict:
        """Exact full display history at a successful active tick boundary."""
        if self._subframe_active:
            from tv_sim.subframe_history import checkpoint as subframe_checkpoint

            return subframe_checkpoint(self)
        if self._zone_active:
            from tv_sim.zone_history import checkpoint as zone_checkpoint

            return zone_checkpoint(self)
        from tv_sim.abl_history import checkpoint

        return checkpoint(self)

    def restore_checkpoint(
        self,
        data: dict,
        *,
        shape: tuple[int, ...] | None = None,
        dtype: DTypeLike | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        """Validate a full checkpoint, then restore atomically with resume policy."""
        if self._subframe_active:
            from tv_sim.subframe_history import restore_checkpoint as restore_subframe_checkpoint

            restore_subframe_checkpoint(self, data, shape=shape, dtype=dtype, elapsed_ms=elapsed_ms)
            return
        if self._zone_active:
            from tv_sim.zone_history import restore_checkpoint as restore_zone_checkpoint

            restore_zone_checkpoint(self, data, shape=shape, dtype=dtype, elapsed_ms=elapsed_ms)
            return
        from tv_sim.abl_history import restore_checkpoint

        restore_checkpoint(self, data, shape=shape, dtype=dtype, elapsed_ms=elapsed_ms)

    def display_subframes(
        self,
        frame: Frame,
        *,
        pts: Fraction,
        duration: Fraction,
        scene_cut: bool = False,
    ) -> SubframeResult:
        """Resolve one prepared tick on an explicit rational clock (seconds)."""
        from tv_sim.subframe_pipeline import display

        return display(self, frame, pts=pts, duration=duration, scene_cut=scene_cut)

    def run_sequence(
        self,
        encoded_frames: Iterable[np.ndarray],
        config: MotionConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[SequenceOutput]:
        """Run an explicitly configured sequence; default is the legacy bypass.

        Optional ``source_pts``, ``last_duration``, ``cuts`` (indices with a
        cut before them), and per-pair ``scenes`` are documented in
        :func:`tv_sim.sequence.render_sequence`.
        """

        from tv_sim.sequence import render_sequence

        return render_sequence(self, encoded_frames, config, **kwargs)

    def run(self, encoded: np.ndarray) -> np.ndarray:
        """Return a ``uint8`` preview image."""

        frame = self.run_linear(encoded)
        if self._colorimetry_active:
            frame = Frame(self.output_in_space(frame, "bt709"), frame.backlight)
        return encode_frame(frame, self.profile.output)

    def _source_apl(self, rgb: np.ndarray) -> float:
        return float(np.mean(np.asarray(rgb, dtype=np.float64) @ self._source_y, dtype=np.float64))

    def _panel_apl(self, rgb: np.ndarray) -> float:
        return float(
            np.mean(
                panel_luminance(rgb, cast(PanelColorimetry, self.panel_colorimetry)),
                dtype=np.float64,
            )
        )

    def _convert_colorimetry(self, frame: Frame) -> Frame:
        converted = convert_rgb(frame.rgb, self._source_to_panel)
        rgb, diagnostics = gamut_map(
            converted,
            cast(PanelColorimetry, self.panel_colorimetry),
            self.colorimetry.gamut_mapping,
            self.colorimetry.compression_knee,
        )
        self.last_colorimetry_diagnostics = diagnostics
        return Frame(rgb, frame.backlight)

    def colorimetry_metadata(self) -> dict:
        """Explicit source/panel/mapping declarations for an active M15 output."""

        if not self._colorimetry_active:
            raise ValueError("colorimetry metadata requires active M15 colorimetry")
        return colorimetry_metadata(
            self.colorimetry, cast(PanelColorimetry, self.panel_colorimetry)
        )

    def output_in_space(self, frame: Frame, space: str) -> np.ndarray:
        """Signed linear XYZ or named RGB coordinates, without a preview clamp."""

        if not self._colorimetry_active:
            raise ValueError("declared output space requires active M15 colorimetry")
        panel_colorimetry = cast(PanelColorimetry, self.panel_colorimetry)
        panel = rgb_to_xyz_matrix(panel_colorimetry.primaries_xy, panel_colorimetry.white_xy)
        if space == "xyz":
            matrix = panel
        elif space in RGB_SPACES:
            matrix = xyz_to_rgb_matrix(RGB_SPACES[space], D65) @ panel
        else:
            raise ValueError("output color space must be xyz, bt709, display_p3, or bt2020")
        return convert_rgb(frame.rgb, matrix)
