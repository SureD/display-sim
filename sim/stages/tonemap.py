"""HDR tone mapping and a placeholder average-brightness limiter.

Below the knee the curve is linear. Above it, luminance eases toward the
allowed peak and chromaticity is kept by scaling RGB together.

ABL, when enabled, lowers that peak as average picture level rises:

``P = full_field + (panel_peak - full_field) * (1 - clip(APL / panel_peak))^gamma``

This is not a measured power-limit curve. It only captures the trend that a
full-white OLED frame cannot hold the small-window peak.
"""

from __future__ import annotations

import numpy as np

from sim.color import luminance
from sim.frame import Frame
from sim.profile import HdrParams


def effective_peak(rgb: np.ndarray, params: HdrParams) -> float:
    """Nit ceiling after the optional ABL term."""

    peak = float(params.panel_peak_nits)
    if peak <= 0:
        raise ValueError("panel_peak_nits must be positive")
    if not params.abl_enabled:
        return peak
    apl = float(luminance(rgb).mean())
    frac = float(np.clip(apl / peak, 0.0, 1.0))
    full = float(params.abl_full_field_nits)
    return full + (peak - full) * (1.0 - frac) ** float(params.abl_gamma)


def _compress(y: np.ndarray, peak: float, knee_ratio: float) -> np.ndarray:
    knee = peak * knee_ratio
    out = np.array(y, dtype=np.float64, copy=True)
    above = out > knee
    span = peak - knee
    if span <= 1e-8:
        out[above] = peak
        return out
    out[above] = knee + span * (1.0 - np.exp(-(out[above] - knee) / span))
    return out


def tone_map(frame: Frame, params: HdrParams) -> Frame:
    """Compress highlights (and the whole picture, via ABL) into the panel budget."""

    if params.tone_map != "soft_clip":
        raise ValueError(
            f"Unsupported tone_map {params.tone_map!r}. This skeleton implements soft_clip."
        )
    peak = effective_peak(frame.rgb, params)
    y = luminance(frame.rgb).astype(np.float64)
    y_out = _compress(y, peak, float(params.knee_ratio))
    scale = np.ones_like(y)
    nonzero = y > 1e-8
    scale[nonzero] = y_out[nonzero] / y[nonzero]
    rgb = np.asarray(frame.rgb, dtype=np.float64) * scale[..., None]
    return Frame(np.clip(rgb, 0.0, None).astype(np.float32), frame.backlight)
