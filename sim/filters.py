"""Small NumPy filters shared by image processing and backlight spread.

Kernels are normalized to unit sum so a flat field is unchanged (DC gain 1).
That keeps a full-white local-dimming frame at the LED drive instead of
dimming it when the point-spread function is applied.
"""

from __future__ import annotations

import numpy as np


def gaussian_kernel1d(sigma: float) -> np.ndarray:
    """Odd-length 1D Gaussian. ``sigma <= 0`` returns a one-tap identity kernel."""

    if sigma <= 1e-6:
        return np.ones(1, dtype=np.float64)
    radius = max(1, int(np.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    return kernel


def convolve_axis(image: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """Reflect-padded convolution along one axis. ``kernel`` is 1D."""

    kernel = np.asarray(kernel, dtype=np.float64)
    if kernel.size == 1:
        return np.asarray(image, dtype=np.float32)
    radius = kernel.size // 2
    moved = np.moveaxis(np.asarray(image, dtype=np.float64), axis, -1)
    # ``reflect`` cannot pad by more than the axis length; ``edge`` can.
    mode = "reflect" if radius < moved.shape[-1] else "edge"
    pad_width = [(0, 0)] * (moved.ndim - 1) + [(radius, radius)]
    padded = np.pad(moved, pad_width, mode=mode)
    windows = np.lib.stride_tricks.sliding_window_view(padded, kernel.size, axis=-1)
    filtered = np.tensordot(windows, kernel, axes=(-1, 0))
    return np.moveaxis(filtered, -1, axis).astype(np.float32)


def gaussian_blur_xy(image: np.ndarray, sigma_x: float, sigma_y: float) -> np.ndarray:
    """Separable Gaussian with independent horizontal and vertical sigma."""

    blurred = convolve_axis(image, gaussian_kernel1d(sigma_x), axis=1)
    return convolve_axis(blurred, gaussian_kernel1d(sigma_y), axis=0)


def gaussian_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur. ``image`` is ``H x W`` or ``H x W x C``."""

    return gaussian_blur_xy(image, sigma, sigma)
