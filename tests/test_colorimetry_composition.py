"""Independent M15 wiring checks across source Y and physical histories."""

from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from tv_sim.abl_dynamics import ABLDynamicsConfig
from tv_sim.block_motion import BlockMotionConfig
from tv_sim.color import pq_oetf
from tv_sim.colorimetry import RGB_SPACES, ColorimetryConfig, rgb_to_xyz_matrix
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.sequence import MotionConfig


def _profile(name="generic_qdoled", source="demand"):
    profile = load_profile(name)
    return replace(
        profile,
        input=replace(profile.input, eotf="pq"),
        processing=replace(profile.processing, sharpen_amount=0),
        hdr=replace(profile.hdr, abl_source=source, abl_response_ms=0),
        temporal=replace(profile.temporal, motion_px_per_frame=0),
        backlight=replace(profile.backlight, psf_sigma_zones=0, psf_tail_weight=0),
    )


def _red():
    rgb = np.zeros((8, 16, 3), dtype=np.float32)
    rgb[..., 0] = 1000
    return rgb


def test_active_demand_apl_uses_declared_source_luminance():
    source = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    pipeline = Pipeline(_profile(), colorimetry=source)
    pipeline.display_content(Frame(_red()))
    expected = 1000 * rgb_to_xyz_matrix(RGB_SPACES["bt2020"])[1, 0]
    assert pipeline.load_state.apl_nits == expected
    assert pipeline.load_state.apl_nits != 1000 * 0.2126


def test_active_emitted_apl_uses_panel_y_after_source_conversion():
    source = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    dynamics = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    pipeline = Pipeline(_profile(source="emitted"), colorimetry=source, abl_dynamics=dynamics)
    pipeline.display_content(Frame(_red()))
    # A flat, unblurred emissive panel followed by the neutral-ray mapper
    # preserves source XYZ Y before the one capacity owner limits it.
    expected = 1000 * rgb_to_xyz_matrix(RGB_SPACES["bt2020"])[1, 0]
    assert pipeline.last_capacity_trace["source"] == "emitted"
    assert pipeline.last_capacity_trace["apl_nits"] == pytest.approx(expected, rel=1e-7)


@pytest.mark.parametrize("mode", ["off", "repeat", "analytic", "mci"])
def test_active_m13_advances_once_for_each_m7_or_m14_output_tick(mode):
    profile = _profile("generic_woled")
    source = ColorimetryConfig(enabled=True, source_primaries="bt2020")
    dynamics = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    pipeline = Pipeline(profile, colorimetry=source, abl_dynamics=dynamics)
    settings = {} if mode == "off" else {"output_fps": "60"}
    if mode == "analytic":
        settings["translation_px"] = (0, 0)
    elif mode == "mci":
        settings["block"] = BlockMotionConfig(
            estimation_width=16,
            estimation_height=8,
            pyramid_levels=2,
            search_radius=2,
            refinement_radius=1,
            subpixel_steps=(),
        )
    inputs = [pq_oetf(_red() * gain) for gain in (1, 0.4, 0.8)]
    outputs = list(
        pipeline.run_sequence(
            inputs,
            MotionConfig(mode=mode, source_fps="24", **settings),
        )
    )
    expected_count = 3 if mode == "off" else 8
    assert len(outputs) == pipeline.capacity_state.ticks == expected_count
    dt = profile.temporal.frame_time_ms if mode == "off" else float(Fraction(1000, 60))
    assert pipeline.capacity_state.elapsed_ms == pytest.approx(expected_count * dt)
    assert all(np.isfinite(output.frame.rgb).all() for output in outputs)


@pytest.mark.parametrize("explicit_off", [False, True], ids=["omitted", "explicit-off"])
def test_off_rendering_never_loads_colorimetry_sidecars_or_calls_new_stages(
    monkeypatch, explicit_off
):
    import tv_sim.colorimetry_provenance as provenance
    import tv_sim.pipeline as pipeline_module

    def unexpected(*args, **kwargs):
        pytest.fail("disabled colorimetry entered sidecar loading or a new color stage")

    monkeypatch.setattr(provenance, "panel_parameters", unexpected)
    for name in ("decode_source", "source_to_panel_matrix", "gamut_map", "joint_tone_map"):
        monkeypatch.setattr(pipeline_module, name, unexpected)
    kwargs = {"colorimetry": ColorimetryConfig(enabled=False)} if explicit_off else {}
    result = Pipeline(_profile(), **kwargs).run_linear(pq_oetf(_red()))
    assert np.isfinite(result.rgb).all()
