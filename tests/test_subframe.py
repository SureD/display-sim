"""M18 analytical response, rational gates, and single-owner state tests."""

import json
import math
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from tv_sim.profile import load_profile
from tv_sim.subframe import (
    MODEL,
    SubframeConfig,
    SubframeState,
    evolution,
    simulate_tick,
    validate_path,
    validate_state,
)


def config(**changes):
    return SubframeConfig(model=MODEL, rise_tau_ms=2, fall_tau_ms=5, **changes)


def image(value, shape=(2, 3, 3)):
    return np.full(shape, value, dtype=np.float64)


def tick(target, settings=None, state=None, *, pts=Fraction(0), duration=Fraction(1, 60), **kwargs):
    target = image(target) if np.isscalar(target) else target
    return simulate_tick(
        target,
        np.full(target.shape[:2], 100.0, dtype=np.float64),
        0,
        SubframeState() if state is None else state,
        pts,
        duration,
        config() if settings is None else settings,
        **kwargs,
    )


def commit(state, result, pts, duration):
    state.previous = result.endpoint.copy()
    state.ticks += 1
    state.next_pts = pts + duration


def profile(name="generic_va_fald_miniled", **legacy):
    original = load_profile(name)
    values = {
        "response_time_ms": 0,
        "overdrive_gain": 0,
        "overdrive_ms": 0,
        "overdrive_ceiling_nits": 0,
        "motion_px_per_frame": 0,
    }
    return replace(original, temporal=replace(original.temporal, **(values | legacy)))


def od_config(**changes):
    return SubframeConfig(
        model=MODEL,
        rise_tau_ms=2,
        fall_tau_ms=2,
        overdrive_levels=(0.0, 0.5, 1.0),
        overdrive_commands=((0.0, 1.0, 1.0), (0.0, 0.5, 1.0), (0.0, 0.0, 1.0)),
        overdrive_fraction="1/2",
        **changes,
    )


def test_default_is_off_and_evolution_has_only_serializable_identity():
    settings = SubframeConfig()
    assert not settings.active
    assert "initial" not in evolution(settings)
    assert json.loads(json.dumps(evolution(config(pwm_hz="240.0"))))["pwm_hz"] == "240/1"
    assert evolution(config(initial="cold")) == evolution(config(initial="resume"))


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "unknown"},
        {"parameter_status": "measured"},
        {"initial": "explicit"},
        {"substeps": 0},
        {"substeps": 4097},
        {"substeps": True},
        {"substeps": 2.5},
        {"rise_tau_ms": None},
        {"rise_tau_ms": -1},
        {"rise_tau_ms": True},
        {"fall_tau_ms": float("nan")},
        {"fall_tau_ms": float("inf")},
        {"pwm_hz": "-1"},
        {"pwm_hz": "inf"},
        {"pwm_hz": True},
        {"pwm_duty": "0"},
        {"pwm_duty": "2"},
        {"pwm_duty": "1/2"},
        {"pwm_phase": "1/4"},
        {"strobe_duty": "0"},
        {"bfi_duty": "-1"},
        {"strobe_phase": "1"},
        {"bfi_phase": "-1/2"},
        {"overdrive_fraction": "-1"},
        {"overdrive_fraction": "2"},
        {"overdrive_fraction": "1/4"},
    ],
)
def test_invalid_configuration_rejects(changes):
    base = {"model": MODEL, "rise_tau_ms": 2, "fall_tau_ms": 5}
    with pytest.raises(ValueError):
        SubframeConfig(**(base | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"rise_tau_ms": 0},
        {"substeps": 8},
        {"initial": "cold"},
        {"pwm_hz": "240"},
        {"strobe_duty": "1/2"},
        {"bfi_phase": "1/4"},
        {"tau_table": ((0, 1, 1), (1, 2, 2))},
    ],
)
def test_off_configuration_never_silently_ignores_options(changes):
    with pytest.raises(ValueError, match="active model"):
        SubframeConfig(**changes)


@pytest.mark.parametrize(
    "table",
    [
        [],
        ((0, 1, 1),),
        ((0, 1), (1, 2)),
        ([0, 1, 1], [1, 1, 1]),
        ((1, 1, 1), (0, 1, 1)),
        ((0, 1, 1), (0, 2, 2)),
        ((0, -1, 1), (1, 2, 2)),
        ((0, 1, float("nan")), (1, 2, 2)),
    ],
)
def test_tau_table_validation(table):
    with pytest.raises(ValueError):
        config(tau_table=table)


@pytest.mark.parametrize(
    "changes",
    [
        {"overdrive_levels": (0, 1)},
        {"overdrive_commands": ((0, 1), (0, 1))},
        {"overdrive_levels": [0, 1], "overdrive_commands": ((0, 1), (0, 1))},
        {"overdrive_levels": (0, 1), "overdrive_commands": ([0, 1], [0, 1])},
        {"overdrive_levels": (0, 1), "overdrive_commands": ((0, 1),)},
        {"overdrive_levels": (0, 0.5), "overdrive_commands": ((0, 1), (0, 0.5))},
        {"overdrive_levels": (0.5, 1), "overdrive_commands": ((0.5, 1), (0, 1))},
        {"overdrive_levels": (0, 1), "overdrive_commands": ((0, 2), (0, 1))},
        {"overdrive_levels": (0, 1), "overdrive_commands": ((0.1, 1), (0, 1))},
        {"overdrive_levels": (0, 1), "overdrive_commands": ((0, 1), (0, 1))},
    ],
)
def test_od_grid_validation(changes):
    with pytest.raises(ValueError):
        config(**changes)


@pytest.mark.parametrize("start,target,tau", [(0, 1, 2), (1, 0, 5), (0.3, 0.3, 2)])
def test_asymmetric_endpoint_and_exact_emission_integral(start, target, tau):
    duration = Fraction(1, 100)
    state = SubframeState(image(start), 1, Fraction(0))
    result = tick(target, state=state, duration=duration)
    seconds = float(duration)
    expected_endpoint = target + (start - target) * math.exp(-seconds * 1000 / tau)
    expected_mean = target + (start - target) * (tau / 1000 / seconds) * (
        1 - math.exp(-seconds * 1000 / tau)
    )
    np.testing.assert_allclose(result.endpoint, expected_endpoint, atol=1e-16)
    np.testing.assert_allclose(result.mean, expected_mean * 100, rtol=1e-7)
    assert state.previous.tobytes() == image(start).tobytes()
    assert state.ticks == 1 and state.next_pts == 0


def test_level_dependent_tau_uses_declared_command_level():
    settings = config(initial="cold", tau_table=((0, 1, 9), (0.5, 5, 7), (1, 9, 5)))
    result = tick(0.25, settings, duration=Fraction(3, 1000))
    np.testing.assert_allclose(result.endpoint, 0.25 * (1 - math.exp(-1)), rtol=2e-15)


def test_tau_table_extrapolation_rejects_without_mutating_history():
    settings = config(tau_table=((0.1, 1, 1), (0.8, 2, 2)))
    state = SubframeState(image(0.3), 1, Fraction(0))
    before = state.previous.tobytes()
    with pytest.raises(ValueError, match="extrapolation"):
        tick(0.9, settings, state)
    assert state.previous.tobytes() == before and state.ticks == 1


def test_zero_tau_is_exact_target_and_endpoint_does_not_depend_on_substeps():
    settings = SubframeConfig(model=MODEL, rise_tau_ms=0, fall_tau_ms=0, initial="cold")
    target = np.random.default_rng(18).random((2, 3, 3))
    result = tick(target, settings)
    assert result.endpoint.tobytes() == target.tobytes()
    assert result.mean.tobytes() == (target * 100).astype(np.float32).tobytes()
    slow = tick(target, config(initial="cold", substeps=1))
    fast = tick(target, config(initial="cold", substeps=71))
    assert slow.endpoint.tobytes() == fast.endpoint.tobytes()
    np.testing.assert_allclose(slow.mean, fast.mean, rtol=1e-7)


def test_extremely_slow_tau_keeps_positive_small_emission():
    settings = SubframeConfig(model=MODEL, rise_tau_ms=1e15, fall_tau_ms=1e15, initial="cold")
    result = tick(1, settings, duration=Fraction(1, 1000))
    assert np.all(result.mean > 0)
    np.testing.assert_allclose(result.mean, 5e-14, rtol=1e-7)


def test_od_prefix_causes_overshoot_and_returns_to_true_target():
    settings = od_config(substeps=100)
    duration = Fraction(1, 100)
    state = SubframeState(image(0), 1, Fraction(0))
    result = tick(0.5, settings, state, duration=duration)
    prefix_endpoint = 1 - math.exp(-2.5)
    expected_endpoint = 0.5 + (prefix_endpoint - 0.5) * math.exp(-2.5)
    np.testing.assert_allclose(result.endpoint, expected_endpoint)
    assert float(np.max([sample.panel.max() for sample in result.samples])) > 0.9
    state.previous = image(1)
    falling = tick(0.5, settings, state, duration=duration)
    assert min(sample.panel.min() for sample in falling.samples) < 0.1
    assert np.all(falling.endpoint < 0.5)


def test_od_leaves_a_settled_interpolated_level_unchanged():
    result = tick(0.25, od_config())
    assert result.endpoint.tobytes() == image(0.25).tobytes()
    assert all(sample.panel.tobytes() == image(0.25).tobytes() for sample in result.samples)


def test_cold_floor_and_lut_cannot_emit_below_physical_lcd_leakage():
    settings = od_config(initial="cold")
    result = tick(0.01, settings, floor=0.01)
    assert np.all(result.endpoint == 0.01)
    assert all(np.all(sample.panel == 0.01) for sample in result.samples)


def test_exact_rational_substep_partition_at_fractional_refresh():
    pts, duration = Fraction(17, 13), Fraction(1001, 60000)
    result = tick(0.5, config(substeps=7), pts=pts, duration=duration)
    assert result.samples[0].pts == pts
    assert result.samples[-1].pts + result.samples[-1].duration == pts + duration
    assert all(sample.duration == duration / 7 for sample in result.samples)
    assert all(
        right.pts == left.pts + left.duration
        for left, right in zip(result.samples, result.samples[1:])
    )


@pytest.mark.parametrize("substeps", [1, 3, 16, 127])
def test_narrow_pwm_pulses_preserve_exact_duty_at_every_substep_count(substeps):
    settings = config(substeps=substeps, pwm_hz="1000", pwm_duty="1/100")
    result = tick(0.7, settings, duration=Fraction(1, 100))
    np.testing.assert_allclose(result.mean, 0.7, rtol=1e-7)
    assert sum(
        (sample.gate_fraction * sample.duration for sample in result.samples), Fraction(0)
    ) == Fraction(1, 10000)


@pytest.mark.parametrize("phase", ["0", "1/4", "3/4"])
def test_tick_strobe_wraps_without_changing_stationary_brightness(phase):
    settings = config(strobe_duty="1/2", strobe_phase=phase)
    result = tick(0.8, settings, pts=Fraction(37, 11))
    assert np.all(result.mean == 40)


def test_pwm_absolute_phase_continues_across_ticks():
    settings = config(substeps=2, pwm_hz="75", pwm_duty="1/2", pwm_phase="1/4")
    state = SubframeState()
    duration = Fraction(1, 60)
    brightness = []
    for index in range(4):
        pts = index * duration
        result = tick(1, settings, state, pts=pts, duration=duration)
        brightness.append(result.mean[0, 0, 0])
        commit(state, result, pts, duration)
    np.testing.assert_allclose(brightness, [40, 60, 60, 40])
    assert state.next_pts == Fraction(1, 15)


def test_pwm_and_strobe_intersect_instead_of_multiplying_mean_duties():
    settings = config(pwm_hz="60", pwm_duty="1/2", strobe_duty="1/2", strobe_phase="1/2")
    assert np.all(tick(1, settings).mean == 0)
    aligned = replace(settings, strobe_phase="0")
    assert np.all(tick(1, aligned).mean == 50)


def test_analytic_response_is_weighted_at_actual_gate_time():
    duration = Fraction(1, 100)
    settings = config(initial="cold", strobe_duty="1/10", strobe_phase="9/10")
    result = tick(1, settings, duration=duration)
    expected = (0.001 - 0.002 * (math.exp(-4.5) - math.exp(-5))) / 0.01 * 100
    np.testing.assert_allclose(result.mean, expected, rtol=1e-7)
    # Late illumination follows LC settling rather than attenuating a whole-tick
    # response average by a duty scalar.
    assert np.all(result.mean > tick(1, config(initial="cold"), duration=duration).mean * 0.1)


def test_ambient_is_ungated_and_not_fed_back_into_response():
    target = image(0.5)
    result = simulate_tick(
        target,
        np.full((2, 3), 100.0),
        3.0,
        SubframeState(),
        Fraction(0),
        Fraction(1, 60),
        config(strobe_duty="1/4"),
    )
    assert np.all(result.mean == 15.5)
    assert np.all(result.endpoint == 0.5)
    assert all(np.all(sample.rgb >= 3) for sample in result.samples)


def test_oled_bfi_brightness_cost_and_endpoint_are_separate():
    result = simulate_tick(
        image(200),
        None,
        0,
        SubframeState(),
        Fraction(0),
        Fraction(1, 60),
        config(bfi_duty="1/4", bfi_phase="3/4"),
        self_emissive=True,
    )
    assert np.all(result.mean == 50)
    assert np.all(result.endpoint == 200)


def test_full_byte_copy_continuation_reproduces_every_sample():
    settings = od_config(pwm_hz="740", pwm_duty="2/5", strobe_duty="3/4", strobe_phase="1/5")
    duration = Fraction(1001, 60000)
    uninterrupted = SubframeState()
    resumed = None
    for index, target in enumerate((0.2, 0.8, 0.4, 0.7, 0.1, 0.9)):
        pts = index * duration
        left = tick(target, settings, uninterrupted, pts=pts, duration=duration)
        if resumed is not None:
            right = tick(target, settings, resumed, pts=pts, duration=duration)
            assert left.endpoint.tobytes() == right.endpoint.tobytes()
            assert left.mean.tobytes() == right.mean.tobytes()
            assert [sample.rgb.tobytes() for sample in left.samples] == [
                sample.rgb.tobytes() for sample in right.samples
            ]
            commit(resumed, right, pts, duration)
        commit(uninterrupted, left, pts, duration)
        if index == 2:
            exact = (
                np.frombuffer(uninterrupted.previous.tobytes(), dtype=np.float64)
                .reshape((2, 3, 3))
                .copy()
            )
            resumed = SubframeState(exact, uninterrupted.ticks, uninterrupted.next_pts)


@pytest.mark.parametrize(
    "legacy",
    [
        {"overdrive_gain": 0.1},
        {"overdrive_ms": 1},
        {"overdrive_ceiling_nits": 1000},
        {"motion_px_per_frame": 1},
        {"bfi_duty": 0.5},
        {"bfi_preserve_mean": True},
        {"integration_samples": 4},
    ],
)
def test_legacy_pixel_or_emission_owners_reject(legacy):
    with pytest.raises(ValueError, match="legacy"):
        validate_path(profile(**legacy), config())


def test_legacy_tau_must_be_explicitly_disabled():
    with pytest.raises(ValueError, match="response_time_ms"):
        validate_path(load_profile("generic_va_fald_miniled"), config())


@pytest.mark.parametrize("hold", [True, False])
def test_zero_motion_legacy_hold_flag_is_numerically_harmless(hold):
    validate_path(profile(sample_and_hold=hold), config())


@pytest.mark.parametrize(
    "name,settings",
    [
        ("generic_va_fald_miniled", config(bfi_duty="1/2")),
        ("generic_ips_edge", config(bfi_phase="1/4")),
        ("generic_woled", config(pwm_hz="240")),
        ("generic_qdoled", config(strobe_duty="1/2")),
        ("generic_woled", od_config()),
        ("generic_va_fald_miniled", config(tau_table=((0.1, 1, 1), (1, 2, 2)))),
    ],
)
def test_lcd_oled_domain_conflicts_reject(name, settings):
    with pytest.raises(ValueError):
        validate_path(profile(name), settings)


@pytest.mark.parametrize(
    "name", ["generic_va_fald_miniled", "generic_ips_edge", "generic_woled", "generic_qdoled"]
)
def test_supported_profiles_admit_explicit_response_owner(name):
    validate_path(profile(name), config())


@pytest.mark.parametrize(
    "state",
    [
        SubframeState(ticks=1),
        SubframeState(next_pts=Fraction(0)),
        SubframeState(ticks=True),
        SubframeState(image(0)),
        SubframeState(image(0), 1, 0),
        SubframeState(image(0).astype(np.float32), 1, Fraction(0)),
        SubframeState(image(-1), 1, Fraction(0)),
        SubframeState(image(float("nan")), 1, Fraction(0)),
        SubframeState(np.zeros((2, 3)), 1, Fraction(0)),
    ],
)
def test_invalid_history_rejects(state):
    with pytest.raises(ValueError):
        validate_state(state)


@pytest.mark.parametrize(
    "target",
    [image(-1), image(1.1), image(float("nan")), image(0).astype(np.float32), np.zeros((2, 3))],
)
def test_invalid_target_rejects_without_mutating_state(target):
    state = SubframeState(image(0.5), 1, Fraction(0))
    before = state.previous.tobytes()
    with pytest.raises(ValueError):
        tick(target, state=state)
    assert state.previous.tobytes() == before


@pytest.mark.parametrize(
    "pts,duration",
    [
        (0, Fraction(1, 60)),
        (Fraction(0), 0.1),
        (Fraction(0), Fraction(0)),
        (Fraction(0), Fraction(-1)),
    ],
)
def test_inexact_or_invalid_tick_clocks_reject(pts, duration):
    with pytest.raises(ValueError):
        tick(0.5, pts=pts, duration=duration)


def test_gap_geometry_resume_and_pwm_work_bound_reject():
    state = SubframeState(image(0.5), 1, Fraction(1, 60))
    with pytest.raises(ValueError, match="timestamp gap"):
        tick(0.5, state=state)
    with pytest.raises(ValueError, match="geometry"):
        tick(np.ones((1, 1, 3)), state=state, pts=Fraction(1, 60))
    with pytest.raises(ValueError, match="checkpoint"):
        tick(0.5, config(initial="resume"))
    with pytest.raises(ValueError, match="too many PWM"):
        tick(0.5, config(pwm_hz="100000000", pwm_duty="1/2"))


@pytest.mark.parametrize("ambient", [-1, float("nan"), np.zeros((2, 3)), image(-1)])
def test_invalid_ambient_rejects(ambient):
    with pytest.raises(ValueError, match="ambient"):
        simulate_tick(
            image(0.5),
            np.full((2, 3), 100.0),
            ambient,
            SubframeState(),
            Fraction(0),
            Fraction(1, 60),
            config(),
        )


@pytest.mark.parametrize(
    "illumination",
    [
        None,
        np.zeros((2, 3), dtype=np.float32),
        np.ones((1, 1)),
        np.full((2, 3), -1.0),
        np.full((2, 3), float("nan")),
    ],
)
def test_invalid_lcd_illumination_rejects(illumination):
    with pytest.raises(ValueError, match="illumination"):
        simulate_tick(
            image(0.5), illumination, 0, SubframeState(), Fraction(0), Fraction(1, 60), config()
        )


def test_low_level_also_rejects_technology_gate_conflicts():
    with pytest.raises(ValueError, match="OLED BFI"):
        tick(0.5, config(bfi_duty="1/2"))
    with pytest.raises(ValueError, match="backlight illumination owner"):
        tick(0.5, self_emissive=True)
    with pytest.raises(ValueError, match="LCD overdrive/PWM/strobe"):
        simulate_tick(
            image(0.5),
            None,
            0,
            SubframeState(),
            Fraction(0),
            Fraction(1, 60),
            config(pwm_hz="240"),
            self_emissive=True,
        )
