"""Every block-motion budget and safeguard remains a versioned P placeholder."""

import json
from copy import deepcopy
from dataclasses import asdict, fields, replace

import pytest

from tv_sim.block_motion import BlockMotionConfig
from tv_sim.motion_provenance import (
    CONFIG_PATH,
    block_config_record,
    load_block_config,
    validate_block_config,
    validate_motion_provenance,
)
from tv_sim.provenance import main


def test_default_snapshot_covers_all_estimator_fields_and_unknown_device_data():
    data = json.loads(CONFIG_PATH.read_text())
    assert validate_motion_provenance() == []
    assert asdict(load_block_config()) == asdict(BlockMotionConfig())
    assert set(data["parameters"]) == {f.name for f in fields(BlockMotionConfig)}
    assert all(entry["evidence"] == "P" for entry in data["parameters"].values())
    assert set(data["unavailable"].values()) == {"NR"}
    assert "profiles" not in CONFIG_PATH.parts


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("evidence", "M"),
        ("parameter_status", "calibrated"),
        ("unavailable", {"measured_thresholds": 0}),
        ("invented_threshold", 0.5),
    ],
)
def test_invalid_evidence_or_unknown_fields_reject(key, value):
    data = block_config_record()
    data[key] = value
    assert validate_block_config(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence_threshold", float("nan")),
        ("confidence_threshold", -1),
        ("block_size", 4),
        ("block_size", True),
        ("pyramid_levels", 1000000),
        ("search_radius", -1),
        ("estimation_width", 0),
        ("luma_reference_nits", 0),
        ("max_displacement_px", float("inf")),
    ],
)
def test_invalid_numerical_parameters_reject(field, value):
    data = block_config_record()
    data["parameters"][field]["value"] = value
    assert validate_block_config(data)


def test_custom_values_retain_labels_and_default_snapshot_is_checked(tmp_path):
    custom = replace(BlockMotionConfig(), confidence_threshold=0.7)
    data = block_config_record(custom)
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(data))
    assert load_block_config(path) == custom
    assert validate_motion_provenance(data)
    changed = deepcopy(data)
    changed["parameters"]["confidence_threshold"]["evidence"] = "M"
    assert validate_block_config(changed)
    del changed["parameters"]["fb_threshold_px"]
    assert validate_block_config(changed)


def test_duplicate_keys_and_missing_config_fail_explicitly(tmp_path):
    path = tmp_path / "duplicates.json"
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate"):
        load_block_config(path)
    with pytest.raises(OSError):
        load_block_config(tmp_path / "absent.json")


def test_provenance_cli_checks_motion_config_with_profile_selection(tmp_path, monkeypatch, capsys):
    import tv_sim.motion_provenance as evidence

    data = block_config_record()
    data["evidence"] = "M"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(evidence, "CONFIG_PATH", path)
    with pytest.raises(SystemExit) as exc:
        main(["--check", "--profiles", "generic_woled"])
    assert exc.value.code == 1
    assert "motion config" in capsys.readouterr().err
