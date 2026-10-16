"""Wire the display stages in plan order.

decode → image processing → backlight / local dimming → panel →
HDR tone map / ABL → ambient reflection → temporal → encode.

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
from typing import TYPE_CHECKING, Iterable, Iterator

import numpy as np

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

if TYPE_CHECKING:
    from sim.sequence import MotionConfig, SequenceOutput


class Pipeline:
    """One TV profile and the state that persists across frames.

    Two histories are kept: the temporal state (panel level and pursuit
    history) and the ABL load state (smoothed demand APL).
    """

    def __init__(
        self,
        profile: TVProfile,
        state: TemporalState | None = None,
        load_state: LoadState | None = None,
    ):
        self.profile = profile
        self.state = state if state is not None else TemporalState()
        self.load_state = load_state if load_state is not None else LoadState()

    def run_linear(self, encoded: np.ndarray) -> Frame:
        """Run every stage except output encode. RGB is linear nits."""

        return self.display_content(self.prepare_content(encoded))

    def prepare_content(self, encoded: np.ndarray) -> Frame:
        """Decode and spatially process one source, without advancing histories."""

        frame = decode_encoded(encoded, self.profile.input)
        return process_image(frame, self.profile.processing)

    def display_content(self, frame: Frame, *, frame_time_ms: float | None = None) -> Frame:
        """Display prepared linear-nit content once; never decode/sharpen it again.

        Sequence callers provide the output tick duration for both panel and
        load dynamics. The legacy entry point uses the original profile object.
        """

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
        )
        frame = tone_map(frame, profile.hdr, demand_apl_nits=apl)
        frame = add_ambient(frame, profile.ambient)
        return apply_temporal(frame, temporal, self.state)

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
