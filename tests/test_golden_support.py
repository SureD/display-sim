"""Portable metadata checks retain useful sensitivity to real regressions."""

import pytest
from golden_support import assert_numeric_metadata, legacy_labels


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
