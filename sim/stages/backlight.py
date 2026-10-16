"""Backlight and local dimming.

Zone model aligned with ``research/02``. For a regular grid the backlight is

``B = clip(PSF(upsample(d)), floor, peak)``

where ``d_j`` is the zone demand (max channel, or a lower percentile) and PSF
is a unit-sum mixture of two separable Gaussians:

``h = (1 - a) G(σ_core) + a G(σ_tail)``.

That mixture is a normalized stand-in for ``B_i = Σ_j H_ij d_j`` on a regular
grid. A dense influence matrix is not built. Kernels are normalized once for
the whole frame (DC gain 1), so a uniform full-drive field is unchanged
before the peak clip. Each zone's footprint is **not** renormalized after
edge clipping: doing that would invent edge brightness (research/02).

Assumptions, none of them measurements:

* Demand is ``max(R, G, B)`` in nits. The picture is already absolute light,
  not a 0–1 code, and there is no separate backlight spectrum.
* ``psf_sigma_*_zones`` are core sigmas in zone-pitch units. Pixel sigma is
  that value times the zone pitch along the same axis. ``per_pixel`` skips
  the grid and reads the same fields as pixel sigmas; 0 is no bloom. On the
  ``per_pixel`` path the map stored here is the emitter drive, and the
  spread is applied to emitted RGB in :mod:`sim.stages.panel` instead:
  blurring a max-channel map and then throwing it away (which is what this
  stage used to do) moved no light at all.
* Tail weight ``a`` defaults to 0 (single Gaussian). The research prior for
  a synthetic direct-lit profile is core 0.2–0.8 pitches, tail 1–3 pitches,
  ``a`` in 0–0.15. Those ranges are modeling choices.
* ``edge`` keeps column behavior by using full-height strips (``zones_y``
  1). A vertically constant strip stays vertically constant under any
  vertical sigma. The light guide is not a measured elongated LSF.
* Reflect or edge padding is only a boundary approximation.
* No zone lag, power cap, or iterative LCD/backlight solver here.
"""

from __future__ import annotations

import numpy as np

from sim.filters import gaussian_blur_xy
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


def pool_zones(
    drive: np.ndarray,
    zones_y: int,
    zones_x: int,
    percentile: float = 100.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pool ``drive`` into a zone grid.

    Percentile 100 is the zone maximum (small highlights are kept). A lower
    percentile is the research/02 robust heuristic and can drop tiny peaks.
    """

    height, width = drive.shape
    y_edges = zone_edges(height, zones_y)
    x_edges = zone_edges(width, zones_x)
    zones = np.zeros((len(y_edges) - 1, len(x_edges) - 1), dtype=np.float32)
    use_max = float(percentile) >= 100.0
    pct = float(np.clip(percentile, 0.0, 100.0))
    for iy in range(zones.shape[0]):
        y0, y1 = int(y_edges[iy]), int(y_edges[iy + 1])
        for ix in range(zones.shape[1]):
            x0, x1 = int(x_edges[ix]), int(x_edges[ix + 1])
            block = drive[y0:y1, x0:x1]
            zones[iy, ix] = block.max() if use_max else np.percentile(block, pct)
    return zones, y_edges, x_edges


def pool_max(drive: np.ndarray, zones_y: int, zones_x: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Max-pool ``drive`` into a zone grid. Returns zones and the edge arrays."""

    return pool_zones(drive, zones_y, zones_x, 100.0)


def upsample_zones(zones: np.ndarray, y_edges: np.ndarray, x_edges: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbor expansion of a zone grid to a pixel map."""

    out = np.empty(shape, dtype=np.float32)
    for iy in range(zones.shape[0]):
        y0, y1 = int(y_edges[iy]), int(y_edges[iy + 1])
        for ix in range(zones.shape[1]):
            x0, x1 = int(x_edges[ix]), int(x_edges[ix + 1])
            out[y0:y1, x0:x1] = zones[iy, ix]
    return out


def _axis_sigma(primary: float, override: float | None, pitch: float) -> float:
    zones = primary if override is None else override
    return float(zones) * float(pitch)


def psf_pixel_sigmas(
    params: BacklightParams,
    *,
    zone_pitch_y: float,
    zone_pitch_x: float,
    per_pixel: bool,
) -> tuple[float, float, float, float]:
    """Core and tail ``(sigma_x, sigma_y)`` in pixels.

    Zoned modes convert zone-pitch sigmas using the pitch of each axis.
    ``per_pixel`` treats the same numbers as pixels.
    """

    if per_pixel:
        pitch_y = pitch_x = 1.0
    else:
        pitch_y = zone_pitch_y
        pitch_x = zone_pitch_x
    core_x = _axis_sigma(params.psf_sigma_zones, None, pitch_x)
    core_y = _axis_sigma(params.psf_sigma_zones, params.psf_sigma_y_zones, pitch_y)
    tail_x = _axis_sigma(params.psf_tail_sigma_zones, None, pitch_x)
    tail_y = _axis_sigma(params.psf_tail_sigma_zones, params.psf_tail_sigma_y_zones, pitch_y)
    return core_x, core_y, tail_x, tail_y


def apply_light_spread(
    field: np.ndarray,
    sigma_x: float,
    sigma_y: float,
    tail_sigma_x: float,
    tail_sigma_y: float,
    tail_weight: float,
) -> np.ndarray:
    """Unit-sum two-component separable Gaussian. ``tail_weight`` 0 skips the tail."""

    core = gaussian_blur_xy(field, sigma_x, sigma_y)
    weight = float(tail_weight)
    if weight <= 1e-8:
        return core
    weight = min(weight, 1.0)
    tail = gaussian_blur_xy(field, tail_sigma_x, tail_sigma_y)
    mixed = (1.0 - weight) * core + weight * tail
    return mixed.astype(np.float32)


def simulate_backlight(
    frame: Frame,
    params: BacklightParams,
    *,
    peak_scale: float = 1.0,
) -> Frame:
    """Attach a nit backlight map. The linear image is left as the target picture.

    ``peak_scale`` derates the drive cap, which is how :mod:`sim.load` passes
    an LCD power limit down to the backlight. 1 leaves the profile cap alone.
    """

    if not 0.0 < float(peak_scale) <= 1.0:
        raise ValueError("peak_scale must be in (0, 1]")
    if params.mode not in {"fald", "edge", "per_pixel"}:
        raise ValueError(f"Unknown backlight mode {params.mode!r}")
    if params.psf_tail_weight < 0.0:
        raise ValueError("psf_tail_weight must be >= 0")
    drive = np.max(frame.rgb, axis=-1).astype(np.float32)
    height, width = drive.shape
    if params.mode == "per_pixel":
        floor = np.float32(params.floor_nits)
        peak = np.float32(float(params.peak_nits) * float(peak_scale))
        return Frame(frame.rgb, np.clip(np.maximum(drive, floor), 0.0, peak))
    # ``edge`` with zones_y == 1 is one full-height strip per column.
    zones, y_edges, x_edges = pool_zones(
        drive, params.zones_y, params.zones_x, params.zone_percentile
    )
    backlight = upsample_zones(zones, y_edges, x_edges, (height, width))
    zone_h = height / zones.shape[0]
    zone_w = width / zones.shape[1]
    sigma_x, sigma_y, tail_x, tail_y = psf_pixel_sigmas(
        params,
        zone_pitch_y=zone_h,
        zone_pitch_x=zone_w,
        per_pixel=False,
    )
    weight = float(params.psf_tail_weight)
    if max(sigma_x, sigma_y, tail_x * weight, tail_y * weight) > 1e-6:
        backlight = apply_light_spread(
            backlight, sigma_x, sigma_y, tail_x, tail_y, params.psf_tail_weight
        )
    floor = np.float32(params.floor_nits)
    peak = np.float32(float(params.peak_nits) * float(peak_scale))
    backlight = np.clip(np.maximum(backlight, floor), 0.0, peak)
    return Frame(frame.rgb, backlight)
