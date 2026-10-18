"""Electro-optical transfer functions and luminance helpers.

The decode stage turns code values into linear nits. The encode stage does the
reverse for preview files. PQ follows SMPTE ST 2084. HLG follows ITU-R BT.2100
(inverse OETF, then the display OOTF with system gamma set from peak luminance).
sRGB uses IEC 61966-2-1.
"""

from __future__ import annotations

import numpy as np

# SMPTE ST 2084 constants.
_PQ_M1 = 2610.0 / 16384.0
_PQ_M2 = 2523.0 / 32.0
_PQ_C1 = 3424.0 / 4096.0
_PQ_C2 = 2413.0 / 128.0
_PQ_C3 = 2392.0 / 128.0

# ITU-R BT.2100 HLG inverse-OETF constants.
_HLG_A = 0.17883277
_HLG_B = 0.28466892
_HLG_C = 0.55991073

_LUMA = {
    "bt709": np.array([0.2126, 0.7152, 0.0722], dtype=np.float64),
    "bt2020": np.array([0.2627, 0.6780, 0.0593], dtype=np.float64),
}


def luminance(rgb: np.ndarray, primary: str = "bt709") -> np.ndarray:
    """Relative luminance of linear RGB, same units as ``rgb`` (nits)."""

    coeffs = _LUMA[primary]
    return (np.asarray(rgb, dtype=np.float64) * coeffs).sum(axis=-1).astype(np.float32)


def srgb_eotf(encoded: np.ndarray) -> np.ndarray:
    """sRGB code values in ``[0, 1]`` to linear light in ``[0, 1]``."""

    u = np.asarray(encoded, dtype=np.float64)
    linear = np.where(u <= 0.04045, u / 12.92, ((u + 0.055) / 1.055) ** 2.4)
    return linear.astype(np.float32)


def srgb_oetf(linear: np.ndarray) -> np.ndarray:
    """Linear light in ``[0, 1]`` to sRGB code values in ``[0, 1]``."""

    x = np.clip(np.asarray(linear, dtype=np.float64), 0.0, None)
    encoded = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return np.clip(encoded, 0.0, 1.0).astype(np.float32)


def pq_eotf(encoded: np.ndarray) -> np.ndarray:
    """PQ (ST 2084) code values in ``[0, 1]`` to absolute nits (0–10000)."""

    v = np.clip(np.asarray(encoded, dtype=np.float64), 0.0, 1.0)
    vp = np.power(v, 1.0 / _PQ_M2)
    num = np.maximum(vp - _PQ_C1, 0.0)
    den = _PQ_C2 - _PQ_C3 * vp
    y = np.power(num / np.maximum(den, 1e-12), 1.0 / _PQ_M1)
    return (y * 10000.0).astype(np.float32)


def pq_oetf(nits: np.ndarray) -> np.ndarray:
    """Absolute nits to PQ code values in ``[0, 1]``."""

    y = np.clip(np.asarray(nits, dtype=np.float64) / 10000.0, 0.0, None)
    ym = np.power(y, _PQ_M1)
    num = _PQ_C1 + _PQ_C2 * ym
    den = 1.0 + _PQ_C3 * ym
    return np.power(num / den, _PQ_M2).astype(np.float32)


def hlg_scene_linear(encoded: np.ndarray) -> np.ndarray:
    """HLG signal in ``[0, 1]`` to scene-linear light, nominal range ``[0, 1]``."""

    v = np.clip(np.asarray(encoded, dtype=np.float64), 0.0, 1.0)
    below = (v * v) / 3.0
    above = (np.exp((v - _HLG_C) / _HLG_A) + _HLG_B) / 12.0
    return np.where(v <= 0.5, below, above).astype(np.float32)


def hlg_eotf(encoded: np.ndarray, peak_nits: float) -> np.ndarray:
    """HLG signal to display-referred nits at the given peak luminance.

    Scene light is recovered with the inverse OETF. The BT.2100 OOTF then
    applies system gamma ``1.2 + 0.42 log10(peak/1000)`` on luminance while
    keeping chromaticity, and scales reference white to ``peak_nits``.
    """

    if peak_nits <= 0:
        raise ValueError("HLG peak_nits must be positive")
    scene = np.asarray(hlg_scene_linear(encoded), dtype=np.float64)
    gamma = 1.2 + 0.42 * np.log10(peak_nits / 1000.0)
    y = luminance(scene, "bt2020").astype(np.float64)
    scale = np.zeros_like(y)
    mask = y > 1e-8
    scale[mask] = np.power(y[mask], gamma - 1.0)
    displayed = peak_nits * scene * scale[..., None]
    return displayed.astype(np.float32)


def apply_matrix(rgb: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Apply a 3x3 matrix to linear RGB row vectors (``rgb @ M.T``)."""

    mat = np.asarray(matrix, dtype=np.float64)
    if mat.shape != (3, 3):
        raise ValueError(f"color matrix must be 3x3, got {mat.shape}")
    out = np.asarray(rgb, dtype=np.float64) @ mat.T
    return out.astype(np.float32)
