"""Small NumPy filters shared by image processing and backlight spread.

Kernels are normalized to unit sum so a flat field is unchanged (DC gain 1).
That keeps a full-white local-dimming frame at the LED drive instead of
dimming it when the point-spread function is applied.
"""

from __future__ import annotations

from typing import Literal

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


def convolve_axis(
    image: np.ndarray,
    kernel: np.ndarray,
    axis: int,
    boundary: str = "reflect",
) -> np.ndarray:
    """Padded convolution along one axis. ``kernel`` is 1D.

    ``reflect`` mirrors content back into the frame, which preserves DC but
    invents light at a border. ``zero`` extends with darkness instead, so a
    border loses the part of the kernel that falls outside (docs/research/02 and
    docs/research/m3-local-dimming-params.md discuss that choice for zone optics).
    """

    kernel = np.asarray(kernel, dtype=np.float64)
    if kernel.size == 1:
        return np.asarray(image, dtype=np.float32)
    radius = kernel.size // 2
    moved = np.moveaxis(np.asarray(image, dtype=np.float64), axis, -1)
    mode: Literal["constant", "reflect", "edge"]
    if boundary == "zero":
        mode = "constant"
    elif boundary == "reflect":
        # ``reflect`` cannot pad by more than the axis length; ``edge`` can.
        mode = "reflect" if radius < moved.shape[-1] else "edge"
    else:
        raise ValueError(f"Unknown convolution boundary {boundary!r}. Use reflect or zero.")
    pad_width = [(0, 0)] * (moved.ndim - 1) + [(radius, radius)]
    padded = np.pad(moved, pad_width, mode=mode)
    windows = np.lib.stride_tricks.sliding_window_view(padded, kernel.size, axis=-1)
    filtered = np.tensordot(windows, kernel, axes=(-1, 0))
    return np.moveaxis(filtered, -1, axis).astype(np.float32)


def exponential_kernel1d(scale: float) -> np.ndarray:
    """Odd-length 1D ``exp(-|x| / scale)``. ``scale <= 0`` is a one-tap identity.

    A diffuser or light-guide skirt falls off far more slowly than a Gaussian
    of the same width. docs/research/02 is explicit that Gaussian optics are
    "convenient, not established universal physics", so this is an alternative
    placeholder shape, not a measured LSF.
    """

    if scale <= 1e-6:
        return np.ones(1, dtype=np.float64)
    radius = max(1, int(np.ceil(5.0 * scale)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-np.abs(x) / scale)
    kernel /= kernel.sum()
    return kernel


def separable_convolve(
    image: np.ndarray,
    kernel_x: np.ndarray,
    kernel_y: np.ndarray,
    boundary: str = "reflect",
) -> np.ndarray:
    """Convolve along x then y with independent 1D kernels."""

    filtered = convolve_axis(image, kernel_x, axis=1, boundary=boundary)
    return convolve_axis(filtered, kernel_y, axis=0, boundary=boundary)


def gaussian_blur_xy(image: np.ndarray, sigma_x: float, sigma_y: float) -> np.ndarray:
    """Separable Gaussian with independent horizontal and vertical sigma."""

    return separable_convolve(image, gaussian_kernel1d(sigma_x), gaussian_kernel1d(sigma_y))


def gaussian_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur. ``image`` is ``H x W`` or ``H x W x C``."""

    return gaussian_blur_xy(image, sigma, sigma)
