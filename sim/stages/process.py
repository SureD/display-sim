"""Spatial processing: resize and an unsharp-mask sharpen.

Motion-compensated frame interpolation (MEMC) is intentionally not implemented.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from sim.filters import gaussian_blur
from sim.frame import Frame
from sim.profile import ProcessingParams

_RESAMPLE = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
}


def _resize(rgb: np.ndarray, scale: float, mode: str) -> np.ndarray:
    if scale == 1.0:
        return rgb
    if scale <= 0:
        raise ValueError("scale_factor must be positive")
    if mode not in _RESAMPLE:
        raise ValueError(f"Unknown scale_mode {mode!r}")
    height, width = rgb.shape[:2]
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    out = np.empty((new_size[1], new_size[0], 3), dtype=np.float32)
    for channel in range(3):
        image = Image.fromarray(np.asarray(rgb[..., channel], dtype=np.float32), mode="F")
        resized = image.resize(new_size, _RESAMPLE[mode])
        out[..., channel] = np.asarray(resized, dtype=np.float32)
    return out


def process_image(frame: Frame, params: ProcessingParams) -> Frame:
    """Scale, then sharpen. Amount 0 leaves the resized image unchanged."""

    rgb = _resize(frame.rgb, float(params.scale_factor), params.scale_mode)
    amount = float(params.sharpen_amount)
    if amount != 0.0:
        blurred = gaussian_blur(rgb, float(params.sharpen_sigma))
        rgb = np.clip(rgb + np.float32(amount) * (rgb - blurred), 0.0, None)
    return Frame(rgb)
