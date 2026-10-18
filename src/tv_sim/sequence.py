"""Opt-in offline source scheduling before the existing display tail.

M/D/P/NR: rational timing is D (deduced from declared inputs); analytic
reconstruction and its thresholds are P. Vendor algorithms/latency are NR.
MotionConfig is a separate runtime sequence profile, leaving shipped TV YAML
values and their versioned provenance untouched. Block estimation is a separate
opt-in path; off/repeat/analytic retain their phase-1 behavior.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence, Sized
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, cast

import numpy as np

from tv_sim.frame import Frame

if TYPE_CHECKING:
    from tv_sim.block_motion import BlockMotionConfig
    from tv_sim.motion import LayerScene
    from tv_sim.pipeline import Pipeline


@dataclass(frozen=True)
class MotionConfig:
    """Sequence settings; ``off`` keeps one legacy call per source picture.

    ``translation_px`` is known (dx, dy) per source interval, in the prepared
    raster after spatial processing. Layer scenes use the same linear-nit
    domain. ``mci`` instead infers vectors using the separate P ``block``
    config; absent block config uses its versioned defaults and this object's
    max_displacement_px. Pursuit motion remains the TV profile's independent
    pixels-per-output-tick parameter.
    """

    mode: str = "off"
    source_fps: str | int | Fraction = "24"
    output_fps: str | int | Fraction | None = None
    translation_px: tuple[float, float] | None = None
    max_displacement_px: float = 256.0
    endpoint_tolerance_nits: float = 0.001
    block: BlockMotionConfig | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("off", "repeat", "analytic", "mci"):
            raise ValueError("MEMC mode must be off, repeat, analytic, or mci")
        if self.mode == "off" and self.output_fps is not None:
            raise ValueError("off preserves profile timing; use repeat to set output_fps")
        if self.mode != "off" and self.output_fps is None:
            raise ValueError("repeat/analytic/mci require an explicit output_fps")
        if self.block is not None:
            from tv_sim.block_motion import BlockMotionConfig

            if self.mode != "mci" or not isinstance(self.block, BlockMotionConfig):
                raise ValueError("block config requires mci and a BlockMotionConfig")
        if self.mode == "mci" and self.translation_px is not None:
            raise ValueError("mci estimates motion; translation_px requires analytic mode")
        for rate in (self.source_fps, self.output_fps):
            if rate is not None and (isinstance(rate, bool) or Fraction(rate) <= 0):
                raise ValueError("frame rates must be positive rational values")
        if not np.isfinite(self.max_displacement_px) or self.max_displacement_px <= 0:
            raise ValueError("max_displacement_px must be positive and finite")
        if self.translation_px is not None:
            if len(self.translation_px) != 2 or not np.isfinite(self.translation_px).all():
                raise ValueError("translation_px must contain two finite displacements")
        if not np.isfinite(self.endpoint_tolerance_nits) or self.endpoint_tolerance_nits < 0:
            raise ValueError("endpoint_tolerance_nits must be finite and nonnegative")


@dataclass
class SequenceOutput:
    """Display output plus independent source/presentation timing diagnostics."""

    frame: Frame
    diagnostics: dict
    motion_maps: dict[str, np.ndarray] | None = None


def _pts_string(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def render_sequence(
    pipeline: Pipeline,
    encoded_frames: Iterable[np.ndarray],
    config: MotionConfig | None = None,
    *,
    source_pts: Sequence[str | int | Fraction] | None = None,
    last_duration: str | int | Fraction | None = None,
    cuts: Iterable[int] = (),
    scenes: Mapping[int, LayerScene] | None = None,
) -> Iterator[SequenceOutput]:
    """Advance panel/load histories exactly once per emitted picture.

    Enabled modes buffer prepared source images, schedule rational half-open
    source intervals, then reconstruct *before* backlight, panel, ABL and
    ambient processing. ``cuts`` marks source indices starting a new shot;
    it suppresses reconstruction across that boundary, without resetting
    physical response history. Explicit PTS require a declared final duration.
    Independent clips should use independent Pipeline instances.
    """

    settings = config if config is not None else MotionConfig()
    source_rate = Fraction(settings.source_fps)
    parsed_pts = None
    if source_pts is not None:
        from tv_sim.motion import as_fraction

        parsed_pts = tuple(as_fraction(value) for value in source_pts)
        if not parsed_pts or any(b <= a for a, b in zip(parsed_pts, parsed_pts[1:])):
            raise ValueError("source_pts must be nonempty and strictly increasing")
        if isinstance(encoded_frames, Sized) and len(encoded_frames) != len(parsed_pts):
            raise ValueError("source_pts must match the number of source frames")
    if settings.mode == "off":
        # No buffering, rate conversion, temporal overrides or extra state calls.
        frame_ms = pipeline.profile.temporal.frame_time_ms
        output_step = Fraction(str(frame_ms)) / 1000
        origin = parsed_pts[0] if parsed_pts else Fraction(0)
        count = 0
        for index, encoded_frame in enumerate(encoded_frames):
            if parsed_pts is not None and index >= len(parsed_pts):
                raise ValueError("source_pts must match the number of source frames")
            source_time = parsed_pts[index] if parsed_pts is not None else index / source_rate
            count += 1
            yield SequenceOutput(
                pipeline.run_linear(encoded_frame),
                {
                    "output_index": index,
                    "source_index": index,
                    "source_pts": _pts_string(source_time),
                    "output_pts": _pts_string(origin + index * output_step),
                    "phase": "0/1",
                    "kind": "original",
                    "mode": "off",
                    "scene_cut": False,
                    "fallback_reasons": [],
                    "fallback_fraction": 0.0,
                    "timing_evidence": "D",
                    "lookahead_seconds": "0/1",
                    "frame_time_ms": frame_ms,
                    "timing_policy": "legacy_profile",
                },
            )
        if parsed_pts is not None and count != len(parsed_pts):
            raise ValueError("source_pts must match the number of source frames")
        return

    if settings.mode == "mci":
        from tv_sim.block_sequence import render_block_sequence

        if scenes is not None:
            raise ValueError("mci estimates motion; known scenes require analytic mode")
        yield from render_block_sequence(
            pipeline,
            encoded_frames,
            settings,
            source_pts=parsed_pts,
            last_duration=last_duration,
            cuts=cuts,
        )
        return

    from tv_sim.motion import fixed_rate_pts, reconstruct, schedule

    encoded = [np.asarray(image) for image in encoded_frames]
    if not encoded:
        raise ValueError("a sequence must contain at least one source frame")
    shape, dtype = encoded[0].shape, encoded[0].dtype
    if any(image.shape != shape or image.dtype != dtype for image in encoded):
        raise ValueError("source geometry and encoding dtype must be constant within a clip")
    if any(not np.isfinite(image).all() for image in encoded):
        raise ValueError("source frames must be finite")
    pts = parsed_pts if parsed_pts is not None else fixed_rate_pts(len(encoded), source_rate)
    if len(pts) != len(encoded):
        raise ValueError("source_pts must match the number of source frames")
    if source_pts is not None and last_duration is None:
        raise ValueError("explicit source_pts require last_duration")
    duration = Fraction(last_duration) if last_duration is not None else 1 / source_rate
    output_fps = cast(str | int | Fraction, settings.output_fps)
    ticks = schedule(pts, duration, output_fps)
    cut_indices = set(cuts)
    if any(type(i) is not int or i <= 0 or i >= len(encoded) for i in cut_indices):
        raise ValueError("cuts must identify source indices after the first frame")
    if scenes is not None and any(
        type(i) is not int or i < 0 or i >= len(encoded) - 1 for i in scenes
    ):
        raise ValueError("scene keys must identify adjacent source pairs")
    prepared = [pipeline.prepare_content(image) for image in encoded]
    if any(not np.isfinite(frame.rgb).all() for frame in prepared):
        raise ValueError("prepared source content must be finite")
    dt_ms = float(1000 / Fraction(output_fps))
    for tick in ticks:
        index = tick.source_index
        left = prepared[index]
        right = prepared[tick.next_source_index] if tick.next_source_index is not None else None
        cut = tick.next_source_index in cut_indices
        if settings.mode == "repeat":
            target = left
            kind = "original" if tick.phase == 0 else "repeated"
            reasons, fraction = [], 0.0
        else:
            reconstructed = reconstruct(
                left,
                right,
                tick.phase,
                translation=settings.translation_px,
                scene=scenes.get(index) if scenes else None,
                cut=cut,
                max_displacement_px=settings.max_displacement_px,
                endpoint_tolerance_nits=settings.endpoint_tolerance_nits,
            )
            target = reconstructed.frame
            kind = reconstructed.kind
            reasons = reconstructed.fallback_reasons
            fraction = reconstructed.fallback_fraction
        diagnostics = tick.to_dict()
        lookahead = (
            pts[index + 1] - pts[index]
            if settings.mode == "analytic" and right is not None
            else Fraction(0)
        )
        diagnostics.update(
            {
                "mode": settings.mode,
                "kind": kind,
                "scene_cut": cut,
                "fallback_reasons": reasons,
                "fallback_fraction": fraction,
                "timing_evidence": "D",
                "reconstruction_evidence": "P",
                "lookahead_seconds": _pts_string(lookahead),
                "frame_time_ms": dt_ms,
            }
        )
        yield SequenceOutput(pipeline.display_content(target, frame_time_ms=dt_ms), diagnostics)
