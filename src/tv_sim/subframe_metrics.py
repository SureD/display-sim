"""Derived waveform and pursuit diagnostics under declared synthetic assumptions.

These are numerical diagnostics, not VESA certification or a biological flicker
safety assessment. Emission samples represent bin means; response crossing times
use linear interpolation between their centres. Pursuit uses midpoint quadrature
of actual emitted RGB with the shutter normalization retaining dark intervals.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from tv_sim.color import luminance
from tv_sim.stages.temporal import shift_x


def _trace(values: Sequence[float] | np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1 or len(result) < 2 or not np.isfinite(result).all():
        raise ValueError("waveform requires at least two finite scalar samples")
    return result


def response_metrics(
    values: Sequence[float] | np.ndarray,
    times_s: Sequence[float] | np.ndarray,
    initial_nits: float,
    target_nits: float,
    *,
    settling_fraction: float = 0.02,
) -> dict[str, Any]:
    """Measure a held step, including censoring when the observation is too short."""
    y, times = _trace(values), _trace(times_s)
    delta = target_nits - initial_nits
    if (
        len(y) != len(times)
        or np.any(np.diff(times) <= 0)
        or not np.isfinite([initial_nits, target_nits, settling_fraction]).all()
        or delta == 0
        or not 0 < settling_fraction < 1
        or times[0] < 0
    ):
        raise ValueError(
            "response requires ordered nonnegative times, distinct levels and tolerance"
        )
    progress = (y - initial_nits) / delta

    def crossing(level: float) -> float | None:
        indices = np.flatnonzero(progress >= level)
        if not len(indices):
            return None
        index = int(indices[0])
        t0, p0 = (0.0, 0.0) if index == 0 else (times[index - 1], progress[index - 1])
        if progress[index] == p0:
            return float(times[index])
        return float(t0 + (times[index] - t0) * (level - p0) / (progress[index] - p0))

    t10, t90 = crossing(0.1), crossing(0.9)
    unresolved = bool(progress[0] >= 0.9)
    resolution = float(np.min(np.diff(times)))
    within = np.abs(progress - 1) <= settling_fraction
    stable = np.logical_and.accumulate(within[::-1])[::-1]
    settling = np.flatnonzero(stable)
    beyond = np.maximum(progress - 1, 0)
    inverse = np.maximum(
        np.maximum(y - max(initial_nits, target_nits), 0), min(initial_nits, target_nits) - y
    )
    return {
        "evidence": "D under P model and metric definitions",
        "initial_nits": float(initial_nits),
        "target_nits": float(target_nits),
        "t10_s": t10,
        "t90_s": t90,
        "response_10_90_s": None if unresolved or t10 is None or t90 is None else t90 - t10,
        "response_10_90_upper_bound_s": float(times[0]) if unresolved else None,
        "unresolved_at_sampling_resolution": unresolved,
        "sampling_interval_s": resolution,
        "settling_s": None if not len(settling) else float(times[settling[0]]),
        "settling_fraction": settling_fraction,
        "settled_within_observation": bool(len(settling)),
        "overshoot_percent": float(np.max(beyond) * 100),
        "overshoot_nits": float(np.max(beyond) * abs(delta)),
        "inverse_ghost_amplitude_nits": float(np.max(inverse)),
        "sampling": "bin means at centres; linear first crossings; settling must remain in band through observation",
    }


def flicker_metrics(
    values: Sequence[float] | np.ndarray,
    sample_duration_s: Fraction | float,
) -> dict[str, Any]:
    """Percent modulation, area index and strongest non-DC uniform-sample FFT bin."""
    y = _trace(values)
    duration = float(sample_duration_s)
    if not np.isfinite(duration) or duration <= 0 or np.any(y < 0):
        raise ValueError("flicker requires nonnegative light and positive sample duration")
    low, high, mean = float(np.min(y)), float(np.max(y)), float(np.mean(y))
    centered = y - mean
    spectrum = np.abs(np.fft.rfft(centered))
    spectrum[0] = 0
    dominant = None
    if high - low > max(1e-12, high * 1e-12):
        dominant = float(np.fft.rfftfreq(len(y), duration)[int(np.argmax(spectrum))])
    return {
        "evidence": "D under P waveform; no IEEE 1789 safety classification",
        "mean_nits": mean,
        "minimum_nits": low,
        "maximum_nits": high,
        "flicker_percent": 0.0 if high + low == 0 else 100 * (high - low) / (high + low),
        "flicker_index": 0.0 if mean == 0 else float(np.sum(np.maximum(centered, 0)) / np.sum(y)),
        "dominant_frequency_hz": dominant,
        "frequency_bin_width_hz": 1 / (len(y) * duration),
        "nyquist_hz": 1 / (2 * duration),
        "definition": "piecewise constant bin-mean light; area above mean / total light area; dominant FFT bin excludes DC and includes content flashing",
    }


def pursuit_image(
    samples: Sequence[np.ndarray],
    pts: Sequence[Fraction],
    durations: Sequence[Fraction],
    velocity_px_s: float,
    reference_pts: Fraction,
) -> np.ndarray:
    """Integrate a tracking shutter, preserving duty-related brightness loss."""
    if not samples or len(samples) != len(pts) or len(samples) != len(durations):
        raise ValueError("pursuit requires matching nonempty samples, PTS and durations")
    shape = samples[0].shape
    if len(shape) != 3 or shape[-1] != 3 or not np.isfinite(velocity_px_s):
        raise ValueError("pursuit requires finite RGB samples and velocity")
    acc = np.zeros(shape, dtype=np.float64)
    total = Fraction(0)
    previous_end = None
    for rgb, point, duration in zip(samples, pts, durations):
        if (
            rgb.shape != shape
            or not np.isfinite(rgb).all()
            or not isinstance(point, Fraction)
            or not isinstance(duration, Fraction)
            or duration <= 0
            or previous_end is not None
            and point != previous_end
        ):
            raise ValueError(
                "pursuit samples require common shape and exact contiguous rational bins"
            )
        midpoint = point + duration / 2
        shift = -velocity_px_s * float(midpoint - reference_pts)
        acc += shift_x(rgb, shift).astype(np.float64) * float(duration)
        total += duration
        previous_end = point + duration
    return (acc / float(total)).astype(np.float32)


def pursuit_metrics(rgb: np.ndarray, velocity_px_s: float) -> dict[str, Any]:
    """Measure the principal rising edge and label the normalized MPRT convention."""
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or rgb.shape[1] < 8 or velocity_px_s == 0:
        raise ValueError("pursuit edge requires RGB width >= 8 and nonzero velocity")
    # RGB validation above guarantees that the height reduction leaves a 1-D edge.
    edge = cast(NDArray[np.float64], np.mean(luminance(rgb), axis=0, dtype=np.float64))
    if not np.isfinite(edge).all() or not np.isfinite(velocity_px_s):
        raise ValueError("pursuit edge and velocity must be finite")
    span = max(1, len(edge) // 8)
    low, high = float(np.mean(edge[:span])), float(np.mean(edge[-span:]))
    if high <= low:
        raise ValueError("pursuit metric requires a rising edge with distinct plateaus")
    normalized = (edge - low) / (high - low)

    def position(level: float) -> float | None:
        crossings = np.flatnonzero((normalized[:-1] <= level) & (normalized[1:] > level))
        if not len(crossings):
            return None
        index = int(crossings[np.argmin(np.abs(crossings - len(edge) / 2))])
        return float(
            index + (level - normalized[index]) / (normalized[index + 1] - normalized[index])
        )

    x10, x90 = position(0.1), position(0.9)
    width = None if x10 is None or x90 is None else max(0.0, x90 - x10)
    return {
        "evidence": "D under P tracking shutter; not ClearMR/MPRT certification",
        "velocity_px_s": velocity_px_s,
        "edge_10_90_width_px": width,
        "effective_10_90_time_s": None if width is None else width / abs(velocity_px_s),
        "normalized_mprt_s": None if width is None else width / (0.8 * abs(velocity_px_s)),
        "inverse_ghost_amplitude_nits": float(max(np.max(edge) - high, low - np.min(edge), 0)),
        "plateau_nits": [low, high],
        "definition": "principal rising 10-90 edge; normalized MPRT = width/(0.8*speed), giving full hold duration for ideal continuous rectangular hold; finite raster and midpoint quadrature contribute",
    }
