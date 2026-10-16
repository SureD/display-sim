"""Gallery output is an offline comparison with reproducible shared exposure."""

from html.parser import HTMLParser
from fractions import Fraction
import json

import numpy as np
from PIL import Image
import pytest

from sim.cli import main
from sim.gallery import (
    PROFILE_NAMES, MEMC_SNAPSHOT_INDEX, memc_position_trace, preview,
    render_memc_pan, scenes,
)
from sim.profile import load_profile


def test_preview_uses_absolute_shared_scale_and_declared_clipping():
    # One hundred nits has the same code regardless of a neighboring TV's peak.
    low_peak = np.array([[[0, 100, 400]]], np.float32)
    high_peak = np.array([[[0, 100, 2000]]], np.float32)
    assert preview(low_peak, 2000)[0, 0, 1] == preview(high_peak, 2000)[0, 0, 1]
    assert preview(low_peak, 2000)[0, 0, 2] < preview(high_peak, 2000)[0, 0, 2]
    assert np.array_equal(preview(np.array([[[0, 10, 2000]]]), 10), [[[0, 255, 255]]])
    with pytest.raises(ValueError):
        preview(low_peak, 0)


def test_gallery_sources_are_deterministic_absolute_nit_patterns():
    first, second = scenes(160, 96), scenes(160, 96)
    assert first.keys() == second.keys()
    for key in first:
        assert np.array_equal(first[key], second[key])
        assert first[key].shape == (96, 160, 3)
        assert np.isfinite(first[key]).all()
    assert first["bright_window"].max() == 2000
    assert first["motion_pan"].max() <= 100


class _LocalReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.stylesheets = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "img":
            self.images.append(attributes["src"])
        if tag == "script" and "src" in attributes:
            self.scripts.append(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.stylesheets.append(attributes["href"])


def test_gallery_cli_renders_all_profiles_and_offline_contact_sheets(tmp_path):
    # Full frame history and all profile stages, at a smaller test resolution.
    main(["gallery", "--out", str(tmp_path), "--width", "160", "--height", "96"])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [p["name"] for p in manifest["profiles"]] == list(PROFILE_NAMES)
    expected = {"starfield", "subtitles", "bright_window", "gradients", "motion_pan", "macro_subpixel", "motion_history", "motion_memc"}
    assert {sheet["id"] for sheet in manifest["sheets"]} == expected
    for sheet in manifest["sheets"]:
        with Image.open(tmp_path / sheet["file"]) as png:
            assert png.mode == "RGB"
            assert png.width >= 4 * 160
            assert png.height > 96
            assert np.asarray(png).std() > 10
        for row in sheet["rows"]:
            assert len(row["statistics"]) == 4
            assert row["reference_nits"] > 0

    window = next(s for s in manifest["sheets"] if s["id"] == "bright_window")
    peaks = [s["peak_channel_nits"] for s in window["rows"][0]["statistics"]]
    assert peaks[0] > peaks[3] > peaks[2] > peaks[1]  # actual profile headroom
    pan = next(s for s in manifest["sheets"] if s["id"] == "motion_pan")
    hold, od, bfi = [r["statistics"] for r in pan["rows"][1:]]
    assert od[0]["peak_channel_nits"] > hold[0]["peak_channel_nits"]
    assert od[2:] == hold[2:]  # OLED OD is explicitly not modeled.
    for h, b in zip(hold, bfi):
        assert b["mean_luminance_nits"] < .3 * h["mean_luminance_nits"]

    memc = next(s for s in manifest["sheets"] if s["id"] == "motion_memc")
    assert len(memc["rows"]) == 2
    assert "3:2" in memc["rows"][0]["title"]
    assert "(P)" in memc["rows"][1]["title"]
    trace = json.loads((tmp_path / manifest["memc_pan"]["trace_file"]).read_text())
    assert trace["timing_evidence"] == "D" and trace["reconstruction_evidence"] == "P"
    assert trace["vendor_algorithm"] == "NR"
    assert set(trace["profiles"]) == set(PROFILE_NAMES)
    assert len(trace["position_trace"]) == 15
    snapshot = trace["position_trace"][trace["snapshot_output_index"]]
    assert Fraction(snapshot["output_pts_seconds"]) == Fraction(11, 60)
    assert Fraction(snapshot["phase"]) == Fraction(2, 5)
    assert Fraction(snapshot["repeat_position_px"]) == 80
    assert Fraction(snapshot["analytic_position_px"]) == 88

    html = (tmp_path / "index.html").read_text()
    references = _LocalReferences()
    references.feed(html)
    assert len(references.images) == len(expected)
    assert not references.scripts and not references.stylesheets
    assert all((tmp_path / name).is_file() for name in references.images)
    assert "Placeholder parameters" in html and "SDR sRGB preview" in html
    assert "25%-duty" in html and "not micrographs" in html
    assert 'href="memc_trace.json"' in html
    assert "cannot demonstrate perceived smoothness" in html


def test_memc_gallery_compares_different_positions_at_matching_output_time():
    profile = load_profile("generic_woled")
    repeated, repeat_ticks = render_memc_pan(profile, 160, 96, "repeat")
    reconstructed, analytic_ticks = render_memc_pan(profile, 160, 96, "analytic")
    assert [tick["source_index"] for tick in repeat_ticks] == [
        0, 0, 0, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5, 5,
    ]
    for repeated_tick, analytic_tick in zip(repeat_ticks, analytic_ticks):
        for key in ("output_pts", "source_index", "source_pts", "phase"):
            assert repeated_tick[key] == analytic_tick[key]
    assert repeat_ticks[MEMC_SNAPSHOT_INDEX]["kind"] == "repeated"
    assert analytic_ticks[MEMC_SNAPSHOT_INDEX]["kind"] == "interpolated"
    assert analytic_ticks[MEMC_SNAPSHOT_INDEX]["fallback_fraction"] == 0
    assert np.max(np.abs(reconstructed - repeated)) > 90
    # At the known intermediate phase the model creates a displaced position,
    # rather than merely changing metadata or crossfading two source pictures.
    x = np.arange(160)
    def centroid(rgb):
        weight = np.maximum(rgb[..., 0] - 2, 0).sum(axis=0)
        return (weight * x).sum() / weight.sum()
    assert centroid(reconstructed) - centroid(repeated) == pytest.approx(8, abs=.3)
    trace = memc_position_trace(repeat_ticks)
    assert Fraction(trace[MEMC_SNAPSHOT_INDEX]["analytic_position_px"]) == 88


def test_column_captions_stay_inside_their_tv(tmp_path):
    from sim.gallery import Row, contact_sheet

    width = 140
    tile = np.zeros((24, width, 3), np.float32)
    contact_sheet(
        tmp_path / "sheet.png",
        "Caption fit",
        [
            Row(
                "row",
                "short note",
                [tile, tile, tile, tile],
                100.0,
                [
                    "RGB stripes / synthetic",
                    "RGB stripes / synthetic",
                    "R/W/B/G + white allocation / synthetic",
                    "Staggered triangular RGB / synthetic",
                ],
            )
        ],
    )
    image = np.asarray(Image.open(tmp_path / "sheet.png"))
    gap, header, row_label = 12, 104, 46
    y0 = header + row_label + tile.shape[0]
    y1 = image.shape[0] - 28
    background = np.array([0x11, 0x17, 0x1E], dtype=np.uint8)
    for index in range(3):
        gutter = gap + (index + 1) * width + index * gap
        assert np.all(image[y0:y1, gutter : gutter + gap] == background)
