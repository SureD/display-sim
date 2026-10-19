"""Compare historical artifacts without tying numeric metadata to one CPU.

Historical rendered arrays accept 2e-6 relative / 1e-7 absolute roundoff;
decoded eight-bit previews accept one code value. Historical JSON floats use
1e-12 relative/absolute tolerance. Profile bytes, discrete arrays, rational
traces, text and same-machine comparisons remain exact.
The legacy label substitutions account solely for M16's package/docs moves.
"""

from __future__ import annotations

import csv
import io
import json
import math
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"


class RenderedDigest(dict):
    """An ordinary exact digest record retaining values for historical checks.

    Equality remains normal dictionary equality. Only the explicit
    ``assert_historical_snapshot`` comparison permits numerical roundoff.
    """

    def __init__(self, record: dict, values: np.ndarray, *, preview: bool = False):
        super().__init__(record)
        self.values = np.array(values, copy=True)
        self.preview = preview
        self.file_kind: str | None = None
        self.payload: bytes | None = None
        self.file_path: Path | None = None
        self.artifact_root: Path | None = None
        self.source_paths: dict[str, Path] = {}


class NumericResult(float):
    """A derived statistic with an explicit tolerance; ordinary equality stays exact."""

    def __new__(cls, value: float, *, rel: float, absolute: float):
        result = super().__new__(cls, value)
        result.rel = rel
        result.absolute = absolute
        return result


def array_digest(array: np.ndarray | None, *, preview: bool = False) -> RenderedDigest | None:
    if array is None:
        return None
    array = np.ascontiguousarray(array)
    return RenderedDigest(
        {
            "shape": list(array.shape),
            "dtype": str(array.dtype),
            "sha256": sha256(array.tobytes()).hexdigest(),
        },
        array,
        preview=preview,
    )


def rendered_file_digest(
    path: Path,
    record: dict,
    *,
    payload: bytes | None = None,
    artifact_root: Path | None = None,
    source_paths: dict[str, Path] | None = None,
) -> RenderedDigest | dict:
    """Decode historical renders/JSON; retain exact hashes for other artifact kinds."""
    if path.suffix == ".png":
        with Image.open(path) as image:
            result = RenderedDigest(record, np.asarray(image), preview=True)
    elif path.suffix == ".npz":
        result = RenderedDigest(record, np.frombuffer(path.read_bytes(), dtype=np.uint8))
    elif path.suffix == ".npy":
        result = RenderedDigest(record, np.load(path, allow_pickle=False))
    elif path.suffix == ".f16":
        result = RenderedDigest(record, np.fromfile(path, dtype="<f2"))
    elif path.suffix == ".json":
        # Canonical snapshots supply their normalised payload; direct callers
        # compare the original JSON. Never hash float-bearing historical JSON
        # as opaque bytes: one ULP can change both its SHA and encoded length.
        payload = path.read_bytes() if payload is None else payload
        result = RenderedDigest(record, np.frombuffer(payload, dtype=np.uint8))
    else:
        return record
    result.file_kind = path.suffix
    result.payload = path.read_bytes() if payload is None else payload
    result.file_path = path
    result.artifact_root = path.parent if artifact_root is None else artifact_root
    result.source_paths = {} if source_paths is None else source_paths
    return result


@lru_cache(maxsize=1)
def _rendered_references() -> dict[str, np.ndarray]:
    with np.load(FIXTURES / "rendered_reference_values.npz", allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def assert_rendered_reference(actual: RenderedDigest, expected: dict, path: str) -> None:
    """Compare with values authenticated against the original captured digest."""
    reference = _rendered_references()[expected["sha256"]]
    if actual.file_kind is not None:
        payload = reference.tobytes()
        assert sha256(payload).hexdigest() == expected["sha256"], path
        if "bytes" in expected:
            assert len(payload) == expected["bytes"], path
        if actual.file_kind == ".png":
            with Image.open(io.BytesIO(payload)) as image:
                reference = np.asarray(image)
        elif actual.file_kind == ".npy":
            reference = np.load(io.BytesIO(payload), allow_pickle=False)
        elif actual.file_kind == ".npz":
            with (
                np.load(io.BytesIO(actual.payload), allow_pickle=False) as current,
                np.load(io.BytesIO(payload), allow_pickle=False) as saved,
            ):
                assert set(current.files) == set(saved.files), path
                for name in saved.files:
                    _assert_array_values(current[name], saved[name], False, f"{path}.{name}")
            return
        elif actual.file_kind == ".f16":
            reference = np.frombuffer(payload, dtype="<f2")
        else:
            current, saved = json.loads(actual.payload), json.loads(payload)
            if actual.file_path.name == "manifest.json" and isinstance(current, dict):
                link_manifest_hashes(current, actual.artifact_root, actual.source_paths)
            if actual.file_path.name in {"motion-validation.json", "pts-trace.json"}:
                # PTS traces live one directory below the report but contain
                # paths relative to the complete experiment's output root.
                current = link_rendered_hashes(current, actual.artifact_root)
            _assert_report_fields(current, saved, path)
            return
    if actual.file_kind is None:
        assert sha256(reference.tobytes()).hexdigest() == expected["sha256"], path
        # Identical bytes can represent, for example, both bool and uint8 masks.
        # SHA keys deduplicate bytes; the historical record owns shape and dtype.
        reference = np.frombuffer(
            reference.tobytes(), dtype=np.dtype(expected.get("dtype", actual.values.dtype))
        ).reshape(expected.get("shape", actual.values.shape))
    if "shape" in expected:
        assert actual["shape"] == expected["shape"], path
        assert actual["dtype"] == expected["dtype"], path
        assert sha256(reference.tobytes()).hexdigest() == expected["sha256"], path
    _assert_array_values(actual.values, reference, actual.preview, path)


def link_manifest_hashes(value: dict, root: Path, source_paths: dict[str, Path]) -> None:
    """Authenticate manifest inputs and experiment artifacts before linking values.

    CLI sources are external encoded inputs: integer PNG pixels stay exact.
    OLED samples hash raw RGB bytes, unlike NPY container hashes in other
    reports. Their paths and trace paths are relative to the trial directory.
    Text/profile inputs remain ordinary exact hashes.
    """
    for source in value.get("sources", []):
        path = source_paths[source["file"]]
        digest = source["sha256"]
        assert sha256(path.read_bytes()).hexdigest() == digest, path
        if path.suffix in {".png", ".npy", ".npz", ".f16"}:
            linked = rendered_file_digest(path, {"sha256": digest})
            linked.preview = False  # Source pixels are discrete inputs, not rendered previews.
            source["sha256"] = linked
    for trial in value.get("trials", []):
        folder = root / trial["trial_id"]
        samples = list(trial["samples"])
        for segment in trial["segments"]:
            samples.extend(segment["samples"])
        for sample in samples:
            path = folder / sample["linear_file"]
            array = np.ascontiguousarray(np.load(path, allow_pickle=False))
            digest = sample["sha256"]
            assert sha256(array.tobytes()).hexdigest() == digest, path
            sample["sha256"] = RenderedDigest({"sha256": digest}, array)
        path = folder / trial["trace_file"]
        digest = trial["trace_sha256"]
        assert sha256(path.read_bytes()).hexdigest() == digest, path
        trial["trace_sha256"] = rendered_file_digest(path, {"sha256": digest}, artifact_root=root)


def _assert_array_values(
    actual: np.ndarray, reference: np.ndarray, preview: bool, path: str
) -> None:
    assert actual.shape == reference.shape, path
    assert actual.dtype == reference.dtype, path
    if preview:
        # Quantising a float preview can move a boundary by one eight-bit step.
        # Compare signed values so uint8 subtraction cannot wrap around.
        np.testing.assert_allclose(
            actual.astype(np.int16),
            reference.astype(np.int16),
            rtol=0,
            atol=1,
            err_msg=path,
        )
    elif np.issubdtype(reference.dtype, np.floating):
        assert np.isfinite(actual).all() and np.isfinite(reference).all(), path
        if reference.dtype.itemsize == 2:
            # Half precision exports may quantise adjacent float32 results to
            # neighbouring codes. Ordered float16 codes also handle binade
            # boundaries, subnormals, negative values and the largest finite value.
            def ordered(values):
                bits = values.view(np.uint16).astype(np.int32)
                return np.where(bits & 0x8000, 0x8000 - (bits & 0x7FFF), 0x8000 + bits)

            assert np.all(np.abs(ordered(actual) - ordered(reference)) <= 1), path
        else:
            rel, absolute = (1e-12, 1e-12) if reference.dtype.itemsize == 8 else (2e-6, 1e-7)
            np.testing.assert_allclose(actual, reference, rtol=rel, atol=absolute, err_msg=path)
    else:
        np.testing.assert_array_equal(actual, reference, err_msg=path)


def assert_historical_snapshot(actual: Any, expected: Any, path: str = "root") -> None:
    """Compare historical rendered/JSON values; ordinary digest equality stays exact."""
    if isinstance(actual, RenderedDigest):
        if isinstance(expected, str):
            expected = {"sha256": expected}
        assert actual.keys() == expected.keys(), path
        assert_rendered_reference(actual, expected, path)
    elif isinstance(actual, NumericResult):
        assert type(expected) is float, path
        assert actual == pytest.approx(expected, rel=actual.rel, abs=actual.absolute), path
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), path
        for key, value in expected.items():
            assert_historical_snapshot(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            assert_historical_snapshot(actual[index], value, f"{path}[{index}]")
    else:
        assert type(actual) is type(expected) and actual == expected, path


def _assert_report_fields(actual: Any, expected: Any, path: str) -> None:
    """Compare historical JSON with strict structure/types and finite float roundoff.

    Float-bearing traces, diagnostics and summaries can vary by a few ULPs
    across CPU/interpreter implementations, including their serialised length.
    Rational strings, integers, booleans, text and keys remain exact. This
    comparator is only used explicitly for historical captures.
    """
    if isinstance(actual, RenderedDigest):
        assert_historical_snapshot(actual, expected, path)
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), path
        for key, value in expected.items():
            _assert_report_fields(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            _assert_report_fields(actual[index], value, f"{path}[{index}]")
    elif isinstance(expected, float):
        assert type(actual) is float, path
        assert math.isfinite(actual) and math.isfinite(expected), path
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12), path
    elif path.endswith((".identity.numpy_version", ".pipeline_identity.numpy_version")):
        # Historical environment identity must truthfully describe this host.
        # The captured environment version is not a simulation invariant.
        assert type(expected) is str and actual == np.__version__, path
    else:
        assert type(actual) is type(expected) and actual == expected, path


def link_rendered_hashes(value: Any, root: Path) -> Any:
    """Check current file identities, then link only rendered hashes to their values.

    Text, protocol/profile hashes, timing and other metadata stay ordinary values.
    Each linked SHA must exactly authenticate its current on-disk artifact before
    the historical comparator may compare decoded values against the old SHA.
    """
    if isinstance(value, list):
        return [link_rendered_hashes(item, root) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: link_rendered_hashes(item, root) for key, item in value.items()}
    for hash_key, file_key in (
        ("sha256", "file"),
        ("sha256", "linear_file"),
        ("truth_sha256", "truth_file"),
        ("linear_sha256", "linear_file"),
        ("display_sha256", "display_file"),
    ):
        if hash_key not in value or file_key not in value:
            continue
        path = root / value[file_key]
        if path.suffix not in {".png", ".npy", ".npz", ".f16"}:
            continue
        assert sha256(path.read_bytes()).hexdigest() == value[hash_key], path
        result[hash_key] = rendered_file_digest(path, {"sha256": value[hash_key]})
    return result


def legacy_labels(value: Any) -> Any:
    """Restore renamed source labels before comparing unchanged old captures."""
    if isinstance(value, RenderedDigest):
        return value
    if isinstance(value, dict):
        return {key: legacy_labels(item) for key, item in value.items()}
    if isinstance(value, list):
        return [legacy_labels(item) for item in value]
    if isinstance(value, str):
        return (
            value.replace("src/tv_sim/", "sim/")
            .replace("tv_sim/profiles/", "sim/profiles/")
            .replace("python3 -m tv_sim", "python3 -m sim")
            .replace("python -m tv_sim", "python -m sim")
            .replace("docs/reports/REPORT.md", "docs/REPORT.md")
            .replace("docs/research/", "research/")
        )
    return value


def assert_numeric_metadata(actual: Any, expected: Any, path: str = "root") -> None:
    """Retain exact structure/text and compare finite numeric metadata tightly."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert actual.keys() == expected.keys(), path
        for key, item in expected.items():
            assert_numeric_metadata(actual[key], item, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), path
        assert len(actual) == len(expected), path
        for index, item in enumerate(expected):
            assert_numeric_metadata(actual[index], item, f"{path}[{index}]")
    elif isinstance(expected, float):
        assert isinstance(actual, (float, int)) and not isinstance(actual, bool), path
        assert actual == pytest.approx(expected, rel=2e-6, abs=1e-7), path
    else:
        assert type(actual) is type(expected), path
        assert actual == expected, path


def gallery_manifest_baseline(expected_digest: str) -> dict[str, Any]:
    """Read an existing full capture and authenticate its original M9 hash."""
    baseline = json.loads((FIXTURES / "oled_dynamics_off_baseline.json").read_text())
    manifest = baseline["gallery"]["False"]["manifest"]
    payload = (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode()
    assert sha256(payload).hexdigest() == expected_digest
    return manifest


def assert_validation_metrics(out: Path, baseline: dict[str, Any]) -> None:
    """Use authenticated pre-M16 numbers for both JSON and typed CSV metrics."""
    for extension in ("json", "csv"):
        fixture = FIXTURES / f"validation_metrics_baseline.{extension}"
        assert sha256(fixture.read_bytes()).hexdigest() == baseline[f"metrics_{extension}_sha256"]
        actual = out / f"metrics.{extension}"
        if extension == "json":
            assert_numeric_metadata(json.loads(actual.read_text()), json.loads(fixture.read_text()))
        else:
            with actual.open(newline="") as handle:
                current = list(csv.DictReader(handle))
            with fixture.open(newline="") as handle:
                expected = list(csv.DictReader(handle))
            for rows in (current, expected):
                for row in rows:
                    if row["python_type"] == "float":
                        row["value"] = float(row["value"])
            assert_numeric_metadata(current, expected)
