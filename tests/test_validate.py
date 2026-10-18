"""The validation harness writes metrics and previews."""

import json

from tv_sim.cli import main
from tv_sim.validate import WINDOW_FRACTIONS


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
    assert (
        "placeholder" in document["disclaimer"].lower()
        or "not laboratory" in document["disclaimer"].lower()
    )
    profile = document["profiles"]["generic_woled"]
    assert len(profile["windows"]) == len(WINDOW_FRACTIONS)
    assert profile["windows"][-1]["halo_nits"] is None
    assert profile["mprt"]["overdrive"]["supported"] is False
    assert profile["mprt"]["bfi"]["blur_px_comparison_duty"] is not None
    text = (out / "metrics.csv").read_text(encoding="utf-8")
    assert "generic_woled,ansi.white_nits" in text
    assert "temporal_blur_px" in text
    comparison = (out / "comparison.md").read_text(encoding="utf-8")
    assert "generic_woled" in comparison
    assert "NR" in comparison
    assert "W1" in comparison
    for name in ("checkerboard", "window_sweep", "moving_edge"):
        assert (out / f"generic_woled_{name}.png").is_file()


def test_ips_temporal_width_is_not_the_backlight_edge():
    from tv_sim.profile import load_profile
    from tv_sim.validate import _edge_blur

    profile = load_profile("generic_ips_edge").with_overrides(motion_px=8.0)
    # Wide enough that the edge-lit PSF is tens of pixels. At a narrow frame
    # that spread shrinks toward the temporal width and the split disappears.
    edge = _edge_blur(profile, 108, 384, 6, 8.0)
    assert edge["still_blur_px"] > 50.0
    assert edge["temporal_blur_px"] < edge["still_blur_px"] / 2.0
    assert edge["blur_px"] > edge["still_blur_px"]
