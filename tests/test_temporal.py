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
