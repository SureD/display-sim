"""Adjacent-pair streaming for the opt-in P block motion experiment.

Only source content is buffered. Physical panel/load histories belong to the
Pipeline and advance once at each rational output tick, including held ticks.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sized
from fractions import Fraction
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from tv_sim.motion import MotionTick, ReconstructionResult, reconstruct

if TYPE_CHECKING:
    from tv_sim.block_motion import PairEstimate
    from tv_sim.pipeline import Pipeline
    from tv_sim.sequence import MotionConfig, SequenceOutput


def render_block_sequence(
    pipeline: Pipeline,
    encoded_frames: Iterable[np.ndarray],
    settings: MotionConfig,
    *,
    source_pts: tuple[Fraction, ...] | None,
    last_duration: str | int | Fraction | None,
    cuts: Iterable[int],
) -> Iterator[SequenceOutput]:
    """Consume two adjacent decoded/prepared sources, never an entire clip.

    Metadata is validated up front where available. For a streaming iterable,
    inconsistent later pictures reject when first encountered; earlier emitted
    ticks remain valid. Independent clips require fresh Pipeline instances.
    """
    from tv_sim.block_motion import BlockMotionConfig, estimate_pair, reconstruct_block
    from tv_sim.sequence import SequenceOutput

    block = (
        settings.block
        if settings.block is not None
        else BlockMotionConfig(max_displacement_px=settings.max_displacement_px)
    )
    source_rate, output_rate = (
        Fraction(settings.source_fps),
        Fraction(cast(str | int | Fraction, settings.output_fps)),
    )
    if source_pts is not None and last_duration is None:
        raise ValueError("explicit source_pts require last_duration")
    duration = Fraction(last_duration) if last_duration is not None else 1 / source_rate
    if duration <= 0:
        raise ValueError("last_duration must be positive")
    cut_indices = set(cuts)
    if any(type(index) is not int or index <= 0 for index in cut_indices):
        raise ValueError("cuts must identify source indices after the first frame")
    if isinstance(encoded_frames, Sized):
        if any(index >= len(encoded_frames) for index in cut_indices):
            raise ValueError("cuts must identify existing source frames")
        if source_pts is not None and len(encoded_frames) != len(source_pts):
            raise ValueError("source_pts must match the number of source frames")

    iterator = iter(encoded_frames)
    expected_geometry = None
    count = 0
    exhausted = False

    def read_source():
        nonlocal expected_geometry, count, exhausted
        try:
            image = np.asarray(next(iterator))
        except StopIteration:
            exhausted = True
            if source_pts is not None and count != len(source_pts):
                raise ValueError("source_pts must match the number of source frames") from None
            if any(index >= count for index in cut_indices):
                raise ValueError("cuts must identify existing source frames") from None
            return None
        if source_pts is not None and count >= len(source_pts):
            raise ValueError("source_pts must match the number of source frames")
        geometry = (image.shape, image.dtype)
        if expected_geometry is None:
            expected_geometry = geometry
        if (
            geometry != expected_geometry
            or image.ndim != 3
            or image.shape[-1] != 3
            or min(image.shape[:2]) < 1
        ):
            raise ValueError("source geometry and encoding dtype must be constant within a clip")
        if not np.isfinite(image).all():
            raise ValueError("source frames must be finite")
        prepared = pipeline.prepare_content(image)
        if not np.isfinite(prepared.rgb).all():
            raise ValueError("prepared source content must be finite")
        count += 1
        return prepared

    def pts(index):
        return source_pts[index] if source_pts is not None else index / source_rate

    left = read_source()
    if left is None:
        raise ValueError("a sequence must contain at least one source frame")
    right = read_source()
    origin, index, output_index = pts(0), 0, 0
    previous = None
    dt_ms = float(1000 / output_rate)
    previous_displayed_source = -1
    while left is not None:
        start = pts(index)
        end = pts(index + 1) if right is not None else start + duration
        estimate = (
            estimate_pair(
                left, right, block, declared_cut=index + 1 in cut_indices, previous=previous
            )
            if right is not None
            else None
        )
        while (output_pts := origin + output_index / output_rate) < end:
            phase = (output_pts - start) / (end - start)
            tick = MotionTick(
                output_index,
                output_pts,
                index,
                start,
                index + 1 if right is not None else None,
                end if right is not None else None,
                phase,
            )
            result: ReconstructionResult = (
                reconstruct_block(left, right, phase, cast("PairEstimate", estimate), block)
                if right is not None
                else reconstruct(left, None, phase)
            )
            diagnostics = tick.to_dict()
            diagnostics.update(
                {
                    "mode": "mci",
                    **result.to_dict(),
                    "timing_evidence": "D",
                    "reconstruction_evidence": "P",
                    "lookahead_seconds": (
                        f"{(end - start).numerator}/{(end - start).denominator}"
                        if right is not None
                        else "0/1"
                    ),
                    "frame_time_ms": dt_ms,
                }
            )
            maps = {"fallback_mask": result.fallback_mask}
            if getattr(result, "reason_map", None) is not None:
                maps["fallback_reason_map"] = cast(Any, result).reason_map
            if estimate is not None:
                diagnostics["estimator"] = estimate.diagnostics
                maps.update(estimate.debug_arrays())
            # No hidden calls before/after this tick. In particular, estimation
            # and cut handling never touch panel or ABL history.
            if pipeline._zone_active:
                # M14's estimated cuts own reconstruction only. Explicit cuts
                # reset zones here; M17 owns its separate target-delta detector.
                boundary_cut = any(
                    previous_displayed_source < cut_index <= index for cut_index in cut_indices
                )
                displayed = pipeline.display_content(
                    result.frame, frame_time_ms=dt_ms, scene_cut=boundary_cut
                )
                diagnostics["zone_backlight"] = cast(dict, pipeline.last_zone_trace).copy()
                previous_displayed_source = index
            else:
                displayed = pipeline.display_content(result.frame, frame_time_ms=dt_ms)
            if pipeline._dynamics_active:
                diagnostics["abl_capacity"] = cast(dict, pipeline.last_capacity_trace).copy()
            yield SequenceOutput(displayed, diagnostics, motion_maps=maps)
            output_index += 1
        previous = estimate if estimate is not None and not estimate.scene_cut else None
        left = right
        index += 1
        right = None if exhausted else read_source()
