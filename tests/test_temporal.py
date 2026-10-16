"""Response-time lag and sample-and-hold blur."""

from dataclasses import replace

import numpy as np
import pytest

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


def test_subframe_exposure_matches_integrated_step_and_retains_endpoint_state():
    params = TemporalParams(
        response_time_ms=12,
        frame_time_ms=16,
        sample_and_hold=False,
        integration_samples=64,
    )
    state = TemporalState()
    black = np.zeros((2, 3, 3), np.float32)
    white = np.full_like(black, 100)
    apply_temporal(Frame(black), params, state)
    shown = apply_temporal(Frame(white), params, state)
    # Exact average of 100*(1-exp(-t/tau)), distinct from the endpoint.
    average = 100 * (1 - 12 / 16 * (1 - np.exp(-16 / 12)))
    endpoint = 100 * (1 - np.exp(-16 / 12))
    assert np.allclose(shown.rgb, average, atol=0.002)
    assert np.allclose(state.previous, endpoint, atol=0.001)
    assert shown.rgb.mean() < state.previous.mean()


def test_subframe_bfi_samples_centered_pulse_and_preserves_panel_history():
    params = TemporalParams(
        response_time_ms=12,
        frame_time_ms=16,
        sample_and_hold=False,
        bfi_duty=0.25,
        integration_samples=64,
    )
    black = np.zeros((2, 3, 3), np.float32)
    white = np.full_like(black, 100)
    state = TemporalState()
    apply_temporal(Frame(black), params, state)
    shown = apply_temporal(Frame(white), params, state)
    # A centered quarter-frame pulse emits over t=[6, 10] ms.
    expected = 100 / 16 * (4 + 12 * (np.exp(-10 / 12) - np.exp(-6 / 12)))
    assert np.allclose(shown.rgb, expected, atol=0.001)
    assert np.allclose(state.previous, 100 * (1 - np.exp(-16 / 12)), atol=0.001)
    # The emission gate never dims the stored response state.
    assert state.previous.mean() > 5 * shown.rgb.mean()


def test_subframe_hold_converges_and_bfi_narrows_ideal_pursuit_edge():
    from sim.metrics import moving_edge_blur_px

    edge = np.zeros((2, 128, 3), np.float32)
    edge[:, 64:] = 100
    params = TemporalParams(response_time_ms=0, motion_px_per_frame=16, integration_samples=16)
    full = apply_temporal(Frame(edge), params)
    refined = apply_temporal(Frame(edge), replace(params, integration_samples=128))
    bfi = apply_temporal(Frame(edge), replace(params, bfi_duty=0.25))
    full_width = moving_edge_blur_px(full.rgb[0, :, 0])
    refined_width = moving_edge_blur_px(refined.rgb[0, :, 0])
    bfi_width = moving_edge_blur_px(bfi.rgb[0, :, 0])
    # Ideal rectangular hold: 10-90% width = .8 * speed * visible_time.
    assert abs(full_width - 12.8) < 0.2
    assert abs(full_width - refined_width) < 0.2
    # Bilinear image sampling adds a small footprint at this narrow width.
    assert abs(bfi_width - 3.2) < 0.25
    assert np.allclose(bfi.rgb[:, -1], 25)


def test_long_pan_distinguishes_response_overdrive_and_hold():
    params = TemporalParams(
        response_time_ms=12,
        frame_time_ms=16,
        motion_px_per_frame=4,
        integration_samples=24,
    )
    modes = {
        "lcd": params,
        "oled": replace(params, response_time_ms=0.2),
        "od": replace(params, overdrive_gain=0.8, overdrive_ms=4),
        "no_hold": replace(params, response_time_ms=0.2, sample_and_hold=False),
    }
    states = {key: TemporalState() for key in modes}
    output = {}
    for index in range(37):
        bar = np.zeros((2, 192, 3), np.float32)
        left = 16 + 4 * max(0, index - 12)  # 12 settled pre-roll frames.
        bar[:, left:left + 12] = 100
        for key, mode in modes.items():
            output[key] = apply_temporal(Frame(bar), mode, states[key]).rgb
    left = 16 + 4 * 24
    # Slow response carries light into older pan positions. OD increases
    # the newly arrived bar's exposure; instantaneous response still blurs
    # in tracking-eye coordinates when the source is held for a frame.
    assert output["lcd"][:, left - 5:left - 2].mean() > output["oled"][:, left - 5:left - 2].mean() + 1
    assert output["od"][:, left + 9:left + 12].mean() > output["lcd"][:, left + 9:left + 12].mean() + 2
    assert output["oled"][:, left + 12].mean() > 1
    assert np.allclose(output["no_hold"][:, left + 12], 0)


@pytest.mark.parametrize("samples", [0, -1, 2.5, True])
def test_subframe_sample_count_requires_positive_integer(samples):
    with pytest.raises(ValueError, match="integration_samples"):
        apply_temporal(Frame(np.zeros((1, 1, 3))), TemporalParams(integration_samples=samples))
