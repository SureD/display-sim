"""Command-line preview and validation.

Preview one still::

    python -m sim --profile NAME --input in.png --output out.png

Run the pattern harness (metrics JSON/CSV, comparison.md, and preview PNGs)::

    python -m sim validate [--profiles NAME ...] [--out reports/]

Build the offline visual gallery::

    python -m sim gallery [--out reports/gallery/]

Schedule a numbered-image motion experiment (default MEMC off)::

    python -m sim motion --profile NAME --input-frames 'clip/*.png' --source-fps 24

Check profile provenance without changing runtime settings::

    python -m sim provenance --check

Fit separate, opt-in window replay datasets::

    python -m sim fit-windows --help
"""

from __future__ import annotations

import argparse
import sys
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
    parser.epilog = (parser.epilog or "") + " Commands: python -m sim {validate,gallery,motion,provenance,fit-windows} --help"
    return parser


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    if argv and argv[0] == "fit-windows":
        from sim.window_replay import main as fit_windows_main

        fit_windows_main(argv[1:])
        return
    if argv and argv[0] == "motion":
        from sim.motion_cli import main as motion_main

        motion_main(argv[1:])
        return
    if argv and argv[0] == "provenance":
        from sim.provenance import main as provenance_main

        provenance_main(argv[1:])
        return
    if argv and argv[0] == "validate":
        from sim.validate import main as validate_main

        validate_main(argv[1:])
        return
    if argv and argv[0] == "gallery":
        from sim.gallery import main as gallery_main

        gallery_main(argv[1:])
        return
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
