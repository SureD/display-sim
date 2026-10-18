"""HDR soft shoulder and a placeholder load limiter.

The shoulder is the docs/research/03 approximation, not BT.2390 and not a vendor
curve. For luminance ``Y``, allowed peak ``P`` and knee ``K < P``:

``f(Y) = Y`` for ``Y <= K``, otherwise
``f(Y) = K + (P - K) * (1 - exp(-(Y - K) / (P - K)))``.

RGB is scaled by ``f(Y) / Y`` so black stays black and neutral colors keep
their chromaticity. The curve is continuous with unit slope at ``K`` and
approaches ``P`` without mapping a mastering peak exactly onto ``P``. If a
channel still exceeds ``P`` (a scalar shoulder does not guarantee that), the
pixel is pulled toward equal-channel white at the shoulder luminance until
it fits in ``[0, P]``. That is a documented desaturation, not ICtCp.

ABL uses average picture level as the mean of linear BT.709 luminance in
nits, not the mean of a PQ code. The peak-versus-APL curve lives in
:mod:`tv_sim.load`; which picture its APL comes from is set by ``abl_source``.
``emitted`` reads the frame this stage was handed, which on an LCD is already
past the panel. ``demand`` requires the caller to pass the APL of the
requested picture, which is what :class:`tv_sim.pipeline.Pipeline` does.

An optional second limiter follows docs/research/03's channel-power proxy
(weighted nits, not watts):

``P_req = mean_i Σ_c k_c e_ic``, ``g = min(1, budget / P_req)``, ``e *= g``.

Budget 0 leaves that gain off. All stored results are float32 nits.
"""

from __future__ import annotations

import numpy as np

from tv_sim.color import luminance
from tv_sim.frame import Frame
from tv_sim.load import abl_capacity, demand_apl
from tv_sim.profile import HdrParams

_EXP_CLIP = np.float32(40.0)


def average_picture_level(rgb: np.ndarray) -> float:
    """Mean linear luminance in nits. This is not a mean PQ code."""

    return demand_apl(rgb)


def effective_peak(
    rgb: np.ndarray,
    params: HdrParams,
    *,
    demand_apl_nits: float | None = None,
) -> float:
    """Nit ceiling after the optional APL curve.

    With ``abl_source == "demand"`` the APL has to arrive from upstream;
    reading it off ``rgb`` here would measure the limiter's own output.
    """

    if not params.abl_enabled:
        peak = float(params.panel_peak_nits)
        if peak <= 0.0 or not np.isfinite(peak):
            raise ValueError("panel_peak_nits must be a positive finite value")
        return peak
    source = str(params.abl_source).lower()
    if source == "demand":
        if demand_apl_nits is None:
            raise ValueError(
                "abl_source='demand' needs the requested picture's APL; pass "
                "demand_apl_nits (tv_sim.pipeline.Pipeline does this)"
            )
        apl = float(demand_apl_nits)
    elif source == "emitted":
        apl = average_picture_level(rgb)
    else:
        raise ValueError(f"Unknown abl_source {params.abl_source!r}. Use emitted or demand.")
    return abl_capacity(apl, params)


def soft_shoulder(y: np.ndarray, peak: float, knee_ratio: float) -> np.ndarray:
    """Float32 soft shoulder. Values at or below the knee are unchanged."""

    level = np.asarray(y, dtype=np.float32)
    peak32 = np.float32(peak)
    if peak32 <= np.float32(0.0):
        raise ValueError("peak must be positive")
    ratio = float(np.clip(knee_ratio, 0.0, 1.0))
    knee = np.float32(peak32 * np.float32(ratio))
    span = np.float32(peak32 - knee)
    if span <= np.float32(1e-5):
        return np.minimum(level, peak32)
    excess = np.maximum(level - knee, np.float32(0.0))
    # Large ratios underflow exp to 0, which is the asymptote at ``peak``.
    attenuated = np.exp(-np.minimum(excess / span, _EXP_CLIP)).astype(np.float32)
    compressed = knee + span * (np.float32(1.0) - attenuated)
    compressed = np.minimum(compressed, peak32)
    return np.where(level <= knee, level, compressed).astype(np.float32)


def _project_into_peak(rgb: np.ndarray, y: np.ndarray, peak: float) -> np.ndarray:
    """Pull pixels that stick out of the peak cube toward white at luminance ``y``."""

    peak32 = np.float32(peak)
    y_col = np.minimum(np.asarray(y, dtype=np.float32), peak32)[..., None]
    color = np.asarray(rgb, dtype=np.float32)
    maximum = np.max(color, axis=-1, keepdims=True)
    excess = maximum - y_col
    room = peak32 - y_col
    scale = np.ones_like(maximum, dtype=np.float32)
    needs = (maximum > peak32) & (excess > np.float32(1e-6))
    fitted = np.clip(room / np.maximum(excess, np.float32(1e-6)), np.float32(0.0), np.float32(1.0))
    scale = np.where(needs, fitted, scale).astype(np.float32)
    projected = y_col + (color - y_col) * scale
    return np.clip(projected, np.float32(0.0), peak32)


def _channel_power_gain(rgb: np.ndarray, params: HdrParams) -> np.ndarray:
    budget = float(params.abl_power_budget_nits)
    if budget <= 0.0:
        return rgb
    weights = np.asarray(params.abl_channel_weights, dtype=np.float32).reshape(1, 1, 3)
    if weights.shape[-1] != 3 or np.any(weights < 0.0):
        raise ValueError("abl_channel_weights must be three nonnegative values")
    required = float(np.mean(np.sum(rgb * weights, axis=-1), dtype=np.float64))
    if required <= 1e-8:
        return rgb
    gain = np.float32(min(1.0, budget / required))
    return (rgb * gain).astype(np.float32)


def tone_map(
    frame: Frame,
    params: HdrParams,
    *,
    demand_apl_nits: float | None = None,
    capacity_nits: float | None = None,
) -> Frame:
    """Compress highlights into the panel budget and optionally limit load."""

    if params.tone_map != "soft_clip":
        raise ValueError(
            f"Unsupported tone_map {params.tone_map!r}. This build implements soft_clip."
        )
    if capacity_nits is None:
        peak = effective_peak(frame.rgb, params, demand_apl_nits=demand_apl_nits)
    else:
        peak = float(capacity_nits)
        if not np.isfinite(peak) or peak <= 0:
            raise ValueError("capacity_nits must be positive and finite")
    y = luminance(frame.rgb).astype(np.float32)
    y_out = soft_shoulder(y, peak, float(params.knee_ratio))
    scale = np.ones_like(y, dtype=np.float32)
    nonzero = y > np.float32(1e-6)
    np.divide(y_out, y, out=scale, where=nonzero)
    rgb = (np.asarray(frame.rgb, dtype=np.float32) * scale[..., None]).astype(np.float32)
    rgb = _project_into_peak(rgb, y_out, peak)
    rgb = _channel_power_gain(rgb, params)
    if rgb.dtype != np.float32 or not np.isfinite(rgb).all():
        raise RuntimeError("tone map produced non-finite or non-float32 nits")
    return Frame(rgb, frame.backlight)
