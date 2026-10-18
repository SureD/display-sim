"""Command-line preview and validation.

Preview one still::

    python -m tv_sim --profile NAME --input in.png --output out.png

Run the pattern harness (metrics JSON/CSV, comparison.md, and preview PNGs)::

    python -m tv_sim validate [--profiles NAME ...] [--out reports/]

Build the offline visual gallery::

    python -m tv_sim gallery [--out reports/gallery/]

Export absolute-linear-nit assets for the static web preview::

    python -m tv_sim export-web [--out web/data/]

Schedule a numbered-image motion experiment (default MEMC off)::

    python -m tv_sim motion --profile NAME --input-frames 'clip/*.png' --source-fps 24

Check profile provenance without changing runtime settings::

    python -m tv_sim provenance --check

Fit separate, opt-in window replay datasets::

    python -m tv_sim fit-windows --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from tv_sim.pipeline import Pipeline
from tv_sim.profile import available_profiles, load_profile
from tv_sim.stages.decode import as_code_values
from tv_sim.viewing_angle import ViewingAngleConfig


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
    parser.add_argument("--profile", required=True, help="YAML profile name in src/tv_sim/profiles")
    parser.add_argument("--input", required=True, type=Path, help="Encoded input image")
    parser.add_argument("--output", required=True, type=Path, help="Preview PNG path")
    parser.add_argument("--input-eotf", choices=("srgb", "pq", "hlg"), default=None)
    from tv_sim.colorimetry_cli import add_arguments

    add_arguments(parser)
    parser.add_argument(
        "--viewing-angle-horizontal",
        "--viewing-angle",
        dest="viewing_angle_horizontal",
        type=float,
        default=None,
        help="Opt into P placeholder angular model: horizontal degrees (combined support 0–45°)",
    )
    parser.add_argument(
        "--viewing-angle-vertical",
        type=float,
        default=None,
        help="Opt into P placeholder angular model: vertical degrees (default 0)",
    )
    parser.add_argument("--ambient-lux", type=float, default=None, help="Room illuminance")
    parser.add_argument(
        "--motion-px",
        type=float,
        default=None,
        help="Sample-and-hold eye motion in pixels per frame",
    )
    parser.epilog = (
        (parser.epilog or "")
        + " Commands: python -m tv_sim {validate,gallery,colorimetry,export-web,motion,provenance,fit-windows,oled-dynamics} --help"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    if argv and argv[0] == "colorimetry":
        from tv_sim.colorimetry_gallery import main as colorimetry_main

        colorimetry_main(argv[1:])
        return
    if argv and argv[0] == "oled-dynamics":
        from tv_sim.oled_dynamics_experiment import main as oled_dynamics_main

        oled_dynamics_main(argv[1:])
        return
    if argv and argv[0] == "export-web":
        from tv_sim.export_web import main as export_web_main

        export_web_main(argv[1:])
        return
    if argv and argv[0] == "fit-windows":
        from tv_sim.window_replay import main as fit_windows_main

        fit_windows_main(argv[1:])
        return
    if argv and argv[0] == "motion":
        from tv_sim.motion_cli import main as motion_main

        motion_main(argv[1:])
        return
    if argv and argv[0] == "provenance":
        from tv_sim.provenance import main as provenance_main

        provenance_main(argv[1:])
        return
    if argv and argv[0] == "validate":
        from tv_sim.validate import main as validate_main

        validate_main(argv[1:])
        return
    if argv and argv[0] == "gallery":
        from tv_sim.gallery import main as gallery_main

        gallery_main(argv[1:])
        return
    parser = build_parser()
    args = parser.parse_args(argv)
    profile = load_profile(args.profile).with_overrides(
        input_eotf=args.input_eotf,
        ambient_lux=args.ambient_lux,
        motion_px=args.motion_px,
    )
    try:
        from tv_sim.colorimetry_cli import configuration

        config = ViewingAngleConfig(
            enabled=args.viewing_angle_horizontal is not None
            or args.viewing_angle_vertical is not None,
            horizontal_deg=args.viewing_angle_horizontal
            if args.viewing_angle_horizontal is not None
            else 0.0,
            vertical_deg=args.viewing_angle_vertical
            if args.viewing_angle_vertical is not None
            else 0.0,
        )
        pipeline = Pipeline(profile, viewing_angle=config, colorimetry=configuration(args))
    except ValueError as exc:
        parser.error(str(exc))
    preview = pipeline.run(load_image(args.input))
    save_image(args.output, preview)


if __name__ == "__main__":
    main()
