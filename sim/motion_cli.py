"""Offline numbered-image motion experiments, with exact timing sidecars.

Analytic reconstruction and the opt-in NumPy block estimator are P proxies.
Neither is a vendor MEMC implementation or a calibrated TV model.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from fractions import Fraction
from glob import glob
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from sim.pipeline import Pipeline
from sim.profile import available_profiles, load_profile, profile_path
from sim.sequence import MotionConfig
from sim.stages.encode import encode_frame


def _rate(value: str) -> Fraction:
    try:
        rate = Fraction(value)
        if rate <= 0:
            raise ValueError
        return rate
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError("use a positive rational rate, e.g. 24000/1001") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=available_profiles())
    parser.add_argument("--input-frames", required=True, help="Quoted glob of RGB images; lexical filename order")
    parser.add_argument("--source-fps", type=_rate, default=Fraction(24))
    parser.add_argument("--output-fps", type=_rate, default=None,
                        help="Explicit output refresh for repeat/analytic/mci; omitted for legacy off")
    parser.add_argument("--memc", choices=("off", "repeat", "analytic", "mci"), default="off",
                        help="Default off is one legacy pipeline call per source")
    parser.add_argument("--translation-px", type=float, nargs=2, metavar=("DX", "DY"),
                        help="P: known displacement per source interval in the prepared raster")
    parser.add_argument("--cut-before", type=int, nargs="*", default=[], metavar="INDEX",
                        help="Zero-based indices of source pictures starting new shots")
    parser.add_argument("--max-displacement-px", type=float, default=None,
                        help="P motion limit (default 256, or the selected block config)")
    parser.add_argument("--endpoint-tolerance-nits", type=float, default=0.001,
                        help="P maximum endpoint model discrepancy (default .001 nit)")
    parser.add_argument("--input-eotf", choices=("srgb", "pq", "hlg"), default=None)
    parser.add_argument("--preview-reference-nits", type=float, default=None,
                        help="Shared fixed preview white; default is the TV profile output reference")
    parser.add_argument("--motion-config", type=Path, default=None,
                        help="Versioned P block config JSON; requires --memc mci")
    parser.add_argument("--block-size", type=int, choices=(8, 16), default=None,
                        help="P estimation block size override; requires mci")
    parser.add_argument("--motion-debug", action="store_true",
                        help="Save vectors in output pixels, confidence, visibility and reason maps")
    parser.add_argument("--abl-dynamics", choices=("off", "capacity_attack_release_v1"), default="off")
    parser.add_argument("--abl-attack-ms", type=float, default=None)
    parser.add_argument("--abl-release-ms", type=float, default=None)
    parser.add_argument("--abl-initial", choices=("cold", "settled_first_tick", "explicit"), default="cold")
    parser.add_argument("--abl-initial-capacity-nits", type=float, default=None)
    parser.add_argument("--out", type=Path, default=Path("reports/motion"))
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "validate":
        from sim.motion_validate import main as validate_main

        validate_main(argv[1:])
        return
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        block = None
        if args.memc == "mci":
            from sim.motion_provenance import load_block_config

            block = load_block_config(args.motion_config)
            if args.block_size is not None:
                block = replace(block, block_size=args.block_size)
            if args.max_displacement_px is not None:
                block = replace(block, max_displacement_px=args.max_displacement_px)
        elif args.motion_config is not None or args.block_size is not None or args.motion_debug:
            raise ValueError("motion-config, block-size and motion-debug require --memc mci")
        config = MotionConfig(
            mode=args.memc, source_fps=args.source_fps, output_fps=args.output_fps,
            translation_px=tuple(args.translation_px) if args.translation_px is not None else None,
            max_displacement_px=(block.max_displacement_px if block is not None else
                                 args.max_displacement_px if args.max_displacement_px is not None else 256.0),
            endpoint_tolerance_nits=args.endpoint_tolerance_nits,
            block=block,
        )
        from sim.abl_dynamics import ABLDynamicsConfig

        dynamics = ABLDynamicsConfig(
            model=args.abl_dynamics, attack_ms=args.abl_attack_ms, release_ms=args.abl_release_ms,
            initial=args.abl_initial, initial_capacity_nits=args.abl_initial_capacity_nits,
        )
    except (OSError, ValueError, ZeroDivisionError) as exc:
        parser.error(str(exc))
    if args.preview_reference_nits is not None and (
        not np.isfinite(args.preview_reference_nits) or args.preview_reference_nits <= 0
    ):
        parser.error("preview-reference-nits must be positive and finite")
    paths = [Path(name) for name in sorted(glob(args.input_frames))]
    if not paths:
        parser.error("input-frames matched no images")
    # Require RGB explicitly: silently coercing modes can hide encoding changes.
    def images():
        for path in paths:
            with Image.open(path) as picture:
                if picture.mode != "RGB":
                    parser.error(f"{path}: input frames must be RGB")
                yield np.asarray(picture).copy()

    frames = images() if config.mode == "mci" else list(images())
    profile = load_profile(args.profile).with_overrides(input_eotf=args.input_eotf)
    # Natural playback has no pursuit snapshot filter baked into each picture.
    # All shipped profiles already use zero eye displacement; keep off untouched.
    if config.mode != "off":
        profile = replace(profile, temporal=replace(profile.temporal, motion_px_per_frame=0.0))
    output = profile.output
    if args.preview_reference_nits is not None:
        output = replace(output, reference_nits=args.preview_reference_nits)
    try:
        pipeline = Pipeline(profile, abl_dynamics=dynamics if dynamics.active else None)
    except ValueError as exc:
        parser.error(str(exc))
    args.out.mkdir(parents=True, exist_ok=True)
    diagnostics = []
    try:
        for result in pipeline.run_sequence(frames, config, cuts=args.cut_before):
            record = result.diagnostics.copy()
            stem = f"frame_{record['output_index']:06d}"
            record.update({"linear_file": f"{stem}.npy", "preview_file": f"{stem}.png"})
            np.save(args.out / record["linear_file"], result.frame.rgb, allow_pickle=False)
            Image.fromarray(encode_frame(result.frame, output)).save(args.out / record["preview_file"])
            if args.motion_debug and result.motion_maps is not None:
                record["motion_maps_file"] = f"{stem}.motion.npz"
                np.savez_compressed(args.out / record["motion_maps_file"], **result.motion_maps)
            diagnostics.append(record)
    except ValueError as exc:
        parser.error(str(exc))
    configuration = asdict(config)
    if config.mode != "mci":
        # Preserve phase-1 config/manifest bytes, including default/off exports.
        configuration.pop("block")
    configuration["source_fps"] = str(config.source_fps)
    configuration["output_fps"] = str(config.output_fps) if config.output_fps is not None else None
    manifest = {
        "schema_version": 1,
        "disclaimer": "P: synthetic analytic reconstruction; no vendor algorithm or measured TV match.",
        "evidence": {"timing": "D", "reconstruction_and_thresholds": "P", "vendor_algorithm_and_latency": "NR"},
        "config": configuration,
        "profile": asdict(profile),
        "profile_yaml_sha256": sha256(profile_path(args.profile).read_bytes()).hexdigest(),
        "sources": [{"file": str(path), "sha256": sha256(path.read_bytes()).hexdigest()} for path in paths],
        "cuts_before_source_indices": args.cut_before,
        "domains": {"reconstruction": "decoded, spatially processed linear RGB nits",
                    "display_output": "linear RGB nits; BT.709 luma convention",
                    "preview": asdict(output)},
        "observer": "no pursuit displacement added; off preserves original profile",
        "lookahead": "Assumed adjacent-source buffer; seconds recorded per tick, separate from PTS; vendor latency NR",
        "frames": diagnostics,
    }
    if config.mode == "mci":
        from sim.motion_provenance import block_config_record

        manifest.update({
            "schema_version": 2,
            "disclaimer": "P: NumPy block motion proxy; thresholds are placeholders; no vendor algorithm or measured TV match.",
            "motion_config": block_config_record(block),
            "domains": {**manifest["domains"],
                        "matching": "BT.709 linear luma / fixed luma_reference_nits",
                        "vectors": "output raster pixels per adjacent source interval"},
        })
    if dynamics.active:
        manifest["abl_dynamics"] = asdict(dynamics)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(diagnostics)} {config.mode} frames and {args.out / 'manifest.json'}")
