"""Compare historical artifacts without tying numeric metadata to one CPU.

Rendered pixels, arrays, profile bytes and trace hashes remain exact. Only
floating-point metadata accepts a 2e-6 relative / 1e-7 absolute tolerance.
The legacy label substitutions account solely for M16's package/docs moves.
"""

from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def legacy_labels(value: Any) -> Any:
    """Restore renamed source labels before comparing unchanged old captures."""
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
