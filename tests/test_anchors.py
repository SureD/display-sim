"""Published anchors stay inside the research note, and scoring is explicit."""

import re
from pathlib import Path

from sim.anchors import ANCHORS, POINT_RELATIVE_TOLERANCE, Anchor, score_reference

RESEARCH = Path("research/m4-reference-ranges.md")


def test_scored_numbers_are_transcribed_from_the_research_note():
    text = RESEARCH.read_text(encoding="utf-8").replace(",", "")
    assert "NR" in text
    for anchors in ANCHORS.values():
        for anchor in anchors:
            for bound in (anchor.low, anchor.high):
                if bound is None:
                    continue
                token = f"{bound:.10g}"
                assert token in text, token
            for token in re.findall(r"\d+(?:\.\d+)?", f"{anchor.published} {anchor.note}"):
                assert token in text, (anchor.metric, token)


def test_envelope_point_and_missing_references():
    inside = Anchor("ten", "window:0.1", "envelope", ("V1",), "x", low=1300.0, high=1774.0)
    point = Anchor("peak", "window:0.1", "point", ("Q1",), "977 nits", low=977.0)
    missing = Anchor("gap", "window:0.02", "nr", (), "NR")
    dark = Anchor("ansi", "ansi.contrast_ratio", "unmeasurable", ("W2",), "unmeasurable")
    assert score_reference(1700.0, inside) == "in"
    assert score_reference(1299.0, inside) == "out"
    assert score_reference(977.0 * (1.0 + POINT_RELATIVE_TOLERANCE), point) == "in"
    assert score_reference(977.0 * (1.0 + POINT_RELATIVE_TOLERANCE) + 1.0, point) == "out"
    assert score_reference(100.0, missing) == "NR"
    assert score_reference(None, dark) == "in"
    assert score_reference(500.0, dark) == "out"
    assert score_reference(None, inside) == "out"
