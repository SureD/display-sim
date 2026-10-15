"""Panel: LCD leakage, subpixel mosaic, viewing angle.

LCD path. The liquid crystal wants transmittance ``target / backlight``, limited
to ``[1/contrast, 1]``. Where local dimming spills light onto a dark pixel, the
cell is already at its floor and the spill is visible as a halo
(``backlight / contrast``).

OLED path. There is no shutter. The target is clipped to the emitter peak and
passed on. Subpixel layout still runs so the mosaic can be inspected; the
box-filtered mosaic is energy-preserving for a flat color, which keeps the
rest of the pipeline at the original resolution.

Viewing angle is a placeholder, not a measured BRDF. Off axis, RGB is mixed
toward the pixel luminance so chroma falls:
``factor = 1 / (1 + angle_loss_per_deg * degrees)``.
"""

from __future__ import annotations

import numpy as np

from sim.color import apply_matrix, luminance
from sim.frame import Frame
from sim.profile import PanelParams


def lcd_transmit(target: np.ndarray, backlight: np.ndarray, contrast: float) -> np.ndarray:
    """Reproduce ``target`` through a backlight and a finite native contrast."""

    if contrast <= 1.0:
        raise ValueError("native_contrast must be greater than 1")
    t_min = np.float32(1.0 / contrast)
    safe = np.maximum(backlight, np.float32(1e-8))
    trans = np.clip(target / safe[..., None], t_min, np.float32(1.0))
    return (safe[..., None] * trans).astype(np.float32)


def render_subpixels(rgb: np.ndarray, layout: str) -> np.ndarray:
    """Expand RGB into a subpixel mosaic.

    Values are scaled so a later box filter returns the original color. The
    geometry is a labeled placeholder, not a micrograph.

    * ``rgb_stripe`` — vertical R, G, B stripes (``H x 3W``).
    * ``wrgb`` — R, G, B residuals plus a white subpixel (``H x 4W``).
    * ``qd_oled`` — two-row triangular placeholder (``2H x 3W``): R and G on
      the even row, B on the odd row.
    """

    image = np.asarray(rgb, dtype=np.float32)
    height, width = image.shape[:2]
    red, green, blue = image[..., 0], image[..., 1], image[..., 2]
    if layout == "rgb_stripe":
        mosaic = np.zeros((height, width * 3, 3), dtype=np.float32)
        mosaic[:, 0::3, 0] = 3.0 * red
        mosaic[:, 1::3, 1] = 3.0 * green
        mosaic[:, 2::3, 2] = 3.0 * blue
        return mosaic
    if layout == "wrgb":
        white = np.minimum(np.minimum(red, green), blue)
        mosaic = np.zeros((height, width * 4, 3), dtype=np.float32)
        mosaic[:, 0::4, 0] = 4.0 * (red - white)
        mosaic[:, 1::4, 1] = 4.0 * (green - white)
        mosaic[:, 2::4, 2] = 4.0 * (blue - white)
        mosaic[:, 3::4, :] = 4.0 * white[..., None]
        return mosaic
    if layout == "qd_oled":
        mosaic = np.zeros((height * 2, width * 3, 3), dtype=np.float32)
        mosaic[0::2, 0::3, 0] = 6.0 * red
        mosaic[0::2, 1::3, 1] = 6.0 * green
        mosaic[1::2, 2::3, 2] = 6.0 * blue
        return mosaic
    raise ValueError(f"Unknown subpixel layout {layout!r}")


def composite_subpixels(mosaic: np.ndarray, layout: str) -> np.ndarray:
    """Box-filter a mosaic from :func:`render_subpixels` back to pixels."""

    if layout == "rgb_stripe":
        height, width3, _ = mosaic.shape
        return mosaic.reshape(height, width3 // 3, 3, 3).mean(axis=2).astype(np.float32)
    if layout == "wrgb":
        height, width4, _ = mosaic.shape
        return mosaic.reshape(height, width4 // 4, 4, 3).mean(axis=2).astype(np.float32)
    if layout == "qd_oled":
        height2, width3, _ = mosaic.shape
        block = mosaic.reshape(height2 // 2, 2, width3 // 3, 3, 3)
        return block.mean(axis=(1, 3)).astype(np.float32)
    raise ValueError(f"Unknown subpixel layout {layout!r}")


def _matrix(values: list[float] | np.ndarray) -> np.ndarray:
    mat = np.asarray(values, dtype=np.float64)
    if mat.shape == (9,):
        mat = mat.reshape(3, 3)
    return mat


def apply_viewing_angle(rgb: np.ndarray, angle_deg: float, loss_per_deg: float) -> np.ndarray:
    """Collapse chroma toward luminance as the off-axis angle grows."""

    if angle_deg <= 0.0 or loss_per_deg <= 0.0:
        return np.asarray(rgb, dtype=np.float32)
    factor = np.float32(1.0 / (1.0 + loss_per_deg * angle_deg))
    y = luminance(rgb)[..., None]
    mixed = y + (np.asarray(rgb, dtype=np.float32) - y) * factor
    return mixed.astype(np.float32)


def simulate_panel(
    frame: Frame,
    params: PanelParams,
    *,
    self_emissive: bool,
    peak_nits: float,
) -> Frame:
    """Turn the target picture plus backlight into emitted linear light."""

    if frame.backlight is None:
        raise ValueError("panel stage requires a backlight map")
    if self_emissive:
        emitted = np.clip(frame.rgb, 0.0, np.float32(peak_nits))
    else:
        emitted = lcd_transmit(frame.rgb, frame.backlight, params.native_contrast)
    emitted = apply_matrix(emitted, _matrix(params.color_matrix))
    mosaic = render_subpixels(emitted, params.subpixel)
    emitted = composite_subpixels(mosaic, params.subpixel)
    emitted = apply_viewing_angle(emitted, params.viewing_angle_deg, params.angle_loss_per_deg)
    emitted = np.clip(emitted, 0.0, None)
    return Frame(emitted, frame.backlight)
