"""Zone dimming, light-spread PSF, and per-pixel OLED drive."""

import numpy as np

from sim.frame import Frame
from sim.profile import BacklightParams
from sim.stages.backlight import simulate_backlight


def _window(size: int = 96, fraction: float = 0.1, nits: float = 100.0) -> Frame:
    image = np.zeros((size, size, 3), dtype=np.float32)
    side = max(1, int(round(size * np.sqrt(fraction))))
    y0 = (size - side) // 2
    x0 = (size - side) // 2
    image[y0 : y0 + side, x0 : x0 + side] = nits
    return Frame(image)


def test_flat_field_fald_preserves_dc_and_respects_peak():
    frame = Frame(np.full((48, 64, 3), 100.0, dtype=np.float32))
    out = simulate_backlight(
        frame,
        BacklightParams(mode="fald", zones_x=8, zones_y=6, psf_sigma_zones=0.8, peak_nits=150.0),
    )
    assert np.allclose(out.backlight, 100.0, atol=0.05)
    hot = simulate_backlight(
        Frame(np.full((32, 32, 3), 400.0, dtype=np.float32)),
        BacklightParams(mode="fald", zones_x=4, zones_y=4, psf_sigma_zones=0.5, peak_nits=150.0),
    )
    assert hot.backlight.max() <= 150.0 + 1e-3


def test_fald_window_blooms_beyond_the_lit_zones():
    frame = _window()
    out = simulate_backlight(
        frame,
        BacklightParams(mode="fald", zones_x=12, zones_y=8, psf_sigma_zones=0.8, peak_nits=500.0),
    )
    # Just outside the window, still inside the blurred skirt.
    near = out.backlight[20, 48]
    corner = out.backlight[0, 0]
    assert near > corner + 1.0
    assert corner < 1.0


def test_oled_per_pixel_does_not_bloom():
    frame = _window(size=32)
    out = simulate_backlight(
        frame,
        BacklightParams(mode="per_pixel", psf_sigma_zones=0.0, peak_nits=800.0),
    )
    assert out.backlight[0, 0] == 0.0
    assert out.backlight[16, 16] == 100.0


def test_edge_lit_column_is_vertically_uniform():
    frame = _window(size=64)
    out = simulate_backlight(
        frame,
        BacklightParams(mode="edge", zones_x=8, zones_y=1, psf_sigma_zones=0.4, peak_nits=400.0),
    )
    column = out.backlight[:, 32]
    assert np.allclose(column, column[0], atol=0.05)
    assert column[0] > out.backlight[32, 0]


def test_profile_small_windows_emit_lcd_halo_with_inverse_contrast_scaling():
    from sim.profile import load_profile
    from sim.stages.panel import lcd_transmit

    profile = load_profile("generic_va_fald_miniled")
    for fraction in (0.01, 0.02, 0.10):
        frame = _window(size=96, fraction=fraction, nits=1000.0)
        driven = simulate_backlight(frame, profile.backlight)
        emitted = lcd_transmit(frame.rgb, driven.backlight, profile.panel.native_contrast)
        dark = frame.rgb[..., 0] == 0
        # Measure emitted halo, rather than interpreting backlight spread as light.
        halo = emitted[..., 0][dark]
        assert halo.max() > 0.001
        assert halo.max() > emitted[0, 0, 0] + 0.001
        assert np.allclose(halo, driven.backlight[dark] / profile.panel.native_contrast,
                           rtol=1e-4, atol=1e-6)
        higher_contrast = lcd_transmit(frame.rgb, driven.backlight,
                                      2 * profile.panel.native_contrast)
        assert np.allclose(higher_contrast[..., 0][dark], halo / 2, atol=1e-6)
        assert np.isfinite(emitted).all()
        assert emitted.min() >= 0
