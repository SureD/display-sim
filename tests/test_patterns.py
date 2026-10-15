"""Geometry of the built-in test patterns."""

import numpy as np

from sim.patterns import ansi_contrast, checkerboard, ramp, white_window, window_bounds


def test_pattern_shapes_and_window():
    assert ramp(32, 8).shape == (8, 32, 3)
    assert ramp(8, 2)[0, 0, 0] == 0
    assert ramp(8, 2)[0, -1, 0] == 255
    board = checkerboard(16, 16, cell=8)
    assert board[0, 0, 0] == 0
    assert board[0, 8, 0] == 255
    ansi = ansi_contrast(cell=4)
    assert ansi.shape == (16, 16, 3)
    image = white_window(40, 20, fraction=0.25)
    y0, y1, x0, x1 = window_bounds(40, 20, 0.25)
    assert np.all(image[y0:y1, x0:x1] == 255)
    assert image[0, 0, 0] == 0
