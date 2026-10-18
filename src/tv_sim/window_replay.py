"""Opt-in, per-window forward fits; never consulted by ordinary rendering.

The P model scales internal drive and all nit-valued capacities together.
The source amplitude is a separate, fixed experimental condition. Targets
appear ONLY in the final-output residual, never as another limiter or gain.
Each trial runs the original display pipeline, with fresh history per trial
and shared history across black pre-roll, settling and the measured hold.
These independent fits do not identify electrical parameters or a TV model.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path

import numpy as np

from tv_sim import profile as profiles
from tv_sim.abl_dynamics import ABLDynamicsConfig, reject_fit_composition
from tv_sim.color import luminance, pq_oetf
from tv_sim.frame import Frame
from tv_sim.load import demand_apl
from tv_sim.pipeline import Pipeline
from tv_sim.profile import TVProfile
from tv_sim.provenance import ProvenanceError, load_provenance, lookup_measurement
from tv_sim.zone_temporal import ZoneTemporalConfig

MODEL = "per_window_normalized_drive_v1"
STATISTIC = "max_center_over_hold_frame_outputs"


def _reject_zone_fit(config: ZoneTemporalConfig | None) -> None:
    """Schema-1 fits lack zone-history conditions and cannot own that state."""
    if config is not None and config.active:
        raise ValueError("M9 schema-1 fits cannot compose with active zone temporal dynamics")


def _finite(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class ReplayConditions:
    """PQ/BT.709 source: level is max-channel nits, color has max component 1.

    Durations must be whole display ticks. Black pre-roll is mandatory so
    the pipeline's settled-first-frame convention cannot erase the onset.
    Hold samples use the pipeline's configured temporal exposure model.
    """

    level_nits: float
    color_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)
    settle_ms: float = 1000.0 / 6.0
    hold_ms: float = 1000.0 / 6.0
    frame_time_ms: float = 1000.0 / 60.0
    pre_roll_ms: float = 1000.0 / 60.0

    def __post_init__(self):
        if not _finite(self.level_nits) or not 0 < self.level_nits <= 10000:
            raise ProvenanceError("level_nits must be in (0, 10000] for PQ")
        if (
            not isinstance(self.color_rgb, (tuple, list))
            or len(self.color_rgb) != 3
            or not all(_finite(v) and 0 <= v <= 1 for v in self.color_rgb)
            or max(self.color_rgb) != 1
        ):
            raise ProvenanceError("color_rgb needs three linear BT.709 components in [0, 1], max 1")
        if not _finite(self.frame_time_ms) or self.frame_time_ms <= 0:
            raise ProvenanceError("frame_time_ms must be positive and finite")
        for field, minimum in (("settle_ms", 0), ("hold_ms", 1), ("pre_roll_ms", 1)):
            duration = getattr(self, field)
            if not _finite(duration) or duration < 0:
                raise ProvenanceError(f"{field} must be finite and nonnegative")
            ticks = duration / self.frame_time_ms
            if ticks < minimum or not math.isclose(ticks, round(ticks), abs_tol=1e-8, rel_tol=0):
                raise ProvenanceError(f"{field} must be whole frame ticks (minimum {minimum})")

    def ticks(self, field: str) -> int:
        return round(getattr(self, field) / self.frame_time_ms)


def measurement_conditions(
    profile: TVProfile, conditions: ReplayConditions, width: int, height: int
) -> dict:
    """Canonical matching fields, also usable when making synthetic records.

    Unknown fields may be assumed only with exploratory=True; a known
    conflicting field always fails, including a white versus colored sweep.
    Other source metadata is retained without claiming it was matched.
    """
    return {
        **_source_conditions(conditions, width, height),
        "ambient_lux": profile.ambient.lux,
        "viewing_angle_deg": profile.panel.viewing_angle_deg,
    }


def _source_conditions(conditions: ReplayConditions, width: int, height: int) -> dict:
    return {
        "requested_window_nits": conditions.level_nits,
        "source_encoding": "pq",
        "source_rgb_primaries": "bt709",
        "stimulus": (
            "neutral_white_window_on_black"
            if list(conditions.color_rgb) == [1, 1, 1]
            else "rgb_window_on_black"
        ),
        "stimulus_rgb_code": pq_oetf(
            np.array(conditions.color_rgb) * conditions.level_nits
        ).tolist(),
        "pattern_aspect_ratio": width / height,
        "position_xy_fraction": [0.5, 0.5],
        "refresh_hz": 1000.0 / conditions.frame_time_ms,
        "dwell_s": (conditions.settle_ms + conditions.hold_ms) / 1000.0,
        "settling_s": conditions.settle_ms / 1000.0,
        "hold_s": conditions.hold_ms / 1000.0,
        "hold_statistic": STATISTIC,
        "prior_pattern_and_duration": {
            "stimulus": "black",
            "duration_s": conditions.pre_roll_ms / 1000.0,
        },
    }


def _equal(left, right) -> bool:
    if _finite(left) and _finite(right):
        return math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-7)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    return type(left) is type(right) and left == right


def _match(recorded: dict, requested: dict, exploratory: bool) -> dict:
    assumptions = {}
    for key, value in requested.items():
        original = recorded.get(key, "NR")
        if original == "NR":
            if not exploratory:
                raise ProvenanceError(
                    f"condition {key} is NR; explicit exploratory replay is required"
                )
            assumptions[key] = {"recorded": "NR", "value": value, "evidence": "P"}
        elif not _equal(original, value):
            raise ProvenanceError(
                f"condition {key} mismatch: recorded {original!r}, requested {value!r}"
            )
    return assumptions


def _fingerprint(profile: TVProfile) -> str:
    return sha256(json.dumps(asdict(profile), sort_keys=True, allow_nan=False).encode()).hexdigest()


def drive_profile(profile: TVProfile, scale: float) -> TVProfile:
    """Transient P capacities for the normalized internal-drive model.

    Preserve every zero sentinel. No source/output/ambient scale, optical
    shape, time constant or dimensionless limiter parameter is fitted.
    """
    if not _finite(scale) or scale <= 0:
        raise ProvenanceError("drive scale must be positive and finite")
    return replace(
        profile,
        input=replace(profile.input, eotf="pq"),
        backlight=replace(
            profile.backlight,
            peak_nits=profile.backlight.peak_nits * scale,
            floor_nits=profile.backlight.floor_nits * scale,
        ),
        hdr=replace(
            profile.hdr,
            **{
                key: getattr(profile.hdr, key) * scale
                for key in (
                    "panel_peak_nits",
                    "abl_full_field_nits",
                    "abl_reference_nits",
                    "abl_power_budget_nits",
                )
            },
        ),
        temporal=replace(
            profile.temporal, overdrive_ceiling_nits=profile.temporal.overdrive_ceiling_nits * scale
        ),
    )


@dataclass
class WindowReplay:
    frame: Frame
    luminance_nits: float
    center_trace_nits: list[float]
    area_fraction_actual: float
    requested_apl_nits: float
    processed_request_apl_nits: float
    drive_apl_nits: float


def _grid(profile: TVProfile, width: int, height: int) -> None:
    _raster_grid(width, height)
    if profile.processing.scale_factor != 1 or profile.temporal.motion_px_per_frame != 0:
        raise ProvenanceError("static replay requires scale_factor=1 and motion_px_per_frame=0")


def _raster_grid(width: int, height: int) -> None:
    if any(type(v) is not int or v < 4 for v in (width, height)):
        raise ProvenanceError("window raster width and height must be integers >= 4")


def _window_size(width: int, height: int, fraction: float) -> tuple[int, int]:
    if not _finite(fraction) or not 0 < fraction <= 1:
        raise ProvenanceError("window fraction must be in (0, 1]")
    h = min(height, math.ceil(height * math.sqrt(fraction)))
    w = min(width, math.ceil(width * math.sqrt(fraction)))
    if min(h, w) < 2:
        raise ProvenanceError(
            "window must span at least two pixels per axis; increase raster resolution"
        )
    return w, h


def _raster_assumption(fraction: float, actual: float, exploratory: bool):
    if math.isclose(fraction, actual, rel_tol=0, abs_tol=1e-12):
        return "not_applicable"
    if not exploratory:
        raise ProvenanceError(
            "rasterized fraction differs from target fraction; increase resolution "
            "or explicitly select exploratory replay"
        )
    return {"nominal_fraction": fraction, "actual_fraction": actual, "evidence": "P"}


def _pattern(width: int, height: int, fraction: float, conditions: ReplayConditions):
    # Round upward so a supported lower endpoint cannot rasterize below support.
    w, h = _window_size(width, height, fraction)
    y, x = (height - h) // 2, (width - w) // 2
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    rgb[y : y + h, x : x + w] = np.array(conditions.color_rgb) * conditions.level_nits
    return pq_oetf(rgb), h * w / (height * width), demand_apl(rgb)


def replay_window(
    profile: TVProfile,
    fraction: float,
    conditions: ReplayConditions,
    drive_scale: float = 1.0,
    *,
    width: int = 160,
    height: int = 90,
    abl_dynamics: ABLDynamicsConfig | None = None,
    zone_temporal: ZoneTemporalConfig | None = None,
) -> WindowReplay:
    """Forward model for one specified experiment; no target enters this call.

    A new pipeline per experiment, one shared pipeline for all its ticks.
    The metric is maximum center luminance during the hold, matching M8's
    peak-center metric. The returned frame is the final hold frame.
    """
    reject_fit_composition(abl_dynamics)
    _reject_zone_fit(zone_temporal)
    _grid(profile, width, height)
    encoded, actual, apl = _pattern(width, height, fraction, conditions)
    pipeline = Pipeline(drive_profile(profile, drive_scale))
    source = pipeline.prepare_content(encoded)
    processed_apl = demand_apl(source.rgb)
    drive = Frame(source.rgb * np.float32(drive_scale))
    black = pipeline.prepare_content(np.zeros_like(encoded))
    for _ in range(conditions.ticks("pre_roll_ms")):
        pipeline.display_content(black, frame_time_ms=conditions.frame_time_ms)
    trace = []
    for index in range(conditions.ticks("settle_ms") + conditions.ticks("hold_ms")):
        frame = pipeline.display_content(drive, frame_time_ms=conditions.frame_time_ms)
        if index >= conditions.ticks("settle_ms"):
            # Central one/two pixels on each axis, symmetric for even rasters.
            center = frame.rgb[
                (height - 1) // 2 : height // 2 + 1, (width - 1) // 2 : width // 2 + 1
            ]
            trace.append(float(np.mean(luminance(center), dtype=np.float64)))
    if not all(math.isfinite(v) for v in trace):
        raise ProvenanceError("forward replay produced nonfinite luminance")
    return WindowReplay(frame, max(trace), trace, actual, apl, processed_apl, demand_apl(drive.rgb))


def _solve(profile, fraction, conditions, target, width, height, atol, rtol, max_iterations):
    def trial(scale):
        return replay_window(profile, fraction, conditions, scale, width=width, height=height)

    tolerance = max(atol, rtol * target)
    low, high = 1e-6, 1e4
    lo, hi = trial(low), trial(high)
    if lo.luminance_nits > target + tolerance or hi.luminance_nits < target - tolerance:
        raise ProvenanceError(f"target {target} nits unreachable in drive scale [{low}, {high}]")
    if abs(lo.luminance_nits - target) <= tolerance:
        return low, lo, 2
    # Geometric midpoint avoids spending iterations on irrelevant decades.
    for index in range(max_iterations):
        scale = math.sqrt(low * high)
        result = trial(scale)
        if abs(result.luminance_nits - target) <= tolerance:
            return scale, result, index + 3
        if result.luminance_nits < target:
            low = scale
        else:
            high = scale
    raise ProvenanceError(f"fit did not converge within {max_iterations} iterations")


def fit_windows(
    profile: TVProfile,
    provenance: dict,
    source_dataset_id: str,
    fitted_dataset_id: str,
    *,
    conditions: ReplayConditions,
    fractions: list[float] | None = None,
    exploratory: bool = False,
    width: int = 160,
    height: int = 90,
    atol_nits: float = 0.01,
    rtol: float = 1e-5,
    max_iterations: int = 60,
    abl_dynamics: ABLDynamicsConfig | None = None,
    zone_temporal: ZoneTemporalConfig | None = None,
) -> dict:
    """Fit independent P drive scales using strict M8 measurement lookup.

    NR source nodes remain in the embedded source snapshot. Default fits
    skip them; an explicitly queried gap uses M8 interpolation and stays P.
    There is no interpolation of fitted drive scales or arbitrary content.
    """
    reject_fit_composition(abl_dynamics)
    _reject_zone_fit(zone_temporal)
    _grid(profile, width, height)
    if provenance.get("profile") != profile.name:
        raise ProvenanceError("source sidecar must belong to the baseline profile")
    if (
        not isinstance(fitted_dataset_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", fitted_dataset_id)
        or fitted_dataset_id in provenance.get("datasets", {})
        or fitted_dataset_id == profile.name
    ):
        raise ProvenanceError(
            "fitted dataset ID must be new and separate from source datasets and profile"
        )
    if (
        not _finite(atol_nits)
        or atol_nits <= 0
        or not _finite(rtol)
        or rtol < 0
        or type(max_iterations) is not int
        or max_iterations < 1
    ):
        raise ProvenanceError(
            "fit tolerances/iteration count must be finite and positive (rtol >= 0)"
        )
    dataset = provenance.get("datasets", {}).get(source_dataset_id)
    if not isinstance(dataset, dict):
        raise ProvenanceError(f"unknown dataset {source_dataset_id!r}")
    if fractions is None:
        fractions = [
            n["fraction"] for n in dataset.get("nodes", []) if n.get("luminance_nits") != "NR"
        ]
    if not fractions:
        raise ProvenanceError(
            "no supported numeric window nodes; unlocated peaks cannot be replayed"
        )
    # Lookup every target before running the solver, including actual support.
    targets = [lookup_measurement(provenance, source_dataset_id, f) for f in fractions]
    if any(a.fraction >= b.fraction for a, b in zip(targets, targets[1:])):
        raise ProvenanceError("fit fractions must be unique and increasing")
    requested = measurement_conditions(profile, conditions, width, height)
    assumptions = _match(dataset["conditions"], requested, exploratory)
    raster_assumptions = []
    for target in targets:
        _, actual, _ = _pattern(width, height, target.fraction, conditions)
        lookup_measurement(provenance, source_dataset_id, actual)
        raster_assumptions.append(_raster_assumption(target.fraction, actual, exploratory))
    nodes = []
    for target, raster_assumption in zip(targets, raster_assumptions):
        scale, result, evaluations = _solve(
            profile,
            target.fraction,
            conditions,
            target.luminance_nits,
            width,
            height,
            atol_nits,
            rtol,
            max_iterations,
        )
        nodes.append(
            {
                "fraction": target.fraction,
                "raster_assumption": raster_assumption,
                "target": {
                    "luminance_nits": target.luminance_nits,
                    "evidence": target.evidence,
                    "interpolated": target.interpolated,
                },
                "drive_scale": {"value": scale, "evidence": "P"},
                "simulation": {
                    "luminance_nits": result.luminance_nits,
                    "evidence": "D",
                    "residual_nits": result.luminance_nits - target.luminance_nits,
                    "center_trace_nits": result.center_trace_nits,
                    "area_fraction_actual": result.area_fraction_actual,
                    "requested_apl_nits": result.requested_apl_nits,
                    "processed_request_apl_nits": result.processed_request_apl_nits,
                    "drive_apl_nits": result.drive_apl_nits,
                    "forward_evaluations": evaluations,
                },
            }
        )
    return {
        "schema_version": 1,
        "kind": "window_drive_fit",
        "dataset_id": fitted_dataset_id,
        "source_dataset_id": source_dataset_id,
        "baseline_profile": profile.name,
        "baseline_sha256": _fingerprint(profile),
        "model": {"name": MODEL, "evidence": "P"},
        "calibrated_profile_fit": "NR",
        "timed_sustained_trace": "NR",
        "source_provenance": {
            "schema_version": provenance["schema_version"],
            "profile": profile.name,
            "datasets": {source_dataset_id: deepcopy(dataset)},
        },
        "conditions": {**asdict(conditions), "color_rgb": list(conditions.color_rgb)},
        "matching_fields": requested,
        "condition_policy": "exploratory" if exploratory else "require_matched",
        "assumptions": assumptions,
        "unmatched_source_conditions": "NR",
        "raster": {"width": width, "height": height, "rounding": "ceil_centered", "evidence": "P"},
        "solver": {
            "method": "bracketed_geometric_bisection",
            "atol_nits": atol_nits,
            "rtol": rtol,
            "max_iterations": max_iterations,
            "scale_bounds": [1e-6, 1e4],
        },
        "support": {
            "fractions": [t.fraction for t in targets],
            "outside": "reject",
            "interpolation": "none",
        },
        "nodes": nodes,
    }


def _validate_fit(data: dict) -> ReplayConditions:
    """Check persisted identity, evidence, support and source target snapshots."""
    try:
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["kind"] != "window_drive_fit"
            or data["model"] != {"name": MODEL, "evidence": "P"}
            or data["calibrated_profile_fit"] != "NR"
            or data["timed_sustained_trace"] != "NR"
        ):
            raise ProvenanceError("unsupported window fit schema/model/evidence")
        if (
            not isinstance(data["dataset_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", data["dataset_id"])
            or data["dataset_id"] in data["source_provenance"]["datasets"]
            or data["dataset_id"] == data["baseline_profile"]
        ):
            raise ProvenanceError("fitted dataset ID must be separate from its source and baseline")
        if (
            not isinstance(data["baseline_profile"], str)
            or not isinstance(data["baseline_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", data["baseline_sha256"])
            or data["source_provenance"]["profile"] != data["baseline_profile"]
        ):
            raise ProvenanceError("invalid baseline identity")
        conditions = ReplayConditions(**data["conditions"])
        raster = data["raster"]
        width, height = raster["width"], raster["height"]
        _raster_grid(width, height)
        if raster.get("evidence") != "P" or raster.get("rounding") != "ceil_centered":
            raise ProvenanceError("rasterization must retain P model evidence")
        if data["condition_policy"] not in ("exploratory", "require_matched"):
            raise ProvenanceError("unsupported condition policy")
        exploratory = data["condition_policy"] == "exploratory"
        requested = data["matching_fields"]
        # Check independently of an installed baseline, so old fits stay inspectable.
        canonical = _source_conditions(conditions, width, height)
        for key, value in canonical.items():
            if key not in requested or not _equal(requested[key], value):
                raise ProvenanceError(f"fit condition {key} changed")
        for key in ("ambient_lux", "viewing_angle_deg"):
            if not _finite(requested[key]):
                raise ProvenanceError(f"invalid condition {key}")
        source = data["source_provenance"]["datasets"][data["source_dataset_id"]]
        if data["assumptions"] != _match(source["conditions"], requested, exploratory):
            raise ProvenanceError("fit assumption record changed")
        solver = data["solver"]
        if (
            solver["method"] != "bracketed_geometric_bisection"
            or solver["scale_bounds"] != [1e-6, 1e4]
            or not _finite(solver["atol_nits"])
            or solver["atol_nits"] <= 0
            or not _finite(solver["rtol"])
            or solver["rtol"] < 0
            or type(solver["max_iterations"]) is not int
            or solver["max_iterations"] < 1
        ):
            raise ProvenanceError("invalid fit solver record")
        fractions = data["support"]["fractions"]
        if (
            not fractions
            or data["support"]["outside"] != "reject"
            or data["support"]["interpolation"] != "none"
            or fractions != [n["fraction"] for n in data["nodes"]]
            or any(a >= b for a, b in zip(fractions, fractions[1:]))
        ):
            raise ProvenanceError("fit supports only its unique, increasing fitted fractions")
        for node in data["nodes"]:
            target = lookup_measurement(
                data["source_provenance"], data["source_dataset_id"], node["fraction"]
            )
            expected = {
                "luminance_nits": target.luminance_nits,
                "evidence": target.evidence,
                "interpolated": target.interpolated,
            }
            if node["target"] != expected or node["drive_scale"]["evidence"] != "P":
                raise ProvenanceError("fit must preserve target evidence and P drive evidence")
            scale = node["drive_scale"]["value"]
            if not _finite(scale) or not 1e-6 <= scale <= 1e4:
                raise ProvenanceError("invalid fitted drive scale")
            w, h = _window_size(width, height, node["fraction"])
            actual = w * h / (width * height)
            lookup_measurement(data["source_provenance"], data["source_dataset_id"], actual)
            if node["raster_assumption"] != _raster_assumption(
                node["fraction"], actual, exploratory
            ):
                raise ProvenanceError("fit raster assumption changed")
            simulation = node["simulation"]
            if simulation["evidence"] != "D":
                raise ProvenanceError("simulated results must have D evidence under the P model")
            for key in (
                "luminance_nits",
                "residual_nits",
                "area_fraction_actual",
                "requested_apl_nits",
                "processed_request_apl_nits",
                "drive_apl_nits",
            ):
                if not _finite(simulation[key]) or (key != "residual_nits" and simulation[key] < 0):
                    raise ProvenanceError(f"invalid simulation {key}")
            trace = simulation["center_trace_nits"]
            if (
                len(trace) != conditions.ticks("hold_ms")
                or not all(_finite(v) and v >= 0 for v in trace)
                or not _equal(max(trace), simulation["luminance_nits"])
                or not _equal(actual, simulation["area_fraction_actual"])
                or not _equal(
                    simulation["residual_nits"],
                    simulation["luminance_nits"] - target.luminance_nits,
                )
                or abs(simulation["residual_nits"])
                > max(solver["atol_nits"], solver["rtol"] * target.luminance_nits)
            ):
                raise ProvenanceError("inconsistent or unconverged simulation record")
        return conditions
    except (KeyError, TypeError, ValueError, FileNotFoundError, AttributeError) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError(f"invalid window fit: {exc}") from exc


def replay_fit(
    profile: TVProfile,
    data: dict,
    *,
    abl_dynamics: ABLDynamicsConfig | None = None,
    zone_temporal: ZoneTemporalConfig | None = None,
) -> list[WindowReplay]:
    """Explicit replay of the recorded experiments, never arbitrary content."""
    reject_fit_composition(abl_dynamics)
    _reject_zone_fit(zone_temporal)
    conditions = _validate_fit(data)
    if data["baseline_profile"] != profile.name or data["baseline_sha256"] != _fingerprint(profile):
        raise ProvenanceError(
            "fit baseline profile changed; refit instead of silently reusing drives"
        )
    width, height = data["raster"]["width"], data["raster"]["height"]
    _grid(profile, width, height)
    requested = measurement_conditions(profile, conditions, width, height)
    if data["condition_policy"] not in ("exploratory", "require_matched"):
        raise ProvenanceError("unsupported condition policy")
    source = data["source_provenance"]["datasets"][data["source_dataset_id"]]
    assumptions = _match(source["conditions"], requested, data["condition_policy"] == "exploratory")
    if assumptions != data["assumptions"] or not _equal(requested, data["matching_fields"]):
        raise ProvenanceError("fit conditions or assumption record changed")
    results = []
    for node in data["nodes"]:
        _, actual, _ = _pattern(width, height, node["fraction"], conditions)
        lookup_measurement(data["source_provenance"], data["source_dataset_id"], actual)
        result = replay_window(
            profile,
            node["fraction"],
            conditions,
            node["drive_scale"]["value"],
            width=width,
            height=height,
        )
        target = node["target"]["luminance_nits"]
        tolerance = max(data["solver"]["atol_nits"], data["solver"]["rtol"] * target)
        if abs(result.luminance_nits - target) > tolerance:
            raise ProvenanceError("replayed drive no longer matches target; refit this experiment")
        results.append(result)
    return results


def save_fit(path: Path, data: dict) -> None:
    """Write a NEW .fit.json outside runtime profiles; never replace a baseline."""
    _validate_fit(data)
    path = Path(path)
    if (
        not path.name.endswith(".fit.json")
        or profiles.PROFILES_DIR.resolve() in path.resolve().parents
    ):
        raise ProvenanceError("write fitted datasets as .fit.json outside src/tv_sim/profiles")
    payload = json.dumps(data, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def load_fit(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProvenanceError(f"cannot read fit {path}: {exc}") from exc
    _validate_fit(data)
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Opt-in M8 window replay / P internal-drive fitting."
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument(
        "--dataset-id", required=True, help="New fitted dataset ID, distinct from the source"
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="New .fit.json path outside src/tv_sim/profiles"
    )
    parser.add_argument("--fractions", type=float, nargs="+", default=None)
    parser.add_argument(
        "--level-nits", type=float, required=True, help="Requested PQ max-channel nits"
    )
    parser.add_argument("--color-rgb", type=float, nargs=3, default=(1.0, 1.0, 1.0))
    parser.add_argument("--settle-ms", type=float, required=True)
    parser.add_argument("--hold-ms", type=float, required=True)
    parser.add_argument("--pre-roll-ms", type=float, default=1000.0 / 60.0)
    parser.add_argument("--frame-time-ms", type=float, default=1000.0 / 60.0)
    parser.add_argument(
        "--exploratory",
        action="store_true",
        help="Explicit P assumptions for NR conditions; known mismatches still fail",
    )
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=90)
    args = parser.parse_args(argv)
    try:
        profile = profiles.load_profile(args.profile)
        conditions = ReplayConditions(
            args.level_nits,
            tuple(args.color_rgb),
            args.settle_ms,
            args.hold_ms,
            args.frame_time_ms,
            args.pre_roll_ms,
        )
        result = fit_windows(
            profile,
            load_provenance(args.profile),
            args.source_dataset,
            args.dataset_id,
            conditions=conditions,
            fractions=args.fractions,
            exploratory=args.exploratory,
            width=args.width,
            height=args.height,
        )
        save_fit(args.out, result)
    except (ProvenanceError, FileNotFoundError, FileExistsError) as exc:
        parser.error(str(exc))
    print(
        f"Window fit OK: {result['dataset_id']}, {len(result['nodes'])} window(s); drive model P, calibration NR"
    )


if __name__ == "__main__":
    main()
