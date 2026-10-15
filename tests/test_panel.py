"""LCD leakage, subpixel mosaics, and viewing angle."""

import numpy as np

from sim.frame import Frame
from sim.profile import PanelParams
from sim.stages.panel import (
    apply_viewing_angle,
    composite_subpixels,
    lcd_transmit,
    render_subpixels,
    simulate_panel,
)


def test_lcd_black_sits_on_the_contrast_floor():
    backlight = np.full((4, 4), 100.0, dtype=np.float32)
    target = np.zeros((4, 4, 3), dtype=np.float32)
    emitted = lcd_transmit(target, backlight, contrast=1000.0)
    assert np.allclose(emitted, 0.1)
    matched = lcd_transmit(np.full((4, 4, 3), 40.0, np.float32), backlight, contrast=1000.0)
    assert np.allclose(matched, 40.0, atol=1e-4)


def test_subpixel_layouts_preserve_flat_color():
    color = np.array([10.0, 20.0, 5.0], dtype=np.float32)
    image = np.broadcast_to(color, (5, 7, 3)).copy()
    for layout, shape in (
        ("rgb_stripe", (5, 21, 3)),
        ("wrgb", (5, 28, 3)),
        ("qd_oled", (10, 21, 3)),
    ):
        mosaic = render_subpixels(image, layout)
        assert mosaic.shape == shape
        assert np.allclose(composite_subpixels(mosaic, layout), image, atol=1e-5)


def test_viewing_angle_reduces_chroma_and_zero_is_identity():
    red = np.array([[[80.0, 0.0, 0.0]]], dtype=np.float32)
    same = apply_viewing_angle(red, angle_deg=0.0, loss_per_deg=0.08)
    assert np.allclose(same, red)
    angled = apply_viewing_angle(red, angle_deg=45.0, loss_per_deg=0.08)
    assert angled[0, 0, 0] < red[0, 0, 0]
    assert angled[0, 0, 1] > 0.0


def test_oled_panel_clips_to_peak_without_lcd_floor():
    target = np.zeros((2, 2, 3), dtype=np.float32)
    target[0, 0] = (50.0, 0.0, 0.0)
    target[0, 1] = (5000.0, 5000.0, 5000.0)
    frame = Frame(target, backlight=np.max(target, axis=-1))
    out = simulate_panel(
        frame,
        PanelParams(subpixel="wrgb"),
        self_emissive=True,
        peak_nits=800.0,
    )
    assert np.allclose(out.rgb[0, 0], (50.0, 0.0, 0.0), atol=1e-4)
    assert np.allclose(out.rgb[0, 1], 800.0, atol=1e-3)
    assert np.allclose(out.rgb[1, 1], 0.0)
