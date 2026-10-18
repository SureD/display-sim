"""Byte-exact full M18 continuation and hostile checkpoint admission checks."""

import json
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from tv_sim import ABLDynamicsConfig, Frame, Pipeline, SubframeConfig, load_profile
from tv_sim.abl_dynamics import digest
from tv_sim.profile import TemporalParams
from tv_sim.zone_temporal import ZoneTemporalConfig


def make(owner="none", *, resume=False, explicit=False, pixel_initial="cold", **changes):
    p = load_profile("generic_woled" if owner == "capacity" else "generic_va_fald_miniled")
    p = replace(
        p,
        temporal=TemporalParams(response_time_ms=0),
        processing=replace(p.processing, sharpen_amount=0),
    )
    config = SubframeConfig(
        model="subframe_emission_v1",
        substeps=5,
        rise_tau_ms=3,
        fall_tau_ms=6,
        initial="resume" if resume else pixel_initial,
        **changes,
    )
    kwargs = {}
    policy = "resume" if resume else "explicit" if explicit else "cold"
    if owner == "zone":
        p = replace(p, backlight=replace(p.backlight, zones_x=2, zones_y=2))
        kwargs["zone_temporal"] = ZoneTemporalConfig(
            model="zone_attack_release_v1",
            attack_s=0.03,
            release_s=0.1,
            initial=policy,
            initial_zones_nits=((10.0, 20.0), (30.0, 40.0)) if policy == "explicit" else None,
        )
    if owner == "capacity":
        kwargs["abl_dynamics"] = ABLDynamicsConfig(
            model="capacity_attack_release_v1",
            attack_ms=30,
            release_ms=150,
            initial=policy,
            initial_capacity_nits=400 if policy == "explicit" else None,
        )
    return Pipeline(p, subframe=config, **kwargs)


def content(index):
    rng = np.random.default_rng(index)
    return Frame(rng.random((4, 8, 3), dtype=np.float32) * 600)


@pytest.mark.parametrize("owner", ["none", "zone", "capacity"])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("pixel_initial", ["cold", "settled_first_tick"])
def test_exact_full_continuation(owner, explicit, gate, pixel_initial):
    options = (
        (
            {"bfi_duty": "2/5", "bfi_phase": "4/5"}
            if owner == "capacity"
            else {
                "pwm_hz": "937/3",
                "pwm_duty": "7/19",
                "pwm_phase": "2/7",
                "strobe_duty": "3/4",
                "strobe_phase": "1/3",
            }
        )
        if gate
        else {}
    )
    original = make(owner, explicit=explicit, pixel_initial=pixel_initial, **options)
    origin, duration = Fraction(31, 23), Fraction(1001, 60000)
    for i in range(4):
        original.display_subframes(content(i), pts=origin + i * duration, duration=duration)
    saved = json.loads(json.dumps(original.checkpoint()))
    resumed = make(owner, resume=True, **options)
    resumed.restore_checkpoint(
        saved, shape=(4, 8, 3), dtype=np.float32, elapsed_ms=float(4 * duration * 1000)
    )
    assert resumed.checkpoint() == saved
    for i in range(4, 8):
        a = original.display_subframes(content(i), pts=origin + i * duration, duration=duration)
        b = resumed.display_subframes(content(i), pts=origin + i * duration, duration=duration)
        assert a.endpoint.tobytes() == b.endpoint.tobytes()
        assert a.mean.tobytes() == b.mean.tobytes()
        for x, y in zip(a.samples, b.samples):
            assert (x.pts, x.duration, x.gate_fraction) == (y.pts, y.duration, y.gate_fraction)
            assert x.rgb.tobytes() == y.rgb.tobytes()
            assert x.panel.tobytes() == y.panel.tobytes()
        assert resumed.checkpoint() == original.checkpoint()


def checkpoint(owner="zone"):
    pipe = make(owner)
    pipe.display_subframes(content(0), pts=Fraction(0), duration=Fraction(1, 60))
    return pipe.checkpoint()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("kind", "other"),
        ("evidence", {}),
        ("identity", {}),
        ("history_sha256", "oops"),
        ("geometry", {"shape": [1, 2]}),
        ("initialization", {}),
        ("extra", 1),
    ],
)
@pytest.mark.parametrize("rehash", [False, True])
def test_bad_top_fields_reject_without_mutation(field, value, rehash):
    saved = checkpoint()
    saved[field] = value
    if rehash:
        saved["checkpoint_sha256"] = digest(
            {k: v for k, v in saved.items() if k != "checkpoint_sha256"}
        )
    resumed = make("zone", resume=True)
    with pytest.raises(ValueError):
        resumed.restore_checkpoint(saved)
    assert resumed.subframe_state.previous is None
    assert resumed.zone_state.zones_nits is None
    # A rejected restore leaves the fresh owner usable for a valid restore.
    resumed.restore_checkpoint(checkpoint())


@pytest.mark.parametrize(
    "change",
    [
        "ticks",
        "time",
        "elapsed",
        "origin",
        "previous_hash",
        "previous_dtype",
        "previous_shape",
        "previous_base64",
        "zone_ticks",
        "zone_time",
        "legacy",
        "load",
        "init_grid",
        "init_capacity",
    ],
)
def test_corrupt_rehashed_history_rejects_atomically(change):
    saved = checkpoint()
    states = saved["states"]
    if change == "ticks":
        states["pixel"]["ticks"] = True
    if change == "time":
        states["pixel"]["next_pts"] = "5/7"
    if change == "elapsed":
        states["elapsed"] = "0"
    if change == "origin":
        states["origin_pts"] = 0
    if change.startswith("previous_"):
        field = change.removeprefix("previous_")
        states["pixel"]["previous"][
            {"hash": "sha256", "dtype": "dtype", "shape": "shape", "base64": "base64"}[field]
        ] = {"hash": "a" * 64, "dtype": "<f4", "shape": [4, 8, 1], "base64": "!invalid!"}[field]
    if change == "zone_ticks":
        states["zones"]["ticks"] = 2
    if change == "zone_time":
        states["zones"]["elapsed_ms_hex"] = float(10).hex()
    if change == "legacy":
        states["legacy_previous"] = states["pixel"]["previous"]
    if change == "load":
        states["load_apl_hex"] = float(1).hex()
    if change == "init_grid":
        saved["initialization"]["zone_initial_zones_nits"] = [[1]]
    if change == "init_capacity":
        saved["initialization"]["capacity_initial_nits"] = 100
    saved["checkpoint_sha256"] = digest(
        {k: v for k, v in saved.items() if k != "checkpoint_sha256"}
    )
    resumed = make("zone", resume=True)
    with pytest.raises(ValueError):
        resumed.restore_checkpoint(saved)
    assert resumed.subframe_state.ticks == 0
    assert resumed.zone_state.ticks == 0


@pytest.mark.parametrize("owner", ["none", "zone", "capacity"])
def test_fresh_resume_required(owner):
    with pytest.raises(ValueError, match="successful"):
        make(owner).checkpoint()
    resumed = make(owner, resume=True)
    with pytest.raises(ValueError, match="complete"):
        resumed.display_subframes(content(0), pts=Fraction(0), duration=Fraction(1, 60))
    saved = checkpoint(owner)
    with pytest.raises(ValueError, match="resume"):
        make(owner).restore_checkpoint(saved)
    resumed.restore_checkpoint(saved)
    with pytest.raises(ValueError, match="fresh"):
        resumed.restore_checkpoint(saved)


@pytest.mark.parametrize("owner", ["zone", "capacity"])
def test_resume_policy_owners_must_agree(owner):
    live = make(owner)
    kwargs = (
        {"zone_temporal": live.zone_temporal}
        if owner == "zone"
        else {"abl_dynamics": live.abl_dynamics}
    )
    with pytest.raises(ValueError, match="all active owners"):
        Pipeline(live.profile, subframe=replace(live.subframe, initial="resume"), **kwargs)


def test_restore_constraints_and_copy_transport():
    saved = checkpoint()
    for kwargs in ({"shape": (1, 2, 3)}, {"dtype": np.float64}, {"elapsed_ms": 100}):
        with pytest.raises(ValueError):
            make("zone", resume=True).restore_checkpoint(saved, **kwargs)
    restored = make("zone", resume=True)
    restored.restore_checkpoint(saved)
    saved["states"]["pixel"]["previous"]["base64"] = "edited"
    assert restored.checkpoint()["states"]["pixel"]["previous"]["base64"] != "edited"


@pytest.mark.parametrize("owner", ["none", "zone", "capacity"])
def test_mutated_owner_or_identity_rejects_checkpoint(owner):
    pipe = make(owner)
    pipe.display_subframes(content(0), pts=Fraction(0), duration=Fraction(1, 60))
    if owner == "zone":
        pipe.zone_state.previous_targets[:] += 0.1
    elif owner == "capacity":
        pipe.capacity_state.capacity_nits += 0.1
    else:
        pipe.subframe_state.previous[:] += 0.01
    with pytest.raises(ValueError, match="outside a tick"):
        pipe.checkpoint()


def test_config_mismatch_rejects():
    saved = checkpoint("none")
    changed = make("none", resume=True, pwm_hz="123", pwm_duty="1/2")
    with pytest.raises(ValueError, match="identity"):
        changed.restore_checkpoint(deepcopy(saved))


@pytest.mark.parametrize("owner", ["none", "zone"])
def test_lcd_overdrive_and_level_dependent_tau_resume_all_response_bytes(owner):
    settings = {
        "overdrive_levels": (0.0, 0.5, 1.0),
        "overdrive_commands": ((0.0, 1.0, 1.0), (0.0, 0.5, 1.0), (0.0, 0.0, 1.0)),
        "overdrive_fraction": "2/5",
        "tau_table": ((0.0, 2.0, 9.0), (0.5, 4.0, 7.0), (1.0, 6.0, 3.0)),
        "pwm_hz": "30000/1001",
        "pwm_duty": "2/3",
    }
    original = make(owner, **settings)
    duration = Fraction(1001, 60000)
    original.display_subframes(content(0), pts=Fraction(0), duration=duration)
    saved = json.loads(json.dumps(original.checkpoint()))
    resumed = make(owner, resume=True, **settings)
    resumed.restore_checkpoint(saved)
    for index in range(1, 4):
        a = original.display_subframes(content(index), pts=index * duration, duration=duration)
        b = resumed.display_subframes(content(index), pts=index * duration, duration=duration)
        assert a.endpoint.tobytes() == b.endpoint.tobytes()
        assert a.mean.tobytes() == b.mean.tobytes()
        assert [sample.rgb.tobytes() for sample in a.samples] == [
            sample.rgb.tobytes() for sample in b.samples
        ]
        assert resumed.checkpoint() == original.checkpoint()
