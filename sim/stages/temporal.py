"""Response time and sample-and-hold.

Response time is a first-order lag. With frame time ``dt`` and time constant
``tau`` (both milliseconds):

``shown = previous + (target - previous) * (1 - exp(-dt / tau))``

The first frame has no history, so it is shown fully settled. Later frames
move toward the new target from the previous *held* image (before eye blur).

Sample-and-hold blur is the eye tracking a moving edge while the panel holds
one sample for the whole frame. The held image is averaged over a few
sub-frame horizontal shifts spanning ``motion_px_per_frame``. Zero motion
leaves the image unchanged. This is a one-axis placeholder, not a 2D pursuit
model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sim.frame import Frame
from sim.profile import TemporalParams


@dataclass
class TemporalState:
    """Visible linear image from the previous frame, before eye blur."""

    previous: np.ndarray | None = None


def _approach(
    previous: np.ndarray,
    target: np.ndarray,
    response_time_ms: float,
    frame_time_ms: float,
) -> np.ndarray:
    if response_time_ms <= 1e-6:
        return np.asarray(target, dtype=np.float32)
    alpha = np.float32(1.0 - np.exp(-float(frame_time_ms) / float(response_time_ms)))
    return (previous + (target - previous) * alpha).astype(np.float32)


def shift_x(rgb: np.ndarray, shift: float) -> np.ndarray:
    """Bilinear horizontal shift. Positive ``shift`` moves content to the right."""

    if shift == 0.0:
        return rgb
    width = rgb.shape[1]
    src = np.arange(width, dtype=np.float64) - float(shift)
    x0 = np.floor(src).astype(np.int32)
    weight = (src - x0).astype(np.float32)
    x0c = np.clip(x0, 0, width - 1)
    x1c = np.clip(x0 + 1, 0, width - 1)
    return rgb[:, x0c] * (1.0 - weight)[None, :, None] + rgb[:, x1c] * weight[None, :, None]


def sample_and_hold(rgb: np.ndarray, motion_px: float, steps: int = 7) -> np.ndarray:
    """Average sub-frame shifts that an eye tracking ``motion_px`` would integrate."""

    if motion_px == 0.0 or steps <= 1:
        return np.asarray(rgb, dtype=np.float32)
    acc = np.zeros(rgb.shape, dtype=np.float64)
    for index in range(steps):
        shift = motion_px * (index / (steps - 1) - 0.5)
        acc += shift_x(rgb, shift)
    return (acc / steps).astype(np.float32)


def apply_temporal(
    frame: Frame,
    params: TemporalParams,
    state: TemporalState | None = None,
) -> Frame:
    """Lag toward the new target, then optionally apply hold blur."""

    target = np.asarray(frame.rgb, dtype=np.float32)
    if state is None or state.previous is None or state.previous.shape != target.shape:
        lagged = target
    else:
        lagged = _approach(
            state.previous, target, params.response_time_ms, params.frame_time_ms
        )
    shown = lagged
    if params.sample_and_hold:
        shown = sample_and_hold(lagged, float(params.motion_px_per_frame))
    if state is not None:
        state.previous = np.asarray(lagged, dtype=np.float32).copy()
    return Frame(shown, frame.backlight)
