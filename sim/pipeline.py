"""Wire the display stages in plan order.

decode → image processing → backlight / local dimming → panel →
HDR tone map / ABL → ambient reflection → temporal → encode.

The opt-in runtime viewing-angle model runs inside LCD transmission, or as
RGB emission gains on emissive panels, before the panel matrix/mosaic. It
replaces the legacy chroma law only when active. Disabled and zero-angle
configurations retain the original path and arithmetic exactly.

The ABL load is read between image processing and the backlight, on the
picture the content requests: see :mod:`sim.load`.

Opt-in sequence reconstruction is in :mod:`sim.sequence`; the one-image
entry points retain their original timing and behavior.

Not in this pipeline: a spectral or measured subpixel model, CRT and
plasma profiles, and a GPU backend. Overdrive and BFI are optional hooks
with placeholder parameters; duty 1 and overdrive gain 0 leave lag plus
sample-and-hold. The subpixel macro view in :mod:`sim.macro` is a separate
renderer, not a pipeline stage.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import TYPE_CHECKING, Iterable, Iterator

import numpy as np

from sim.abl_dynamics import (
    ABLCapacityState, ABLDynamicsConfig, digest, finite_number, initial_capacity,
    target_trace, update_capacity, validate_dynamics, validate_state,
)
from sim.frame import Frame
from sim.load import LoadState, backlight_derate, demand_apl, smooth_apl
from sim.profile import TVProfile
from sim.stages.ambient import add_ambient
from sim.stages.backlight import simulate_backlight
from sim.stages.decode import decode_encoded
from sim.stages.encode import encode_frame
from sim.stages.panel import emission_psf, simulate_panel
from sim.stages.process import process_image
from sim.stages.temporal import TemporalState, apply_temporal
from sim.stages.tonemap import tone_map
from sim.viewing_angle import (
    AngularParams, ViewingAngleConfig, angular_parameters, validate_angular_path,
)

if TYPE_CHECKING:
    from sim.sequence import MotionConfig, SequenceOutput


class Pipeline:
    """One TV profile and the state that persists across frames.

    The legacy histories are panel level and smoothed demand APL. The
    optional capacity controller owns a separate scalar and leaves legacy
    APL history untouched. It cannot be enabled/disabled within a history.

    ``viewing_angle`` and optional synthetic ``angular_params`` are separate
    runtime controls; neither changes the profile or loads a fitted dataset.
    ``abl_dynamics`` is also separate and defaults off; its taus are explicit
    P inputs. Complete checkpoint restoration requires ``initial='resume'``.
    """

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
    ):
        self.profile = profile
        self.state = state if state is not None else TemporalState()
        self.load_state = load_state if load_state is not None else LoadState()
        self.viewing_angle = viewing_angle if viewing_angle is not None else ViewingAngleConfig()
        self.angular_params = angular_params
        if self.viewing_angle.active:
            self.angular_params = angular_params if angular_params is not None else angular_parameters(profile)
            validate_angular_path(self.viewing_angle, self.angular_params,
                                  self_emissive=profile.self_emissive,
                                  contrast=profile.panel.native_contrast)
        self.abl_dynamics = abl_dynamics
        self._initial_abl_dynamics = abl_dynamics
        self._dynamics_active = abl_dynamics is not None and abl_dynamics.active
        self.capacity_state = None
        if self._dynamics_active:
            from sim.abl_history import boundary

            validate_dynamics(profile, abl_dynamics)
            candidate = capacity_state if capacity_state is not None else ABLCapacityState()
            validate_state(candidate, profile.hdr.panel_peak_nits, profile.hdr.abl_full_field_nits)
            if candidate.ticks or candidate.elapsed_ms:
                raise ValueError("stale capacity_state: restore a complete checkpoint for continuation")
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
                "capacity_nits": abl_dynamics.initial_capacity_nits, "evidence": "P",
            }
            self._capacity_boundary = boundary(self)
            if self.state.previous is not None or self.load_state.apl_nits is not None:
                self._capacity_initialization["supplied_partial_history_sha256"] = self._capacity_boundary
            self._capacity_history_hash = digest({"initialization": self._capacity_initialization,
                                                  "initial_boundary": self._capacity_boundary})
            self._capacity_source_hash = None
            self.last_capacity_trace = None
            self.last_pre_temporal = None
            self._capacity_identity = self.identity()
        elif capacity_state is not None:
            raise ValueError("capacity_state requires active ABL dynamics")

    def run_linear(self, encoded: np.ndarray) -> Frame:
        """Run every stage except output encode. RGB is linear nits."""

        return self.display_content(self.prepare_content(encoded))

    def prepare_content(self, encoded: np.ndarray) -> Frame:
        """Decode and spatially process one source, without advancing histories."""

        frame = decode_encoded(encoded, self.profile.input)
        return process_image(frame, self.profile.processing)

    def display_content(self, frame: Frame, *, frame_time_ms: float | None = None,
                        timestamp_ms: float | None = None) -> Frame:
        """Display prepared linear-nit content once; never decode/sharpen it again.

        Sequence callers provide the output tick duration for both panel and
        load dynamics. The legacy entry point uses the original profile object.
        """

        if self.abl_dynamics is not self._initial_abl_dynamics:
            raise ValueError("changing ABL dynamics mode/config requires a fresh Pipeline history")
        if self._dynamics_active:
            return self._display_capacity(frame, frame_time_ms=frame_time_ms,
                                          timestamp_ms=timestamp_ms)
        profile = self.profile
        temporal = profile.temporal
        if frame_time_ms is not None:
            temporal = replace(temporal, frame_time_ms=frame_time_ms)
        # The requested picture, before the panel and before any limiting.
        # research/m3-hdr-abl-params.md requires the load to be read here.
        apl = smooth_apl(
            self.load_state,
            demand_apl(frame.rgb),
            profile.hdr,
            temporal.frame_time_ms,
        )
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
        )
        frame = tone_map(frame, profile.hdr, demand_apl_nits=apl)
        frame = add_ambient(frame, profile.ambient)
        return apply_temporal(frame, temporal, self.state)

    def _display_capacity(self, frame: Frame, *, frame_time_ms, timestamp_ms) -> Frame:
        """One capacity owner; commit both histories only after a valid tick."""
        from hashlib import sha256
        from sim.abl_history import boundary

        profile, config = self.profile, self.abl_dynamics
        validate_dynamics(profile, config)
        if self.identity() != self._capacity_identity:
            raise ValueError("profile/config/angle identity changed; restart the display history")
        state = self.capacity_state
        validate_state(state, profile.hdr.panel_peak_nits, profile.hdr.abl_full_field_nits)
        if boundary(self) != self._capacity_boundary:
            raise ValueError("display history changed outside a tick; restart or restore a complete checkpoint")
        if config.initial == "resume" and not self._capacity_resumed:
            raise ValueError("resume requires a complete validated checkpoint")
        dt = profile.temporal.frame_time_ms if frame_time_ms is None else frame_time_ms
        dt = finite_number(dt, "frame_time_ms")
        if dt <= 0:
            raise ValueError("frame_time_ms must be positive")
        if timestamp_ms is not None:
            time = finite_number(timestamp_ms, "timestamp_ms")
            if not math.isclose(time, state.elapsed_ms, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError("timestamp gap or out-of-order tick: supply explicit held/black intervals")
        geometry = {"shape": list(frame.rgb.shape), "dtype": frame.rgb.dtype.str}
        if self._capacity_geometry is not None and geometry != self._capacity_geometry:
            raise ValueError("geometry/dtype changed; restart the display history")
        if (frame.rgb.dtype != np.float32 or not np.isfinite(frame.rgb).all() or np.any(frame.rgb < 0)
                or min(frame.rgb.shape[:2]) < 1):
            raise ValueError("capacity input must have finite nonnegative float32 RGB nits and nonempty geometry")
        if self.state.previous is not None and (
            self.state.previous.shape != frame.rgb.shape or self.state.previous.dtype != np.float32
            or not np.isfinite(self.state.previous).all() or np.any(self.state.previous < 0)
        ):
            raise ValueError("panel history geometry/dtype or values do not match capacity history")
        requested_apl = demand_apl(frame.rgb)
        panel = simulate_backlight(frame, profile.backlight)
        panel = simulate_panel(
            panel, profile.panel, self_emissive=profile.self_emissive,
            peak_nits=profile.backlight.peak_nits, psf=emission_psf(profile.backlight),
            viewing_angle=self.viewing_angle, angular_params=self.angular_params,
        )
        apl = requested_apl if str(profile.hdr.abl_source).lower() == "demand" else demand_apl(panel.rgb)
        trace = target_trace(apl, profile.hdr)
        candidate = replace(state)
        before = initial_capacity(candidate, trace["target_nits"], profile.hdr.panel_peak_nits, config)
        capacity = update_capacity(candidate, trace["target_nits"], profile.hdr.panel_peak_nits,
                                   profile.hdr.abl_full_field_nits, dt, config)
        mapped = tone_map(panel, profile.hdr, capacity_nits=capacity)
        pre_temporal = add_ambient(mapped, profile.ambient)
        temporal_state = TemporalState(self.state.previous)
        temporal = replace(profile.temporal, frame_time_ms=dt)
        result = apply_temporal(pre_temporal, temporal, temporal_state)
        if not np.isfinite(result.rgb).all():
            raise ValueError("capacity display produced nonfinite output")
        source_hash = sha256(np.ascontiguousarray(frame.rgb).tobytes()).hexdigest()
        history_hash = digest({"previous": self._capacity_history_hash,
                               "source": source_hash, "dt_ms_hex": dt.hex(), "geometry": geometry})
        trace.update(before_nits=before, after_nits=capacity,
                     branch="attack" if trace["target_nits"] < before else
                            "release" if trace["target_nits"] > before else "equal",
                     attack_ms=config.attack_ms, release_ms=config.release_ms,
                     dt_ms=dt, elapsed_ms=candidate.elapsed_ms, ticks=candidate.ticks)
        state.capacity_nits, state.elapsed_ms, state.ticks = (
            candidate.capacity_nits, candidate.elapsed_ms, candidate.ticks)
        self.state.previous = temporal_state.previous
        self._capacity_geometry = geometry
        self._capacity_source_hash, self._capacity_history_hash = source_hash, history_hash
        self._capacity_boundary = boundary(self)
        self.last_capacity_trace = trace
        self.last_pre_temporal = pre_temporal
        return result

    def identity(self) -> dict:
        """Effective profile/controller/target/angle fingerprints, active only."""
        from sim.abl_history import identity

        return identity(self)

    def checkpoint(self) -> dict:
        """Exact full display history at a successful active tick boundary."""
        from sim.abl_history import checkpoint

        return checkpoint(self)

    def restore_checkpoint(self, data: dict, *, shape=None, dtype=None, elapsed_ms=None) -> None:
        """Validate a full checkpoint, then restore atomically with resume policy."""
        from sim.abl_history import restore_checkpoint

        restore_checkpoint(self, data, shape=shape, dtype=dtype, elapsed_ms=elapsed_ms)

    def run_sequence(
        self,
        encoded_frames: Iterable[np.ndarray],
        config: MotionConfig | None = None,
        **kwargs,
    ) -> Iterator[SequenceOutput]:
        """Run an explicitly configured sequence; default is the legacy bypass.

        Optional ``source_pts``, ``last_duration``, ``cuts`` (indices with a
        cut before them), and per-pair ``scenes`` are documented in
        :func:`sim.sequence.render_sequence`.
        """

        from sim.sequence import render_sequence

        return render_sequence(self, encoded_frames, config, **kwargs)

    def run(self, encoded: np.ndarray) -> np.ndarray:
        """Return a ``uint8`` preview image."""

        return encode_frame(self.run_linear(encoded), self.profile.output)
