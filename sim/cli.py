"""Command-line preview: ``python -m sim.cli --profile NAME --input in.png --output out.png``."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from sim.pipeline import Pipeline
from sim.profile import available_profiles, load_profile
from sim.stages.decode import as_code_values


def load_image(path: Path) -> np.ndarray:
    """Load an image as float code values in ``[0, 1]`` (RGB)."""

    array = np.asarray(Image.open(path))
    return as_code_values(array)


def save_image(path: Path, encoded: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(encoded, mode="RGB").save(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate a TV profile on one still image.",
        epilog="Profiles: " + ", ".join(available_profiles()),
    )
    parser.add_argument("--profile", required=True, help="YAML profile name in sim/profiles")
    parser.add_argument("--input", required=True, type=Path, help="Encoded input image")
    parser.add_argument("--output", required=True, type=Path, help="Preview PNG path")
    parser.add_argument("--input-eotf", choices=("srgb", "pq", "hlg"), default=None)
    parser.add_argument("--viewing-angle", type=float, default=None, help="Off-axis degrees")
    parser.add_argument("--ambient-lux", type=float, default=None, help="Room illuminance")
    parser.add_argument(
        "--motion-px",
        type=float,
        default=None,
        help="Sample-and-hold eye motion in pixels per frame",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    profile = load_profile(args.profile).with_overrides(
        input_eotf=args.input_eotf,
        viewing_angle_deg=args.viewing_angle,
        ambient_lux=args.ambient_lux,
        motion_px=args.motion_px,
    )
    preview = Pipeline(profile).run(load_image(args.input))
    save_image(args.output, preview)


if __name__ == "__main__":
    main()
