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
