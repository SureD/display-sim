"""Export unencoded, absolute-linear-nit assets for the static web preview.

This is an opt-in adapter around the existing gallery/pipeline. The browser
chooses a separate presentation transform; no SDR exposure is baked into the
binary assets, and no default simulator settings are changed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from sim.color import luminance, pq_oetf
from sim.gallery import (
    DISCLAIMER, HDR_REFERENCE, INTEGRATION_SAMPLES, MACRO_REFERENCE,
    MOTION_REFERENCE, PAN_SPEED, PRE_ROLL, PROFILE_LABELS, PROFILE_NAMES,
    _gallery_profile, render_still, scenes,
)
from sim.macro import render_macro
from sim.pipeline import Pipeline
from sim.profile import TVProfile, load_profile, profile_path


SCHEMA_VERSION = 1
DEFAULT_MOTION_FRAMES = 24
MACRO_SCALE = 16

STILL_SCENES = (
    ("starfield", "Starfield", "Sparse 600–2,000-nit stars reveal local dimming, leakage and optical spread.", HDR_REFERENCE),
    ("subtitles", "Subtitles on black", "1,000-nit subtitle glyphs on a black surround.", HDR_REFERENCE),
    ("bright_window", "Bright window · 12%", "A roughly 12%-area window requests 2,000 nits.", HDR_REFERENCE),
    ("wide_window", "Bright window · 56%", "A roughly 56%-area window requests the same 2,000 nits.", HDR_REFERENCE),
    ("gradients", "Neutral & color ramps", "Rows: 0–100, 0–2,000, 0–2 nits, then a synthetic RGB mixture.", HDR_REFERENCE),
    ("macro_subpixel", "Logical subpixel source", "100-nit neutral and RGBW bars at the center; use the aperture macro to inspect geometry.", MOTION_REFERENCE),
)


def _write_frames(out: Path, relative: str, frames: Iterable[np.ndarray]) -> dict:
    """Stream headerless little-endian RGB FP16 and describe its exact bytes."""
    path = out / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256()
    shape = None
    count = 0
    peak = 0.0
    minimum = float("inf")
    luminance_sum = 0.0
    max_error = 0.0
    with path.open("wb") as handle:
        for rgb in frames:
            image = np.asarray(rgb, dtype=np.float32)
            if image.ndim != 3 or image.shape[-1] != 3 or min(image.shape[:2]) < 1:
                raise ValueError("export frames must be nonempty H x W x 3 RGB arrays")
            if not np.isfinite(image).all() or np.any(image < 0) or np.any(image > np.finfo(np.float16).max):
                raise ValueError("export frames must be finite nonnegative nits representable as float16")
            if shape is not None and image.shape != shape:
                raise ValueError("every frame in one asset must share its dimensions")
            shape = image.shape
            packed = image.astype("<f2")
            transport = packed.astype(np.float32)
            payload = packed.tobytes(order="C")
            handle.write(payload)
            digest.update(payload)
            peak = max(peak, float(transport.max()))
            minimum = min(minimum, float(transport.min()))
            luminance_sum += float(luminance(transport).astype(np.float64).sum())
            max_error = max(max_error, float(np.max(np.abs(image - transport))))
            count += 1
    if shape is None:
        raise ValueError("an export asset must contain at least one frame")
    height, width, _ = shape
    stride = width * height * 3 * 2
    return {
        "file": relative, "width": width, "height": height,
        "frame_count": count, "frame_stride_bytes": stride,
        "byte_length": count * stride, "sha256": digest.hexdigest(),
        "statistics": {
            "source": "decoded float16 transport; mean uses BT.709 luminance weights",
            "peak_channel_nits": peak, "minimum_channel_nits": minimum,
            "mean_luminance_nits": luminance_sum / (count * width * height),
            "float16_max_absolute_error_nits": max_error,
        },
    }


def _motion_frames(profile: TVProfile, source: np.ndarray, count: int) -> Iterable[np.ndarray]:
    """Reuse one pipeline, including load/response histories and real pre-roll."""
    pipeline = Pipeline(_gallery_profile(profile, motion=PAN_SPEED))
    encoded = pq_oetf(source)
    for _ in range(PRE_ROLL):
        pipeline.run_linear(encoded)
    for index in range(1, count + 1):
        yield pipeline.run_linear(np.roll(encoded, int(index * PAN_SPEED), axis=1)).rgb


def _snapshot_profiles(out: Path, profiles: list[TVProfile]) -> list[dict]:
    records = []
    for profile, label in zip(profiles, PROFILE_LABELS):
        snapshots = {}
        for kind, suffix in (("profile", ".yaml"), ("provenance", ".provenance.yaml"), ("angular", ".angular.yaml")):
            source = profile_path(profile.name).with_name(profile.name + suffix)
            payload = source.read_bytes()
            relative = f"metadata/{source.name}"
            destination = out / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            snapshots[kind] = {
                "file": relative, "sha256": sha256(payload).hexdigest(),
                "byte_length": len(payload), "source": f"sim/profiles/{source.name}",
            }
        records.append({
            "id": profile.name, "name": profile.name, "label": label,
            "technology": profile.technology, "settings": asdict(profile),
            "yaml_sha256": snapshots["profile"]["sha256"], "snapshots": snapshots,
            "effective_settings": {
                "still": asdict(_gallery_profile(profile)),
                "motion": asdict(_gallery_profile(profile, motion=PAN_SPEED)),
            },
            "calibration_status": "P placeholders; provenance contains separate M/D/P/NR evidence, not a named-TV calibration",
        })
    return records


def generate_web_export(
    out: Path, width: int = 256, height: int = 144, *,
    motion_frames: int = DEFAULT_MOTION_FRAMES,
    colorimetry=None, output_space: str = "bt2020",
) -> dict:
    """Export all four gallery profiles; return the JSON-compatible manifest."""
    if colorimetry is not None and colorimetry.enabled:
        from sim.colorimetry_export import generate_colorimetric_export

        return generate_colorimetric_export(out, width, height, motion_frames=motion_frames,
                                            config=colorimetry, output_space=output_space)
    if type(width) is not int or type(height) is not int or width < 160 or height < 96:
        raise ValueError("web export resolution must be integers at least 160x96")
    if type(motion_frames) is not int or motion_frames < 1:
        raise ValueError("motion_frames must be a positive integer")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    profiles = [load_profile(name) for name in PROFILE_NAMES]
    sources = scenes(width, height)
    frame_time_ms = profiles[0].temporal.frame_time_ms
    if any(profile.temporal.frame_time_ms != frame_time_ms for profile in profiles):
        raise ValueError("side-by-side motion export requires a common profile frame duration")
    sim_root = Path(__file__).resolve().parent
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": "python3 -m sim export-web",
        "disclaimer": DISCLAIMER,
        "resolution": [width, height],
        "format": {
            "dtype": "float16", "byte_order": "little", "channels": 3,
            "layout": "frame-major HWC RGB", "units": "linear-nit",
            "color_space": "linear-srgb", "primaries": "BT.709 / sRGB", "white_point": "D65",
            "transfer": "linear absolute channel intensities; neutral R=G=B=N represents N cd/m²",
            "alpha": "none", "row_order": "top-to-bottom", "header_bytes": 0,
            "colorimetry_status": "P preview interpretation: the simulator has synthetic RGB matrices, no calibrated gamut or spectral model",
            "pq_source_note": "Procedural RGB nits use PQ per-channel for pipeline input only; PQ transfer does not imply BT.2020 primaries.",
            "presentation": "No SDR exposure, OETF or per-TV normalization is baked into assets. Browser mapping is a separate transform.",
        },
        "profile_overrides": {
            "input_eotf": "pq", "viewing_angle_deg": 0, "ambient_lux": 0,
            "integration_samples": INTEGRATION_SAMPLES,
            "motion_px_per_frame": {"stills": 0, "pan": PAN_SPEED},
        },
        "temporal_protocol": {
            "pre_roll_frames": PRE_ROLL, "pan_frames": motion_frames,
            "pan_px_per_frame": PAN_SPEED, "frame_time_ms": frame_time_ms,
            "fps": 1000.0 / frame_time_ms, "integration_samples": INTEGRATION_SAMPLES,
            "history": "One persistent response/load pipeline per profile; pre-roll holds the initial source, then frame i advances i*8 pixels with wrap.",
            "observer": "Synthetic horizontal pursuit integration; full hold, MEMC off; playback loop resets to the saved first frame.",
            "loop_boundary": "Not a continuous loop; response/load history jumps from the final saved frame to the first saved frame.",
        },
        "implementation_sha256": {
            f"sim/{path.relative_to(sim_root).as_posix()}": sha256(path.read_bytes()).hexdigest()
            for path in sorted(sim_root.rglob("*.py"))
        },
        "profiles": _snapshot_profiles(out, profiles),
        "scenes": [],
    }

    def new_scene(identifier: str, title: str, description: str, kind: str, reference: float,
                  scene_width: int = width, scene_height: int = height, count: int = 1) -> dict:
        record = {
            "id": identifier, "title": title, "description": description,
            "kind": kind, "reference_nits": reference,
            "width": scene_width, "height": scene_height, "frame_count": count,
            "fps": 1000.0 / frame_time_ms if kind == "motion" else 0,
            "assets": {},
        }
        if identifier in sources:
            record["source_linear_float32_sha256"] = sha256(sources[identifier].astype("<f4").tobytes()).hexdigest()
        manifest["scenes"].append(record)
        return record

    for identifier, title, description, reference in STILL_SCENES:
        record = new_scene(identifier, title, description, "still", reference)
        for profile in profiles:
            record["assets"][profile.name] = _write_frames(
                out, f"frames/{identifier}/{profile.name}.f16",
                [render_still(profile, sources[identifier])],
            )

    crop_height, crop_width = 8, 16
    cy, cx = height // 2 - 4, width // 2 - 8
    record = new_scene(
        "macro_apertures", "Synthetic subpixel apertures",
        "A 16×8 logical crop with area-normalized RGB, RGBW or staggered triangular apertures; arbitrary geometry, not measured emitter nits.",
        "macro", MACRO_REFERENCE, crop_width * MACRO_SCALE, crop_height * MACRO_SCALE,
    )
    record["macro"] = {
        "crop_yxhw": [cy, cx, crop_height, crop_width], "scale": MACRO_SCALE,
        "fill_factor": .72, "white_fraction": .65,
        "geometry_status": "P synthetic, unmeasured; no spectral or physical emitter-radiance model",
        "statistics_note": "Aperture peaks encode concentrated channel light; they are not physical measured emitter luminance.",
    }
    for profile in profiles:
        logical = render_still(profile, sources["macro_subpixel"])[cy:cy+crop_height, cx:cx+crop_width]
        record["assets"][profile.name] = _write_frames(
            out, f"frames/macro_apertures/{profile.name}.f16",
            [render_macro(logical, profile.panel.subpixel, scale=MACRO_SCALE)],
        )

    record = new_scene(
        "motion_pan", "Pan · persistent response history",
        f"{PRE_ROLL} held pre-roll frames, then {motion_frames} saved pan frames at {1000 / frame_time_ms:.4f} Hz; 8 pixels/frame, wrap boundary, synthetic pursuit integration.",
        "motion", MOTION_REFERENCE, count=motion_frames,
    )
    record["frame_time_ms"] = frame_time_ms
    record["frame_source_indices"] = list(range(1, motion_frames + 1))
    record["pts_seconds"] = [index * frame_time_ms / 1000 for index in range(motion_frames)]
    record["loop_boundary"] = manifest["temporal_protocol"]["loop_boundary"]
    for profile in profiles:
        record["assets"][profile.name] = _write_frames(
            out, f"frames/motion_pan/{profile.name}.f16",
            _motion_frames(profile, sources["motion_pan"], motion_frames),
        )

    manifest["asset_bytes"] = sum(asset["byte_length"] for scene in manifest["scenes"] for asset in scene["assets"].values())
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("web/data"))
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=144)
    parser.add_argument("--motion-frames", type=int, default=DEFAULT_MOTION_FRAMES)
    from sim.colorimetry_cli import add_arguments, configuration

    add_arguments(parser, output=True)
    args = parser.parse_args(argv)
    if args.width < 160 or args.height < 96:
        parser.error("resolution must be at least 160x96")
    if args.motion_frames < 1:
        parser.error("--motion-frames must be positive")
    try:
        result = generate_web_export(args.out, args.width, args.height, motion_frames=args.motion_frames,
                                     colorimetry=configuration(args), output_space=args.colorimetry_output or "bt2020")
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Wrote {len(result['scenes'])} scenes × {len(result['profiles'])} profiles ({result['asset_bytes'] / 1_000_000:.1f} MB) to {args.out / 'manifest.json'}")


if __name__ == "__main__":
    main()
