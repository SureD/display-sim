"""Zone dimming, light-spread PSF, and per-pixel OLED drive."""

import numpy as np
import pytest

from tv_sim.frame import Frame
from tv_sim.profile import BacklightParams, PsfProfile
from tv_sim.stages.backlight import simulate_backlight, table_kernel1d


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
    from tv_sim.profile import load_profile
    from tv_sim.stages.panel import lcd_transmit

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
        assert np.allclose(
            halo, driven.backlight[dark] / profile.panel.native_contrast, rtol=1e-4, atol=1e-6
        )
        higher_contrast = lcd_transmit(
            frame.rgb, driven.backlight, 2 * profile.panel.native_contrast
        )
        assert np.allclose(higher_contrast[..., 0][dark], halo / 2, atol=1e-6)
        assert np.isfinite(emitted).all()
        assert emitted.min() >= 0


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
        BacklightParams(
            mode="fald", zones_x=9, zones_y=9, psf_sigma_zones=0.35, psf_tail_weight=0.0
        ),
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
        BacklightParams(
            mode="fald", zones_x=1, zones_y=1, psf_sigma_zones=0.0, zone_percentile=100.0
        ),
    )
    robust = simulate_backlight(
        Frame(image),
        BacklightParams(
            mode="fald", zones_x=1, zones_y=1, psf_sigma_zones=0.0, zone_percentile=50.0
        ),
    )
    assert peaked.backlight[8, 8] == 100.0
    assert robust.backlight[8, 8] < 1.0


def test_exponential_tail_reaches_further_than_a_gaussian_tail():
    frame = _window(size=96, fraction=0.02, nits=400.0)
    shared = dict(
        mode="fald",
        zones_x=12,
        zones_y=12,
        psf_sigma_zones=0.4,
        psf_tail_sigma_zones=1.5,
        psf_tail_weight=0.12,
        peak_nits=600.0,
    )
    gaussian = simulate_backlight(frame, BacklightParams(**shared, psf_shape="gaussian"))
    skirt = simulate_backlight(frame, BacklightParams(**shared, psf_shape="exponential_tail"))
    far = (4, 48)
    assert skirt.backlight[far] > gaussian.backlight[far]
    # Both still preserve DC on a flat field.
    flat = Frame(np.full((48, 48, 3), 90.0, dtype=np.float32))
    for shape in ("gaussian", "exponential_tail"):
        out = simulate_backlight(
            flat,
            BacklightParams(
                mode="fald",
                zones_x=6,
                zones_y=6,
                psf_sigma_zones=0.4,
                psf_tail_sigma_zones=1.5,
                psf_tail_weight=0.12,
                psf_shape=shape,
                peak_nits=200.0,
            ),
        )
        assert np.allclose(out.backlight, 90.0, atol=0.1)


def test_unknown_psf_shape_and_boundary_are_rejected():
    frame = _window(size=32)
    with pytest.raises(ValueError, match="psf_shape"):
        simulate_backlight(frame, BacklightParams(zones_x=4, zones_y=4, psf_shape="bspline"))
    with pytest.raises(ValueError, match="psf_boundary"):
        simulate_backlight(frame, BacklightParams(zones_x=4, zones_y=4, psf_boundary="wrap"))


def test_zero_boundary_darkens_a_corner_and_calibration_restores_it():
    flat = Frame(np.full((48, 48, 3), 100.0, dtype=np.float32))
    shared = dict(mode="fald", zones_x=6, zones_y=6, psf_sigma_zones=0.8, peak_nits=400.0)
    reflected = simulate_backlight(flat, BacklightParams(**shared, psf_boundary="reflect"))
    zeroed = simulate_backlight(flat, BacklightParams(**shared, psf_boundary="zero"))
    calibrated = simulate_backlight(flat, BacklightParams(**shared, psf_boundary="calibrated_zero"))
    assert np.allclose(reflected.backlight, 100.0, atol=0.1)
    # Zero extension loses the footprint that falls off the panel.
    assert zeroed.backlight[0, 0] < 80.0
    # The all-on normalization puts the commanded drive back at the border.
    assert np.allclose(calibrated.backlight, 100.0, atol=0.1)


def test_calibrated_zero_does_not_mirror_a_highlight_inward():
    image = np.zeros((48, 48, 3), dtype=np.float32)
    image[:, :4] = 500.0
    shared = dict(mode="fald", zones_x=12, zones_y=12, psf_sigma_zones=0.9, peak_nits=600.0)
    reflected = simulate_backlight(Frame(image), BacklightParams(**shared))
    calibrated = simulate_backlight(
        Frame(image), BacklightParams(**shared, psf_boundary="calibrated_zero")
    )
    # Reflect padding folds the strip's own light back across the border, so
    # the dark region next to it reads brighter than the calibrated policy.
    # Far enough in that the two policies agree again, the margin vanishes.
    dark = slice(5, 11)
    assert np.all(reflected.backlight[24, dark] > calibrated.backlight[24, dark])


def test_table_kernel_is_unit_sum_and_symmetric():
    kernel = table_kernel1d([1.0, 0.6, 0.25, 0.08, 0.0], step_px=2.0)
    assert kernel.sum() == pytest.approx(1.0)
    assert np.allclose(kernel, kernel[::-1])
    assert kernel.size == 2 * 8 + 1
    assert kernel[8] == kernel.max()


def test_table_kernel_rejects_unusable_tables():
    with pytest.raises(ValueError, match="at least two"):
        table_kernel1d([1.0], step_px=2.0)
    with pytest.raises(ValueError, match="nonnegative"):
        table_kernel1d([1.0, -0.2], step_px=2.0)
    with pytest.raises(ValueError, match="positive centre"):
        table_kernel1d([0.0, 0.5], step_px=2.0)
    with pytest.raises(ValueError, match="one-pixel radius"):
        table_kernel1d([1.0, 0.5], step_px=0.4)


def test_tabulated_lsf_overrides_the_parametric_axis():
    frame = _window(size=96, fraction=0.02, nits=400.0)
    shared = dict(
        mode="fald",
        zones_x=12,
        zones_y=12,
        psf_sigma_zones=0.4,
        peak_nits=600.0,
    )
    parametric = simulate_backlight(frame, BacklightParams(**shared))
    # A deliberately wide half-profile on x only.
    tabulated = simulate_backlight(
        frame,
        BacklightParams(
            **shared,
            psf_profile=PsfProfile(step_zones=0.5, x=[1.0, 0.75, 0.45, 0.2, 0.05, 0.0]),
        ),
    )
    # The isotropic Gaussian halo is gone at this distance on both axes; the
    # tabulated x profile reaches it horizontally and not vertically.
    assert parametric.backlight[48, 24] == pytest.approx(0.0, abs=1e-3)
    assert parametric.backlight[24, 48] == pytest.approx(0.0, abs=1e-3)
    assert tabulated.backlight[48, 24] > 1.0
    assert tabulated.backlight[24, 48] == pytest.approx(0.0, abs=1e-3)


def test_psf_profile_accepts_a_yaml_mapping():
    params = BacklightParams(psf_profile={"step_zones": 0.5, "y": [1.0, 0.4, 0.0]})
    assert isinstance(params.psf_profile, PsfProfile)
    assert params.psf_profile.x is None
    assert params.psf_profile.y == [1.0, 0.4, 0.0]
