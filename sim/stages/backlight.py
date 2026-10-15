"""Backlight and local dimming.

LCD modes pool the frame into a zone grid (max channel in each zone), stretch
that grid back to pixels, and blur it with a Gaussian stand-in for the optical
light-spread function. A full-screen white field stays flat because the kernel
sums to one.

``per_pixel`` skips the grid. The drive at each pixel is the max RGB channel,
which matches a self-emissive panel with no optical bloom when sigma is 0.
"""

from __future__ import annotations

import numpy as np

from sim.filters import gaussian_blur
from sim.frame import Frame
from sim.profile import BacklightParams


def zone_edges(length: int, zones: int) -> np.ndarray:
    """Pixel boundaries for ``zones`` slices covering ``length`` pixels."""

    zones = max(1, min(int(zones), int(length)))
    edges = np.round(np.linspace(0, length, zones + 1)).astype(int)
    for index in range(1, len(edges)):
        if edges[index] <= edges[index - 1]:
            edges[index] = min(length, edges[index - 1] + 1)
    edges[-1] = length
    return edges


def pool_max(drive: np.ndarray, zones_y: int, zones_x: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Max-pool ``drive`` into a zone grid. Returns zones and the edge arrays."""

    height, width = drive.shape
    y_edges = zone_edges(height, zones_y)
    x_edges = zone_edges(width, zones_x)
    zones = np.zeros((len(y_edges) - 1, len(x_edges) - 1), dtype=np.float32)
    for iy in range(zones.shape[0]):
        y0, y1 = int(y_edges[iy]), int(y_edges[iy + 1])
        for ix in range(zones.shape[1]):
            x0, x1 = int(x_edges[ix]), int(x_edges[ix + 1])
            zones[iy, ix] = drive[y0:y1, x0:x1].max()
    return zones, y_edges, x_edges


def upsample_zones(zones: np.ndarray, y_edges: np.ndarray, x_edges: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbor expansion of a zone grid to a pixel map."""

    out = np.empty(shape, dtype=np.float32)
    for iy in range(zones.shape[0]):
        y0, y1 = int(y_edges[iy]), int(y_edges[iy + 1])
        for ix in range(zones.shape[1]):
            x0, x1 = int(x_edges[ix]), int(x_edges[ix + 1])
            out[y0:y1, x0:x1] = zones[iy, ix]
    return out


def _sigma_px(params: BacklightParams, zones: np.ndarray, shape: tuple[int, int]) -> float:
    height, width = shape
    zone_h = height / zones.shape[0]
    zone_w = width / zones.shape[1]
    return float(params.psf_sigma_zones) * 0.5 * (zone_h + zone_w)


def simulate_backlight(frame: Frame, params: BacklightParams) -> Frame:
    """Attach a nit backlight map. The linear image is left as the target picture."""

    if params.mode not in {"fald", "edge", "per_pixel"}:
        raise ValueError(f"Unknown backlight mode {params.mode!r}")
    drive = np.max(frame.rgb, axis=-1).astype(np.float32)
    height, width = drive.shape
    if params.mode == "per_pixel":
        # Sigma is in pixels here. Zone units would not mean anything, and
        # zero is a panel with no optical crosstalk.
        backlight = drive
        sigma = float(params.psf_sigma_zones)
    else:
        zones, y_edges, x_edges = pool_max(drive, params.zones_y, params.zones_x)
        backlight = upsample_zones(zones, y_edges, x_edges, (height, width))
        sigma = _sigma_px(params, zones, (height, width))
    if sigma > 1e-6:
        backlight = gaussian_blur(backlight, sigma)
    floor = np.float32(params.floor_nits)
    peak = np.float32(params.peak_nits)
    backlight = np.clip(np.maximum(backlight, floor), 0.0, peak)
    return Frame(frame.rgb, backlight)
