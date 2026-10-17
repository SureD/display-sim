"""Explicit angular experiments preserve defaults and separate optical terms.

All numeric angular parameters below are synthetic P experiments. They do not
describe a named TV or imply a fitted viewing-angle response.
"""

from dataclasses import replace

import numpy as np
import pytest

from sim.pipeline import Pipeline
from sim.profile import available_profiles, load_profile
from sim.stages.encode import encode_frame
from sim.stages.panel import lcd_transmit
from sim.stages.viewing_angle import emissive_angular_gain, lcd_angular_transmit
from sim.viewing_angle import (
    EmissiveAngularParams,
    LcdAngularParams,
    ViewingAngleConfig,
    angular_parameters,
)


PROFILES = tuple(available_profiles())


def assert_identical(first, second):
    if first is None or second is None:
        assert first is second
        return
    assert first.shape == second.shape
    assert first.dtype == second.dtype
    assert first.tobytes() == second.tobytes()


def angle(horizontal=45.0, vertical=0.0, *, enabled=True):
    return ViewingAngleConfig(
        enabled=enabled, horizontal_deg=horizontal, vertical_deg=vertical
    )


def lcd_params(**overrides):
    params = LcdAngularParams(
        max_angle_deg=45.0,
        white_gain_45=(1.0, 1.0, 1.0),
        black_gain_45=(1.0, 1.0, 1.0),
        gray_exponent_45=(1.0, 1.0, 1.0),
    )
    return replace(params, **overrides)


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize(
    "config",
    [ViewingAngleConfig(), angle(enabled=False), angle(0.0)],
    ids=["default-off", "explicit-off-axis-disabled", "enabled-on-axis"],
)
def test_disabled_or_zero_angle_preserves_outputs_and_both_histories(name, config):
    profile = load_profile(name)
    baseline, configured = Pipeline(profile), Pipeline(profile, viewing_angle=config)
    rng = np.random.default_rng(20261017)
    pattern = rng.integers(0, 256, (16, 24, 3), dtype=np.uint8)
    for source in (
        np.zeros_like(pattern), pattern, np.full_like(pattern, 255),
        np.roll(pattern, 3, axis=1), np.zeros_like(pattern),
    ):
        expected, actual = baseline.run_linear(source), configured.run_linear(source)
        assert_identical(expected.rgb, actual.rgb)
        assert_identical(expected.backlight, actual.backlight)
        assert_identical(encode_frame(expected, profile.output), encode_frame(actual, profile.output))
        assert_identical(baseline.state.previous, configured.state.previous)
        assert baseline.load_state.apl_nits.hex() == configured.load_state.apl_nits.hex()


@pytest.mark.parametrize("name", PROFILES)
def test_zero_angle_retains_legacy_angle_behavior_as_well(name):
    # A zero-angle M10 config is a true bypass even for an explicit legacy
    # chroma experiment; it must not replace any part of the original path.
    profile = load_profile(name).with_overrides(viewing_angle_deg=27.0)
    source = np.array([[[255, 40, 5], [0, 180, 80]]], dtype=np.uint8)
    assert_identical(
        Pipeline(profile).run_linear(source).rgb,
        Pipeline(profile, viewing_angle=angle(0.0)).run_linear(source).rgb,
    )


@pytest.mark.parametrize("config", [angle(0.0), angle(enabled=False)])
def test_stage_bypass_retains_legacy_numerics_at_zero_backlight(config):
    target = np.array([[[0.0, 1.0, 100.0], [0.0, 0.01, 1.0]]], dtype=np.float32)
    backlight = np.array([[100.0, 0.0]], dtype=np.float32)
    assert_identical(
        lcd_transmit(target, backlight, 2000.0),
        lcd_angular_transmit(target, backlight, 2000.0, config, lcd_params()),
    )
    assert_identical(
        target,
        emissive_angular_gain(
            target, config,
            EmissiveAngularParams(max_angle_deg=45.0, emission_gain_45=(0.8, 0.9, 0.7)),
        ),
    )


def test_lcd_leakage_monotonically_reduces_contrast_without_reducing_white():
    target = np.broadcast_to(np.array([0.0, 100.0], np.float32)[None, :, None], (1, 2, 3))
    backlight = np.full((1, 2), 100.0, dtype=np.float32)
    params = lcd_params(black_gain_45=(16.0, 16.0, 16.0))
    black_levels, contrasts = [], []
    for degrees in (0.0, 15.0, 30.0, 45.0):
        rgb = lcd_angular_transmit(target, backlight, 2000.0, angle(degrees), params)
        black, white = rgb[0, 0, 0], rgb[0, 1, 0]
        assert white == pytest.approx(100.0)
        black_levels.append(black)
        contrasts.append(white / black)
    assert np.all(np.diff(black_levels) > 0)
    assert np.all(np.diff(contrasts) < 0)
    assert contrasts[0] == pytest.approx(2000.0)
    assert contrasts[-1] == pytest.approx(125.0)


def test_lcd_white_black_and_gray_terms_are_independently_identified():
    contrast, light = 1000.0, 200.0
    eps0 = 1.0 / contrast
    q = np.array([0.0, 0.1, 0.5, 1.0], dtype=np.float32)
    target = np.broadcast_to((light * (eps0 + (1.0 - eps0) * q))[None, :, None], (1, 4, 3))
    # Explicit zero and full-open requests fix the transmission endpoints.
    target = target.copy()
    target[:, 0] = 0.0
    backlight = np.full((1, 4), light, np.float32)
    baseline = lcd_params(white_gain_45=(0.8,) * 3, black_gain_45=(4.0,) * 3)
    leakage = replace(baseline, black_gain_45=(12.0,) * 3)
    gray = replace(baseline, gray_exponent_45=(0.65,) * 3)
    values = [lcd_angular_transmit(target, backlight, contrast, angle(), p)[0, :, 0]
              for p in (baseline, leakage, gray)]
    original, leaked, washed = values
    assert original[0] == pytest.approx(light / contrast * 4.0)
    assert leaked[0] == pytest.approx(light / contrast * 12.0)
    assert original[-1] == leaked[-1] == pytest.approx(light * 0.8)
    assert washed[0] == pytest.approx(original[0])
    assert washed[-1] == pytest.approx(original[-1])
    assert np.all(washed[1:-1] > original[1:-1])

    def normalize(values):
        return (values - values[0]) / (values[-1] - values[0])

    # Leakage changes contrast while preserving the normalized gray transfer.
    np.testing.assert_allclose(normalize(leaked), normalize(original), atol=2e-7)
    np.testing.assert_allclose(normalize(original), q, atol=2e-7)
    np.testing.assert_allclose(normalize(washed), q**0.65, atol=2e-7)


def test_lcd_rgb_gray_shift_changes_color_without_moving_black_or_white():
    target = np.full((1, 3, 3), 50.0, np.float32)
    target[0, 0] = 0.0
    target[0, 2] = 100.0
    backlight = np.full((1, 3), 100.0, np.float32)
    neutral = lcd_params()
    shifted = replace(neutral, gray_exponent_45=(0.6, 1.0, 1.4))
    baseline = lcd_angular_transmit(target, backlight, 1000.0, angle(), neutral)
    rgb = lcd_angular_transmit(target, backlight, 1000.0, angle(), shifted)
    np.testing.assert_allclose(rgb[:, [0, 2]], baseline[:, [0, 2]])
    assert rgb[0, 1, 0] > rgb[0, 1, 1] > rgb[0, 1, 2]
    assert rgb[0, 1, 1] == pytest.approx(50.0)


def test_lcd_rgb_white_and_black_gains_control_their_own_endpoints():
    target = np.array([[[0.0] * 3, [100.0] * 3]], dtype=np.float32)
    backlight = np.full((1, 2), 100.0, np.float32)
    params = lcd_params(white_gain_45=(0.8, 0.9, 1.0), black_gain_45=(2.0, 4.0, 8.0))
    actual = lcd_angular_transmit(target, backlight, 1000.0, angle(), params)
    np.testing.assert_allclose(actual[0, 0], [0.2, 0.4, 0.8], rtol=2e-6)
    np.testing.assert_allclose(actual[0, 1], [80.0, 90.0, 100.0], rtol=2e-6)


@pytest.mark.parametrize("name", ["generic_woled", "generic_qdoled"])
def test_emissive_pipeline_ignores_lcd_contrast_and_legacy_chroma_terms(name):
    profile = load_profile(name)
    modified = replace(
        profile,
        panel=replace(profile.panel, native_contrast=2.0, viewing_angle_deg=75.0,
                      angle_loss_per_deg=9.0),
    )
    source = np.array([[[255, 5, 40], [25, 200, 80], [0, 0, 0]]], np.uint8)
    params = EmissiveAngularParams(
        max_angle_deg=45.0, emission_gain_45=(0.7, 0.85, 0.95)
    )
    first = Pipeline(profile, viewing_angle=angle(), angular_params=params).run_linear(source)
    second = Pipeline(modified, viewing_angle=angle(), angular_params=params).run_linear(source)
    assert_identical(first.rgb, second.rgb)
    assert_identical(first.backlight, second.backlight)


def test_emissive_gain_scales_channels_without_creating_black_emission():
    target = np.array([[[0.0, 0.0, 0.0], [50.0, 80.0, 100.0]]], np.float32)
    params = EmissiveAngularParams(
        max_angle_deg=45.0, emission_gain_45=(0.7, 0.85, 0.95)
    )
    actual = emissive_angular_gain(target, angle(), params)
    assert_identical(actual[:, :1], target[:, :1])
    np.testing.assert_allclose(actual[0, 1], [35.0, 68.0, 95.0], rtol=2e-6)


@pytest.mark.parametrize("name", PROFILES)
def test_signed_angles_and_axis_exchange_share_the_explicit_symmetric_preset(name):
    profile = load_profile(name)
    source = np.array([[[240, 90, 20], [40, 0, 20]]], np.uint8)
    reference = Pipeline(profile, viewing_angle=angle(20.0, 25.0)).run_linear(source).rgb
    for horizontal, vertical in ((-20.0, 25.0), (20.0, -25.0), (-20.0, -25.0), (25.0, 20.0)):
        actual = Pipeline(profile, viewing_angle=angle(horizontal, vertical)).run_linear(source).rgb
        assert_identical(reference, actual)


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("horizontal, vertical", [
    (45.0001, 0.0), (0.0, -45.0001), (40.0, 40.0), (89.9, 0.0),
])
def test_out_of_support_angles_are_rejected_without_extrapolation(name, horizontal, vertical):
    with pytest.raises(ValueError):
        pipeline = Pipeline(load_profile(name), viewing_angle=angle(horizontal, vertical))
        pipeline.run_linear(np.zeros((2, 2, 3), np.uint8))


@pytest.mark.parametrize("bad", [
    float("nan"), float("inf"), -float("inf"), True,
    pytest.param(10**400, id="oversized-integer"), 90.0, -90.0,
])
@pytest.mark.parametrize("field", ["horizontal_deg", "vertical_deg"])
def test_nonfinite_or_nonphysical_coordinates_are_rejected(field, bad):
    with pytest.raises(ValueError):
        ViewingAngleConfig(enabled=True, **{field: bad})


@pytest.mark.parametrize("name", PROFILES)
def test_active_pipeline_requires_the_matching_optical_parameter_family(name):
    profile = load_profile(name)
    wrong = lcd_params() if profile.self_emissive else EmissiveAngularParams(
        max_angle_deg=45.0, emission_gain_45=(1.0, 1.0, 1.0)
    )
    with pytest.raises(ValueError):
        pipeline = Pipeline(profile, viewing_angle=angle(), angular_params=wrong)
        pipeline.run_linear(np.zeros((2, 2, 3), np.uint8))


@pytest.mark.parametrize("name", PROFILES)
def test_default_parameter_family_matches_panel_construction(name):
    profile = load_profile(name)
    params = angular_parameters(profile)
    assert isinstance(params, EmissiveAngularParams if profile.self_emissive else LcdAngularParams)
    assert params.max_angle_deg == 45.0


def test_identity_angular_terms_preserve_compensated_lcd_response():
    target = np.array([[[0.0, 0.1, 1.0], [30.0, 90.0, 100.0]]], np.float32)
    backlight = np.full((1, 2), 100.0, np.float32)
    np.testing.assert_allclose(
        lcd_angular_transmit(target, backlight, 2000.0, angle(), lcd_params()),
        lcd_transmit(target, backlight, 2000.0), rtol=2e-7,
    )


@pytest.mark.parametrize("field", ["white_gain_45", "black_gain_45", "gray_exponent_45"])
@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_lcd_model_rejects_invalid_rgb_terms(field, value):
    with pytest.raises(ValueError):
        lcd_params(**{field: (1.0, value, 1.0)})


def test_lcd_extinction_cannot_exceed_white_within_model_support():
    params = lcd_params(white_gain_45=(0.5,) * 3, black_gain_45=(1000.0,) * 3)
    with pytest.raises(ValueError, match="epsilon"):
        Pipeline(load_profile("generic_ips_edge"), viewing_angle=angle(10),
                 angular_params=params)
