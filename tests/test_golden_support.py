"""Portable metadata checks retain useful sensitivity to real regressions."""

import importlib
import json
import math
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
                if key.endswith((".png", ".npy", ".npz", ".f16", ".state.json")) or (
                    key.endswith(".json")
                    and isinstance(item, dict)
                    and {"bytes", "sha256"} <= item.keys()
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


@pytest.mark.parametrize("filename", ["pts-trace.json", "trace.json", "manifest.json"])
def test_historical_json_allows_one_byte_float_serialisation_difference(
    monkeypatch, tmp_path, filename
):
    expected_values = [
        {"pts": "1001/60000", "count": 1, "held": False, "apl_nits": 26.769044335683187}
    ]
    payload = json.dumps(expected_values, sort_keys=True, allow_nan=False).encode()
    expected = {
        "bytes": len(payload),
        "sha256": _reference(monkeypatch, np.frombuffer(payload, dtype=np.uint8)),
    }
    actual_values = [
        {**expected_values[0], "apl_nits": math.nextafter(expected_values[0]["apl_nits"], math.inf)}
    ]
    current = json.dumps(actual_values, sort_keys=True, allow_nan=False).encode()
    assert len(current) == len(payload) - 1
    path = tmp_path / filename
    path.write_bytes(current)
    actual = rendered_file_digest(
        path, {"bytes": len(current), "sha256": sha256(current).hexdigest()}
    )
    # Historical tolerance is explicit. Same-machine/off-on digest equality
    # continues to reject these different byte sequences.
    assert actual != expected
    assert_historical_snapshot(actual, expected)
    actual_values[0]["apl_nits"] += 0.001
    current = json.dumps(actual_values, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(current)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(
            rendered_file_digest(
                path, {"bytes": len(current), "sha256": sha256(current).hexdigest()}
            ),
            expected,
        )


@pytest.mark.parametrize(
    "actual,expected",
    [
        ({"pts": "1/60"}, {"pts": "1001/60000"}),
        ({"count": 2}, {"count": 1}),
        ({"count": True}, {"count": 1}),
        ({"enabled": 0}, {"enabled": False}),
        ({"nits": 1}, {"nits": 1.0}),
        ({"nits": 1.0}, {"nits": 1}),
        ({"renamed": 1.0}, {"original": 1.0}),
        ([1.0], [1.0, 2.0]),
    ],
)
def test_historical_json_keeps_structure_and_nonfloat_fields_exact(actual, expected):
    with pytest.raises(AssertionError):
        golden_support._assert_report_fields(actual, expected, "trace")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_historical_json_rejects_nonfinite_floats(value):
    with pytest.raises(AssertionError):
        golden_support._assert_report_fields(value, 1.0, "trace.nits")
    with pytest.raises(AssertionError):
        golden_support._assert_report_fields(value, value, "trace.nits")


def test_historical_json_still_authenticates_reference_byte_length(monkeypatch, tmp_path):
    path = tmp_path / "trace.json"
    payload = b'{"nits": 1.0}'
    path.write_bytes(payload)
    digest = _reference(monkeypatch, np.frombuffer(payload, dtype=np.uint8))
    actual = rendered_file_digest(path, {"bytes": len(payload), "sha256": digest})
    with pytest.raises(AssertionError):
        assert_historical_snapshot(actual, {"bytes": len(payload) + 1, "sha256": digest})


def test_nested_pts_trace_resolves_rendered_hashes_from_experiment_root(monkeypatch, tmp_path):
    folder = tmp_path / "cut"
    folder.mkdir()
    image = folder / "linear.npy"
    reference = np.array([100], dtype=np.float32)
    np.save(image, reference)
    original_image = image.read_bytes()
    original_hash = sha256(original_image).hexdigest()
    saved = [{"linear_file": "cut/linear.npy", "linear_sha256": original_hash, "pts": "1/60"}]
    original_json = json.dumps(saved, sort_keys=True, allow_nan=False).encode()
    json_hash = sha256(original_json).hexdigest()
    monkeypatch.setattr(
        golden_support,
        "_rendered_references",
        lambda: {
            original_hash: np.frombuffer(original_image, dtype=np.uint8),
            json_hash: np.frombuffer(original_json, dtype=np.uint8),
        },
    )
    np.save(image, reference + np.float32(0.00001))
    current = [{**saved[0], "linear_sha256": sha256(image.read_bytes()).hexdigest()}]
    path = folder / "pts-trace.json"
    payload = json.dumps(current, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(payload)
    expected = {"bytes": len(original_json), "sha256": json_hash}
    actual = rendered_file_digest(
        path, {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}, artifact_root=tmp_path
    )
    assert_historical_snapshot(actual, expected)
    image.write_bytes(b"invalid-current-payload")
    with pytest.raises(AssertionError):
        assert_historical_snapshot(actual, expected)


def test_historical_csv_compares_typed_floats_and_retains_exact_integer_cells(
    monkeypatch, tmp_path
):
    fixtures, out = tmp_path / "fixtures", tmp_path / "actual"
    fixtures.mkdir()
    out.mkdir()
    monkeypatch.setattr(golden_support, "FIXTURES", fixtures)
    original_csv = "metric,python_type,value\nnits,float,26.769044335683187\ncount,int,1\n"
    original_json = '{"nits": 26.769044335683187, "count": 1}'
    expected = {}
    for extension, payload in (("csv", original_csv), ("json", original_json)):
        fixture = fixtures / f"validation_metrics_baseline.{extension}"
        fixture.write_text(payload)
        expected[f"metrics_{extension}_sha256"] = sha256(fixture.read_bytes()).hexdigest()
        (out / f"metrics.{extension}").write_text(
            payload.replace("26.769044335683187", "26.76904433568319")
        )
    golden_support.assert_validation_metrics(out, expected)
    (out / "metrics.csv").write_text(original_csv.replace("count,int,1", "count,int,2"))
    with pytest.raises(AssertionError):
        golden_support.assert_validation_metrics(out, expected)


@pytest.mark.parametrize("module_name", ["test_colorimetry_parity", "test_m14_parity"])
def test_cli_source_png_reencoding_preserves_exact_pixels_and_current_checksum(
    monkeypatch, tmp_path, module_name
):
    sources, out = tmp_path / "sources", tmp_path / "motion"
    sources.mkdir()
    out.mkdir()
    source = sources / "input.png"
    pixels = np.full((3, 4, 3), 100, dtype=np.uint8)
    Image.fromarray(pixels).save(source, compress_level=0)
    original_png = source.read_bytes()
    original_hash = sha256(original_png).hexdigest()
    saved = {"sources": [{"file": source.name, "sha256": original_hash}], "pts": "1001/60000"}
    original_json = json.dumps(saved, sort_keys=True, allow_nan=False).encode()
    json_hash = sha256(original_json).hexdigest()
    monkeypatch.setattr(
        golden_support,
        "_rendered_references",
        lambda: {
            original_hash: np.frombuffer(original_png, dtype=np.uint8),
            json_hash: np.frombuffer(original_json, dtype=np.uint8),
        },
    )
    expected = {"manifest.json": {"bytes": len(original_json), "sha256": json_hash}}
    collect = importlib.import_module(module_name)._artifact_snapshot

    def snapshot():
        current = {
            **saved,
            "sources": [{"file": str(source), "sha256": sha256(source.read_bytes()).hexdigest()}],
        }
        (out / "manifest.json").write_text(json.dumps(current))
        return collect(out)

    Image.fromarray(pixels).save(source, compress_level=9)
    assert sha256(source.read_bytes()).hexdigest() != original_hash
    actual = snapshot()
    assert actual != expected  # Ordinary same-machine digest equality stays byte-exact.
    assert_historical_snapshot(actual, expected)
    changed = pixels.copy()
    changed[0, 0, 0] += 1
    Image.fromarray(changed).save(source, compress_level=9)
    with pytest.raises(AssertionError):
        assert_historical_snapshot(snapshot(), expected)
    # The collector must authenticate the current hash before erasing directories.
    source.write_bytes(b"tampered after manifest creation")
    with pytest.raises(AssertionError):
        collect(out)


@pytest.mark.parametrize("suffix", [".txt", ".yaml"])
def test_manifest_text_and_profile_source_hashes_remain_exact(monkeypatch, tmp_path, suffix):
    source = tmp_path / ("source" + suffix)
    source.write_text("level: 1\n")
    saved = {"sources": [{"file": source.name, "sha256": sha256(source.read_bytes()).hexdigest()}]}
    payload = json.dumps(saved, sort_keys=True, allow_nan=False).encode()
    expected = {
        "bytes": len(payload),
        "sha256": _reference(monkeypatch, np.frombuffer(payload, dtype=np.uint8)),
    }
    source.write_text("level: 2\n")
    current = {
        "sources": [{"file": source.name, "sha256": sha256(source.read_bytes()).hexdigest()}]
    }
    payload = json.dumps(current, sort_keys=True, allow_nan=False).encode()
    path = tmp_path / "manifest.json"
    path.write_bytes(payload)
    actual = rendered_file_digest(
        path,
        {"bytes": len(payload), "sha256": sha256(payload).hexdigest()},
        source_paths={source.name: source},
    )
    with pytest.raises(AssertionError):
        assert_historical_snapshot(actual, expected)


@pytest.mark.parametrize("tamper", [None, "array", "trace", "drift"])
def test_oled_manifest_links_raw_float_samples_and_trace_json(monkeypatch, tmp_path, tamper):
    folder = tmp_path / "trial"
    folder.mkdir()
    image, trace_path = folder / "sample.npy", folder / "trace.json"
    reference = np.array([100], dtype=np.float32)
    raw_hash = sha256(reference.tobytes()).hexdigest()
    old_trace = b'{"nits": 100.0, "pts": "1/60"}'
    trace_hash = sha256(old_trace).hexdigest()
    sample = {"linear_file": image.name, "sha256": raw_hash}
    saved = {
        "trials": [
            {
                "trial_id": folder.name,
                "samples": [sample],
                "segments": [{"samples": [sample]}],
                "trace_file": trace_path.name,
                "trace_sha256": trace_hash,
            }
        ]
    }
    payload = json.dumps(saved, sort_keys=True, allow_nan=False).encode()
    expected = {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}
    refs = {
        raw_hash: reference,
        trace_hash: np.frombuffer(old_trace, dtype=np.uint8),
        expected["sha256"]: np.frombuffer(payload, dtype=np.uint8),
    }
    monkeypatch.setattr(golden_support, "_rendered_references", lambda: refs)
    array = np.nextafter(reference, np.float32(np.inf))
    if tamper == "drift":
        array = reference + np.float32(0.1)
    np.save(image, array)
    trace_path.write_text(json.dumps({"nits": math.nextafter(100.0, math.inf), "pts": "1/60"}))
    current = json.loads(payload)
    trial = current["trials"][0]
    for record in (trial["samples"][0], trial["segments"][0]["samples"][0]):
        record["sha256"] = sha256(array.tobytes()).hexdigest()
    trial["trace_sha256"] = sha256(trace_path.read_bytes()).hexdigest()
    path = tmp_path / "manifest.json"
    payload = json.dumps(current, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(payload)
    actual = rendered_file_digest(
        path, {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}
    )
    assert actual != expected
    if tamper is None:
        assert_historical_snapshot(actual, expected)
    else:
        if tamper == "array":
            np.save(image, array + 1)
        elif tamper == "trace":
            trace_path.write_text('{"nits": 101.0, "pts": "1/60"}')
        with pytest.raises(AssertionError):
            assert_historical_snapshot(actual, expected)
