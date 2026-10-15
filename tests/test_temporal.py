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


def test_still_image_stays_settled_with_overdrive_enabled():
    params = TemporalParams(
        response_time_ms=40.0,
        frame_time_ms=16.666,
        sample_and_hold=True,
        motion_px_per_frame=0.0,
        overdrive_gain=0.8,
        overdrive_ms=4.0,
        overdrive_ceiling_nits=400.0,
        bfi_duty=1.0,
    )
    image = np.full((4, 4, 3), 70.0, dtype=np.float32)
    state = TemporalState()
    first = apply_temporal(Frame(image), params, state)
    second = apply_temporal(Frame(image), params, state)
    assert np.allclose(first.rgb, image)
    assert np.allclose(second.rgb, image)


def test_overdrive_rises_faster_than_the_plain_lag():
    plain = TemporalParams(
        response_time_ms=100.0,
        frame_time_ms=16.666,
        sample_and_hold=False,
        overdrive_gain=0.0,
    )
    driven = TemporalParams(
        response_time_ms=100.0,
        frame_time_ms=16.666,
        sample_and_hold=False,
        overdrive_gain=1.0,
        overdrive_ms=16.666,
        overdrive_ceiling_nits=400.0,
    )
    black = np.zeros((2, 2, 3), dtype=np.float32)
    white = np.full_like(black, 100.0)
    plain_state = TemporalState()
    driven_state = TemporalState()
    apply_temporal(Frame(black), plain, plain_state)
    apply_temporal(Frame(black), driven, driven_state)
    plain_out = apply_temporal(Frame(white), plain, plain_state)
    driven_out = apply_temporal(Frame(white), driven, driven_state)
    assert driven_out.rgb.mean() > plain_out.rgb.mean() + 1.0
    assert driven_out.rgb.max() <= 400.0


def test_bfi_dims_a_still_and_shortens_pursuit_blur():
    image = np.zeros((8, 32, 3), dtype=np.float32)
    image[:, 16:] = 100.0
    held = apply_temporal(
        Frame(image),
        TemporalParams(sample_and_hold=True, motion_px_per_frame=0.0, bfi_duty=0.5),
        TemporalState(),
    )
    assert np.allclose(held.rgb, 0.5 * image, rtol=1e-5)
    full = apply_temporal(
        Frame(image),
        TemporalParams(sample_and_hold=True, motion_px_per_frame=8.0, bfi_duty=1.0),
        TemporalState(),
    )
    strobed = apply_temporal(
        Frame(image),
        TemporalParams(sample_and_hold=True, motion_px_per_frame=8.0, bfi_duty=0.25),
        TemporalState(),
    )
    # Duty scales both the level and the blur width, so the dark side of the
    # edge stays closer to black than a full-hold blur of the same motion.
    assert strobed.rgb[4, 12, 0] < full.rgb[4, 12, 0]
