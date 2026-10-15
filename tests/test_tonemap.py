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


def test_oled_profiles_reduce_highlight_output_as_window_load_increases():
    from dataclasses import replace
    from sim.profile import load_profile

    for name in ("generic_woled", "generic_qdoled"):
        params = load_profile(name).hdr
        peaks, highlights = [], []
        for side in (2, 6, 10, 14, 20):
            rgb = np.zeros((20, 20, 3), np.float32)
            rgb[:side, :side] = params.panel_peak_nits
            peaks.append(effective_peak(rgb, params))
            highlights.append(tone_map(Frame(rgb), params).rgb.max())
            # Load has no effect on the ceiling when the limiter is disabled.
            assert effective_peak(rgb, replace(params, abl_enabled=False)) == params.panel_peak_nits
        assert np.all(np.diff(peaks) < 0)
        assert np.all(np.diff(highlights) < 0)
        assert np.isclose(peaks[-1], params.abl_full_field_nits)
        assert highlights[-1] <= params.abl_full_field_nits + 1e-3


def test_neutral_hdr_ramp_remains_monotone_and_bounded():
    params = HdrParams(panel_peak_nits=1000, knee_ratio=0.7, abl_enabled=False)
    ramp = np.linspace(0, 10000, 1001, dtype=np.float32)
    rgb = np.repeat(ramp[None, :, None], 3, axis=2)
    output = tone_map(Frame(rgb), params).rgb
    assert np.isfinite(output).all()
    assert output[0, 0, 0] == 0
    assert np.all(np.diff(output[0, :, 0]) >= 0)
    assert output.max() <= params.panel_peak_nits + 1e-3
    assert np.allclose(output[0, ramp <= 700, 0], ramp[ramp <= 700], atol=1e-4)
