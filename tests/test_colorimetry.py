"""Numerical contracts for the opt-in M15 tristimulus/P capacity model."""

import json
from dataclasses import replace

import numpy as np
import pytest

from tv_sim.abl_dynamics import MODEL, ABLDynamicsConfig
from tv_sim.color import hlg_scene_linear
from tv_sim.colorimetry import (
    D65,
    RGB_SPACES,
    ColorimetryConfig,
    PanelColorimetry,
    convert_rgb,
    decode_source,
    gamut_map,
    joint_tone_map,
    panel_luminance,
    rgb_to_xyz_matrix,
    source_to_panel_matrix,
    xyz_to_rgb_matrix,
)
from tv_sim.colorimetry_provenance import panel_parameters
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import HdrParams, InputParams, available_profiles, load_profile
from tv_sim.viewing_angle import ViewingAngleConfig


def panel(space="display_p3", ratio=1):
    return PanelColorimetry(RGB_SPACES[space], D65, ratio, 2)


def uv(xyz):
    xyz = np.asarray(xyz, dtype=np.float64)
    denominator = xyz[..., 0] + 15 * xyz[..., 1] + 3 * xyz[..., 2]
    return np.stack((4 * xyz[..., 0] / denominator, 9 * xyz[..., 1] / denominator), axis=-1)


@pytest.mark.parametrize("space", RGB_SPACES)
def test_matrix_roundtrip_white_and_exact_y(space):
    matrix = rgb_to_xyz_matrix(RGB_SPACES[space])
    inverse = xyz_to_rgb_matrix(RGB_SPACES[space])
    random = np.random.default_rng(15).uniform(-2, 8, (100, 3))
    np.testing.assert_allclose(random @ matrix.T @ inverse.T, random, atol=1e-14, rtol=1e-14)
    expected_white = (D65[0] / D65[1], 1, (1 - sum(D65)) / D65[1])
    np.testing.assert_allclose(matrix @ np.ones(3), expected_white, atol=3e-16)
    assert matrix.dtype == np.float64
    assert np.all(matrix[1] > 0)
    assert np.isclose(matrix[1].sum(), 1, atol=1e-15)


def test_709_matrix_from_primary_definition_not_rounded_luma():
    matrix = rgb_to_xyz_matrix(RGB_SPACES["bt709"])
    np.testing.assert_allclose(
        matrix[1], [0.212639005871510, 0.715168678767756, 0.072192315360734], atol=1e-15
    )
    assert not np.array_equal(matrix[1], [0.2126, 0.7152, 0.0722])


@pytest.mark.parametrize("source", RGB_SPACES)
@pytest.mark.parametrize("destination", RGB_SPACES)
def test_conversion_preserves_xyz_and_common_white(source, destination):
    config = ColorimetryConfig(enabled=True, source_primaries=source)
    target = panel(destination)
    conversion = source_to_panel_matrix(config, target)
    np.testing.assert_allclose(conversion @ np.ones(3), np.ones(3), atol=2e-15)
    np.testing.assert_allclose(
        rgb_to_xyz_matrix(target.primaries_xy) @ conversion,
        rgb_to_xyz_matrix(RGB_SPACES[source]),
        atol=2e-16,
    )


def test_differing_white_preserves_xyz_without_implicit_adaptation():
    source_white = (0.3457, 0.3585)
    config = ColorimetryConfig(enabled=True, source_white_xy=source_white)
    target = panel()
    mapped_white = source_to_panel_matrix(config, target) @ np.ones(3)
    assert not np.allclose(mapped_white, np.ones(3))
    xyz = rgb_to_xyz_matrix(target.primaries_xy) @ mapped_white
    np.testing.assert_allclose(
        xyz,
        [source_white[0] / source_white[1], 1, (1 - sum(source_white)) / source_white[1]],
        atol=5e-16,
    )


@pytest.mark.parametrize(
    "primaries,white",
    [
        (((0.3, 0.3), (0.3, 0.3), (0.15, 0.06)), D65),
        (RGB_SPACES["bt709"], (0.8, 0.1)),
        (((0, 0.3), (0.3, 0.6), (0.15, 0.06)), D65),
        (RGB_SPACES["bt709"], (float("nan"), 0.3)),
    ],
)
def test_invalid_matrix_declarations_rejected(primaries, white):
    with pytest.raises(ValueError):
        rgb_to_xyz_matrix(primaries, white)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_primaries": "unknown"},
        {"gamut_mapping": "unknown"},
        {"compression_knee": 1},
        {"compression_knee": -1},
        {"compression_knee": float("nan")},
        {"enabled": 1},
    ],
)
def test_invalid_runtime_declarations_rejected(kwargs):
    with pytest.raises(ValueError):
        ColorimetryConfig(**kwargs)


def test_hard_clip_cone_and_diagnostics_has_no_brightness_clamp():
    color = np.array([[[-1, 2, 3], [0, 4, 0], [1, 1, 1]]], dtype=np.float32)
    mapped, info = gamut_map(color, panel(), "clip")
    np.testing.assert_array_equal(mapped, np.maximum(color, 0))
    assert info["input_out_of_gamut_fraction"] == 1 / 3
    np.testing.assert_array_equal(info["input_out_of_gamut_mask"], [[True, False, False]])
    assert mapped.max() == 4


def test_compression_preserves_exact_y_and_declared_uv_hue_ray():
    target = panel("bt709")
    source = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    rgb = convert_rgb(
        np.array(
            [
                [
                    [1000, 0, 0],
                    [0, 1000, 0],
                    [0, 0, 1000],
                    [1000, 1000, 0],
                    [0, 1000, 1000],
                    [1000, 0, 1000],
                ]
            ]
        ),
        source_to_panel_matrix(source, target),
    )
    mapped, info = gamut_map(rgb, target)
    assert np.all(mapped >= 0)
    np.testing.assert_allclose(
        panel_luminance(mapped, target), panel_luminance(rgb, target), rtol=8e-8, atol=2e-6
    )
    matrix = rgb_to_xyz_matrix(target.primaries_xy)
    before, after = uv(rgb @ matrix.T), uv(mapped @ matrix.T)
    white = uv(matrix @ np.ones(3))
    initial_ray, mapped_ray = before - white, after - white
    cross = initial_ray[..., 0] * mapped_ray[..., 1] - initial_ray[..., 1] * mapped_ray[..., 0]
    np.testing.assert_allclose(cross, 0, atol=2e-9)
    assert np.all(np.sum(initial_ray * mapped_ray, axis=-1) > 0)
    assert info["input_out_of_gamut_fraction"] == 1


def test_compression_low_chroma_identity_continuity_and_scale_invariance():
    target = panel()
    color = np.array([[[0, 0, 0], [1, 1, 1], [0.9, 1.1, 1], [0, 2, 0.2]]], dtype=np.float32)
    mapped, _ = gamut_map(color, target)
    np.testing.assert_array_equal(mapped[:, :3], color[:, :3])
    scaled, _ = gamut_map(color * 100, target)
    np.testing.assert_allclose(scaled, mapped * 100, rtol=1e-7, atol=2e-6)
    # Construct colors along one exact-Y ray and sample immediately either side of its knee.
    weights = rgb_to_xyz_matrix(target.primaries_xy)[1]
    direction = np.array([-1, weights[0] / weights[1], 0])
    samples = np.array([1 + (0.8 + epsilon) * direction for epsilon in (-1e-7, 0, 1e-7)])[None]
    result, _ = gamut_map(samples, target)
    assert np.max(np.abs(np.diff(result, axis=1))) < 2e-7


@pytest.mark.parametrize("space", RGB_SPACES)
def test_active_hlg_ootf_uses_declared_source_y(space):
    codes = np.array([[[0.8, 0.4, 0.2], [0.2, 0.9, 0.5]]], dtype=np.float32)
    source = ColorimetryConfig(enabled=True, source_primaries=space)
    scene = hlg_scene_linear(codes).astype(np.float64)
    y = scene @ rgb_to_xyz_matrix(RGB_SPACES[space])[1]
    expected = 1000 * scene * y[..., None] ** 0.2
    actual = decode_source(codes, InputParams(eotf="hlg"), source)
    np.testing.assert_array_equal(actual.rgb, expected.astype(np.float32))


def test_joint_capacity_one_shoulder_white_boost_and_chromaticity():
    params = HdrParams(panel_peak_nits=1000, knee_ratio=0.85)
    colors = np.array(
        [[[1e7, 0, 0], [0, 1e7, 0], [0, 0, 1e7], [1e7, 1e7, 1e7], [1e7, 0.5e7, 0.5e7]]],
        dtype=np.float32,
    )
    target = panel(ratio=0.45)
    result, info = joint_tone_map(Frame(colors), params, target, capacity_nits=1000)
    np.testing.assert_allclose(result.rgb.max(axis=-1), [[450, 450, 450, 1000, 587.5]], atol=1e-4)
    original_ratio = colors / colors.max(axis=-1, keepdims=True)
    mapped_ratio = result.rgb / result.rgb.max(axis=-1, keepdims=True)
    np.testing.assert_allclose(mapped_ratio, original_ratio, atol=1e-7)
    assert info["capacity_owner"] == "joint_hdr_abl_rgbw_v1"
    assert info["volume_exceeded_fraction"] == 1


def test_joint_capacity_combines_abl_by_minimum_without_double_limiting():
    params = HdrParams(panel_peak_nits=1000)
    colors = Frame(np.array([[[1e7, 0, 0], [1e7, 1e7, 1e7]]]))
    result, info = joint_tone_map(colors, params, panel(ratio=0.45), capacity_nits=200)
    # Global capacity dominates both endpoints; the RGBW ratio is not multiplied again.
    np.testing.assert_allclose(result.rgb.max(axis=-1), [[200, 200]], atol=1e-5)
    np.testing.assert_array_equal(info["joint_capacity_nits"], [[200, 200]])


@pytest.mark.parametrize("name", available_profiles())
def test_pipeline_metadata_output_and_m10_composition(name):
    config = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    pipeline = Pipeline(
        load_profile(name),
        colorimetry=config,
        viewing_angle=ViewingAngleConfig(enabled=True, horizontal_deg=20),
    )
    rgb = np.zeros((12, 20, 3), dtype=np.float32)
    rgb[..., 0] = 800
    result = pipeline.display_content(Frame(rgb))
    xyz = pipeline.output_in_space(result, "xyz")
    np.testing.assert_allclose(
        xyz[..., 1], panel_luminance(result.rgb, pipeline.panel_colorimetry), rtol=1e-7
    )
    for space in RGB_SPACES:
        exported = pipeline.output_in_space(result, space)
        np.testing.assert_allclose(
            exported @ rgb_to_xyz_matrix(RGB_SPACES[space]).T, xyz, rtol=1e-6, atol=2e-5
        )
    metadata = json.loads(json.dumps(pipeline.colorimetry_metadata()))
    assert metadata["source"]["primaries"] == "bt2020"
    assert metadata["panel"]["evidence"] == "P"
    assert metadata["chromatic_adaptation"] == "none_absolute_xyz"
    assert pipeline.last_colorimetry_diagnostics["input_out_of_gamut_fraction"] > 0


def _history_profile(name="generic_woled"):
    original = load_profile(name)
    return replace(
        original,
        hdr=replace(original.hdr, abl_source="demand"),
        temporal=replace(original.temporal, response_time_ms=4),
    )


@pytest.mark.parametrize("name", ["generic_woled", "generic_qdoled"])
@pytest.mark.parametrize("angle", [False, True])
def test_active_m13_checkpoint_json_roundtrip_exact_and_single_tick(name, angle):
    config = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    dynamics = ABLDynamicsConfig(model=MODEL, attack_ms=100, release_ms=500)
    viewing = ViewingAngleConfig(enabled=angle, horizontal_deg=20)
    original = Pipeline(
        _history_profile(name), colorimetry=config, abl_dynamics=dynamics, viewing_angle=viewing
    )
    original.display_content(Frame(np.full((12, 20, 3), 600)), frame_time_ms=10)
    assert original.capacity_state.ticks == 1
    checkpoint = json.loads(json.dumps(original.checkpoint()))
    resumed = Pipeline(
        _history_profile(name),
        colorimetry=config,
        abl_dynamics=replace(dynamics, initial="resume"),
        viewing_angle=viewing,
    )
    resumed.restore_checkpoint(checkpoint)
    for value in (100, 800, 0):
        frame = Frame(np.full((12, 20, 3), value))
        expected = original.display_content(frame, frame_time_ms=10)
        actual = resumed.display_content(frame, frame_time_ms=10)
        np.testing.assert_array_equal(actual.rgb, expected.rgb)
        assert actual.rgb.tobytes() == expected.rgb.tobytes()
        assert original.last_capacity_trace == resumed.last_capacity_trace
    assert original.capacity_state.ticks == 4


@pytest.mark.parametrize("change", ["source", "white", "method", "knee", "panel", "off"])
def test_active_m13_checkpoint_rejects_colorimetry_identity_changes(change):
    config = ColorimetryConfig(enabled=True)
    dynamics = ABLDynamicsConfig(model=MODEL, attack_ms=100, release_ms=500)
    source = Pipeline(_history_profile(), colorimetry=config, abl_dynamics=dynamics)
    source.display_content(Frame(np.ones((12, 20, 3))))
    panel_config = panel_parameters(_history_profile())
    if change == "source":
        config = replace(config, source_primaries="bt2020")
    elif change == "white":
        config = replace(config, source_white_xy=(0.32, 0.34))
    elif change == "method":
        config = replace(config, gamut_mapping="clip")
    elif change == "knee":
        config = replace(config, compression_knee=0.7)
    elif change == "panel":
        panel_config = replace(panel_config, woled_rgb_peak_ratio=0.5)
    else:
        config = replace(config, enabled=False)
        panel_config = None
    resumed = Pipeline(
        _history_profile(),
        colorimetry=config,
        panel_colorimetry=panel_config,
        abl_dynamics=replace(dynamics, initial="resume"),
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        resumed.restore_checkpoint(source.checkpoint())


def test_off_m13_identity_shape_unchanged_and_active_declarations_protected():
    dynamics = ABLDynamicsConfig(model=MODEL, attack_ms=100, release_ms=500)
    assert "colorimetry" not in Pipeline(_history_profile(), abl_dynamics=dynamics).identity()
    active = Pipeline(_history_profile(), colorimetry=ColorimetryConfig(enabled=True))
    active.colorimetry = replace(active.colorimetry, source_primaries="bt2020")
    with pytest.raises(ValueError, match="fresh Pipeline"):
        active.display_content(Frame(np.ones((12, 20, 3))))


@pytest.mark.parametrize("field", ["matrix", "angle", "power", "tracking"])
def test_active_rejects_ambiguous_legacy_color_or_duplicate_limiters(field):
    profile = load_profile("generic_woled")
    if field == "matrix":
        profile = replace(
            profile, panel=replace(profile.panel, color_matrix=np.diag([1, 1, 0.9]).tolist())
        )
    elif field == "angle":
        profile = replace(profile, panel=replace(profile.panel, viewing_angle_deg=10))
    elif field == "power":
        profile = replace(profile, hdr=replace(profile.hdr, abl_power_budget_nits=1))
    else:
        profile = replace(profile, hdr=replace(profile.hdr, abl_backlight_tracking=0.5))
    with pytest.raises(ValueError):
        Pipeline(profile, colorimetry=ColorimetryConfig(enabled=True))


def test_active_preview_converts_to_709_and_export_keeps_signed_coordinates():
    profile = load_profile("generic_qdoled")
    config = ColorimetryConfig(enabled=True, source_primaries="bt2020", gamut_mapping="clip")
    encoded = np.zeros((12, 20, 3), dtype=np.float32)
    encoded[..., 0] = 1
    linear_pipeline = Pipeline(profile, colorimetry=config)
    linear = linear_pipeline.run_linear(encoded)
    output = linear_pipeline.output_in_space(linear, "bt709")
    assert np.min(output) < 0
    from tv_sim.stages.encode import encode_frame

    expected = encode_frame(Frame(output), profile.output)
    np.testing.assert_array_equal(Pipeline(profile, colorimetry=config).run(encoded), expected)
