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
    """One TV profile and the temporal state that persists across frames."""

    def __init__(self, profile: TVProfile, state: TemporalState | None = None):
        self.profile = profile
        self.state = state if state is not None else TemporalState()

    def run_linear(self, encoded: np.ndarray) -> Frame:
        """Run every stage except output encode. RGB is linear nits."""

        profile = self.profile
        frame = decode_encoded(encoded, profile.input)
        frame = process_image(frame, profile.processing)
        frame = simulate_backlight(frame, profile.backlight)
        frame = simulate_panel(
            frame,
            profile.panel,
            self_emissive=profile.self_emissive,
            peak_nits=profile.backlight.peak_nits,
        )
        frame = tone_map(frame, profile.hdr)
        frame = add_ambient(frame, profile.ambient)
        return apply_temporal(frame, profile.temporal, self.state)

    def run(self, encoded: np.ndarray) -> np.ndarray:
        """Return a ``uint8`` preview image."""

        return encode_frame(self.run_linear(encoded), self.profile.output)
