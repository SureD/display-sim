"""Soft-clip tone map and the placeholder ABL peak."""

import numpy as np

from sim.frame import Frame
from sim.profile import HdrParams
from sim.stages.tonemap import effective_peak, tone_map


def test_soft_clip_is_identity_below_the_knee_and_limits_highlights():
    params = HdrParams(panel_peak_nits=100.0, knee_ratio=0.5, abl_enabled=False)
    mid = tone_map(Frame(np.full((2, 2, 3), 40.0, np.float32)), params)
    assert np.allclose(mid.rgb, 40.0)
    hot = tone_map(Frame(np.full((2, 2, 3), 10_000.0, np.float32)), params)
    assert hot.rgb.max() <= 100.0 + 1e-3
    assert hot.rgb.max() > 90.0
    black = tone_map(Frame(np.zeros((2, 2, 3), np.float32)), params)
    assert np.allclose(black.rgb, 0.0)


def test_abl_pulls_a_full_field_down_more_than_a_small_window():
    params = HdrParams(
        panel_peak_nits=100.0,
        knee_ratio=0.85,
        abl_enabled=True,
        abl_full_field_nits=25.0,
        abl_gamma=2.0,
    )
    full = np.full((20, 20, 3), 100.0, dtype=np.float32)
    window = np.zeros_like(full)
    window[9:11, 9:11] = 100.0
    assert effective_peak(full, params) < effective_peak(window, params)
    full_out = tone_map(Frame(full), params)
    window_out = tone_map(Frame(window), params)
    assert full_out.rgb.max() < 30.0
    assert window_out.rgb.max() > full_out.rgb.max()
    assert full_out.rgb.dtype == np.float32
    assert np.isfinite(full_out.rgb).all()


def test_apl_is_linear_luminance_so_red_dims_less_than_white():
    params = HdrParams(
        panel_peak_nits=100.0,
        knee_ratio=0.5,
        abl_enabled=True,
        abl_full_field_nits=20.0,
        abl_gamma=1.0,
    )
    white = np.full((8, 8, 3), 100.0, dtype=np.float32)
    red = np.zeros_like(white)
    red[..., 0] = 100.0
    assert effective_peak(red, params) > effective_peak(white, params)


def test_saturated_highlight_is_pulled_toward_white_inside_the_peak():
    params = HdrParams(panel_peak_nits=100.0, knee_ratio=0.5, abl_enabled=False)
    red = np.zeros((2, 2, 3), dtype=np.float32)
    red[..., 0] = 1000.0
    out = tone_map(Frame(red), params)
    assert out.rgb.dtype == np.float32
    assert out.rgb.max() <= 100.0 + 1e-3
    assert out.rgb[..., 1].mean() > 1.0
    assert out.rgb[..., 0].mean() > out.rgb[..., 1].mean()


def test_channel_power_budget_scales_a_heavy_frame():
    params = HdrParams(
        panel_peak_nits=500.0,
        knee_ratio=0.99,
        abl_enabled=False,
        abl_power_budget_nits=30.0,
        abl_channel_weights=[1.0, 1.0, 1.0],
    )
    image = np.full((4, 4, 3), 40.0, dtype=np.float32)
    out = tone_map(Frame(image), params)
    # P_req = 120 weighted nits, so the gain is 30/120.
    assert np.allclose(out.rgb, 10.0, rtol=1e-4)
