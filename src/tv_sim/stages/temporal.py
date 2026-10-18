"""Response lag, optional overdrive, sample-and-hold, and a BFI hook.

Response time is a first-order lag on the linear nit image. With no
overdrive (gain 0 or drive interval 0):

``shown = previous + (target - previous) * (1 - exp(-dt / tau))``

Overdrive, when enabled, follows the docs/research/04 command for a short prefix
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
Opt-in synthetic MEMC reconstruction runs earlier on requested content in
``tv_sim.sequence``; response state here is never used as a source picture.

``integration_samples > 1`` opts into a time-resolved exposure instead of
the legacy endpoint plus seven-shift approximation above. Analytic samples
of the response/overdrive trace are averaged during a centered rectangular
BFI pulse. The tracking eye advances continuously, so each sample is shifted
by ``-motion_px_per_frame * (t / frame_time - 0.5)``. Both fast OLEDs and
slower LCDs therefore show hold blur; LCDs additionally retain the preceding
pan positions through the response state. The end-of-frame panel level is
stored separately, so longer clips retain response tails without feeding
pursuit blur or emission gating back into the panel. This remains emitted
RGB filtering, not a measured transmission/voltage or scanout model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tv_sim.frame import Frame
from tv_sim.profile import TemporalParams


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


def _overdrive_command(
    previous: np.ndarray, target: np.ndarray, params: TemporalParams
) -> np.ndarray:
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


def _integrate_exposure(
    previous: np.ndarray,
    target: np.ndarray,
    params: TemporalParams,
    samples: int,
) -> np.ndarray:
    """Midpoint quadrature of emission in tracking-eye coordinates.

    Sample only the illuminated part of the frame, then retain the duty
    factor in ``apply_bfi``. This avoids missing a narrow pulse between
    quadrature points and gives a shorter temporal aperture at any sample
    count. The BFI pulse is centered; its phase/waveform is a synthetic
    experiment setting, not a measured TV capability.
    """

    frame_ms = float(params.frame_time_ms)
    if not np.isfinite(frame_ms) or frame_ms <= 0:
        raise ValueError("frame_time_ms must be positive for subframe integration")
    # Validate the duty even when no prior frame exists.
    _, duty = apply_bfi(target, params)
    start = (1.0 - duty) / 2.0
    drive_ms = min(float(params.overdrive_ms), frame_ms)
    driven = params.overdrive_gain > 0 and drive_ms > 0
    command = _overdrive_command(previous, target, params) if driven else target
    mid = _approach(previous, command, params.response_time_ms, drive_ms) if driven else previous
    acc = np.zeros(target.shape, dtype=np.float64)
    for index in range(samples):
        phase = start + duty * ((index + 0.5) / samples)
        time_ms = phase * frame_ms
        if driven and time_ms > drive_ms:
            panel = _approach(mid, target, params.response_time_ms, time_ms - drive_ms)
        else:
            panel = _approach(previous, command, params.response_time_ms, time_ms)
        emitted, _ = apply_bfi(panel, params)
        if params.sample_and_hold:
            emitted = shift_x(emitted, -float(params.motion_px_per_frame) * (phase - 0.5))
        acc += emitted
    return (acc / samples).astype(np.float32)


def apply_temporal(
    frame: Frame,
    params: TemporalParams,
    state: TemporalState | None = None,
) -> Frame:
    """Keep response history and render an endpoint or subframe exposure."""

    target = np.asarray(frame.rgb, dtype=np.float32)
    samples = params.integration_samples
    if isinstance(samples, bool) or not isinstance(samples, (int, np.integer)) or samples < 1:
        raise ValueError("integration_samples must be a positive integer")
    if state is None or state.previous is None or state.previous.shape != target.shape:
        # No history: a still (and the first frame of a clip) is fully settled.
        previous = target
        lagged = target
    else:
        previous = state.previous
        lagged = respond(previous, target, params)
    if samples > 1:
        shown = _integrate_exposure(previous, target, params, samples)
        if state is not None:
            state.previous = np.asarray(lagged, dtype=np.float32).copy()
        return Frame(shown, frame.backlight)
    if state is not None:
        state.previous = np.asarray(lagged, dtype=np.float32).copy()
    visible, motion_scale = apply_bfi(lagged, params)
    shown = visible
    if params.sample_and_hold:
        shown = sample_and_hold(visible, float(params.motion_px_per_frame) * motion_scale)
    return Frame(shown, frame.backlight)
