"""Published comparison anchors for the M4 harness.

Every numeric bound is transcribed from ``research/m4-reference-ranges.md``.
Cells that document has no verified figure for are ``NR``. This module does
not add luminances, ratios, or uncertainty bars of its own.

A single published sample is an anchor, not a range. ``POINT_RELATIVE_TOLERANCE``
is a project rule for scoring those anchors in ``reports/comparison.md``. It
is not a publisher tolerance and it is not in the research note.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Project scoring rule for an isolated published number. Not from the research note.
POINT_RELATIVE_TOLERANCE = 0.05

SOURCES: dict[str, str] = {
    "V1": "AVForums Samsung QN95B review",
    "V2": "FlatpanelsHD Sony X95K review",
    "V3": "TFTCentral Cooler Master GP2711 review (monitor, not a TV)",
    "V4": "RTINGS Samsung QN90B review",
    "I1": "HDTVTest LG 55UH770V review",
    "I2": "HDTVTest LG 49UB850V review",
    "I3": "RTINGS LG NANO85 2021 review",
    "W1": "TFTCentral LG 42C2 review",
    "W2": "HDTVTest LG 55EG960V review",
    "W3": "TechSpot LG C2 42-inch review",
    "Q1": "AVForums Samsung S95B review",
    "Q2": "Sound & Vision Samsung 65 S95B test bench",
    "Q3": "RTINGS Samsung S95B review",
}


@dataclass(frozen=True)
class Anchor:
    """One sim metric compared with the research note.

    ``kind`` is ``envelope`` (inclusive ``low``..``high``), ``point`` (``low``
    is the published sample), ``unmeasurable`` (published black at the meter
    floor, no finite ratio), or ``nr`` (no numeric reference to score).
    """

    metric: str
    sim_key: str
    kind: str
    sources: tuple[str, ...]
    published: str
    note: str = ""
    low: float | None = None
    high: float | None = None


def _windows(prefix_note: str = "") -> tuple[Anchor, ...]:
    """HDR window rows. Callers overwrite the cells that have numbers."""

    rows = []
    for fraction, label in (
        (0.02, "2%"),
        (0.10, "10%"),
        (0.25, "25%"),
        (0.50, "50%"),
        (1.0, "100%"),
    ):
        rows.append(
            Anchor(
                metric=f"HDR window {label} peak",
                sim_key=f"window:{fraction}",
                kind="nr",
                sources=(),
                published="NR",
                note=prefix_note,
            )
        )
    rows.append(
        Anchor(
            metric="full-field sustained",
            sim_key="window:1.0",
            kind="nr",
            sources=(),
            published="NR",
            note="No duration-qualified sustained value. The sim repeats the static full-field reading.",
        )
    )
    return tuple(rows)


def _temporal(sources: tuple[str, ...], note: str) -> Anchor:
    return Anchor(
        metric="temporal-only moving-edge width",
        sim_key="temporal_blur_px",
        kind="nr",
        sources=sources,
        published="NR",
        note=note,
    )


_VA_WINDOWS = list(_windows())
_VA_WINDOWS[1] = Anchor(
    metric="HDR window 10% peak",
    sim_key="window:0.1",
    kind="envelope",
    low=1300.0,
    high=1774.0,
    sources=("V1", "V2"),
    published="~1,300–1,774 nits",
    note="V1 is 1,774 nits at 10% (QN95B HDR Filmmaker). V2 is ~1,300 nits at 10% (X95K). Not a matched pair.",
)
_VA_WINDOWS[4] = Anchor(
    metric="HDR window 100% peak",
    sim_key="window:1.0",
    kind="envelope",
    low=591.0,
    high=650.0,
    sources=("V1", "V2"),
    published="591–almost 650 nits",
    note="Upper end uses the research wording almost 650, scored as 650. Not a timed sustained reading.",
)

_IPS_WINDOWS = list(_windows("I1 reports a 455-nit peak with no usable window size, so no cell is filled."))

_WOLED_WINDOWS = list(_windows())
_WOLED_WINDOWS[0] = Anchor(
    metric="HDR window 2% peak",
    sim_key="window:0.02",
    kind="nr",
    sources=("W1",),
    published="NR",
    note="W1 says small windows through 10% reach ~717 nits but does not tabulate 2%.",
)
_WOLED_WINDOWS[1] = Anchor(
    metric="HDR window 10% peak",
    sim_key="window:0.1",
    kind="envelope",
    low=667.0,
    high=717.0,
    sources=("W1", "W3"),
    published="667–717 nits",
    note="W1 ~717 nits (42C2 HDR Standard, DTM off; reporting envelope also cited as ~707–717). W3 667 nits at 10%. Different setups.",
)
_WOLED_WINDOWS[4] = Anchor(
    metric="HDR window 100% peak",
    sim_key="window:1.0",
    kind="nr",
    sources=("W1", "W2"),
    published="NR",
    note="No HDR full-white cell. SDR max full-white readings (C2 ~170 nits, EG960V 149 nits) are a different protocol and are not scored.",
)

_QD_WINDOWS = list(_windows())
_QD_WINDOWS[1] = Anchor(
    metric="HDR window 10% peak",
    sim_key="window:0.1",
    kind="point",
    low=977.0,
    sources=("Q1",),
    published="977 nits",
    note="S95B HDR Filmmaker, firmware 1211, 10% window. A 1,004-nit peak without a stated area is excluded.",
)
_QD_WINDOWS[4] = Anchor(
    metric="HDR window 100% peak",
    sim_key="window:1.0",
    kind="point",
    low=199.0,
    sources=("Q1",),
    published="199 nits",
    note="Same S95B Filmmaker setup as the 10% anchor. Not a timed sustained reading.",
)

ANCHORS: dict[str, tuple[Anchor, ...]] = {
    "generic_va_fald_miniled": (
        Anchor(
            metric="ANSI contrast",
            sim_key="ansi.contrast_ratio",
            kind="nr",
            sources=("V1", "V3"),
            published="NR",
            note="No accessible TV ANSI ratio. QN95B ANSI black is 0.048 nits without a same-pattern white. GP2711 ~3,598–3,800:1 is a monitor-only supporting anchor and is not scored.",
        ),
        Anchor(
            metric="sequential contrast",
            sim_key="on_off.contrast_ratio",
            kind="nr",
            sources=("V1",),
            published="NR",
            note="No published full-on/full-off ratio in the selected TV sources.",
        ),
        *_VA_WINDOWS,
        _temporal(("V4",), "Numeric TV GtG and MPRT are NR. QN90B response notes are qualitative."),
    ),
    "generic_ips_edge": (
        Anchor(
            metric="ANSI contrast",
            sim_key="ansi.contrast_ratio",
            kind="envelope",
            low=764.0,
            high=1290.0,
            sources=("I1", "I2"),
            published="~764–1,290:1",
            note="Derived at 120-nit white with dimming off (0.157 nits → ~764:1, 0.093 nits → ~1,290:1). The harness uses PQ white and this profile's edge dimming, so membership is a plausibility check.",
        ),
        Anchor(
            metric="sequential contrast",
            sim_key="on_off.contrast_ratio",
            kind="nr",
            sources=("I1",),
            published="NR",
            note="Full-black raster 0.066 nits must not replace the ANSI denominator. No sequential ratio is scored.",
        ),
        *_IPS_WINDOWS,
        _temporal(("I3",), "Numeric GtG, MPRT, and pulse duty are NR."),
    ),
    "generic_woled": (
        Anchor(
            metric="ANSI contrast",
            sim_key="ansi.contrast_ratio",
            kind="unmeasurable",
            sources=("W2",),
            published="unmeasurable (0-nit black)",
            note="EG960V returned a 0-nit meter reading on full black and 4×4 ANSI. No finite ratio.",
        ),
        Anchor(
            metric="sequential contrast",
            sim_key="on_off.contrast_ratio",
            kind="unmeasurable",
            sources=("W2",),
            published="unmeasurable (0-nit black)",
            note="Same 0-nit full-black reading. A finite sim ratio would disagree with that meter result.",
        ),
        *_WOLED_WINDOWS,
        _temporal(
            ("W1",),
            "C2 GtG 0.3 ms best / 0.6 ms mean is not pursuit width and is not scored against the edge metric.",
        ),
    ),
    "generic_qdoled": (
        Anchor(
            metric="ANSI contrast",
            sim_key="ansi.contrast_ratio",
            kind="nr",
            sources=("Q2",),
            published="NR",
            note="Q2 is sequential, not ANSI. Numeric ANSI is NR.",
        ),
        Anchor(
            metric="sequential contrast",
            sim_key="on_off.contrast_ratio",
            kind="unmeasurable",
            sources=("Q2",),
            published="unmeasurable (0.000-nit black)",
            note="S95B HDR10 Filmmaker full-on/full-off contrast was reported unmeasurable.",
        ),
        *_QD_WINDOWS,
        _temporal(("Q3",), "Accessible numeric GtG and MPRT are NR."),
    ),
}


def score_reference(sim: float | None, anchor: Anchor) -> str:
    """``in``, ``out``, or ``NR`` for one anchor."""

    if anchor.kind == "nr":
        return "NR"
    if anchor.kind == "unmeasurable":
        return "in" if sim is None else "out"
    if sim is None or isinstance(sim, bool) or not isinstance(sim, (int, float)):
        return "out"
    value = float(sim)
    if not math.isfinite(value):
        return "out"
    if anchor.kind == "envelope":
        if anchor.low is None or anchor.high is None:
            raise ValueError(f"{anchor.metric} envelope is missing a bound")
        return "in" if anchor.low <= value <= anchor.high else "out"
    if anchor.kind == "point":
        if anchor.low is None:
            raise ValueError(f"{anchor.metric} point anchor is missing a value")
        span = abs(anchor.low) * POINT_RELATIVE_TOLERANCE
        return "in" if abs(value - anchor.low) <= span + 1e-6 else "out"
    raise ValueError(f"unknown anchor kind {anchor.kind!r}")


def sim_metric(metrics: dict, sim_key: str) -> float | None:
    """Pull one harness metric. Window keys are ``window:<fraction>``."""

    if sim_key.startswith("window:"):
        fraction = float(sim_key.split(":", 1)[1])
        for row in metrics["windows"]:
            if abs(float(row["area_fraction_requested"]) - fraction) < 1e-9:
                return row["peak_nits"]
        raise KeyError(sim_key)
    if sim_key == "temporal_blur_px":
        return metrics["mprt"]["as_configured"]["temporal_blur_px"]
    node: object = metrics
    for part in sim_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(sim_key)
        node = node[part]
    if node is None:
        return None
    return float(node)


def comparison_rows(profile: str, metrics: dict) -> list[dict[str, str]]:
    """Rows for one profile. Unknown profiles get a single NR line."""

    anchors = ANCHORS.get(profile)
    if not anchors:
        return [
            {
                "profile": profile,
                "metric": "(no published rows)",
                "sim": "",
                "published": "NR",
                "flag": "NR",
                "sources": "",
                "note": "This profile has no rows in sim/anchors.py.",
            }
        ]
    rows = []
    for anchor in anchors:
        sim = sim_metric(metrics, anchor.sim_key)
        rows.append(
            {
                "profile": profile,
                "metric": anchor.metric,
                "sim": _format_sim(sim),
                "published": anchor.published,
                "flag": score_reference(sim, anchor),
                "sources": ",".join(anchor.sources),
                "note": anchor.note,
            }
        )
    return rows


def _format_sim(value: float | None) -> str:
    if value is None:
        return "undefined"
    return f"{float(value):.6g}"


def render_comparison(profile_metrics: dict[str, dict]) -> str:
    """Markdown report. ``profile_metrics`` is the harness ``profiles`` object."""

    lines = [
        "# Sim vs published anchors",
        "",
        "Generated by `python3 -m sim validate`. The four `generic_*` profiles are placeholders, not emulations of the reviewed sets.",
        "",
        "Numbers in the Published column are transcribed from `research/m4-reference-ranges.md`. "
        "An envelope is `in` when the simulator value is inside those bounds, inclusive. "
        f"A single published sample is `in` when the simulator is within {POINT_RELATIVE_TOLERANCE:.0%} relative. "
        "That percentage is a project scoring rule, not a publisher tolerance. "
        "`NR` means the research note has no numeric value for that protocol, or the only cited figure is a different device class and is not scored. "
        "`out` means a numeric reference was scored and the simulator missed it. "
        "`undefined` is a simulator black at or below the reporting floor (no finite contrast).",
        "",
        "| Profile | Metric | Sim | Published | Flag | Sources | Note |",
        "|---|---|---:|---|---|---|---|",
    ]
    for name, metrics in profile_metrics.items():
        for row in comparison_rows(name, metrics):
            lines.append(
                "| {profile} | {metric} | {sim} | {published} | {flag} | {sources} | {note} |".format(
                    **{key: _cell(value) for key, value in row.items()}
                )
            )
    lines.extend(["", "## Sources", ""])
    used: set[str] = set()
    for name in profile_metrics:
        for anchor in ANCHORS.get(name, ()):
            used.update(anchor.sources)
    for source_id in sorted(used):
        lines.append(f"- **{source_id}**: {SOURCES[source_id]}")
    lines.append("")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
