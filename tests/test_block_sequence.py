"""M14 integration: bounded buffering and one physical update per output tick."""

import json
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest
from PIL import Image

from tv_sim.abl_dynamics import ABLDynamicsConfig
from tv_sim.cli import main
from tv_sim.color import srgb_oetf
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.sequence import MotionConfig


def profile():
    p = load_profile("generic_woled")
    return replace(
        p,
        processing=replace(p.processing, sharpen_amount=0),
        temporal=replace(p.temporal, sample_and_hold=False, motion_px_per_frame=0),
    )


class Recorder(Pipeline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prepares = 0
        self.targets = []

    def prepare_content(self, encoded):
        self.prepares += 1
        return super().prepare_content(encoded)

    def display_content(self, frame, **kwargs):
        self.targets.append(frame.rgb.copy())
        return super().display_content(frame, **kwargs)


def sources(count=3):
    rng = np.random.default_rng(7)
    # Retain a textured pan inside a black canvas, without wraparound content.
    texture = rng.uniform(10, 90, (32, 80, 3)).astype(np.float32)
    frames = []
    for index in range(count):
        rgb = np.zeros_like(texture)
        offset = index * 2
        rgb[:, offset:] = texture[:, : 80 - offset]
        frames.append(srgb_oetf(rgb / 100))
    return frames


def test_mci_streams_adjacent_sources_and_prepares_each_once():
    seen = []
    pipeline = Recorder(profile())
    frames = sources(4)

    def stream():
        for index, image in enumerate(frames):
            seen.append(index)
            yield image

    output = pipeline.run_sequence(stream(), MotionConfig(mode="mci", output_fps=60))
    first = next(output)
    assert seen == [0, 1] and pipeline.prepares == 2
    assert len(pipeline.targets) == 1 and first.diagnostics["phase"] == "0/1"
    second = next(output)
    assert seen == [0, 1] and pipeline.prepares == 2
    assert second.diagnostics["phase"] == "2/5"
    rest = list(output)
    assert len(rest) + 2 == len(pipeline.targets) == 10
    assert seen == [0, 1, 2, 3] and pipeline.prepares == 4
    assert rest[-1].diagnostics["fallback_reasons"] == ["last_frame_hold"]


@pytest.mark.parametrize("abl_source", ["demand", "emitted"])
def test_mci_composes_with_m13_one_capacity_and_panel_update_per_output_tick(abl_source):
    p = profile()
    p = replace(p, hdr=replace(p.hdr, abl_source=abl_source))
    dynamics = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    pipeline = Recorder(p, abl_dynamics=dynamics)
    output = list(
        pipeline.run_sequence(sources(), MotionConfig(mode="mci", output_fps=60), cuts=[1])
    )
    reference = Pipeline(p, abl_dynamics=dynamics)
    for tick, target in zip(output, pipeline.targets):
        expected = reference.display_content(Frame(target), frame_time_ms=1000 / 60)
        assert np.array_equal(expected.rgb, tick.frame.rgb)
        assert np.array_equal(expected.backlight, tick.frame.backlight)
        assert tick.diagnostics["abl_capacity"] == reference.last_capacity_trace
    assert pipeline.capacity_state.ticks == reference.capacity_state.ticks == len(output) == 8
    assert (
        pipeline.capacity_state.elapsed_ms
        == reference.capacity_state.elapsed_ms
        == sum([1000 / 60] * 8)
    )
    assert pipeline.capacity_state.capacity_nits == reference.capacity_state.capacity_nits
    assert np.array_equal(pipeline.state.previous, reference.state.previous)
    # The reconstruction stage holds the old picture throughout the cut pair.
    for target in pipeline.targets[:3]:
        assert np.array_equal(target, pipeline.targets[0])
    assert output[1].diagnostics["scene_cut"]
    assert output[1].diagnostics["fallback_fraction"] == 1


def test_declared_cut_flushes_confidence_history_and_never_estimates_across_it(monkeypatch):
    import tv_sim.block_motion as motion

    real = motion.estimate_pair
    calls = []

    def estimate(left, right, config, **kwargs):
        result = real(left, right, config, **kwargs)
        calls.append((kwargs.get("declared_cut"), kwargs.get("previous"), result))
        return result

    monkeypatch.setattr(motion, "estimate_pair", estimate)
    pipeline = Recorder(profile())
    output = list(
        pipeline.run_sequence(sources(4), MotionConfig(mode="mci", output_fps=48), cuts=[2])
    )
    assert len(calls) == 3
    assert calls[1][0] and calls[1][2].scene_cut
    assert calls[2][1] is None
    # The held target persists up to t=2/24, then the new source is exact.
    assert np.array_equal(pipeline.targets[2], pipeline.targets[3])
    assert not np.array_equal(pipeline.targets[3], pipeline.targets[4])
    assert output[4].diagnostics["source_index"] == 2


def test_mci_rational_pts_single_tail_and_clip_state_are_deterministic():
    config = MotionConfig(mode="mci", source_fps="24000/1001", output_fps="60000/1001")
    runs = []
    for _ in range(2):
        pipeline = Pipeline(profile())
        output = list(pipeline.run_sequence(sources(), config))
        runs.append((output, pipeline))
    assert [r.diagnostics for r in runs[0][0]] == [r.diagnostics for r in runs[1][0]]
    for a, b in zip(runs[0][0], runs[1][0]):
        assert np.array_equal(a.frame.rgb, b.frame.rgb)
        assert a.motion_maps.keys() == b.motion_maps.keys()
        for key in a.motion_maps:
            assert np.array_equal(a.motion_maps[key], b.motion_maps[key])
    assert Fraction(runs[0][0][1].diagnostics["output_pts"]) == Fraction(1001, 60000)
    one = list(Pipeline(profile()).run_sequence(sources(1), config))
    assert len(one) == 3 and one[0].diagnostics["kind"] == "original"
    assert one[1].diagnostics["fallback_reasons"] == ["last_frame_hold"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_pts": [0, 0], "last_duration": 1},
        {"source_pts": [0, 1]},
        {"cuts": [0]},
        {"cuts": [2]},
        {"last_duration": 0},
    ],
)
def test_mci_rejects_bad_available_metadata_before_display(kwargs):
    pipeline = Recorder(profile())
    with pytest.raises(ValueError):
        list(pipeline.run_sequence(sources(2), MotionConfig(mode="mci", output_fps=60), **kwargs))
    assert not pipeline.targets


def test_mci_stream_geometry_rejection_happens_when_pair_is_read():
    pipeline = Recorder(profile())
    with pytest.raises(ValueError, match="geometry"):
        list(
            pipeline.run_sequence(
                [np.zeros((8, 8, 3)), np.zeros((8, 9, 3))], MotionConfig(mode="mci", output_fps=60)
            )
        )
    assert not pipeline.targets


def test_motion_cli_mci_saves_config_maps_fixed_exposure_and_m13_trace(tmp_path):
    for index, image in enumerate(sources(2)):
        Image.fromarray(np.round(image * 255).astype(np.uint8)).save(
            tmp_path / f"source_{index}.png"
        )
    out = tmp_path / "mci"
    main(
        [
            "motion",
            "--profile",
            "generic_woled",
            "--input-frames",
            str(tmp_path / "source_*.png"),
            "--memc",
            "mci",
            "--output-fps",
            "60",
            "--motion-debug",
            "--block-size",
            "16",
            "--preview-reference-nits",
            "1000",
            "--abl-dynamics",
            "capacity_attack_release_v1",
            "--abl-attack-ms",
            "100",
            "--abl-release-ms",
            "1000",
            "--out",
            str(out),
        ]
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema_version"] == 2
    assert manifest["motion_config"]["parameters"]["block_size"]["value"] == 16
    assert manifest["domains"]["preview"]["reference_nits"] == 1000
    assert len(manifest["frames"]) == 5
    for record in manifest["frames"]:
        assert np.isfinite(np.load(out / record["linear_file"])).all()
        assert record["abl_capacity"]["ticks"] == record["output_index"] + 1
        with np.load(out / record["motion_maps_file"]) as maps:
            assert maps["fallback_mask"].shape == (32, 80)


def test_legacy_modes_do_not_discover_estimator_config(monkeypatch):
    import tv_sim.motion_provenance as evidence

    def forbidden(*args, **kwargs):
        raise AssertionError("off path must not load estimator config")

    monkeypatch.setattr(evidence, "load_block_config", forbidden)
    list(Pipeline(profile()).run_sequence(sources(1)))
    list(Pipeline(profile()).run_sequence(sources(1), MotionConfig(mode="repeat", output_fps=60)))
