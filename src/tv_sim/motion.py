"""Rational cadence (D) and declared synthetic motion reconstruction (P).

This is an offline reference model, not a motion estimator or a model of a
vendor's MEMC. Times remain rational; RGB reconstruction takes place on
requested linear-nit content before display processing and physical histories.
Translations and layer velocities are pixels per source interval, not pixels/s.
Vendor algorithms and calibrated numerical thresholds remain NR.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np

from tv_sim.frame import Frame


def as_fraction(value: Fraction | str | int | float) -> Fraction:
    """Parse an exact rate/PTS; decimal floats use their decimal spelling."""

    if isinstance(value, bool):
        raise ValueError("a rate or PTS cannot be boolean")
    try:
        return value if isinstance(value, Fraction) else Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"invalid finite rational value: {value!r}") from exc


def rational_string(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


@dataclass(frozen=True)
class MotionTick:
    """One output instant and the half-open source interval containing it."""

    output_index: int
    output_pts: Fraction
    source_index: int
    source_pts: Fraction
    next_source_index: int | None
    next_source_pts: Fraction | None
    phase: Fraction

    @property
    def alpha(self) -> float:
        return float(self.phase)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_index": self.output_index,
            "output_pts": rational_string(self.output_pts),
            "source_index": self.source_index,
            "source_pts": rational_string(self.source_pts),
            "next_source_index": self.next_source_index,
            "next_source_pts": (
                None if self.next_source_pts is None else rational_string(self.next_source_pts)
            ),
            "phase": rational_string(self.phase),
        }


def fixed_rate_pts(
    count: int,
    source_fps: Fraction | str | int | float,
    start: Fraction | str | int | float = 0,
) -> tuple[Fraction, ...]:
    """Create source PTS without accumulation of rounded frame durations."""

    if isinstance(count, bool) or not isinstance(count, (int, np.integer)) or count < 1:
        raise ValueError("source frame count must be a positive integer")
    rate = as_fraction(source_fps)
    if rate <= 0:
        raise ValueError("source_fps must be positive")
    origin = as_fraction(start)
    return tuple(origin + Fraction(index, 1) / rate for index in range(count))


def schedule(
    source_pts: Iterable[Fraction | str | int | float],
    last_duration: Fraction | str | int | float,
    output_fps: Fraction | str | int | float,
) -> list[MotionTick]:
    """Schedule ``start + j / fps < last PTS + last_duration`` exactly.

    At each tick repetition selects the latest available source. The final
    source has no right endpoint; its phase describes its declared hold.
    Both irregular source PTS and rational fractional rates are supported.
    """

    pts = tuple(as_fraction(value) for value in source_pts)
    if not pts or any(right <= left for left, right in zip(pts, pts[1:])):
        raise ValueError("source_pts must be nonempty and strictly increasing")
    duration, rate = as_fraction(last_duration), as_fraction(output_fps)
    if duration <= 0 or rate <= 0:
        raise ValueError("last_duration and output_fps must be positive")
    end = pts[-1] + duration
    ticks: list[MotionTick] = []
    index = 0
    while (output_pts := pts[0] + Fraction(index, 1) / rate) < end:
        source_index = bisect_right(pts, output_pts) - 1
        next_index = source_index + 1 if source_index + 1 < len(pts) else None
        next_pts = pts[next_index] if next_index is not None else None
        interval_end = next_pts if next_pts is not None else end
        ticks.append(
            MotionTick(
                index,
                output_pts,
                source_index,
                pts[source_index],
                next_index,
                next_pts,
                (output_pts - pts[source_index]) / (interval_end - pts[source_index]),
            )
        )
        index += 1
    return ticks


def _sample(
    image: np.ndarray,
    dx: float,
    dy: float,
    *,
    zero_pad: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear gather; mark unsupported coordinates instead of reflecting."""

    height, width = image.shape[:2]
    yy, xx = np.indices((height, width), dtype=np.float64)
    xx -= dx
    yy -= dy
    valid = (xx >= 0) & (xx <= width - 1) & (yy >= 0) & (yy <= height - 1)
    if zero_pad:
        # A declared layer is transparent beyond its masked raster. Retain
        # partial coverage from an edge texel instead of dropping its whole
        # bilinear footprint when the sample center moves outside the canvas.
        # Coordinates farther than one texel outside have zero support; cap
        # them before integer conversion even for a very distant global time.
        padded_x, padded_y = np.clip(xx, -1, width), np.clip(yy, -1, height)
        x0, y0 = np.floor(padded_x).astype(np.intp), np.floor(padded_y).astype(np.intp)
        wx, wy = padded_x - x0, padded_y - y0

        def tap(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            supported = (x >= 0) & (x < width) & (y >= 0) & (y < height)
            values = image[np.clip(y, 0, height - 1), np.clip(x, 0, width - 1)]
            return values * (supported[..., None] if image.ndim == 3 else supported)

        p00, p10 = tap(x0, y0), tap(x0 + 1, y0)
        p01, p11 = tap(x0, y0 + 1), tap(x0 + 1, y0 + 1)
    else:
        # Clamping is only for safe indexing; invalid translation samples
        # never become content. Keep the historical valid-sample arithmetic.
        x0 = np.floor(np.clip(xx, 0, width - 1)).astype(np.intp)
        y0 = np.floor(np.clip(yy, 0, height - 1)).astype(np.intp)
        x1, y1 = np.minimum(x0 + 1, width - 1), np.minimum(y0 + 1, height - 1)
        wx, wy = np.clip(xx, 0, width - 1) - x0, np.clip(yy, 0, height - 1) - y0
        p00, p10, p01, p11 = image[y0, x0], image[y0, x1], image[y1, x0], image[y1, x1]
    if image.ndim == 3:
        wx, wy = wx[..., None], wy[..., None]
    sampled = p00 * (1 - wx) * (1 - wy) + p10 * wx * (1 - wy) + p01 * (1 - wx) * wy + p11 * wx * wy
    return sampled.astype(np.float32), valid


@dataclass(frozen=True)
class AnalyticLayer:
    """An opaque, full-canvas masked texture with a declared linear path.

    Larger depth is in front. Subpixel mask edges have bilinear area coverage;
    premultiplied sampling prevents hidden texture from bleeding through edges.
    """

    rgb: np.ndarray
    mask: np.ndarray
    velocity: tuple[float, float] = (0.0, 0.0)
    depth: float = 0.0


@dataclass(frozen=True)
class LayerScene:
    """A known static background and moving opaque layers, all synthetic (P)."""

    background: np.ndarray
    layers: tuple[AnalyticLayer, ...] = ()

    def render(self, phase: float | Fraction) -> Frame:
        """Render a known time; global phases outside [0, 1] are allowed."""

        time = float(phase)
        rgb = np.asarray(self.background, dtype=np.float32)
        if (
            rgb.ndim != 3
            or rgb.shape[-1] != 3
            or min(rgb.shape[:2]) < 1
            or not np.isfinite(rgb).all()
            or not np.isfinite(time)
        ):
            raise ValueError("layer background and phase must be finite RGB content")
        rgb = rgb.copy()
        if any(not np.isfinite(layer.depth) for layer in self.layers):
            raise ValueError("layer depths must be finite")
        for layer in sorted(self.layers, key=lambda item: item.depth):
            texture = np.asarray(layer.rgb, dtype=np.float32)
            mask = np.asarray(layer.mask, dtype=np.float32)
            velocity = np.asarray(layer.velocity, dtype=np.float64)
            if (
                texture.shape != rgb.shape
                or mask.shape != rgb.shape[:2]
                or velocity.shape != (2,)
                or not np.isfinite(velocity).all()
                or not np.isfinite(texture).all()
                or not np.isin(mask, (0, 1)).all()
            ):
                raise ValueError("layers require matching finite RGB, binary masks and 2D velocity")
            dx, dy = velocity * time
            if not np.isfinite((dx, dy)).all():
                raise ValueError("layer displacement must be finite")
            coverage, _ = _sample(mask, dx, dy, zero_pad=True)
            premultiplied, _ = _sample(texture * mask[..., None], dx, dy, zero_pad=True)
            rgb = premultiplied + rgb * (1 - coverage[..., None])
        return Frame(rgb)


@dataclass
class ReconstructionResult:
    frame: Frame
    kind: str
    fallback_reasons: list[str]
    fallback_fraction: float
    fallback_mask: np.ndarray
    scene_cut: bool = False
    evidence: str = "P"

    def to_dict(self) -> dict[str, str | float | bool | list[str]]:
        return {
            "kind": self.kind,
            "fallback_reasons": self.fallback_reasons,
            "fallback_fraction": self.fallback_fraction,
            "scene_cut": self.scene_cut,
            "evidence": self.evidence,
        }


def reconstruct(
    left: Frame,
    right: Frame | None,
    alpha: float | Fraction,
    *,
    translation: tuple[float, float] | None = None,
    scene: LayerScene | None = None,
    cut: bool = False,
    max_displacement_px: float = 256.0,
    endpoint_tolerance_nits: float = 0.001,
) -> ReconstructionResult:
    """Reconstruct declared synthetic motion, otherwise hold the left source.

    Exact source times return the original Frame and arrays. A declared cut
    holds the old shot until alpha=1. Model checks and limits are P safeguards;
    neither estimation nor automatic cut detection is performed. Translation
    prefers the left warp, uses the right only where the left is unsupported,
    and source-holds pixels unsupported by both. No border content is invented.
    """

    time = float(alpha)
    if not np.isfinite(time) or not 0 <= time <= 1:
        raise ValueError("alpha must be finite and in [0, 1]")
    if right is not None and right.shape != left.shape:
        raise ValueError("source frame shapes must match")
    shape = left.shape[:2]

    def result(
        frame: Frame, kind: str, reason: str | None = None, mask: np.ndarray | None = None
    ) -> ReconstructionResult:
        fallback = np.full(shape, reason is not None, dtype=bool) if mask is None else mask
        return ReconstructionResult(
            frame,
            kind,
            [] if reason is None else [reason],
            float(np.mean(fallback)),
            fallback,
            bool(cut),
        )

    if time == 0:
        return result(left, "original")
    if right is not None and time == 1:
        return result(right, "original")
    if not np.isfinite(left.rgb).all():
        raise ValueError("left source must contain finite RGB content")
    if right is None:
        return result(left, "repeated", "last_frame_hold")
    if cut:
        return result(left, "repeated", "scene_cut")
    if not np.isfinite(right.rgb).all():
        return result(left, "repeated", "nonfinite_source")
    if np.array_equal(left.rgb, right.rgb):
        return result(left, "repeated")
    if (
        not np.isfinite(max_displacement_px)
        or max_displacement_px <= 0
        or not np.isfinite(endpoint_tolerance_nits)
        or endpoint_tolerance_nits < 0
    ):
        raise ValueError("motion limit must be positive and endpoint tolerance nonnegative")
    if scene is not None and translation is not None:
        raise ValueError("choose a layer scene or a translation")
    if scene is not None:
        try:
            for layer in scene.layers:
                vector = np.asarray(layer.velocity, dtype=np.float64)
                if vector.shape != (2,) or not np.isfinite(vector).all():
                    return result(left, "repeated", "nonfinite_motion")
                if np.linalg.norm(vector) > max_displacement_px:
                    return result(left, "repeated", "motion_out_of_range")
            start, end = scene.render(0), scene.render(1)
            if start.shape != left.shape or end.shape != right.shape:
                return result(left, "repeated", "model_endpoint_mismatch")
            if not np.allclose(
                start.rgb, left.rgb, atol=endpoint_tolerance_nits, rtol=0
            ) or not np.allclose(end.rgb, right.rgb, atol=endpoint_tolerance_nits, rtol=0):
                return result(left, "repeated", "model_endpoint_mismatch")
            return result(scene.render(time), "interpolated")
        except (ValueError, TypeError, OverflowError):
            return result(left, "repeated", "invalid_scene")
    if translation is None:
        return result(left, "repeated", "missing_motion_model")
    vector = np.asarray(translation, dtype=np.float64)
    if vector.shape != (2,) or not np.isfinite(vector).all():
        return result(left, "repeated", "nonfinite_motion")
    if np.linalg.norm(vector) > max_displacement_px:
        return result(left, "repeated", "motion_out_of_range")
    dx, dy = vector
    endpoint, endpoint_valid = _sample(left.rgb, dx, dy)
    if not endpoint_valid.any():
        return result(left, "repeated", "out_of_bounds")
    if not np.allclose(
        endpoint[endpoint_valid], right.rgb[endpoint_valid], atol=endpoint_tolerance_nits, rtol=0
    ):
        return result(left, "repeated", "model_endpoint_mismatch")
    forward, left_valid = _sample(left.rgb, time * dx, time * dy)
    backward, right_valid = _sample(right.rgb, -(1 - time) * dx, -(1 - time) * dy)
    rgb = left.rgb.copy()
    rgb[right_valid] = backward[right_valid]
    rgb[left_valid] = forward[left_valid]
    missing = ~(left_valid | right_valid)
    return result(Frame(rgb), "interpolated", "out_of_bounds" if missing.any() else None, missing)
