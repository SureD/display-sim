"""Response-time lag and sample-and-hold blur."""

import numpy as np

from sim.frame import Frame
from sim.profile import TemporalParams
from sim.stages.temporal import TemporalState, apply_temporal


def test_response_time_lags_a_step():
    params = TemporalParams(
        response_time_ms=100.0,
        frame_time_ms=16.666,
        sample_and_hold=True,
        motion_px_per_frame=0.0,
    )
    state = TemporalState()
    black = apply_temporal(Frame(np.zeros((4, 4, 3), np.float32)), params, state)
    assert np.allclose(black.rgb, 0.0)
    white = apply_temporal(Frame(np.full((4, 4, 3), 100.0, np.float32)), params, state)
    alpha = 1.0 - np.exp(-16.666 / 100.0)
    assert np.allclose(white.rgb, 100.0 * alpha, rtol=1e-4)
    assert white.rgb.mean() < 100.0


def test_sample_and_hold_blurs_a_moving_edge_and_zero_motion_does_not():
    image = np.zeros((8, 32, 3), dtype=np.float32)
    image[:, 16:] = 100.0
    still = apply_temporal(
        Frame(image),
        TemporalParams(sample_and_hold=True, motion_px_per_frame=0.0),
        TemporalState(),
    )
    assert np.allclose(still.rgb, image)
    moving = apply_temporal(
        Frame(image),
        TemporalParams(sample_and_hold=True, motion_px_per_frame=6.0),
        TemporalState(),
    )
    # The held edge is smeared, so the pixel just left of the step rises
    # and the pixel just right of it falls.
    assert moving.rgb[4, 15, 0] > image[4, 15, 0]
    assert moving.rgb[4, 16, 0] < image[4, 16, 0]


def test_history_preserves_afterglow_and_converges_without_overshoot():
    params = TemporalParams(response_time_ms=20, frame_time_ms=5, sample_and_hold=False)
    state = TemporalState()
    dark = Frame(np.zeros((2, 2, 3), np.float32))
    bright = Frame(np.full((2, 2, 3), 100, np.float32))
    apply_temporal(dark, params, state)
    rising = [apply_temporal(bright, params, state).rgb.mean() for _ in range(40)]
    assert 0 < rising[0] < 100
    assert np.all(np.diff(rising) >= 0)
    assert 99.9 < rising[-1] <= 100
    falling = [apply_temporal(dark, params, state).rgb.mean() for _ in range(40)]
    assert 0 < falling[0] < rising[-1]
    assert np.all(np.diff(falling) <= 0)
    assert 0 <= falling[-1] < 0.01
    # Independent clips start settled instead of inheriting another clip's trail.
    assert np.array_equal(apply_temporal(dark, params, TemporalState()).rgb, dark.rgb)


def test_pursuit_blur_does_not_accumulate_in_response_history():
    image = np.zeros((4, 32, 3), np.float32)
    image[:, 16:] = 100
    params = TemporalParams(response_time_ms=20, motion_px_per_frame=8)
    state = TemporalState()
    first = apply_temporal(Frame(image), params, state)
    assert not np.array_equal(first.rgb, image)
    assert np.array_equal(state.previous, image)
    second = apply_temporal(Frame(image), params, state)
    assert np.allclose(second.rgb, first.rgb)
