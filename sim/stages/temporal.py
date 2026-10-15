"""Response lag, optional overdrive, sample-and-hold, and a BFI hook.

Response time is a first-order lag on the linear nit image. With no
overdrive (gain 0 or drive interval 0):

``shown = previous + (target - previous) * (1 - exp(-dt / tau))``

Overdrive, when enabled, follows the research/04 command for a short prefix
of the frame and then the real target:

``u_od = clip(u + k (u - q_start), 0, ceiling)``

``ceiling`` 0 clips only at zero, so the command can overshoot a mid-gray
target. There is no measured overdrive LUT and no second pole, so inverse
ghosting is not reproduced. The state stored for the next frame is the
panel level after this lag, not the eye-blurred or strobed picture.

The first frame has no history and is shown fully settled. A repeated still
has ``u == q_start``, so overdrive adds nothing and the image stays put.

Sample-and-hold blur averages a few sub-frame horizontal shifts spanning
``motion_px_per_frame``. Zero motion leaves the image unchanged.

BFI is an emission gate after the panel state. Duty ``d`` in (0, 1] scales
the visible hold: at fixed peak drive the frame mean falls by about ``d``,
and pursuit blur uses ``d * motion_px_per_frame`` because the visible time
is ``d / refresh``. ``bfi_preserve_mean`` raises the pulse toward
``1 / d`` and then clips to ``overdrive_ceiling_nits`` when that ceiling is
positive, so the time average stays near the unstrobed level until the clip.
Duty 1 is ordinary sample-and-hold. This is not a scanout or PWM waveform.
MEMC is not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sim.frame import Frame
from sim.profile import TemporalParams


@dataclass
class TemporalState:
    """Visible linear image from the previous frame, before eye blur and BFI."""

    previous: np.ndarray | None = None


def _approach(
    previous: np.ndarray,
    target: np.ndarray,
    response_time_ms: float,
    frame_time_ms: float,
) -> np.ndarray:
    if response_time_ms <= 1e-6 or frame_time_ms <= 1e-9:
        return np.asarray(target, dtype=np.float32)
    alpha = np.float32(1.0 - np.exp(-float(frame_time_ms) / float(response_time_ms)))
    return (previous + (target - previous) * alpha).astype(np.float32)


def _overdrive_command(previous: np.ndarray, target: np.ndarray, params: TemporalParams) -> np.ndarray:
    command = target + np.float32(params.overdrive_gain) * (target - previous)
    command = np.maximum(command, np.float32(0.0))
    ceiling = float(params.overdrive_ceiling_nits)
    if ceiling > 0.0:
        command = np.minimum(command, np.float32(ceiling))
    return command.astype(np.float32)


def respond(previous: np.ndarray, target: np.ndarray, params: TemporalParams) -> np.ndarray:
    """One frame of lag, with an optional overdriven prefix."""

    gain = float(params.overdrive_gain)
    drive_ms = float(params.overdrive_ms)
    frame_ms = float(params.frame_time_ms)
    if gain <= 0.0 or drive_ms <= 0.0:
        return _approach(previous, target, params.response_time_ms, frame_ms)
    drive_ms = min(drive_ms, frame_ms)
    command = _overdrive_command(previous, target, params)
    mid = _approach(previous, command, params.response_time_ms, drive_ms)
    rest_ms = frame_ms - drive_ms
    if rest_ms <= 1e-6:
        return mid
    return _approach(mid, target, params.response_time_ms, rest_ms)


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


def apply_bfi(rgb: np.ndarray, params: TemporalParams) -> tuple[np.ndarray, float]:
    """Emission gate. Returns the visible image and the motion scale in ``(0, 1]``."""

    duty = float(params.bfi_duty)
    if not np.isfinite(duty) or duty <= 0.0 or duty > 1.0:
        raise ValueError(f"bfi_duty must be in (0, 1], got {duty}")
    if duty >= 1.0 - 1e-8:
        return np.asarray(rgb, dtype=np.float32), 1.0
    if params.bfi_preserve_mean:
        boosted = np.asarray(rgb, dtype=np.float32) / np.float32(duty)
        ceiling = float(params.overdrive_ceiling_nits)
        if ceiling > 0.0:
            boosted = np.minimum(boosted, np.float32(ceiling))
        visible = (boosted * np.float32(duty)).astype(np.float32)
        return visible, duty
    return (np.asarray(rgb, dtype=np.float32) * np.float32(duty)).astype(np.float32), duty


def apply_temporal(
    frame: Frame,
    params: TemporalParams,
    state: TemporalState | None = None,
) -> Frame:
    """Lag toward the new target, then apply the emission gate and hold blur."""

    target = np.asarray(frame.rgb, dtype=np.float32)
    if state is None or state.previous is None or state.previous.shape != target.shape:
        # No history: a still (and the first frame of a clip) is fully settled.
        lagged = target
    else:
        lagged = respond(state.previous, target, params)
    if state is not None:
        state.previous = np.asarray(lagged, dtype=np.float32).copy()
    visible, motion_scale = apply_bfi(lagged, params)
    shown = visible
    if params.sample_and_hold:
        shown = sample_and_hold(visible, float(params.motion_px_per_frame) * motion_scale)
    return Frame(shown, frame.backlight)
