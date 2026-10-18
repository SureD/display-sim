"""Panel: LCD leakage, subpixel mosaic, viewing angle.

LCD path. The liquid crystal wants transmittance ``target / backlight``, limited
to ``[1/contrast, 1]``. Where local dimming spills light onto a dark pixel, the
cell is already at its floor and the spill is visible as a halo
(``backlight / contrast``).

OLED path. There is no shutter. The legacy target is clipped to the emitter peak,
then an optional emission PSF spreads each channel: this is the near-field
glow of the stack, encapsulation and front glass, so unlike an LCD halo it
acts on emitted RGB rather than on a shared backlight. ``emission_psf``
carries the ``per_pixel`` sigmas from the backlight profile section (pixels,
not zone pitches) because that is where they are declared. The kernel is
unit-sum, so a flat field is unchanged and no light is created. There is
still no measured OLED PSF behind those numbers.

The opt-in M15 path defers the emitter peak to the joint HDR/ABL/color-volume
capacity owner, so an earlier channel clip cannot destroy chromaticity.

Subpixel layout still runs so the mosaic can be inspected; the box-filtered
mosaic is energy-preserving for a flat color, which keeps the rest of the
pipeline at the original resolution. A separate illustration of these layout
families, with synthetic apertures and a black matrix, lives in :mod:`tv_sim.macro`.

The legacy viewing angle is a placeholder, not a measured BRDF. Off axis, RGB is mixed
toward the pixel luminance so chroma falls:
``factor = 1 / (1 + angle_loss_per_deg * degrees)``.
The separate M10 opt-in model replaces that law with angular LCD transmission
or emissive RGB gains; see :mod:`tv_sim.stages.viewing_angle`. Both are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np

from tv_sim.color import apply_matrix, luminance
from tv_sim.frame import Frame
from tv_sim.profile import BacklightParams, PanelParams
from tv_sim.stages.backlight import apply_light_spread, psf_axis_kernels
from tv_sim.viewing_angle import (
    AngularParams,
    EmissiveAngularParams,
    LcdAngularParams,
    ViewingAngleConfig,
)


@dataclass(frozen=True)
class EmissionPsf:
    """Unit-sum emission kernels in pixels, plus the boundary policy."""

    kernels: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]
    boundary: str = "reflect"


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


def emission_psf(params: BacklightParams) -> EmissionPsf:
    """Per-pixel emission kernels and the boundary policy from a profile."""

    kernels = psf_axis_kernels(params, zone_pitch_y=1.0, zone_pitch_x=1.0, per_pixel=True)
    return EmissionPsf(kernels=kernels, boundary=params.psf_boundary)


def spread_emission(rgb: np.ndarray, psf: EmissionPsf) -> np.ndarray:
    """Blur emitted RGB per channel with the unit-sum emission PSF."""

    core_kx, core_ky, tail_kx, tail_ky, weight = psf.kernels
    if weight < 0.0:
        raise ValueError("emission PSF tail weight must be >= 0")
    tail_spreads = weight > 1e-8 and max(tail_kx.size, tail_ky.size) > 1
    if max(core_kx.size, core_ky.size) <= 1 and not tail_spreads:
        return np.asarray(rgb, dtype=np.float32)
    return apply_light_spread(np.asarray(rgb, dtype=np.float32), psf.kernels, psf.boundary)


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
    psf: EmissionPsf | None = None,
    viewing_angle: ViewingAngleConfig | None = None,
    angular_params: AngularParams | None = None,
    defer_emissive_peak: bool = False,
) -> Frame:
    """Turn the target picture plus backlight into emitted linear light."""

    if frame.backlight is None:
        raise ValueError("panel stage requires a backlight map")
    angular_active = viewing_angle is not None and viewing_angle.active
    if angular_active:
        from tv_sim.viewing_angle import validate_angular_path

        if angular_params is None:
            raise ValueError("active viewing angle requires angular parameters")
        validate_angular_path(
            cast(ViewingAngleConfig, viewing_angle),
            angular_params,
            self_emissive=self_emissive,
            contrast=params.native_contrast,
        )
    if self_emissive:
        # M15 owns the joint HDR/ABL/color-volume capacity after this stage.
        # Preserve over-peak chromaticity until that single common-gain map.
        emitted = (
            np.clip(frame.rgb, 0.0, None)
            if defer_emissive_peak
            else np.clip(frame.rgb, 0.0, np.float32(peak_nits))
        )
        if psf is not None:
            emitted = spread_emission(emitted, psf)
        if angular_active:
            from tv_sim.stages.viewing_angle import emissive_angular_gain

            emitted = emissive_angular_gain(
                emitted,
                cast(ViewingAngleConfig, viewing_angle),
                cast(EmissiveAngularParams, angular_params),
            )
    else:
        if angular_active:
            from tv_sim.stages.viewing_angle import lcd_angular_transmit

            emitted = lcd_angular_transmit(
                frame.rgb,
                frame.backlight,
                params.native_contrast,
                cast(ViewingAngleConfig, viewing_angle),
                cast(LcdAngularParams, angular_params),
            )
        else:
            emitted = lcd_transmit(frame.rgb, frame.backlight, params.native_contrast)
    emitted = apply_matrix(emitted, _matrix(params.color_matrix))
    mosaic = render_subpixels(emitted, params.subpixel)
    emitted = composite_subpixels(mosaic, params.subpixel)
    if not angular_active:
        emitted = apply_viewing_angle(emitted, params.viewing_angle_deg, params.angle_loss_per_deg)
    emitted = np.clip(emitted, 0.0, None)
    return Frame(emitted, frame.backlight)
