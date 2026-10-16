"""Macro views retain logical-pixel light while exposing synthetic apertures."""

import numpy as np
import pytest

from sim.macro import render_macro


def _cell_means(image, height, width, scale):
    return image.reshape(height, scale, width, scale, 3).mean(axis=(1, 3))


@pytest.mark.parametrize("layout", ["rgb_stripe", "wrgb", "qd_oled"])
def test_macro_preserves_light_in_each_logical_pixel(layout):
    source = np.random.default_rng(15).uniform(0, 250, (3, 5, 3)).astype(np.float32)
    original = source.copy()
    macro = render_macro(source, layout, scale=20)
    assert macro.shape == (60, 100, 3)
    assert macro.dtype == np.float32
    assert np.allclose(_cell_means(macro, 3, 5, 20), source, rtol=2e-6, atol=1e-4)
    assert np.array_equal(source, original)


def test_rgb_stripes_have_channel_order_and_black_matrix():
    macro = render_macro(np.ones((1, 1, 3)), "rgb_stripe", scale=24)
    assert np.array_equal(macro[12, 4] > 0, [True, False, False])
    assert np.array_equal(macro[12, 12] > 0, [False, True, False])
    assert np.array_equal(macro[12, 20] > 0, [False, False, True])
    assert np.all(macro[0] == 0)


def test_wrgb_has_neutral_white_and_residual_colored_apertures():
    neutral = np.ones((1, 1, 3), dtype=np.float32) * 50.0
    macro = render_macro(neutral, "wrgb", scale=32)
    assert np.array_equal(macro[16, 4] > 0, [True, False, False])
    assert np.all(macro[16, 12] > 0)
    assert np.ptp(macro[16, 12]) == 0
    assert np.array_equal(macro[16, 20] > 0, [False, False, True])
    assert np.array_equal(macro[16, 28] > 0, [False, True, False])
    red = render_macro(np.array([[[50.0, 0.0, 0.0]]]), "wrgb", scale=32)
    assert np.all(red[:, 8:16] == 0)  # No W emission from saturated red.
    assert np.all(red[..., 1:] == 0)


def test_qd_green_is_above_red_blue_and_repeat_is_staggered():
    macro = render_macro(np.ones((2, 1, 3)), "qd_oled", scale=40)
    yy, xx = np.indices((40, 40))
    centers = []
    for row in range(2):
        cell = macro[row * 40 : (row + 1) * 40]
        centers.append(
            [(float((xx * cell[..., c]).sum() / cell[..., c].sum()),
              float((yy * cell[..., c]).sum() / cell[..., c].sum())) for c in range(3)]
        )
    for red, green, blue in centers:
        assert green[1] < red[1] and green[1] < blue[1]
        assert red[0] < green[0] < blue[0]
    assert centers[1][1][0] - centers[0][1][0] > 1.0
    assert np.any(np.all(macro == 0, axis=-1))


def test_smaller_aperture_increases_black_matrix_and_peak_without_losing_light():
    source = np.ones((1, 1, 3), dtype=np.float32) * 100.0
    broad = render_macro(source, "rgb_stripe", scale=32, fill_factor=0.9)
    narrow = render_macro(source, "rgb_stripe", scale=32, fill_factor=0.4)
    assert np.allclose(broad.mean(axis=(0, 1), dtype=np.float64), source[0, 0], rtol=2e-6)
    assert np.allclose(narrow.mean(axis=(0, 1), dtype=np.float64), source[0, 0], rtol=2e-6)
    assert np.count_nonzero(narrow) < np.count_nonzero(broad)
    assert narrow.max() > broad.max() > source.max()


@pytest.mark.parametrize("layout", ["rgb_stripe", "wrgb", "qd_oled"])
def test_macro_black_stays_black(layout):
    assert not np.any(render_macro(np.zeros((2, 3, 3)), layout))


@pytest.mark.parametrize("kwargs", [
    {"scale": 3}, {"scale": 8.5}, {"scale": True},
    {"fill_factor": 0}, {"fill_factor": 1.1}, {"fill_factor": np.nan},
    {"white_fraction": -0.1}, {"white_fraction": np.inf},
])
def test_macro_rejects_invalid_render_parameters(kwargs):
    with pytest.raises(ValueError):
        render_macro(np.ones((1, 1, 3)), "wrgb", **kwargs)


@pytest.mark.parametrize("source", [
    np.zeros((2, 2)), np.zeros((1, 1, 4)), np.zeros((0, 1, 3)),
    np.full((1, 1, 3), -1), np.full((1, 1, 3), np.nan),
])
def test_macro_rejects_invalid_linear_images(source):
    with pytest.raises(ValueError):
        render_macro(source, "rgb_stripe")


def test_macro_rejects_unknown_layout():
    with pytest.raises(ValueError, match="Unknown subpixel layout"):
        render_macro(np.ones((1, 1, 3)), "unknown")
