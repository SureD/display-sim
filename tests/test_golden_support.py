"""Portable metadata checks retain useful sensitivity to real regressions."""

import json
from hashlib import sha256
from pathlib import Path

import golden_support
import numpy as np
import pytest
from golden_support import (
    array_digest,
    assert_historical_snapshot,
    assert_numeric_metadata,
    legacy_labels,
    link_rendered_hashes,
    rendered_file_digest,
)
from PIL import Image


def test_float_roundoff_is_tolerated_but_material_drift_is_rejected():
    assert_numeric_metadata({"nits": [1000.0001, 0.00000001]}, {"nits": [1000.0, 0.0]})
    with pytest.raises(AssertionError):
        assert_numeric_metadata({"nits": 1000.1}, {"nits": 1000.0})


@pytest.mark.parametrize(
    "actual,expected",
    [
        ({"new": 1.0}, {"old": 1.0}),
        ([1.0], [1.0, 2.0]),
        ({"hash": "changed"}, {"hash": "saved"}),
        ({"count": True}, {"count": 1}),
        ({"count": 1.0}, {"count": 1}),
        ({"enabled": 1}, {"enabled": True}),
    ],
)
def test_metadata_structure_and_text_remain_exact(actual, expected):
    with pytest.raises(AssertionError):
        assert_numeric_metadata(actual, expected)


def test_layout_compatibility_changes_only_declared_labels():
    actual = {"source": "src/tv_sim/profiles/example.yaml", "value": [12.5, "tv_sim"]}
    assert legacy_labels(actual) == {
        "source": "sim/profiles/example.yaml",
        "value": [12.5, "tv_sim"],
    }


def _reference(monkeypatch, values):
    digest = sha256(values.tobytes()).hexdigest()
    monkeypatch.setattr(golden_support, "_rendered_references", lambda: {digest: values})
    return digest


def test_historical_roundoff_does_not_change_same_machine_digest_equality(monkeypatch):
    expected = array_digest(np.array([100], dtype=np.float32))
    actual = array_digest(np.array([100.00001], dtype=np.float32))
    _reference(monkeypatch, expected.values)
    assert actual != expected
    assert_historical_snapshot(actual, expected)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(array_digest(np.array([100.01], dtype=np.float32)), expected)


@pytest.mark.parametrize("dtype", [np.bool_, np.uint8, np.int32])
def test_historical_discrete_masks_and_reason_codes_remain_exact(monkeypatch, dtype):
    expected = array_digest(np.array([0, 1], dtype=dtype))
    _reference(monkeypatch, expected.values)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(array_digest(np.array([1, 1], dtype=dtype)), expected)


def test_identical_reference_bytes_use_historical_shape_and_dtype(monkeypatch):
    expected = array_digest(np.zeros((2, 3), dtype=bool))
    _reference(monkeypatch, np.zeros(6, dtype=np.uint8))
    assert_historical_snapshot(array_digest(expected.values), expected)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(array_digest(np.zeros((2, 3), dtype=np.uint8)), expected)


@pytest.mark.parametrize(
    "values", [np.array([[100]], dtype=np.float32), np.array([100], dtype=np.float64)]
)
def test_historical_shape_and_dtype_are_strict(monkeypatch, values):
    expected = array_digest(np.array([100], dtype=np.float32))
    _reference(monkeypatch, expected.values)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(array_digest(values), expected)


def test_reference_values_must_authenticate_against_original_hash(monkeypatch):
    expected = array_digest(np.array([100], dtype=np.float32))
    monkeypatch.setattr(
        golden_support,
        "_rendered_references",
        lambda: {expected["sha256"]: np.array([101], dtype=np.float32)},
    )
    with pytest.raises(AssertionError):
        assert_historical_snapshot(expected, expected)


def test_png_encoding_is_irrelevant_and_pixel_tolerance_uses_signed_subtraction(
    monkeypatch, tmp_path
):
    path = tmp_path / "preview.png"
    values = np.array([[[0, 100, 255]]], dtype=np.uint8)
    Image.fromarray(values).save(path, compress_level=0)
    payload = path.read_bytes()
    expected = {
        "bytes": len(payload),
        "sha256": _reference(monkeypatch, np.frombuffer(payload, dtype=np.uint8)),
    }
    Image.fromarray(values).save(path, compress_level=9)
    actual = rendered_file_digest(
        path, {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}
    )
    assert actual != expected
    assert_historical_snapshot(actual, expected)
    for preview, passes in (
        (np.array([[[1, 100, 254]]], dtype=np.uint8), True),
        (np.array([[[255, 100, 0]]], dtype=np.uint8), False),
    ):
        Image.fromarray(preview).save(path)
        actual = rendered_file_digest(
            path, {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}
        )
        if passes:
            assert_historical_snapshot(actual, expected)
        else:
            with pytest.raises(AssertionError):
                assert_historical_snapshot(actual, expected)


@pytest.mark.parametrize("value", [0, 1, -1, 65504, -65504])
def test_float16_tolerance_is_one_adjacent_finite_code(monkeypatch, value):
    reference = np.array([value], dtype=np.float16)
    expected = array_digest(reference)
    _reference(monkeypatch, reference)
    direction = np.float16(0 if value else 1)
    neighbour = np.nextafter(reference, direction)
    assert_historical_snapshot(array_digest(neighbour), expected)
    second = np.nextafter(neighbour, direction if value else np.float16(1))
    with pytest.raises(AssertionError):
        assert_historical_snapshot(array_digest(second), expected)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(array_digest(np.array([np.inf], dtype=np.float16)), expected)


def test_npz_member_names_and_discrete_values_stay_strict(monkeypatch, tmp_path):
    path = tmp_path / "maps.npz"
    values = {"flow": np.array([100], dtype=np.float32), "reason": np.array([1], dtype=np.uint8)}
    np.savez_compressed(path, **values)
    payload = path.read_bytes()
    expected = {"sha256": _reference(monkeypatch, np.frombuffer(payload, dtype=np.uint8))}
    np.savez(path, **values)
    assert_historical_snapshot(
        rendered_file_digest(path, {"sha256": sha256(path.read_bytes()).hexdigest()}), expected
    )
    for changed in ({**values, "reason": np.array([2], dtype=np.uint8)}, {"flow": values["flow"]}):
        np.savez(path, **changed)
        with pytest.raises(AssertionError):
            assert_historical_snapshot(
                rendered_file_digest(path, {"sha256": sha256(path.read_bytes()).hexdigest()}),
                expected,
            )


def test_linked_report_hash_must_match_current_artifact(monkeypatch, tmp_path):
    path = tmp_path / "linear.npy"
    reference = np.array([100], dtype=np.float32)
    np.save(path, reference)
    payload = path.read_bytes()
    digest = _reference(monkeypatch, np.frombuffer(payload, dtype=np.uint8))
    expected = {"linear_file": path.name, "linear_sha256": digest, "pts": "1001/60000"}
    np.save(path, reference + np.float32(0.00001))
    actual = {**expected, "linear_sha256": sha256(path.read_bytes()).hexdigest()}
    assert_historical_snapshot(link_rendered_hashes(actual, tmp_path), expected)
    with pytest.raises(AssertionError):
        link_rendered_hashes(expected, tmp_path)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(
            link_rendered_hashes({**actual, "pts": "1/60"}, tmp_path), expected
        )


def test_all_saved_rendered_references_authenticate_and_cover_historical_files():
    refs = golden_support._rendered_references()
    for digest, values in refs.items():
        assert sha256(values.tobytes()).hexdigest() == digest

    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key.endswith((".png", ".npy", ".npz", ".f16", ".state.json"))
                    or key == "motion-validation.json"
                ):
                    digest = item["sha256"] if isinstance(item, dict) else item
                    assert digest in refs, key
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    for path in (Path(__file__).parent / "fixtures").glob("*.json"):
        check(json.loads(path.read_text()))


def test_legacy_labels_preserves_linked_rendered_comparison(monkeypatch):
    expected = array_digest(np.array([100], dtype=np.float32))
    _reference(monkeypatch, expected.values)
    actual = array_digest(np.array([100.00001], dtype=np.float32))
    assert_historical_snapshot(legacy_labels({"asset": actual}), {"asset": expected})


def test_report_metrics_tolerate_roundoff_while_metadata_stays_exact():
    expected = {
        "summary": {
            "repeat": {"regions": {"boundary": {"linear_luma_mae_nits": 3.948065422819853}}}
        },
        "pts": "1001/60000",
        "preview_reference_nits": 1000.0,
    }
    actual = json.loads(json.dumps(expected))
    actual["summary"]["repeat"]["regions"]["boundary"]["linear_luma_mae_nits"] = 3.9480654228198535
    golden_support._assert_report_fields(actual, expected, "root")
    for key, value in (("pts", "1/60"), ("preview_reference_nits", 1000.00000001)):
        with pytest.raises(AssertionError):
            golden_support._assert_report_fields({**actual, key: value}, expected, "root")
    actual["summary"]["repeat"]["regions"]["boundary"]["linear_luma_mae_nits"] += 0.001
    with pytest.raises(AssertionError):
        golden_support._assert_report_fields(actual, expected, "root")


def test_historical_numpy_identity_must_describe_running_environment():
    expected = {"identity": {"numpy_version": "2.5.4"}, "ticks": 14}
    actual = {"identity": {"numpy_version": np.__version__}, "ticks": 14}
    golden_support._assert_report_fields(actual, expected, "checkpoint")
    for changed in ({**actual, "ticks": 15}, {**actual, "identity": {"numpy_version": "invented"}}):
        with pytest.raises(AssertionError):
            golden_support._assert_report_fields(changed, expected, "checkpoint")
