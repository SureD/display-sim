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


def test_two_component_psf_keeps_dc_and_widens_the_halo():
    flat = simulate_backlight(
        Frame(np.full((48, 48, 3), 80.0, dtype=np.float32)),
        BacklightParams(
            mode="fald",
            zones_x=6,
            zones_y=6,
            psf_sigma_zones=0.4,
            psf_tail_sigma_zones=1.5,
            psf_tail_weight=0.12,
            peak_nits=200.0,
        ),
    )
    assert np.allclose(flat.backlight, 80.0, atol=0.05)
    frame = _window(size=72, fraction=0.04, nits=100.0)
    core = simulate_backlight(
        frame,
        BacklightParams(mode="fald", zones_x=9, zones_y=9, psf_sigma_zones=0.35, psf_tail_weight=0.0),
    )
    tailed = simulate_backlight(
        frame,
        BacklightParams(
            mode="fald",
            zones_x=9,
            zones_y=9,
            psf_sigma_zones=0.35,
            psf_tail_sigma_zones=1.8,
            psf_tail_weight=0.15,
        ),
    )
    # Farther from the window, the tail carries more light than the core alone.
    assert tailed.backlight[2, 36] > core.backlight[2, 36] + 0.2


def test_zone_percentile_can_ignore_a_tiny_highlight():
    image = np.zeros((16, 16, 3), dtype=np.float32)
    image[0, 0] = 100.0
    image[0, 1] = 100.0
    peaked = simulate_backlight(
        Frame(image),
        BacklightParams(mode="fald", zones_x=1, zones_y=1, psf_sigma_zones=0.0, zone_percentile=100.0),
    )
    robust = simulate_backlight(
        Frame(image),
        BacklightParams(mode="fald", zones_x=1, zones_y=1, psf_sigma_zones=0.0, zone_percentile=50.0),
    )
    assert peaked.backlight[8, 8] == 100.0
    assert robust.backlight[8, 8] < 1.0
