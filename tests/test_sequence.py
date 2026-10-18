"""Sequence integration gates: source/display domains and independent histories."""

import json
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest
from PIL import Image

from tv_sim.cli import main
from tv_sim.color import srgb_oetf
from tv_sim.motion import AnalyticLayer, LayerScene
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.sequence import MotionConfig
from tv_sim.stages.encode import encode_frame


def _profile():
    profile = load_profile("generic_woled")
    return replace(
        profile,
        processing=replace(profile.processing, sharpen_amount=0),
        temporal=replace(profile.temporal, sample_and_hold=False, motion_px_per_frame=0),
    )


class _RecordingPipeline(Pipeline):
    def __init__(self, profile):
        super().__init__(profile)
        self.prepared = []
        self.targets = []
        self.durations = []

    def prepare_content(self, encoded):
        frame = super().prepare_content(encoded)
        self.prepared.append(frame)
        return frame

    def display_content(self, frame, *, frame_time_ms=None):
        self.targets.append(frame)
        self.durations.append(frame_time_ms)
        return super().display_content(frame, frame_time_ms=frame_time_ms)


def test_repeat_prepares_each_source_once_and_advances_display_only_at_output_ticks():
    profile = _profile()
    pipeline = _RecordingPipeline(profile)
    sources = [np.zeros((8, 20, 3), np.uint8), np.full((8, 20, 3), 255, np.uint8)]
    results = list(pipeline.run_sequence(sources, MotionConfig(mode="repeat", output_fps=60)))
    assert len(pipeline.prepared) == 2
    assert len(results) == len(pipeline.targets) == 5
    assert pipeline.durations == [1000 / 60] * 5
    assert [result.diagnostics["source_index"] for result in results] == [0, 0, 0, 1, 1]
    assert [result.diagnostics["phase"] for result in results] == [
        "0/1",
        "2/5",
        "4/5",
        "1/5",
        "3/5",
    ]
    assert pipeline.profile is profile  # timing override does not mutate it
    reference = Pipeline(
        replace(profile, temporal=replace(profile.temporal, frame_time_ms=1000 / 60))
    )
    for result, index in zip(results, (0, 0, 0, 1, 1)):
        expected = reference.run_linear(sources[index])
        assert np.array_equal(result.frame.rgb, expected.rgb)
        assert np.array_equal(result.frame.backlight, expected.backlight)
    assert pipeline.load_state.apl_nits == reference.load_state.apl_nits
    assert np.array_equal(pipeline.state.previous, reference.state.previous)


def test_analytic_reconstruction_is_before_panel_and_never_decoded_twice():
    profile = _profile()
    background = np.full((8, 24, 3), 2.0, np.float32)
    texture = np.full_like(background, 40.0)
    mask = np.zeros(background.shape[:2], np.float32)
    mask[2:6, 5:9] = 1
    scene = LayerScene(background, (AnalyticLayer(texture, mask, velocity=(4, 0)),))
    sources = [srgb_oetf(scene.render(t).rgb / profile.input.sdr_white_nits) for t in (0, 1)]
    pipeline = _RecordingPipeline(profile)
    results = list(
        pipeline.run_sequence(
            sources,
            MotionConfig(mode="analytic", output_fps=48),
            scenes={0: scene},
        )
    )
    assert len(pipeline.prepared) == 2 and len(pipeline.targets) == 4
    assert results[1].diagnostics["kind"] == "interpolated"
    assert results[1].diagnostics["fallback_fraction"] == 0
    assert np.array_equal(pipeline.targets[1].rgb, scene.render(Fraction(1, 2)).rgb)
    assert pipeline.targets[0] is pipeline.prepared[0]
    assert pipeline.targets[2] is pipeline.prepared[1]
    assert results[-1].diagnostics["fallback_reasons"] == ["last_frame_hold"]
    assert results[1].diagnostics["lookahead_seconds"] == "1/24"


def test_cut_holds_old_requested_content_without_resetting_physical_history():
    profile = _profile()
    pipeline = _RecordingPipeline(
        replace(profile, temporal=replace(profile.temporal, response_time_ms=20))
    )
    sources = [np.zeros((8, 20, 3), np.uint8), np.full((8, 20, 3), 255, np.uint8)]
    results = list(
        pipeline.run_sequence(
            sources,
            MotionConfig(mode="analytic", output_fps=48, translation_px=(0, 0)),
            cuts=[1],
        )
    )
    assert results[1].diagnostics["scene_cut"] is True
    assert results[1].diagnostics["fallback_reasons"] == ["scene_cut"]
    assert pipeline.targets[1] is pipeline.prepared[0]
    # A physical response tail across a shot boundary is expected, independently
    # of the reconstruction guarantee that the old shot receives no future light.
    assert pipeline.targets[2] is pipeline.prepared[1]
    assert np.any(results[2].frame.rgb < pipeline.targets[2].rgb)


def test_irregular_source_pts_and_final_duration():
    sources = [np.zeros((4, 4, 3), np.uint8)] * 3
    results = list(
        Pipeline(_profile()).run_sequence(
            sources,
            MotionConfig(mode="repeat", output_fps=10),
            source_pts=["1", "11/10", "13/10"],
            last_duration="1/5",
        )
    )
    assert [result.diagnostics["output_pts"] for result in results] == [
        "1/1",
        "11/10",
        "6/5",
        "13/10",
        "7/5",
    ]
    assert [result.diagnostics["source_index"] for result in results] == [0, 1, 1, 2, 2]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "off", "output_fps": 60},
        {"mode": "repeat"},
        {"mode": "bad"},
        {"source_fps": 0},
        {"source_fps": "nan"},
        {"translation_px": (np.nan, 0)},
        {"max_displacement_px": -1},
        {"source_fps": True},
        {"endpoint_tolerance_nits": np.nan},
    ],
)
def test_invalid_motion_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MotionConfig(**kwargs)


@pytest.mark.parametrize(
    "sources,kwargs",
    [
        ([], {}),
        ([np.zeros((4, 4, 3)), np.zeros((4, 5, 3))], {}),
        ([np.zeros((4, 4, 3)), np.zeros((4, 4, 3), np.uint8)], {}),
        ([np.full((4, 4, 3), np.nan)], {}),
        ([np.zeros((4, 4, 3))], {"source_pts": [0]}),
        ([np.zeros((4, 4, 3))], {"source_pts": [0, 1], "last_duration": 1}),
        ([np.zeros((4, 4, 3))] * 2, {"source_pts": [1, 0], "last_duration": 1}),
        ([np.zeros((4, 4, 3))] * 2, {"cuts": [2]}),
    ],
)
def test_enabled_sequence_rejects_inconsistent_clips_before_state_advances(sources, kwargs):
    pipeline = _RecordingPipeline(_profile())
    with pytest.raises(ValueError):
        list(pipeline.run_sequence(sources, MotionConfig(mode="repeat", output_fps=60), **kwargs))
    assert not pipeline.targets
    assert pipeline.state.previous is None and pipeline.load_state.apl_nits is None


def test_memc_off_does_not_buffer_an_input_generator():
    pipeline = Pipeline(_profile())

    def sources():
        yield np.zeros((4, 4, 3), np.uint8)
        assert pipeline.state.previous is not None
        yield np.ones((4, 4, 3), np.uint8)

    assert len(list(pipeline.run_sequence(sources()))) == 2


def test_off_diagnostics_separate_declared_source_pts_from_legacy_profile_timing():
    profile = _profile()
    results = list(
        Pipeline(profile).run_sequence(
            [np.zeros((4, 4, 3), np.uint8)] * 3,
            source_pts=[1, "25/24", "13/12"],
        )
    )
    step = Fraction(str(profile.temporal.frame_time_ms)) / 1000
    assert [Fraction(result.diagnostics["source_pts"]) for result in results] == [
        1,
        Fraction(25, 24),
        Fraction(13, 12),
    ]
    assert [Fraction(result.diagnostics["output_pts"]) for result in results] == [
        1 + i * step for i in range(3)
    ]
    assert all(result.diagnostics["timing_policy"] == "legacy_profile" for result in results)


@pytest.mark.parametrize("pts", [[1, 0], [0], [0, float("nan")]])
def test_off_rejects_inconsistent_explicit_metadata_before_rendering_sized_inputs(pts):
    pipeline = Pipeline(_profile())
    with pytest.raises(ValueError):
        list(pipeline.run_sequence([np.zeros((4, 4, 3), np.uint8)] * 2, source_pts=pts))
    assert pipeline.state.previous is None


def test_motion_cli_defaults_off_and_saves_same_preview_and_linear_output(tmp_path):
    source = np.full((8, 20, 3), 150, np.uint8)
    Image.fromarray(source).save(tmp_path / "source.png")
    out = tmp_path / "motion"
    main(
        [
            "motion",
            "--profile",
            "generic_woled",
            "--input-frames",
            str(tmp_path / "source.png"),
            "--out",
            str(out),
        ]
    )
    manifest = json.loads((out / "manifest.json").read_text())
    expected = Pipeline(load_profile("generic_woled")).run_linear(source)
    assert np.array_equal(np.load(out / "frame_000000.npy"), expected.rgb)
    assert np.array_equal(
        np.asarray(Image.open(out / "frame_000000.png")),
        encode_frame(expected, load_profile("generic_woled").output),
    )
    assert manifest["config"]["mode"] == "off" and len(manifest["frames"]) == 1
    assert manifest["profile_yaml_sha256"]


def test_motion_cli_analytic_records_cut_fallback_and_separate_pts(tmp_path):
    for index, level in enumerate((0, 255)):
        Image.fromarray(np.full((8, 20, 3), level, np.uint8)).save(tmp_path / f"in_{index}.png")
    out = tmp_path / "motion"
    main(
        [
            "motion",
            "--profile",
            "generic_woled",
            "--input-frames",
            str(tmp_path / "in_*.png"),
            "--source-fps",
            "24000/1001",
            "--output-fps",
            "60000/1001",
            "--memc",
            "analytic",
            "--translation-px",
            "0",
            "0",
            "--cut-before",
            "1",
            "--out",
            str(out),
        ]
    )
    manifest = json.loads((out / "manifest.json").read_text())
    records = manifest["frames"]
    assert len(records) == 5
    assert records[1]["source_pts"] == "0/1"
    assert records[1]["output_pts"] == "1001/60000"
    assert records[1]["phase"] == "2/5"
    assert records[1]["fallback_reasons"] == ["scene_cut"]
    assert manifest["evidence"]["reconstruction_and_thresholds"] == "P"


def test_cli_rejects_rate_conversion_when_off(tmp_path):
    with pytest.raises(SystemExit):
        main(
            [
                "motion",
                "--profile",
                "generic_woled",
                "--input-frames",
                "missing*",
                "--output-fps",
                "60",
            ]
        )
