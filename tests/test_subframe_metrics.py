"""Analytic response, modulation and tracking-aperture checks for M18."""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from tv_sim.subframe_metrics import (
    flicker_metrics,
    pursuit_image,
    pursuit_metrics,
    response_metrics,
)


def test_first_order_response_matches_log_nine_and_settles_only_in_suffix():
    tau = 0.005
    t = np.linspace(0.00001, 0.1, 10000)
    result = response_metrics(20 + 80 * (1 - np.exp(-t / tau)), t, 20, 100)
    assert result["response_10_90_s"] == pytest.approx(np.log(9) * tau, abs=1e-8)
    assert result["settling_s"] == pytest.approx(-tau * np.log(0.02), abs=1e-5)
    assert result["overshoot_nits"] == 0
    assert result["inverse_ghost_amplitude_nits"] == 0


@pytest.mark.parametrize("old,new", [(20, 100), (100, 20)])
def test_response_direction_and_overshoot_are_symmetric(old, new):
    result = response_metrics(
        old + (new - old) * np.array([0.1, 0.9, 1.2, 1.0]), [0.01, 0.02, 0.03, 0.04], old, new
    )
    assert result["response_10_90_s"] == pytest.approx(0.01)
    assert result["overshoot_percent"] == pytest.approx(20)
    assert result["inverse_ghost_amplitude_nits"] == pytest.approx(16)
    assert result["settling_s"] == 0.04


def test_short_response_is_censored_and_intermediate_settling_does_not_count():
    result = response_metrics([0, 0.99, 0.7, 0.8], [0, 0.1, 0.2, 0.3], 0, 1)
    assert result["settling_s"] is None
    assert not result["settled_within_observation"]
    short = response_metrics([0, 0.2], [0, 0.1], 0, 1)
    assert short["response_10_90_s"] is None


def test_square_wave_flicker_metrics_and_black_dc_conventions():
    result = flicker_metrics(np.tile([0, 10], 100), Fraction(1, 100))
    assert result["flicker_percent"] == 100
    assert result["flicker_index"] == 0.5
    assert result["mean_nits"] == 5
    assert result["dominant_frequency_hz"] == 50
    for level in (0, 50):
        steady = flicker_metrics(np.full(64, level), Fraction(1, 1000))
        assert steady["flicker_percent"] == steady["flicker_index"] == 0
        assert steady["dominant_frequency_hz"] is None


def test_sinusoidal_flicker_has_known_modulation_and_frequency():
    time = np.arange(1000) / 1000
    result = flicker_metrics(100 + 20 * np.cos(2 * np.pi * 100 * time), Fraction(1, 1000))
    assert result["flicker_percent"] == 20
    assert result["dominant_frequency_hz"] == 100


def test_tracking_rectangular_hold_matches_declared_mprt_normalization():
    count = 400
    dt = Fraction(1, 10000)
    image = np.zeros((2, 256, 3), dtype=np.float32)
    image[:, 128:] = 100
    pursuit = pursuit_image(
        [image] * count, [i * dt for i in range(count)], [dt] * count, 1000, count * dt / 2
    )
    metrics = pursuit_metrics(pursuit, 1000)
    assert metrics["edge_10_90_width_px"] == pytest.approx(32, abs=0.01)
    assert metrics["normalized_mprt_s"] == pytest.approx(0.04, abs=2e-5)
    assert metrics["effective_10_90_time_s"] == pytest.approx(0.032, abs=2e-5)


def test_pursuit_keeps_dark_time_and_static_zero_velocity_average():
    white = np.full((2, 16, 3), 100, dtype=np.float32)
    black = np.zeros_like(white)
    out = pursuit_image(
        [white, black], [Fraction(0), Fraction(1, 2)], [Fraction(1, 2)] * 2, 0, Fraction(0)
    )
    np.testing.assert_array_equal(out, np.full_like(white, 50))


@pytest.mark.parametrize(
    "values,times,old,new",
    [([1], [0], 0, 1), ([0, 1], [0, 0], 0, 1), ([0, 1], [0, 1], 1, 1), ([0, np.nan], [0, 1], 0, 1)],
)
def test_invalid_response_inputs_reject(values, times, old, new):
    with pytest.raises(ValueError):
        response_metrics(values, times, old, new)


@pytest.mark.parametrize(
    "values,dt", [([0, -1], 0.1), ([0, 1], 0), ([0, 1], float("nan")), ([0, float("inf")], 0.1)]
)
def test_invalid_flicker_inputs_reject(values, dt):
    with pytest.raises(ValueError):
        flicker_metrics(values, dt)


def test_pursuit_rejects_clock_gaps_and_flat_edge():
    image = np.zeros((2, 16, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="contiguous"):
        pursuit_image(
            [image, image], [Fraction(0), Fraction(1)], [Fraction(1, 2)] * 2, 1, Fraction(0)
        )
    with pytest.raises(ValueError, match="distinct"):
        pursuit_metrics(image, 1)


def test_instant_response_is_reported_as_unresolved_at_sampling_resolution():
    result = response_metrics([100, 100], [0.001, 0.002], 0, 100)
    assert result["response_10_90_s"] is None
    assert result["response_10_90_upper_bound_s"] == 0.001
    assert result["unresolved_at_sampling_resolution"]
