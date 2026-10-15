"""The validation harness writes metrics and previews."""

import json

from sim.cli import main
from sim.validate import WINDOW_FRACTIONS


def test_validate_writes_reports_for_one_profile(tmp_path):
    out = tmp_path / "reports"
    main(
        [
            "validate",
            "--profiles",
            "generic_woled",
            "--out",
            str(out),
            "--width",
            "96",
            "--height",
            "48",
            "--motion-px",
            "4",
            "--edge-frames",
            "4",
        ]
    )
    document = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert "placeholder" in document["disclaimer"].lower() or "not laboratory" in document["disclaimer"].lower()
    profile = document["profiles"]["generic_woled"]
    assert len(profile["windows"]) == len(WINDOW_FRACTIONS)
    assert profile["windows"][-1]["halo_nits"] is None
    assert profile["mprt"]["overdrive"]["supported"] is False
    assert profile["mprt"]["bfi"]["blur_px_comparison_duty"] is not None
    text = (out / "metrics.csv").read_text(encoding="utf-8")
    assert "generic_woled,ansi.white_nits" in text
    for name in ("checkerboard", "window_sweep", "moving_edge"):
        assert (out / f"generic_woled_{name}.png").is_file()
