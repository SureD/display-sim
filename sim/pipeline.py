"""Wire the display stages in plan order.

decode → image processing → backlight / local dimming → panel →
HDR tone map / ABL → ambient reflection → temporal → encode.

Not in this pipeline: MEMC, a spectral or measured subpixel model, CRT and
plasma profiles, and a GPU backend. Overdrive and BFI are optional hooks
with placeholder parameters; duty 1 and overdrive gain 0 leave lag plus
sample-and-hold.
"""

from __future__ import annotations

import numpy as np

from sim.frame import Frame
from sim.load import LoadState, backlight_derate, demand_apl, smooth_apl
from sim.profile import TVProfile
from sim.stages.ambient import add_ambient
from sim.stages.backlight import simulate_backlight
from sim.stages.decode import decode_encoded
from sim.stages.encode import encode_frame
from sim.stages.panel import simulate_panel
from sim.stages.process import process_image
from sim.stages.temporal import TemporalState, apply_temporal
from sim.stages.tonemap import tone_map


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

        profile = self.profile
        frame = decode_encoded(encoded, profile.input)
        frame = process_image(frame, profile.processing)
        # The requested picture, before the panel and before any limiting.
        # research/m3-hdr-abl-params.md requires the load to be read here.
        apl = smooth_apl(
            self.load_state,
            demand_apl(frame.rgb),
            profile.hdr,
            profile.temporal.frame_time_ms,
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
        )
        frame = tone_map(frame, profile.hdr, demand_apl_nits=apl)
        frame = add_ambient(frame, profile.ambient)
        return apply_temporal(frame, profile.temporal, self.state)

    def run(self, encoded: np.ndarray) -> np.ndarray:
        """Return a ``uint8`` preview image."""

        return encode_frame(self.run_linear(encoded), self.profile.output)
