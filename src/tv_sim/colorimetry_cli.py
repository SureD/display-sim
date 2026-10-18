"""Shared opt-in colorimetry arguments; omitted controls retain legacy behavior."""

from __future__ import annotations

import argparse

from tv_sim.colorimetry import ColorimetryConfig


def add_arguments(parser: argparse.ArgumentParser, *, output: bool = False) -> None:
    parser.add_argument(
        "--colorimetry",
        action="store_true",
        help="Opt into M15 placeholder panel colorimetry and color volume",
    )
    parser.add_argument(
        "--source-primaries",
        choices=("bt709", "display_p3", "bt2020"),
        default=None,
        help="Declared RGB container primaries (default BT.709)",
    )
    parser.add_argument(
        "--source-white",
        type=float,
        nargs=2,
        metavar=("X", "Y"),
        default=None,
        help="Declared source white CIE xy (default D65)",
    )
    parser.add_argument(
        "--gamut-mapping",
        choices=("clip", "compress"),
        default=None,
        help="M15 chromatic gamut mapper (default compress)",
    )
    parser.add_argument(
        "--gamut-compression-knee",
        type=float,
        default=None,
        help="P normalized chroma knee (default 0.8)",
    )
    if output:
        parser.add_argument(
            "--colorimetry-output",
            choices=("bt2020", "display_p3", "xyz", "bt709"),
            default=None,
            help="Linear export basis (default BT.2020 with M15)",
        )


def configuration(args: argparse.Namespace) -> ColorimetryConfig:
    values = (
        args.source_primaries,
        args.source_white,
        args.gamut_mapping,
        args.gamut_compression_knee,
        getattr(args, "colorimetry_output", None),
    )
    if not args.colorimetry and any(value is not None for value in values):
        raise ValueError("colorimetry controls require --colorimetry")
    return ColorimetryConfig(
        enabled=args.colorimetry,
        source_primaries=args.source_primaries or "bt709",
        source_white_xy=tuple(args.source_white)
        if args.source_white is not None
        else (0.3127, 0.3290),
        gamut_mapping=args.gamut_mapping or "compress",
        compression_knee=args.gamut_compression_knee
        if args.gamut_compression_knee is not None
        else 0.8,
    )
