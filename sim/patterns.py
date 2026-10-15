"""Still test patterns used to exercise the simulator.

Patterns are ``uint8`` sRGB (or gamma-encoded preview) images:

* ``ramp`` — horizontal code-value ramp
* ``checkerboard`` — high-frequency black/white cells
* ``ansi_contrast`` — 4×4 ANSI checker
* ``white_window`` — white window on black for blooming / ABL
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def ramp(width: int = 256, height: int = 64) -> np.ndarray:
    row = np.linspace(0, 255, width)
    image = np.broadcast_to(row, (height, width)).astype(np.uint8)
    return np.stack([image, image, image], axis=-1)


def checkerboard(width: int = 128, height: int = 128, cell: int = 8) -> np.ndarray:
    if cell < 1:
        raise ValueError("cell must be >= 1")
    yy, xx = np.indices((height, width))
    board = (((yy // cell) + (xx // cell)) % 2).astype(np.uint8) * np.uint8(255)
    return np.stack([board, board, board], axis=-1)


def ansi_contrast(cell: int = 32) -> np.ndarray:
    """4×4 black/white ANSI contrast checker."""

    return checkerboard(cell * 4, cell * 4, cell)


def white_window(
    width: int = 200,
    height: int = 200,
    fraction: float = 0.10,
    window: int = 255,
    background: int = 0,
) -> np.ndarray:
    """Centered window covering ``fraction`` of the image area."""

    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be in (0, 1]")
    image = np.full((height, width, 3), background, dtype=np.uint8)
    window_h = max(1, int(round(height * np.sqrt(fraction))))
    window_w = max(1, int(round(width * np.sqrt(fraction))))
    y0 = (height - window_h) // 2
    x0 = (width - window_w) // 2
    image[y0 : y0 + window_h, x0 : x0 + window_w] = window
    return image


def window_bounds(
    width: int, height: int, fraction: float = 0.10
) -> tuple[int, int, int, int]:
    """``(y0, y1, x0, x1)`` matching :func:`white_window`."""

    window_h = max(1, int(round(height * np.sqrt(fraction))))
    window_w = max(1, int(round(width * np.sqrt(fraction))))
    y0 = (height - window_h) // 2
    x0 = (width - window_w) // 2
    return y0, y0 + window_h, x0, x0 + window_w


def write_patterns(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    images = {
        "ramp.png": ramp(),
        "checkerboard.png": checkerboard(),
        "ansi_contrast.png": ansi_contrast(),
        "white_window.png": white_window(),
    }
    for name, image in images.items():
        Image.fromarray(image, mode="RGB").save(directory / name)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write simulator test patterns.")
    parser.add_argument("--output-dir", type=Path, default=Path("patterns"))
    args = parser.parse_args(argv)
    write_patterns(args.output_dir)


if __name__ == "__main__":
    main()
