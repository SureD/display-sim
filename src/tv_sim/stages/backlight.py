"""Backlight and local dimming.

Zone model aligned with ``docs/research/02``. For a regular grid the backlight is

``B = clip(PSF(upsample(d)), floor, peak)``

where ``d_j`` is the zone demand (max channel, or a lower percentile) and PSF
is a unit-sum mixture of two separable Gaussians:

``h = (1 - a) G(σ_core) + a G(σ_tail)``.

That mixture is a normalized stand-in for ``B_i = Σ_j H_ij d_j`` on a regular
grid. A dense influence matrix is not built. Kernels are normalized once for
the whole frame (DC gain 1), so a uniform full-drive field is unchanged
before the peak clip. Each zone's footprint is **not** renormalized after
edge clipping: doing that would invent edge brightness (docs/research/02).

Assumptions, none of them measurements:

* Demand is ``max(R, G, B)`` in nits. The picture is already absolute light,
  not a 0–1 code, and there is no separate backlight spectrum.
* ``psf_sigma_*_zones`` are core sigmas in zone-pitch units. Pixel sigma is
  that value times the zone pitch along the same axis. ``per_pixel`` skips
  the grid and reads the same fields as pixel sigmas; 0 is no bloom. On the
  ``per_pixel`` path the map stored here is the emitter drive, and the
  spread is applied to emitted RGB in :mod:`tv_sim.stages.panel` instead:
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

from tv_sim.filters import (
    exponential_kernel1d,
    gaussian_kernel1d,
    separable_convolve,
)
from tv_sim.frame import Frame
from tv_sim.profile import BacklightParams


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
    percentile is the docs/research/02 robust heuristic and can drop tiny peaks.
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


def pool_max(
    drive: np.ndarray, zones_y: int, zones_x: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Max-pool ``drive`` into a zone grid. Returns zones and the edge arrays."""

    return pool_zones(drive, zones_y, zones_x, 100.0)


def upsample_zones(
    zones: np.ndarray, y_edges: np.ndarray, x_edges: np.ndarray, shape: tuple[int, int]
) -> np.ndarray:
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


def table_kernel1d(samples: list[float] | np.ndarray, step_px: float) -> np.ndarray:
    """Unit-sum 1D kernel from a half-profile LSF sampled every ``step_px``."""

    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 1 or values.size < 2:
        raise ValueError("an LSF table needs at least two samples")
    if np.any(values < 0.0):
        raise ValueError("LSF samples must be nonnegative")
    if values[0] <= 0.0:
        raise ValueError("the LSF table must start with a positive centre sample")
    if step_px <= 0.0:
        raise ValueError("psf_profile step must be positive")
    radius = int(np.floor((values.size - 1) * step_px))
    if radius < 1:
        raise ValueError(
            f"LSF table spans {(values.size - 1) * step_px:.3f} px, which cannot "
            "fill a one-pixel radius; use a coarser step or more samples"
        )
    offsets = np.abs(np.arange(-radius, radius + 1, dtype=np.float64)) / step_px
    kernel = np.interp(offsets, np.arange(values.size, dtype=np.float64), values)
    total = kernel.sum()
    if total <= 0.0:
        raise ValueError("LSF table resampled to zero total response")
    return kernel / total


def psf_axis_kernels(
    params: BacklightParams,
    *,
    zone_pitch_y: float,
    zone_pitch_x: float,
    per_pixel: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Core and tail 1D kernels for x and y, plus the tail weight.

    Both components are unit-sum, so the 2D mixture
    ``(1 - a) K_core + a K_tail`` is unit-sum as well.
    """

    core_x, core_y, tail_x, tail_y = psf_pixel_sigmas(
        params, zone_pitch_y=zone_pitch_y, zone_pitch_x=zone_pitch_x, per_pixel=per_pixel
    )
    shape = str(params.psf_shape).lower()
    if shape == "gaussian":
        tail_kx = gaussian_kernel1d(tail_x)
        tail_ky = gaussian_kernel1d(tail_y)
    elif shape == "exponential_tail":
        tail_kx = exponential_kernel1d(tail_x)
        tail_ky = exponential_kernel1d(tail_y)
    else:
        raise ValueError(
            f"Unknown psf_shape {params.psf_shape!r}. Use gaussian or exponential_tail."
        )
    core_kx = gaussian_kernel1d(core_x)
    core_ky = gaussian_kernel1d(core_y)
    table = params.psf_profile
    if table is not None:
        pitch_x = 1.0 if per_pixel else zone_pitch_x
        pitch_y = 1.0 if per_pixel else zone_pitch_y
        step = float(table.step_zones)
        if table.x is not None:
            core_kx = tail_kx = table_kernel1d(table.x, step * pitch_x)
        if table.y is not None:
            core_ky = tail_ky = table_kernel1d(table.y, step * pitch_y)
    return core_kx, core_ky, tail_kx, tail_ky, float(params.psf_tail_weight)


def apply_light_spread(
    field: np.ndarray,
    kernels: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float],
    boundary: str = "reflect",
) -> np.ndarray:
    """Unit-sum two-component separable spread. ``tail_weight`` 0 skips the tail.

    ``calibrated_zero`` divides by the all-on response so a border zone keeps
    its commanded drive without mirroring light inward; ``zero`` leaves the
    border short, which is what an uncompensated panel edge does.
    """

    core_kx, core_ky, tail_kx, tail_ky, tail_weight = kernels
    if boundary == "calibrated_zero":
        pad = "zero"
    elif boundary in {"reflect", "zero"}:
        pad = boundary
    else:
        raise ValueError(
            f"Unknown psf_boundary {boundary!r}. Use reflect, zero, or calibrated_zero."
        )

    def spread(data: np.ndarray) -> np.ndarray:
        core = separable_convolve(data, core_kx, core_ky, boundary=pad)
        weight = min(max(float(tail_weight), 0.0), 1.0)
        if weight <= 1e-8:
            return core
        tail = separable_convolve(data, tail_kx, tail_ky, boundary=pad)
        return ((1.0 - weight) * core + weight * tail).astype(np.float32)

    spread_field = spread(np.asarray(field, dtype=np.float32))
    if boundary != "calibrated_zero":
        return spread_field.astype(np.float32)
    all_on = spread(np.ones_like(spread_field, dtype=np.float32))
    return (spread_field / np.maximum(all_on, np.float32(1e-6))).astype(np.float32)


def simulate_backlight(
    frame: Frame,
    params: BacklightParams,
    *,
    peak_scale: float = 1.0,
) -> Frame:
    """Attach a nit backlight map. The linear image is left as the target picture.

    ``peak_scale`` derates the drive cap, which is how :mod:`tv_sim.load` passes
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
    kernels = psf_axis_kernels(
        params,
        zone_pitch_y=zone_h,
        zone_pitch_x=zone_w,
        per_pixel=False,
    )
    if any(kernel.size > 1 for kernel in kernels[:2]) or (
        kernels[4] > 1e-8 and any(kernel.size > 1 for kernel in kernels[2:4])
    ):
        backlight = apply_light_spread(backlight, kernels, params.psf_boundary)
    floor = np.float32(params.floor_nits)
    peak = np.float32(float(params.peak_nits) * float(peak_scale))
    backlight = np.clip(np.maximum(backlight, floor), 0.0, peak)
    return Frame(frame.rgb, backlight)
