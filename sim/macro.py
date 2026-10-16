"""Illustrative subpixel apertures for a close-up, in linear RGB nits.

The renderer expands each *square logical pixel* into a square of samples.
RGB stripes, an R/W/B/G allocation and a triangular RGB repeat illustrate
layout families; their aperture dimensions, fill factor and white allocation
are synthetic. The QD-OLED repeat is not a measured mask or a claim about
PenTile resolution. No spectral or physical emitter-radiance model is used.

Each aperture is normalized to unit mean over its logical pixel. Consequently
averaging a rendered cell recovers the input RGB, even when the black matrix
or geometry changes. Aperture peaks can exceed the input nits: they encode
the unresolved channel's light in a smaller area, not measured emitter peaks.
Apply one shared preview transform across TVs after rendering. Do not add
this visible grid to the normal, distant-view pipeline output.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np


LAYOUT_LABELS = {
    "rgb_stripe": "RGB stripes; synthetic apertures",
    "wrgb": "WRGB, R/W/B/G repeat; synthetic apertures and white allocation",
    "qd_oled": "QD-OLED triangular staggered RGB; synthetic, no pixel sharing",
}


def _clip_polygon(
    polygon: np.ndarray, normal: np.ndarray, limit: float
) -> np.ndarray:
    """Clip a convex polygon to ``point @ normal <= limit``."""

    clipped = []
    for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
        start_distance = float(start @ normal - limit)
        end_distance = float(end @ normal - limit)
        start_inside = start_distance <= 0.0
        end_inside = end_distance <= 0.0
        if start_inside:
            clipped.append(start)
        if start_inside != end_inside:
            fraction = start_distance / (start_distance - end_distance)
            clipped.append(start + fraction * (end - start))
    return np.asarray(clipped, dtype=np.float64)


def _polygons(layout: str, parity: int) -> tuple[np.ndarray, list[np.ndarray]]:
    if layout == "rgb_stripe":
        centers = np.array([(1 / 6, 0.5), (0.5, 0.5), (5 / 6, 0.5)])
    elif layout == "wrgb":
        centers = np.array([(0.125, 0.5), (0.375, 0.5), (0.625, 0.5), (0.875, 0.5)])
    else:
        # Emitter order R,G,B. Green is above red/blue; alternating the small
        # offsets gives a visibly staggered repeat without sharing pixels.
        centers = np.array(
            [(0.23, 0.74), (0.46, 0.21), (0.75, 0.71)]
            if parity == 0
            else [(0.25, 0.71), (0.54, 0.21), (0.77, 0.74)]
        )
    polygons = []
    for index, center in enumerate(centers):
        polygon = np.array([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        for other_index, other in enumerate(centers):
            if index != other_index:
                normal = other - center
                limit = float((other @ other - center @ center) / 2.0)
                polygon = _clip_polygon(polygon, normal, limit)
        polygons.append(polygon)
    return centers, polygons


@lru_cache(maxsize=48)
def _apertures(layout: str, scale: int, fill_factor: float, parity: int) -> np.ndarray:
    """Antialiased masks, normalized independently to unit cell mean."""

    supersample = 4
    samples = scale * supersample
    coordinate = (np.arange(samples, dtype=np.float64) + 0.5) / samples
    xx, yy = np.meshgrid(coordinate, coordinate)
    centers, polygons = _polygons(layout, parity)
    masks = []
    for center, polygon in zip(centers, polygons):
        # Homothetic shrink preserves polygon topology and makes continuous
        # total aperture area equal to fill_factor before raster sampling.
        polygon = center + np.sqrt(fill_factor) * (polygon - center)
        inside = np.ones((samples, samples), dtype=bool)
        for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
            edge = end - start
            inside &= edge[0] * (yy - start[1]) - edge[1] * (xx - start[0]) >= -1e-12
        coverage = inside.reshape(scale, supersample, scale, supersample).mean(axis=(1, 3))
        area = float(coverage.mean())
        if area == 0.0:
            raise ValueError("fill_factor is too small to resolve at this scale")
        masks.append(coverage / area)
    masks = np.asarray(masks, dtype=np.float32)
    masks.setflags(write=False)
    return masks


def render_macro(
    rgb: np.ndarray,
    layout: str,
    *,
    scale: int = 18,
    fill_factor: float = 0.72,
    white_fraction: float = 0.65,
) -> np.ndarray:
    """Expand an ``H x W x 3`` linear-nit crop to ``H*scale x W*scale x 3``.

    ``scale`` counts preview samples per logical-pixel side, not subpixels
    or physical magnification. ``fill_factor`` is the synthetic total active
    area fraction; coverage is antialiased with four samples per output axis.
    In WRGB, ``white_fraction * min(R,G,B)`` is sent to W and subtracted from
    each colored channel. The default deliberately leaves RGB active on
    neutral pixels so all four apertures can be inspected. This allocation
    is illustrative and differs from the pipeline's all-common-light W proxy.

    Values are returned unclipped. Box-averaging each logical cell preserves
    the input light, so comparisons can keep a common exposure.
    """

    if layout not in LAYOUT_LABELS:
        raise ValueError(f"Unknown subpixel layout {layout!r}")
    if isinstance(scale, bool) or not isinstance(scale, (int, np.integer)) or scale < 4:
        raise ValueError("scale must be an integer >= 4")
    if not np.isfinite(fill_factor) or not 0.0 < fill_factor <= 1.0:
        raise ValueError("fill_factor must be finite and in (0, 1]")
    if not np.isfinite(white_fraction) or not 0.0 <= white_fraction <= 1.0:
        raise ValueError("white_fraction must be finite and in [0, 1]")
    image = np.asarray(rgb, dtype=np.float32)
    if image.ndim != 3 or image.shape[-1] != 3 or min(image.shape[:2]) < 1:
        raise ValueError("rgb must be a nonempty H x W x 3 image")
    if not np.isfinite(image).all() or np.any(image < 0.0):
        raise ValueError("rgb must contain finite, nonnegative linear nits")

    height, width = image.shape[:2]
    output = np.zeros((height, scale, width, scale, 3), dtype=np.float32)
    if layout == "wrgb":
        white = np.min(image, axis=-1) * np.float32(white_fraction)
        residual = image - white[..., None]
        emitters = (
            (residual[..., 0], (1.0, 0.0, 0.0)),
            (white, (1.0, 1.0, 1.0)),
            (residual[..., 2], (0.0, 0.0, 1.0)),
            (residual[..., 1], (0.0, 1.0, 0.0)),
        )
    else:
        emitters = tuple((image[..., channel], np.eye(3)[channel]) for channel in range(3))

    for parity in (0, 1):
        rows = slice(parity, None, 2)
        masks = _apertures(layout, int(scale), float(fill_factor), parity)
        for mask, (drive, color) in zip(masks, emitters):
            output[rows] += (
                drive[rows, None, :, None, None]
                * mask[None, :, None, :, None]
                * np.asarray(color, dtype=np.float32)
            )
    return output.reshape(height * scale, width * scale, 3)
