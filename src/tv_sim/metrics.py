"""Radiometric metrics for validation patterns.

These helpers score luminance arrays in nits. They do not render frames and
they do not read TV profiles. A black level at or below ``BLACK_FLOOR_NITS``
does not produce a contrast ratio: a synthetic zero is left undefined rather
than reported as infinite contrast.

Definitions
-----------
ANSI contrast
    Mean luminance of the white cells over the mean of the black cells on a
    4×4 checker. Each cell contributes its central region (default inset 25%
    per side) so the score is the cell center, which is the usual ANSI sample.
    Top-left is black, matching :func:`tv_sim.patterns.checkerboard`.

Window peak
    Mean luminance of the center of a rectangular white window.

Bloom
    Mean luminance in a Chebyshev ring just outside the window (distances
    ``1 .. near_px``). ``bloom_excess_nits`` subtracts the same pixels of a
    full-field black frame when one is supplied. Far-field black is the mean
    at distance ``>= far_px``. A window that covers the frame has no outside
    samples; those fields are ``None``.

ABL ratio
    Window peak divided by the peak of a reference window (the smallest one
    in the sweep).

EOTF tracking
    On a 1-D ramp, mean absolute relative error where the ideal luminance is
    at least ``rel_floor_nits``, and mean absolute error in nits below that.
    The clipping code is the first code whose measured luminance reaches
    ``clip_fraction`` of the measured peak while the ideal curve still grows
    and the measured curve does not. An unclipped ramp has clipping code
    ``None``.

MPRT-style blur width
    Distance in pixels between the 10% and 90% points of a 1-D edge, using
    the median of each end as the dark and bright plateau. Time in
    milliseconds is ``width_px * frame_time_ms / motion_px_per_frame`` at the
    pursuit speed. Quadrature removal of a still-edge width is only a rough
    split. When backlight spread dominates, the temporal width has to be
    measured on a sharp step that never sees that spread. Quadrature removal of a still-edge width is only a rough
    split. When the still edge is wide (backlight spread), the pursuit width
    mostly repeats that spread. The temporal-only width is measured on an
    ideal step that never sees the backlight.
"""

from __future__ import annotations

import numpy as np

BLACK_FLOOR_NITS = 1e-4


def contrast_ratio(
    white_nits: float,
    black_nits: float,
    black_floor: float = BLACK_FLOOR_NITS,
) -> float | None:
    """White/black ratio, or ``None`` when black is at or below the floor."""

    white = float(white_nits)
    black = float(black_nits)
    if not np.isfinite(white) or not np.isfinite(black):
        return None
    if black <= float(black_floor) or white < 0.0:
        return None
    return white / black


def ansi_cell_means(
    luminance: np.ndarray,
    cells: int = 4,
    inset_fraction: float = 0.25,
) -> tuple[float, float]:
    """``(white_mean, black_mean)`` for a ``cells``×``cells`` checker.

    Top-left is black. ``inset_fraction`` trims each side of a cell before
    the mean; 0.25 keeps the central half.
    """

    if cells < 1:
        raise ValueError("cells must be >= 1")
    image = np.asarray(luminance, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError("luminance must be a 2-D array")
    height, width = image.shape
    cell_h, cell_w = height // cells, width // cells
    if cell_h < 1 or cell_w < 1:
        raise ValueError("image is smaller than the checker grid")
    inset = float(inset_fraction)
    if not 0.0 <= inset < 0.5:
        raise ValueError("inset_fraction must be in [0, 0.5)")
    whites: list[float] = []
    blacks: list[float] = []
    for iy in range(cells):
        for ix in range(cells):
            block = image[iy * cell_h : (iy + 1) * cell_h, ix * cell_w : (ix + 1) * cell_w]
            y_pad = int(block.shape[0] * inset)
            x_pad = int(block.shape[1] * inset)
            if y_pad > 0 and x_pad > 0:
                block = block[y_pad:-y_pad, x_pad:-x_pad]
            target = whites if (iy + ix) % 2 == 1 else blacks
            target.append(float(np.mean(block)))
    return float(np.mean(whites)), float(np.mean(blacks))


def ansi_contrast(
    luminance: np.ndarray,
    cells: int = 4,
    inset_fraction: float = 0.25,
    black_floor: float = BLACK_FLOOR_NITS,
) -> dict[str, float | None]:
    """White and black cell means and their ratio."""

    white, black = ansi_cell_means(luminance, cells=cells, inset_fraction=inset_fraction)
    return {
        "white_nits": white,
        "black_nits": black,
        "contrast_ratio": contrast_ratio(white, black, black_floor=black_floor),
    }


def rectangle_chebyshev_distance(
    height: int,
    width: int,
    y0: int,
    y1: int,
    x0: int,
    x1: int,
) -> np.ndarray:
    """Chebyshev distance to a half-open rectangle. Inside pixels are 0."""

    if not (0 <= y0 <= y1 <= height and 0 <= x0 <= x1 <= width):
        raise ValueError("rectangle is outside the image")
    yy = np.arange(height, dtype=np.int32)[:, None]
    xx = np.arange(width, dtype=np.int32)[None, :]
    dy = np.where(yy < y0, y0 - yy, np.where(yy >= y1, yy - (y1 - 1), 0))
    dx = np.where(xx < x0, x0 - xx, np.where(xx >= x1, xx - (x1 - 1), 0))
    return np.maximum(dy, dx)


def window_peak_nits(luminance: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> float:
    """Mean of the central half of the window, or the whole window if it is tiny."""

    block = np.asarray(luminance, dtype=np.float64)[y0:y1, x0:x1]
    if block.size == 0:
        raise ValueError("window is empty")
    height, width = block.shape
    y_pad = height // 4 if height >= 8 else 0
    x_pad = width // 4 if width >= 8 else 0
    if y_pad > 0 and x_pad > 0:
        block = block[y_pad:-y_pad, x_pad:-x_pad]
    return float(np.mean(block))


def window_bloom(
    luminance: np.ndarray,
    y0: int,
    y1: int,
    x0: int,
    x1: int,
    *,
    near_px: int = 4,
    far_px: int = 16,
    black_luminance: np.ndarray | None = None,
) -> dict[str, float | None]:
    """Peak inside the window and black-level bloom just outside it.

    ``bloom_excess_nits`` is the near-ring mean after subtracting the same
    pixels of ``black_luminance`` when that frame is given. Without it, the
    excess is near-ring minus far-field on this frame. Full-frame windows
    leave the outside fields as ``None``.
    """

    image = np.asarray(luminance, dtype=np.float64)
    if near_px < 1:
        raise ValueError("near_px must be >= 1")
    if far_px <= near_px:
        raise ValueError("far_px must be greater than near_px")
    height, width = image.shape
    distance = rectangle_chebyshev_distance(height, width, y0, y1, x0, x1)
    peak = window_peak_nits(image, y0, y1, x0, x1)
    near = (distance >= 1) & (distance <= int(near_px))
    far = distance >= int(far_px)
    halo = float(np.mean(image[near])) if np.any(near) else None
    far_black = float(np.mean(image[far])) if np.any(far) else None
    excess: float | None
    if halo is None:
        excess = None
    elif black_luminance is not None:
        black = np.asarray(black_luminance, dtype=np.float64)
        if black.shape != image.shape:
            raise ValueError("black_luminance shape does not match the window frame")
        excess = halo - float(np.mean(black[near]))
    elif far_black is not None:
        excess = halo - far_black
    else:
        excess = None
    above_far = None if halo is None or far_black is None else halo - far_black
    return {
        "peak_nits": peak,
        "halo_nits": halo,
        "far_black_nits": far_black,
        "bloom_excess_nits": excess,
        "bloom_above_far_nits": above_far,
    }


def abl_ratios(peak_nits: list[float], reference_index: int = 0) -> list[float | None]:
    """Each peak divided by ``peak_nits[reference_index]``."""

    if reference_index < 0 or reference_index >= len(peak_nits):
        raise ValueError("reference_index is outside the peak list")
    reference = float(peak_nits[reference_index])
    if not np.isfinite(reference) or reference <= BLACK_FLOOR_NITS:
        return [None] * len(peak_nits)
    ratios: list[float | None] = []
    for peak in peak_nits:
        value = float(peak)
        ratios.append(None if not np.isfinite(value) else value / reference)
    return ratios


def eotf_tracking(
    measured_nits: np.ndarray,
    ideal_nits: np.ndarray,
    codes: np.ndarray,
    *,
    rel_floor_nits: float = 1.0,
    clip_fraction: float = 0.95,
    ideal_growth: float = 0.20,
    measured_growth: float = 0.05,
) -> dict[str, float | None]:
    """Relative tracking error and a clipping code along one ramp.

    Clipping is recorded only when the measured curve has reached
    ``clip_fraction`` of its peak, the ideal luminance still rises by more
    than ``ideal_growth`` after that code, and the measured luminance rises
    by less than ``measured_growth`` of its peak. Otherwise ``clipping_code``
    is ``None``.
    """

    measured = np.asarray(measured_nits, dtype=np.float64).reshape(-1)
    ideal = np.asarray(ideal_nits, dtype=np.float64).reshape(-1)
    code = np.asarray(codes, dtype=np.float64).reshape(-1)
    if measured.shape != ideal.shape or measured.shape != code.shape:
        raise ValueError("measured, ideal, and codes must have the same length")
    if measured.size == 0:
        raise ValueError("ramp is empty")
    above = ideal >= float(rel_floor_nits)
    relative = (
        np.abs(measured[above] - ideal[above]) / np.maximum(ideal[above], 1e-12)
        if np.any(above)
        else np.empty(0, dtype=np.float64)
    )
    near = np.abs(measured[~above] - ideal[~above]) if np.any(~above) else np.empty(0)
    clipping_code: float | None = None
    clipping_nits: float | None = None
    peak = float(np.max(measured))
    if peak > 0.0 and 0.0 < clip_fraction <= 1.0:
        hits = np.flatnonzero(measured >= clip_fraction * peak)
        if hits.size:
            index = int(hits[0])
            ideal_at = float(ideal[index])
            ideal_grew = (float(ideal[-1]) - ideal_at) / max(abs(ideal_at), 1e-6)
            measured_grew = (float(measured[-1]) - float(measured[index])) / peak
            if ideal_grew > ideal_growth and measured_grew < measured_growth:
                clipping_code = float(code[index])
                clipping_nits = float(measured[index])
    return {
        "mean_abs_rel_error": float(np.mean(relative)) if relative.size else None,
        "max_abs_rel_error": float(np.max(relative)) if relative.size else None,
        "mean_abs_error_nits_near_black": float(np.mean(near)) if near.size else None,
        "clipping_code": clipping_code,
        "clipping_nits": clipping_nits,
    }


def _first_upward_crossing(samples: np.ndarray, threshold: float) -> float | None:
    above = np.flatnonzero(samples >= threshold)
    if above.size == 0:
        return None
    index = int(above[0])
    if index == 0:
        return 0.0
    y0 = float(samples[index - 1])
    y1 = float(samples[index])
    if y1 == y0:
        return float(index)
    return (index - 1) + (threshold - y0) / (y1 - y0)


def moving_edge_blur_px(
    profile: np.ndarray,
    *,
    low: float = 0.10,
    high: float = 0.90,
    plateau_fraction: float = 0.15,
) -> float | None:
    """10–90% width, in pixels, of an edge profile. ``None`` if there is no edge."""

    samples = np.asarray(profile, dtype=np.float64).reshape(-1)
    if samples.size < 4:
        raise ValueError("edge profile is too short")
    if not 0.0 < low < high < 1.0:
        raise ValueError("need 0 < low < high < 1")
    count = max(1, int(round(samples.size * float(plateau_fraction))))
    left = float(np.median(samples[:count]))
    right = float(np.median(samples[-count:]))
    if abs(right - left) <= BLACK_FLOOR_NITS:
        return None
    oriented = samples if right >= left else samples[::-1]
    dark = min(left, right)
    bright = max(left, right)
    span = bright - dark
    x_low = _first_upward_crossing(oriented, dark + low * span)
    x_high = _first_upward_crossing(oriented, dark + high * span)
    if x_low is None or x_high is None:
        return None
    return abs(x_high - x_low)


def motion_blur_px(moving_px: float | None, still_px: float | None) -> float | None:
    """Rough motion share of a 10–90% width, still edge removed in quadrature.

    This is not the temporal-only width. A wide static backlight edge barely
    grows under a short pursuit smear, so the quadrature remainder does not
    equal the smear of a sharp step. The result is ``None`` when either width
    is missing.
    """

    if moving_px is None or still_px is None:
        return None
    return float(np.sqrt(max(0.0, float(moving_px) ** 2 - float(still_px) ** 2)))


def blur_width_ms(
    blur_px: float | None, motion_px_per_frame: float, frame_time_ms: float
) -> float | None:
    """Convert a pursuit blur width to milliseconds at the eye's tracking speed."""

    if blur_px is None:
        return None
    if motion_px_per_frame == 0.0:
        raise ValueError("motion_px_per_frame must be non-zero to convert blur to time")
    return float(blur_px) * float(frame_time_ms) / float(motion_px_per_frame)
