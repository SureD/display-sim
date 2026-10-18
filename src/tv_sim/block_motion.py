"""Deterministic, reduced-resolution NumPy MEMC experiment (M14, all P).

This deliberately conservative block proxy is neither optical-flow ground truth
nor an implementation of any manufacturer's MEMC. It estimates requested linear
content only; panel, backlight and load histories never enter this module.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from fractions import Fraction

import numpy as np

from tv_sim.frame import Frame
from tv_sim.motion import ReconstructionResult

MODEL = "numpy_bidirectional_block_v1"
REASON_CODES = {
    "none": 0,
    "low_texture": 1,
    "ambiguous_match": 2,
    "high_sad": 3,
    "inconsistent_motion": 4,
    "out_of_bounds": 5,
    "motion_out_of_range": 6,
    "scene_cut_declared": 7,
    "scene_cut_detected": 8,
    "exposure_change": 9,
    "nonfinite_source": 10,
    "low_confidence": 11,
    "collision": 12,
    "hole": 13,
    "whole_frame_low_confidence": 14,
}


@dataclass(frozen=True)
class BlockMotionConfig:
    """Versioned P policy. Numerical controls are explicit and serializable.

    Search uses a factor-two pyramid, a coarse square of ``search_radius``
    pixels, then a square of ``refinement_radius`` pixels at each finer level.
    Blocks are 8 or 16 pixels on the reduced estimation raster. All vectors
    exposed to callers are converted to original output-raster pixels.
    """

    schema_version: int = 1
    parameter_status: str = "placeholder"
    estimation_width: int = 320
    estimation_height: int = 180
    block_size: int = 8
    pyramid_levels: int = 3
    search_radius: int = 3
    refinement_radius: int = 2
    subpixel_steps: tuple[float, ...] = (0.5, 0.25)
    max_displacement_px: float = 256.0
    luma_reference_nits: float = 1000.0
    neighbor_penalty: float = 0.002
    minimum_block_support: float = 0.5
    boundary_penalty: float = 0.02
    texture_threshold: float = 0.005
    sad_threshold: float = 0.08
    uniqueness_threshold: float = 0.03
    fb_threshold_px: float = 2.0
    confidence_threshold: float = 0.25
    confidence_hysteresis: float = 0.05
    whole_frame_fallback_fraction: float = 0.8
    cut_histogram_bins: int = 32
    cut_histogram_threshold: float = 0.6
    cut_sad_threshold: float = 0.25
    cut_changed_fraction: float = 0.8
    cut_pixel_threshold: float = 0.15
    flash_sad_threshold: float = 0.08
    flash_correlation_threshold: float = 0.98
    collision_variance_nits: float = 20.0
    collision_vector_threshold_px: float = 2.0
    minimum_splat_weight: float = 1e-6
    numerical_epsilon: float = 1e-12

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("block motion schema_version must be 1")
        if self.parameter_status != "placeholder":
            raise ValueError("block motion parameter_status must be placeholder (P)")
        integers = (
            "estimation_width",
            "estimation_height",
            "block_size",
            "pyramid_levels",
            "search_radius",
            "refinement_radius",
            "cut_histogram_bins",
        )
        for name in integers:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.block_size not in (8, 16):
            raise ValueError("block_size must be 8 or 16 estimation pixels")
        # Schema support bounds keep accidental configs within the offline
        # reference budget; these are admission limits, not fitted thresholds.
        if self.estimation_width > 320 or self.estimation_height > 180:
            raise ValueError("schema 1 estimation budget is at most 320x180")
        if self.search_radius > 8 or self.refinement_radius > 4 or self.pyramid_levels > 4:
            raise ValueError("schema 1 supports only a small declared pyramid search")
        if self.cut_histogram_bins > 256:
            raise ValueError("schema 1 supports at most 256 histogram bins")
        if self.pyramid_levels > int(math.log2(self.block_size)) + 1:
            raise ValueError("pyramid_levels would reduce a block below one pixel")
        for name, value in asdict(self).items():
            if name in integers or name in ("schema_version", "parameter_status", "subpixel_steps"):
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} must be nonnegative")
        for name in (
            "max_displacement_px",
            "luma_reference_nits",
            "texture_threshold",
            "sad_threshold",
            "uniqueness_threshold",
            "fb_threshold_px",
            "collision_variance_nits",
            "collision_vector_threshold_px",
            "minimum_splat_weight",
            "numerical_epsilon",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "minimum_block_support",
            "confidence_threshold",
            "confidence_hysteresis",
            "whole_frame_fallback_fraction",
            "cut_histogram_threshold",
            "cut_changed_fraction",
            "flash_correlation_threshold",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if not self.minimum_block_support or not self.whole_frame_fallback_fraction:
            raise ValueError("support and whole-frame fallback fractions must be positive")
        if not isinstance(self.subpixel_steps, (tuple, list)):
            raise ValueError("subpixel_steps must be a sequence")
        if len(self.subpixel_steps) > 4:
            raise ValueError("schema 1 supports at most four fractional refinements")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not 0 < v < 1
            for v in self.subpixel_steps
        ):
            raise ValueError("subpixel steps must be finite fractions of a pixel")
        object.__setattr__(self, "subpixel_steps", tuple(float(v) for v in self.subpixel_steps))

    def to_dict(self) -> dict:
        return {"model": MODEL, **asdict(self)}


@dataclass
class PairEstimate:
    """One adjacent pair; block vectors use OUTPUT pixels per source interval."""

    forward: np.ndarray
    backward: np.ndarray
    forward_confidence: np.ndarray
    backward_confidence: np.ndarray
    forward_visibility: np.ndarray
    backward_visibility: np.ndarray
    forward_reasons: np.ndarray
    backward_reasons: np.ndarray
    estimation_shape: tuple[int, int]
    output_shape: tuple[int, int]
    block_size: int
    scene_cut: bool = False
    cut_reason: str | None = None
    static: bool = False
    diagnostics: dict = field(default_factory=dict)

    def dense_field(self, array: np.ndarray) -> np.ndarray:
        """Nearest block expansion, also usable for confidence/reason maps."""
        height, width = self.output_shape
        eh, ew = self.estimation_shape
        rows = np.minimum(np.arange(height) * eh // height // self.block_size, array.shape[0] - 1)
        cols = np.minimum(np.arange(width) * ew // width // self.block_size, array.shape[1] - 1)
        return array[rows[:, None], cols[None, :]]

    def debug_arrays(self) -> dict[str, np.ndarray]:
        return {
            name: getattr(self, name)
            for name in (
                "forward",
                "backward",
                "forward_confidence",
                "backward_confidence",
                "forward_visibility",
                "backward_visibility",
                "forward_reasons",
                "backward_reasons",
            )
        }


@dataclass
class BlockReconstruction(ReconstructionResult):
    diagnostics: dict = field(default_factory=dict)
    reason_fractions: dict[str, float] = field(default_factory=dict)
    reason_map: np.ndarray | None = None

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "reason_fractions": self.reason_fractions,
            "diagnostics": self.diagnostics,
        }


def _luma(rgb: np.ndarray) -> np.ndarray:
    # Existing simulator convention: BT.709 luma weights, independent of input
    # primaries. These are the declared color transform, not fitted thresholds.
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _area_axis(image: np.ndarray, count: int, axis: int) -> np.ndarray:
    """Exact box-area reduction; no full candidate or resize-weight tensor."""
    image = np.moveaxis(image, axis, 0)
    if count == image.shape[0]:
        return np.moveaxis(image, 0, axis)
    positions = np.linspace(0, image.shape[0], count + 1)
    indices = np.minimum(positions.astype(np.intp), image.shape[0] - 1)
    cumulative = np.concatenate(
        (np.zeros_like(image[:1]), np.cumsum(image, axis=0, dtype=np.float64))
    )
    fractions = positions - np.floor(positions)
    integral = cumulative[np.floor(positions).astype(np.intp)]
    integral += image[indices] * fractions.reshape((-1,) + (1,) * (image.ndim - 1))
    reduced = np.diff(integral, axis=0) / (image.shape[0] / count)
    return np.moveaxis(reduced, 0, axis)


def _reduced_luma(frame: Frame, shape: tuple[int, int], reference: float) -> np.ndarray:
    return _area_axis(_area_axis(_luma(frame.rgb), shape[0], 0), shape[1], 1) / reference


def _patch_cost(
    source: np.ndarray,
    target: np.ndarray,
    bounds: tuple[int, int, int, int],
    dx: float,
    dy: float,
    config: BlockMotionConfig,
) -> tuple[float, float]:
    y0, y1, x0, x1 = bounds
    yy, xx = np.mgrid[y0:y1, x0:x1]
    xx, yy = xx + dx, yy + dy
    valid = (xx >= 0) & (xx <= target.shape[1] - 1) & (yy >= 0) & (yy <= target.shape[0] - 1)
    support = float(np.mean(valid))
    if support < config.minimum_block_support or not valid.any():
        return float("inf"), support
    sx, sy = xx[valid], yy[valid]
    ix, iy = sx.astype(np.intp), sy.astype(np.intp)
    fx, fy = sx - ix, sy - iy
    nx, ny = np.minimum(ix + 1, target.shape[1] - 1), np.minimum(iy + 1, target.shape[0] - 1)
    values = (
        target[iy, ix] * (1 - fx) * (1 - fy)
        + target[iy, nx] * fx * (1 - fy)
        + target[ny, ix] * (1 - fx) * fy
        + target[ny, nx] * fx * fy
    )
    sad = float(np.mean(np.abs(source[y0:y1, x0:x1][valid] - values)))
    return sad + config.boundary_penalty * (1 - support), support


def _match(source: np.ndarray, target: np.ndarray, config: BlockMotionConfig):
    height, width = source.shape
    gh, gw = (
        (height + config.block_size - 1) // config.block_size,
        (width + config.block_size - 1) // config.block_size,
    )
    forward = np.zeros((gh, gw, 2), np.float32)
    residual = np.zeros((gh, gw), np.float32)
    uniqueness = np.zeros_like(residual)
    texture = np.zeros_like(residual)
    support = np.zeros_like(residual)
    # Each level reduces the same block footprint. A candidate is evaluated
    # individually; memory does not grow with the number of search candidates.
    levels = min(config.pyramid_levels, int(math.log2(min(height, width))) + 1)
    pyramids = [[image] for image in (source, target)]
    for pyramid in pyramids:
        for _ in range(1, levels):
            previous = pyramid[-1]
            pyramid.append(
                _area_axis(
                    _area_axis(previous, max(1, previous.shape[0] // 2), 0),
                    max(1, previous.shape[1] // 2),
                    1,
                )
            )
    maximum_search = config.search_radius * 2 ** (levels - 1)
    maximum_search += config.refinement_radius * (2 ** (levels - 1) - 1)
    for by in range(gh):
        for bx in range(gw):
            y0, x0 = by * config.block_size, bx * config.block_size
            y1, x1 = min(height, y0 + config.block_size), min(width, x0 + config.block_size)
            texture[by, bx] = np.std(source[y0:y1, x0:x1])
            neighbors = []
            if bx:
                neighbors.append(forward[by, bx - 1])
            if by:
                neighbors.append(forward[by - 1, bx])
            neighbor = np.median(neighbors, axis=0) if neighbors else np.zeros(2)
            vector = np.zeros(2, dtype=np.float64)
            best, runner, selected_support = float("inf"), float("inf"), 0.0
            appearance_uniqueness = 1.0
            for level in range(levels - 1, -1, -1):
                a, b = pyramids[0][level], pyramids[1][level]
                scale_x, scale_y = width / a.shape[1], height / a.shape[0]
                bounds = (
                    y0 * a.shape[0] // height,
                    max(y0 * a.shape[0] // height + 1, (y1 * a.shape[0] + height - 1) // height),
                    x0 * a.shape[1] // width,
                    max(x0 * a.shape[1] // width + 1, (x1 * a.shape[1] + width - 1) // width),
                )
                center = np.rint(vector / (scale_x, scale_y)).astype(int)
                radius = config.search_radius if level == levels - 1 else config.refinement_radius
                best, runner = float("inf"), float("inf")
                selected = center.astype(float)
                candidates = []
                for dy in range(center[1] - radius, center[1] + radius + 1):
                    for dx in range(center[0] - radius, center[0] + radius + 1):
                        if abs(dx * scale_x) > maximum_search or abs(dy * scale_y) > maximum_search:
                            continue
                        cost, valid = _patch_cost(a, b, bounds, dx, dy, config)
                        candidates.append((cost, dx, dy))
                        penalty = config.neighbor_penalty * np.linalg.norm(
                            np.array((dx * scale_x, dy * scale_y)) - neighbor
                        )
                        ranked = cost + penalty
                        if ranked < best:
                            runner, best = best, ranked
                            selected, selected_support = np.array((dx, dy), float), valid
                        elif ranked < runner:
                            runner = ranked
                selected_cost = next(
                    (cost for cost, dx, dy in candidates if (dx, dy) == tuple(selected)),
                    float("inf"),
                )
                appearance_runner = min(
                    (cost for cost, dx, dy in candidates if (dx, dy) != tuple(selected)),
                    default=float("inf"),
                )
                distinct = (
                    (appearance_runner - selected_cost)
                    / max(abs(appearance_runner), config.numerical_epsilon)
                    if np.isfinite(appearance_runner)
                    else 0.0
                )
                appearance_uniqueness = min(appearance_uniqueness, distinct)
                vector = selected * (scale_x, scale_y)
            integer_cost, selected_support = _patch_cost(
                source, target, (y0, y1, x0, x1), vector[0], vector[1], config
            )
            # Ambiguity uses appearance alone. Neighbor regularization can
            # choose a periodic match but cannot provide evidence it is true.
            runner = min(
                (cost for cost, dx, dy in candidates if (dx, dy) != tuple(vector)),
                default=float("inf"),
            )
            uniqueness[by, bx] = min(
                appearance_uniqueness,
                (runner - integer_cost) / max(abs(runner), config.numerical_epsilon)
                if np.isfinite(runner)
                else 0.0,
            )
            # Fractional refinement is local and does not turn tiny nearby
            # offsets into the distinct runner-up used by ambiguity detection.
            for step in config.subpixel_steps:
                center = vector.copy()
                for oy in (-step, 0.0, step):
                    for ox in (-step, 0.0, step):
                        trial = center + (ox, oy)
                        if np.max(np.abs(trial)) > maximum_search:
                            continue
                        cost, valid = _patch_cost(
                            source, target, (y0, y1, x0, x1), trial[0], trial[1], config
                        )
                        if cost < integer_cost:
                            integer_cost, vector, selected_support = cost, trial, valid
            forward[by, bx] = vector
            residual[by, bx], support[by, bx] = integer_cost, selected_support
    return forward, residual, uniqueness, texture, support, maximum_search


def _sample_blocks(field: np.ndarray, x: np.ndarray, y: np.ndarray, block_size: int) -> np.ndarray:
    # Block centers are at (block_size-1)/2. Edge clamping only samples a vector;
    # raster validity is handled separately and never manufactures image RGB.
    gx, gy = (
        x / block_size - (block_size - 1) / (2 * block_size),
        y / block_size - (block_size - 1) / (2 * block_size),
    )
    gx, gy = np.clip(gx, 0, field.shape[1] - 1), np.clip(gy, 0, field.shape[0] - 1)
    ix, iy = gx.astype(int), gy.astype(int)
    nx, ny = np.minimum(ix + 1, field.shape[1] - 1), np.minimum(iy + 1, field.shape[0] - 1)
    wx, wy = (gx - ix)[..., None], (gy - iy)[..., None]
    return (
        field[iy, ix] * (1 - wx) * (1 - wy)
        + field[iy, nx] * wx * (1 - wy)
        + field[ny, ix] * (1 - wx) * wy
        + field[ny, nx] * wx * wy
    )


def estimate_pair(
    left: Frame,
    right: Frame,
    config: BlockMotionConfig,
    *,
    declared_cut: bool = False,
    previous: PairEstimate | None = None,
) -> PairEstimate:
    """Estimate exactly one adjacent source pair, without physical-state calls.

    Previous confidence can delay re-enabling an uncertain block within a shot.
    Previous vectors are never reused. A declared/detected cut ignores history.
    """
    if left.shape != right.shape or min(left.shape[:2]) < 1:
        raise ValueError("block motion source shapes must match and be nonempty")
    height, width = left.shape[:2]
    scale = min(1.0, config.estimation_width / width, config.estimation_height / height)
    shape = max(1, int(height * scale)), max(1, int(width * scale))
    grid = tuple((value + config.block_size - 1) // config.block_size for value in shape)
    vectors = np.zeros((*grid, 2), np.float32)
    zero, visible, reasons = (
        np.zeros(grid, np.float32),
        np.zeros(grid, bool),
        np.zeros(grid, np.uint8),
    )
    result = PairEstimate(
        vectors,
        vectors.copy(),
        zero,
        zero.copy(),
        visible,
        visible.copy(),
        reasons,
        reasons.copy(),
        shape,
        (height, width),
        config.block_size,
    )
    result.diagnostics = {
        "model": MODEL,
        "evidence": "P",
        "estimation_shape": list(shape),
        "output_shape": [height, width],
        "vector_units": "output_pixels_per_source_interval",
        "estimation_scale_xy": [shape[1] / width, shape[0] / height],
        "matching_domain": "fixed_reference_linear_BT709_luma",
        "luma_reference_nits": config.luma_reference_nits,
        "history_reused": False,
        "reason_codes": REASON_CODES,
    }

    def stop(reason: str, cut=False):
        result.forward_reasons.fill(REASON_CODES[reason])
        result.backward_reasons.fill(REASON_CODES[reason])
        result.scene_cut, result.cut_reason = bool(cut), reason if cut else None
        result.diagnostics.update(scene_cut=bool(cut), stop_reason=reason)
        return result

    if declared_cut:
        return stop("scene_cut_declared", True)
    if not np.isfinite(left.rgb).all() or not np.isfinite(right.rgb).all():
        return stop("nonfinite_source")
    if np.array_equal(left.rgb, right.rgb):
        result.static = True
        result.forward_confidence.fill(1)
        result.backward_confidence.fill(1)
        result.forward_visibility.fill(True)
        result.backward_visibility.fill(True)
        result.diagnostics.update(scene_cut=False, static=True)
        return result
    a, b = (_reduced_luma(image, shape, config.luma_reference_nits) for image in (left, right))
    difference = np.abs(a - b)
    hist_a, _ = np.histogram(np.clip(a, 0, 1), bins=config.cut_histogram_bins, range=(0, 1))
    hist_b, _ = np.histogram(np.clip(b, 0, 1), bins=config.cut_histogram_bins, range=(0, 1))
    histogram = float(np.sum(np.abs(hist_a / a.size - hist_b / b.size)) / 2)
    sad, changed = (
        float(np.mean(difference)),
        float(np.mean(difference >= config.cut_pixel_threshold)),
    )
    ac, bc = a - np.mean(a), b - np.mean(b)
    variance = float(np.sqrt(np.sum(ac * ac) * np.sum(bc * bc)))
    correlation = float(np.sum(ac * bc) / variance) if variance > config.numerical_epsilon else 0.0
    result.diagnostics.update(
        histogram_distance=histogram,
        normalized_pair_sad=sad,
        changed_fraction=changed,
        appearance_correlation=correlation,
    )
    # A coherent exposure change is held, but is not called a new shot. The
    # simple detector still has documented false positives/negatives.
    if sad >= config.flash_sad_threshold and correlation >= config.flash_correlation_threshold:
        return stop("exposure_change")
    if (
        histogram >= config.cut_histogram_threshold
        and sad >= config.cut_sad_threshold
        and changed >= config.cut_changed_fraction
    ):
        return stop("scene_cut_detected", True)
    matches = [_match(a, b, config), _match(b, a, config)]
    scale_xy = np.array((width / shape[1], height / shape[0]))
    yy, xx = np.indices(grid, dtype=float)
    xx = np.minimum(xx * config.block_size + (config.block_size - 1) / 2, shape[1] - 1)
    yy = np.minimum(yy * config.block_size + (config.block_size - 1) / 2, shape[0] - 1)
    for index, (name, _opposite) in enumerate((("forward", "backward"), ("backward", "forward"))):
        vector, residual, unique, texture, support, maximum = matches[index]
        reverse = matches[1 - index][0]
        mapped_x, mapped_y = xx + vector[..., 0], yy + vector[..., 1]
        fb = np.linalg.norm(
            (vector + _sample_blocks(reverse, mapped_x, mapped_y, config.block_size)) * scale_xy,
            axis=-1,
        )
        valid = (
            (mapped_x >= 0)
            & (mapped_x <= shape[1] - 1)
            & (mapped_y >= 0)
            & (mapped_y <= shape[0] - 1)
            & (support >= 1)
        )
        visibility = valid & (fb < config.fb_threshold_px)
        confidence = np.minimum.reduce(
            (
                np.clip(texture / config.texture_threshold, 0, 1),
                np.clip(1 - residual / config.sad_threshold, 0, 1),
                np.clip(unique / config.uniqueness_threshold, 0, 1),
                np.clip(1 - fb / config.fb_threshold_px, 0, 1),
            )
        )
        reason = np.zeros(grid, np.uint8)
        # Ordered reasons keep visibility independent of generic match quality.
        reason[texture < config.texture_threshold] = REASON_CODES["low_texture"]
        reason[(reason == 0) & (unique < config.uniqueness_threshold)] = REASON_CODES[
            "ambiguous_match"
        ]
        reason[(reason == 0) & (residual >= config.sad_threshold)] = REASON_CODES["high_sad"]
        reason[(reason == 0) & (fb >= config.fb_threshold_px)] = REASON_CODES["inconsistent_motion"]
        reason[~valid] = REASON_CODES["out_of_bounds"]
        out_of_range = (np.linalg.norm(vector * scale_xy, axis=-1) > config.max_displacement_px) | (
            np.max(np.abs(vector), axis=-1) >= maximum
        )
        reason[out_of_range] = REASON_CODES["motion_out_of_range"]
        confidence[~visibility | out_of_range] = 0
        if (
            previous is not None
            and not previous.scene_cut
            and previous.output_shape == result.output_shape
            and getattr(previous, name + "_confidence").shape == grid
        ):
            old = getattr(previous, name + "_confidence")
            reenable = (old < config.confidence_threshold) & (
                confidence < config.confidence_threshold + config.confidence_hysteresis
            )
            confidence[reenable] = 0
            result.diagnostics["history_reused"] = True
        reason[(reason == 0) & (confidence < config.confidence_threshold)] = REASON_CODES[
            "low_confidence"
        ]
        setattr(result, name, (vector * scale_xy).astype(np.float32))
        setattr(result, name + "_confidence", confidence.astype(np.float32))
        setattr(result, name + "_visibility", visibility)
        setattr(result, name + "_reasons", reason)
        result.diagnostics[name + "_mean_confidence"] = float(np.mean(confidence))
        result.diagnostics[name + "_visibility_fraction"] = float(np.mean(visibility))
        result.diagnostics[name + "_mean_fb_error_px"] = float(np.mean(fb))
    result.diagnostics.update(scene_cut=False, search_radius_estimation_px=matches[0][-1])
    return result


def reconstruct_block(
    left: Frame,
    right: Frame,
    alpha: float | Fraction,
    estimate: PairEstimate,
    config: BlockMotionConfig,
) -> BlockReconstruction:
    """Confidence/visibility-weighted bilinear splats, with explicit safe holds.

    Colliding trajectories or disagreeing luma are rejected rather than using
    normalized accumulation as a substitute for unknown depth ordering.
    """
    time = float(alpha)
    if not math.isfinite(time) or not 0 <= time <= 1:
        raise ValueError("alpha must be finite and in [0, 1]")
    if right.shape != left.shape or left.shape[:2] != estimate.output_shape:
        raise ValueError("reconstruction and estimate source shapes must match")
    shape = estimate.output_shape
    reason_map = np.zeros(shape, np.uint8)

    def finish(frame, kind, mask=None, reasons=None, diagnostics=None):
        mask = np.zeros(shape, bool) if mask is None else mask
        fractions = (
            {
                name: float(np.mean(reason_map == code))
                for name, code in REASON_CODES.items()
                if code and np.any(reason_map == code)
            }
            if reasons is None
            else reasons
        )
        return BlockReconstruction(
            frame=frame,
            kind=kind,
            fallback_reasons=sorted(fractions),
            fallback_fraction=float(np.mean(mask)),
            fallback_mask=mask,
            scene_cut=estimate.scene_cut,
            diagnostics=diagnostics or {},
            reason_fractions=fractions,
            reason_map=reason_map.copy(),
        )

    if time == 0:
        return finish(left, "original")
    if time == 1:
        return finish(right, "original")
    if estimate.static:
        return finish(left, "repeated")
    if estimate.scene_cut or "stop_reason" in estimate.diagnostics:
        reason = estimate.cut_reason or estimate.diagnostics["stop_reason"]
        reason_map.fill(REASON_CODES[reason])
        return finish(left, "repeated", np.ones(shape, bool))
    height, width = shape
    accum = np.zeros((height * width, 3), np.float64)
    weight = np.zeros(height * width, np.float64)
    endpoint_luma = np.zeros((2, height * width), np.float64)
    endpoint_weight = np.zeros_like(endpoint_luma)
    vector_sum = np.zeros((height * width, 2), np.float64)
    vector_square = np.zeros_like(weight)
    yy, xx = np.indices(shape, dtype=float)
    for endpoint, (name, source, phase, temporal_weight, orientation) in enumerate(
        (("forward", left, time, 1 - time, 1), ("backward", right, 1 - time, time, -1))
    ):
        flow = estimate.dense_field(getattr(estimate, name))
        confidence = estimate.dense_field(getattr(estimate, name + "_confidence"))
        visibility = estimate.dense_field(getattr(estimate, name + "_visibility"))
        reliable = visibility & (confidence >= config.confidence_threshold)
        target_x, target_y = xx + phase * flow[..., 0], yy + phase * flow[..., 1]
        ix, iy = np.floor(target_x).astype(np.intp), np.floor(target_y).astype(np.intp)
        wx, wy = target_x - ix, target_y - iy
        luminance = _luma(source.rgb)
        motion = flow * orientation
        for ox, oy, spatial in (
            (0, 0, (1 - wx) * (1 - wy)),
            (1, 0, wx * (1 - wy)),
            (0, 1, (1 - wx) * wy),
            (1, 1, wx * wy),
        ):
            tx, ty = ix + ox, iy + oy
            supported = (
                reliable & (tx >= 0) & (tx < width) & (ty >= 0) & (ty < height) & (spatial > 0)
            )
            destinations = ty[supported] * width + tx[supported]
            weights = spatial[supported] * confidence[supported] * temporal_weight
            np.add.at(weight, destinations, weights)
            np.add.at(accum, destinations, source.rgb[supported] * weights[:, None])
            np.add.at(endpoint_luma[endpoint], destinations, luminance[supported] * weights)
            np.add.at(endpoint_weight[endpoint], destinations, weights)
            np.add.at(vector_sum, destinations, motion[supported] * weights[:, None])
            np.add.at(
                vector_square, destinations, np.sum(motion[supported] ** 2, axis=-1) * weights
            )
    safe_weight = np.maximum(weight, config.minimum_splat_weight)
    # Neighboring texels naturally differ during a fractional-pixel splat.
    # Compare the two endpoint reconstructions *after* their spatial filtering,
    # so ordinary fine texture is never mistaken for a visibility collision.
    endpoint_mean = endpoint_luma / np.maximum(endpoint_weight, config.minimum_splat_weight)
    combined_mean = np.sum(endpoint_luma, axis=0) / safe_weight
    luma_variance = (
        np.sum(endpoint_weight * (endpoint_mean - combined_mean) ** 2, axis=0) / safe_weight
    )
    vector_variance = np.maximum(
        0, vector_square / safe_weight - np.sum((vector_sum / safe_weight[:, None]) ** 2, axis=-1)
    )
    holes = (weight < config.minimum_splat_weight).reshape(shape)
    collisions = (
        (luma_variance > config.collision_variance_nits**2)
        | (vector_variance > config.collision_vector_threshold_px**2)
    ).reshape(shape)
    missing = holes | collisions
    held_reasons = estimate.dense_field(estimate.forward_reasons)
    reason_map[holes] = held_reasons[holes]
    reason_map[holes & (reason_map == 0)] = REASON_CODES["hole"]
    reason_map[collisions] = REASON_CODES["collision"]
    diagnostics = {
        "hole_fraction": float(np.mean(holes)),
        "collision_fraction": float(np.mean(collisions)),
        "raw_fallback_fraction": float(np.mean(missing)),
        "visibility_policy": "consistent_visible_endpoints_only; unresolved_collisions_hold",
    }
    if np.mean(missing) >= config.whole_frame_fallback_fraction:
        raw_fractions = {
            name: float(np.mean(reason_map == code))
            for name, code in REASON_CODES.items()
            if code and np.any(reason_map == code)
        }
        diagnostics["local_reason_fractions"] = raw_fractions
        diagnostics["whole_frame_hold"] = True
        # Keep a partition of held pixels: local causes retain their code and
        # otherwise usable pixels record the whole-frame policy decision.
        reason_map[~missing] = REASON_CODES["whole_frame_low_confidence"]
        return finish(left, "repeated", np.ones(shape, bool), diagnostics=diagnostics)
    rgb = (accum / safe_weight[:, None]).reshape((*shape, 3)).astype(np.float32)
    rgb[missing] = left.rgb[missing]
    return finish(Frame(rgb), "interpolated", missing, diagnostics=diagnostics)
