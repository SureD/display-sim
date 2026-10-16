"""LCD leakage, subpixel mosaics, and viewing angle."""

import numpy as np
import pytest

from sim.frame import Frame
from sim.profile import BacklightParams, PanelParams
from sim.stages.panel import (
    EmissionPsf,
    apply_viewing_angle,
    composite_subpixels,
    emission_psf,
    lcd_transmit,
    render_subpixels,
    simulate_panel,
    spread_emission,
)


def _gaussian_psf(sigma: float, tail_sigma: float = 2.0, weight: float = 0.0) -> EmissionPsf:
    return emission_psf(
        BacklightParams(
            mode="per_pixel",
            psf_sigma_zones=sigma,
            psf_tail_sigma_zones=tail_sigma,
            psf_tail_weight=weight,
        )
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


def test_emission_psf_sigmas_are_pixels_not_zone_pitches():
    from sim.filters import gaussian_kernel1d

    psf = _gaussian_psf(0.45, tail_sigma=2.0, weight=0.1)
    # 0.45 is read as 0.45 px, so the kernel is the one-pixel-sigma Gaussian.
    assert np.allclose(psf.kernels[0], gaussian_kernel1d(0.45))
    assert np.allclose(psf.kernels[2], gaussian_kernel1d(2.0))
    assert psf.kernels[4] == pytest.approx(0.1)


def test_emission_psf_moves_light_onto_dark_neighbors_without_creating_any():
    # Wide enough that the tail stays inside the frame: reflect padding would
    # otherwise mirror light back and inflate the sum (research/m3 boundary note).
    emitted = np.zeros((25, 25, 3), dtype=np.float32)
    emitted[12, 12] = (300.0, 0.0, 0.0)
    spread = spread_emission(emitted, _gaussian_psf(0.8, 2.0, 0.05))
    assert spread[12, 13, 0] > 0.0
    assert spread[12, 12, 0] < 300.0
    # Only the red emitter was lit, so only red moves.
    assert np.allclose(spread[..., 1:], 0.0)
    assert float(spread.sum()) == pytest.approx(300.0, rel=1e-3)


def test_zero_emission_psf_is_identity():
    emitted = np.zeros((5, 5, 3), dtype=np.float32)
    emitted[2, 2] = (120.0, 60.0, 30.0)
    assert np.allclose(spread_emission(emitted, _gaussian_psf(0.0)), emitted)


def test_oled_emission_psf_glows_past_the_emitter_edge():
    target = np.zeros((9, 9, 3), dtype=np.float32)
    target[3:6, 3:6] = 500.0
    frame = Frame(target, backlight=np.max(target, axis=-1))
    sharp = simulate_panel(
        frame,
        PanelParams(subpixel="qd_oled"),
        self_emissive=True,
        peak_nits=600.0,
    )
    glowing = simulate_panel(
        frame,
        PanelParams(subpixel="qd_oled"),
        self_emissive=True,
        peak_nits=600.0,
        psf=_gaussian_psf(0.6),
    )
    assert float(sharp.rgb[3, 2].max()) == 0.0
    assert float(glowing.rgb[3, 2].max()) > 0.0
    # A self-emissive panel still reaches zero away from the lit block.
    assert float(glowing.rgb[0, 0].max()) == pytest.approx(0.0, abs=1e-6)
