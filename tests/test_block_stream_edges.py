"""Streaming edge cases against the independent phase-1 cadence contract."""

from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from tv_sim.abl_dynamics import ABLDynamicsConfig
from tv_sim.motion import schedule
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile
from tv_sim.sequence import MotionConfig


def _profile():
    profile = load_profile("generic_woled")
    return replace(
        profile,
        processing=replace(profile.processing, sharpen_amount=0),
        temporal=replace(profile.temporal, sample_and_hold=False, motion_px_per_frame=0),
    )


@pytest.mark.parametrize(
    "pts,last_duration,output_fps",
    [
        (["-3/2"], "1/25", "7"),
        (["5/2", "51/20", "8/3", "14/5"], "1/100", "5"),
        (["-3/2", "-7/5", "-11/10"], "1/20", "7"),
    ],
)
def test_streaming_first_skipped_intervals_and_tail_match_phase1_schedule(
    pts,
    last_duration,
    output_fps,
):
    """Irregular downconversion must not emit extra source or tail pictures."""
    expected = [tick.to_dict() for tick in schedule(pts, last_duration, output_fps)]
    source = np.full((8, 16, 3), 0.25, np.float32)
    output = list(
        Pipeline(_profile()).run_sequence(
            (source.copy() for _ in pts),
            MotionConfig(mode="mci", output_fps=output_fps),
            source_pts=pts,
            last_duration=last_duration,
        )
    )
    assert len(output) == len(expected)
    assert [
        {key: result.diagnostics[key] for key in tick} for result, tick in zip(output, expected)
    ] == expected
    assert output[0].diagnostics["kind"] == "original"
    assert output[0].diagnostics["phase"] == "0/1"
    assert all(
        result.diagnostics["frame_time_ms"] == float(1000 / Fraction(output_fps))
        for result in output
    )
    assert Fraction(output[-1].diagnostics["output_pts"]) < Fraction(pts[-1]) + Fraction(
        last_duration
    )
    if pts[-1] == "14/5":
        # Both source 1's interval and the entire short final hold are skipped.
        assert [result.diagnostics["source_index"] for result in output] == [0, 2]


@pytest.mark.parametrize("failure", ["geometry", "dtype", "nonfinite"])
def test_late_invalid_stream_picture_preserves_last_successful_m13_history(failure):
    first = np.zeros((8, 16, 3), np.float32)
    second = np.ones_like(first)
    bad = {
        "geometry": np.zeros((9, 16, 3), np.float32),
        "dtype": np.zeros((8, 16, 3), np.float64),
        "nonfinite": np.full((8, 16, 3), np.nan, np.float32),
    }[failure]
    consumed = []

    def source_stream():
        for index, source in enumerate((first, second, bad)):
            consumed.append(index)
            yield source

    pipeline = Pipeline(
        _profile(),
        abl_dynamics=ABLDynamicsConfig(
            model="capacity_attack_release_v1",
            attack_ms=100,
            release_ms=1000,
        ),
    )
    output = pipeline.run_sequence(source_stream(), MotionConfig(mode="mci", output_fps=60))
    completed = [next(output) for _ in range(3)]
    assert consumed == [0, 1]
    assert [result.diagnostics["output_pts"] for result in completed] == ["0/1", "1/60", "1/30"]
    assert pipeline.capacity_state.ticks == 3
    checkpoint = pipeline.checkpoint()
    with pytest.raises(ValueError, match="finite" if failure == "nonfinite" else "geometry"):
        next(output)
    assert consumed == [0, 1, 2]
    # Includes exact scalar clock/capacity/load, temporal array bytes and the
    # full source/history chain; reading the bad picture advances none of them.
    assert pipeline.checkpoint() == checkpoint


def test_declared_cut_flushes_pair_history_even_when_cut_interval_has_no_tick(monkeypatch):
    import tv_sim.block_motion as motion

    real_estimate = motion.estimate_pair
    calls = []

    def estimate(left, right, config, **kwargs):
        result = real_estimate(left, right, config, **kwargs)
        calls.append((kwargs["declared_cut"], kwargs["previous"], result))
        return result

    monkeypatch.setattr(motion, "estimate_pair", estimate)
    old = np.zeros((8, 16, 3), np.uint8)
    new = np.full_like(old, 80)
    dynamics = ABLDynamicsConfig(model="capacity_attack_release_v1", attack_ms=100, release_ms=1000)
    pipeline = Pipeline(_profile(), abl_dynamics=dynamics)
    output = list(
        pipeline.run_sequence(
            iter([old, old.copy(), new, new.copy(), new.copy()]),
            MotionConfig(mode="mci", source_fps=24, output_fps=6),
            cuts=[2],
        )
    )
    assert [result.diagnostics["source_index"] for result in output] == [0, 4]
    assert len(calls) == 4
    assert calls[1][0] and calls[1][2].scene_cut
    assert calls[2][1] is None
    assert calls[3][1] is calls[2][2]
    assert pipeline.capacity_state.ticks == 2
    assert not np.array_equal(output[0].frame.rgb, output[1].frame.rgb)
