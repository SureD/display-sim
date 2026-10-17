"""History-aware P OLED capacity experiments, separate from the M4 harness.

One pipeline owns each complete trial, including black pre-roll. Synthetic
settings are read only on explicit invocation; ordinary rendering never reads
this protocol. The trace records D results under a P model, never measurements.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
from hashlib import sha256
from html import escape
import json
import math
import os
from pathlib import Path
import re
import tempfile

import numpy as np
from PIL import Image, ImageDraw

from sim.color import luminance, pq_oetf
from sim.frame import Frame
from sim.load import demand_apl
from sim.pipeline import Pipeline
from sim.profile import TVProfile, available_profiles, load_profile, profile_path
from sim.stages.encode import encode_frame

DEFAULT_PROTOCOL = Path(__file__).resolve().parents[1] / "research/measurements/oled_dynamics_synthetic_v1.json"
PROTOCOL_SCHEMA = 1
_TOP = {"schema_version", "protocol_id", "parameter_status", "evidence", "settings",
        "demonstration", "unavailable", "trials", "notes"}
_SETTINGS = {"width", "height", "level_nits", "input_eotf", "primaries", "output_fps",
             "preview_reference_nits", "onset_interval_s", "late_interval_s", "ambient_lux",
             "bfi_duty", "overdrive_gain", "motion_px_per_frame", "horizontal_deg", "vertical_deg"}
_UNAVAILABLE = {"measured_attack_ms", "measured_release_ms", "thermal_controller",
                "static_image_controller", "calibrated_profile_fit"}


def _finite(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _fraction(value, name: str, *, zero: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Fraction)):
        raise ValueError(f"{name} must be a positive rational number")
    try:
        number = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite rational number") from exc
    if number < 0 or (number == 0 and not zero):
        raise ValueError(f"{name} must be {'nonnegative' if zero else 'positive'}")
    return number


def _keys(data, keys: set[str], name: str) -> None:
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError(f"{name} requires exactly these fields: {', '.join(sorted(keys))}")


def _id(value, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", value) is None:
        raise ValueError(f"{name} must contain only letters, numbers, underscores and hyphens")


def validate_protocol(data: dict, *, output_fps=None) -> None:
    """Reject unknown fields, unsupported conditions and incomplete timing.

    Every protocol choice inherits the explicit top-level P evidence label.
    The separate unavailable ledger is NR. Demonstration taus are documentation,
    never inferred runtime defaults. A caller must supply an active config.
    """
    _keys(data, _TOP, "protocol")
    if type(data["schema_version"]) is not int or data["schema_version"] != PROTOCOL_SCHEMA:
        raise ValueError("protocol schema_version must be 1")
    _id(data["protocol_id"], "protocol_id")
    if data["parameter_status"] != "placeholder" or data["evidence"] != "P":
        raise ValueError("synthetic protocol parameters require placeholder status and P evidence")
    if not isinstance(data["notes"], str) or not data["notes"].strip():
        raise ValueError("protocol notes must explain the synthetic interpretation")
    settings = data["settings"]
    _keys(settings, _SETTINGS, "settings")
    for field in ("width", "height"):
        if type(settings[field]) is not int or settings[field] < 4:
            raise ValueError(f"{field} must be an integer >= 4")
    if not _finite(settings["level_nits"]) or not 0 < settings["level_nits"] <= 10000:
        raise ValueError("level_nits must be in (0, 10000] for PQ")
    if settings["input_eotf"] != "pq" or settings["primaries"] != "bt709":
        raise ValueError("schema 1 requires float PQ input and linear BT.709 primaries")
    if not _finite(settings["preview_reference_nits"]) or settings["preview_reference_nits"] <= 0:
        raise ValueError("preview_reference_nits must be positive and finite")
    for name, expected in (("ambient_lux", 0), ("bfi_duty", 1), ("overdrive_gain", 0),
                           ("motion_px_per_frame", 0), ("horizontal_deg", 0), ("vertical_deg", 0)):
        if not _finite(settings[name]) or settings[name] != expected:
            raise ValueError(f"schema 1 requires {name}={expected} (P isolated on-axis experiment)")
    _fraction(settings["output_fps"], "output_fps")
    fps = _fraction(output_fps if output_fps is not None else settings["output_fps"], "output_fps")
    for field in ("onset_interval_s", "late_interval_s"):
        _fraction(settings[field], field)
    _keys(data["demonstration"], {"attack_ms", "release_ms", "initial"}, "demonstration")
    for field in ("attack_ms", "release_ms"):
        if not _finite(data["demonstration"][field]) or data["demonstration"][field] < 0:
            raise ValueError(f"demonstration {field} must be finite and nonnegative")
    if data["demonstration"]["initial"] != "cold":
        raise ValueError("demonstration initialization must be cold")
    _keys(data["unavailable"], _UNAVAILABLE, "unavailable")
    if any(value != "NR" for value in data["unavailable"].values()):
        raise ValueError("measured dynamics, controller and calibrated fit constants remain NR")
    if not isinstance(data["trials"], list) or not data["trials"]:
        raise ValueError("protocol needs at least one independent trial")
    identifiers = set()
    for trial in data["trials"]:
        _keys(trial, {"trial_id", "family", "segments"}, "trial")
        _id(trial["trial_id"], "trial_id")
        _id(trial["family"], "family")
        if trial["trial_id"] in identifiers:
            raise ValueError("trial_id must be unique")
        identifiers.add(trial["trial_id"])
        if not isinstance(trial["segments"], list) or not trial["segments"]:
            raise ValueError("each trial needs an ordered stimulus history")
        for segment in trial["segments"]:
            _keys(segment, {"label", "fraction", "duration_s"}, "segment")
            _id(segment["label"], "segment label")
            if not _finite(segment["fraction"]) or not 0 <= segment["fraction"] <= 1:
                raise ValueError("fraction must be finite and in [0, 1]; 0 denotes black")
            duration = _fraction(segment["duration_s"], "duration_s", zero=True)
            if duration == 0 and segment["fraction"] != 0:
                raise ValueError("only an omitted black gap may have zero duration")
            if (duration * fps).denominator != 1:
                raise ValueError("every duration must be whole output ticks; elapsed intervals cannot be missing")
        if sum(_fraction(s["duration_s"], "duration_s", zero=True) for s in trial["segments"]) <= 0:
            raise ValueError("trial history must contain positive-duration ticks")


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_protocol(path: Path = DEFAULT_PROTOCOL) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_json)
    validate_protocol(data)
    return data


def _hash(data) -> str:
    return sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _array_hash(array: np.ndarray) -> str:
    return sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _json(path: Path, data) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")


def _output_path(path: Path) -> Path:
    path = Path(path).resolve()
    profile_tree = profile_path(available_profiles()[0]).parent.resolve()
    if path == profile_tree or profile_tree in path.parents or path.suffix or path.exists():
        raise ValueError("out must be a new experiment directory outside sim/profiles; existing artifacts cannot be overwritten")
    # Do not hide a new experiment in an existing fit/experiment artifact.
    for parent in path.parents:
        if parent.is_dir() and (parent / "manifest.json").exists():
            raise ValueError("out cannot be nested in an existing experiment artifact")
    return path


def _stimulus(width: int, height: int, fraction: float, level: float):
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    bounds = None
    actual = 0.0
    if fraction > 0:
        w = max(1, min(width, round(width * math.sqrt(fraction))))
        h = max(1, min(height, round(height * math.sqrt(fraction))))
        y, x = (height-h)//2, (width-w)//2
        rgb[y:y+h, x:x+w] = np.float32(level)
        bounds = [y, y+h, x, x+w]
        actual = h*w/(height*width)
    return pq_oetf(rgb), bounds, actual, demand_apl(rgb)


def _center(rgb):
    height, width = rgb.shape[:2]
    patch = rgb[(height-1)//2:height//2+1, (width-1)//2:width//2+1]
    return np.mean(patch, axis=(0, 1), dtype=np.float64).tolist(), float(np.mean(luminance(patch), dtype=np.float64))


def _metrics(rows: list[dict], start: int, end: int, fps: Fraction, settings: dict) -> dict:
    onset = max(1, math.ceil(_fraction(settings["onset_interval_s"], "onset_interval_s")*fps))
    late = max(1, math.ceil(_fraction(settings["late_interval_s"], "late_interval_s")*fps))
    chosen = rows[start:end]
    first, last = chosen[0], chosen[-1]
    peak = max(chosen[:onset], key=lambda r: r["center_y_nits"])
    hold_peak = max(chosen, key=lambda r: r["center_y_nits"])
    tail = chosen[-late:]
    ys = [r["center_y_nits"] for r in tail]
    span_s = float(Fraction(len(tail)-1, 1)/fps)
    # This empirical interval is in rendered-output space. It is deliberately
    # normalized to observed segment endpoints, not relabeled a measured tau.
    delta = last["center_y_nits"]-first["center_y_nits"]
    crossings = {}
    if abs(delta) > 1e-6:
        for fraction in (.1, .9):
            crossing = next((r for r in chosen if (r["center_y_nits"]-first["center_y_nits"])/delta >= fraction), None)
            crossings[str(fraction)] = None if crossing is None else crossing["right_pts"]
    else:
        crossings = {"0.1":None, "0.9":None}
    return {
        "evidence": "D under P model",
        "onset_interval_pts": [first["pts"], chosen[min(onset, len(chosen))-1]["right_pts"]],
        "peak_onset_center_y_nits": peak["center_y_nits"], "peak_onset_pts": peak["right_pts"],
        "hold_interval_pts": [first["pts"], last["right_pts"]],
        "peak_hold_center_y_nits": hold_peak["center_y_nits"], "peak_hold_pts": hold_peak["right_pts"],
        "late_interval_pts": [tail[0]["pts"], last["right_pts"]],
        "late_label": "late-interval output; equilibrium is not assumed",
        "late_mean_center_y_nits": float(np.mean(ys)), "late_min_center_y_nits": min(ys),
        "late_range_center_y_nits": [min(ys), max(ys)], "final_capacity_nits": last["capacity"]["after_nits"],
        "remaining_center_slope_nits_per_s": (ys[-1]-ys[0])/span_s if span_s else None,
        "remaining_capacity_slope_nits_per_s": (
            (tail[-1]["capacity"]["after_nits"]-tail[0]["capacity"]["after_nits"])/span_s if span_s else None),
        "output_transition": {"normalization":"observed first/final segment center Y; includes pixel response and shoulder",
                              "threshold_pts":crossings, "duration_10_90_ms": (
                                  float((Fraction(crossings["0.9"])-Fraction(crossings["0.1"]))*1000)
                                  if all(crossings.values()) else None)},
    }


def _plot_fallback(path: Path, rows: list[dict], title: str) -> None:
    """Fixed-axis PNG chart, using Pillow (no additional plotting dependency)."""
    image = Image.new("RGB", (1200, 560), "#fafafa")
    draw = ImageDraw.Draw(image)
    draw.text((20, 12), title, fill="#111111")
    draw.text((20, 32), "D under P model; capacity at tick right boundary; output has separate pixel response", fill="#333333")
    left, top, right, bottom = 75, 85, 1175, 485
    xmax = max(float(Fraction(r["right_pts"])) for r in rows)
    ymax = max(max(r["capacity"]["before_nits"], r["capacity"]["after_nits"],
                   r["center_y_nits"], r["capacity"]["target_nits"]) for r in rows)*1.05
    ymax = max(1., ymax)
    def point(time, level):
        return (left+(right-left)*time/xmax, bottom-(bottom-top)*level/ymax)
    for n in range(6):
        level = ymax*n/5
        y = point(0, level)[1]
        draw.line((left, y, right, y), fill="#dddddd")
        draw.text((7, y-5), f"{level:.0f}", fill="#333333")
        sec = xmax*n/5
        x = point(sec, 0)[0]
        draw.text((x-12, bottom+10), f"{sec:.2f}", fill="#333333")
    draw.text((left, top-20), "nits", fill="#333333")
    draw.text((right-95, bottom+30), "simulation seconds", fill="#333333")
    traces = [("target capacity", "#b77e00", lambda r:r["capacity"]["target_nits"]),
              ("available capacity", "#2454b7", lambda r:r["capacity"]["after_nits"]),
              ("center output Y", "#b02e66", lambda r:r["center_y_nits"])]
    for i, (name, color, getter) in enumerate(traces):
        points = [point(float(Fraction(r["right_pts"])), getter(r)) for r in rows]
        if len(points) > 1:
            draw.line(points, fill=color, width=2)
        draw.line((left+i*300, 540, left+25+i*300, 540), fill=color, width=3)
        draw.text((left+32+i*300, 534), name, fill=color)
    draw.rectangle((left, top, right, bottom), outline="#333333")
    image.save(path)


def _plot(path: Path, rows: list[dict], title: str) -> None:
    """Standalone scientific trace, with an optional-dependency fallback."""
    try:
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir())/"tv-sim-matplotlib"))
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except ImportError:
        _plot_fallback(path, rows, title)
        return
    times = np.array([float(Fraction(r["right_pts"])) for r in rows])
    target = np.array([r["capacity"]["target_nits"] for r in rows])
    capacity = np.array([r["capacity"]["after_nits"] for r in rows])
    output = np.array([r["center_y_nits"] for r in rows])
    fig = plt.figure(figsize=(12, 7), layout="constrained")
    grid = fig.add_gridspec(2, 2, height_ratios=[1.6,1])
    whole = fig.add_subplot(grid[0,:])
    attack_axis, release_axis = fig.add_subplot(grid[1,0]), fig.add_subplot(grid[1,1])
    for axis in (whole, attack_axis, release_axis):
        axis.plot(times,target,color="#ad7d00",linestyle="--",label="Target capacity")
        axis.plot(times,capacity,color="#2454b7",label="Available capacity")
        axis.plot(times,output,color="#b02e66",label="Center output Y")
        axis.set_ylabel("nits")
        axis.set_xlabel("Simulation time / s (tick right boundary)")
        axis.grid(alpha=.2)
        axis.set_ylim(bottom=0)
    whole.legend(loc="upper right",ncols=3,fontsize=9)
    changes = [i for i,r in enumerate(rows) if i == 0 or r["segment_index"] != rows[i-1]["segment_index"]]
    for i in changes:
        whole.axvline(float(Fraction(rows[i]["pts"])), color="gray",alpha=.25,linewidth=.8)
        whole.text(float(Fraction(rows[i]["pts"])), .03, rows[i]["segment_label"].replace("_"," "),
                   rotation=90,transform=whole.get_xaxis_transform(),fontsize=7,va="bottom")
    attack = next((i for i,r in enumerate(rows) if r["capacity"]["branch"] == "attack" and r["nominal_fraction"] == 1),0)
    release = next((i for i,r in enumerate(rows) if r["capacity"]["branch"] == "release" and r["nominal_fraction"] > 0),len(rows)//2)
    for axis,index,window,name in ((attack_axis,attack,.6,"Load onset"),(release_axis,release,3.,"Bright-probe recovery")):
        start = float(Fraction(rows[index]["pts"]))
        axis.set_xlim(start,max(start+float(Fraction(rows[index]["dt_s"])),min(times[-1],start+window)))
        axis.set_title(name,fontsize=10)
    fig.suptitle(title+"\nP placeholder settings; D model outputs; independent pixel response; shared preview exposure",fontsize=11)
    fig.savefig(path,dpi=120)
    plt.close(fig)


def _checkpoint(pipeline, next_pts: Fraction, fps: Fraction, protocol_hash: str, trial_id: str) -> dict:
    from sim.abl_dynamics import digest

    data = pipeline.checkpoint()
    data["experiment_timing"] = {"schema_version":1, "next_pts":str(next_pts), "output_fps":str(fps),
                                 "protocol_sha256":protocol_hash, "trial_id":trial_id, "evidence":"D under P protocol"}
    data["checkpoint_sha256"] = digest({key:value for key,value in data.items() if key != "checkpoint_sha256"})
    return data


def _resume_pts(checkpoint: dict, fps: Fraction) -> Fraction:
    if not isinstance(checkpoint,dict):
        raise ValueError("experiment checkpoint must be a mapping")
    timing = checkpoint.get("experiment_timing")
    if (not isinstance(timing,dict) or timing.get("schema_version") != 1
            or timing.get("evidence") != "D under P protocol"):
        raise ValueError("experiment resume requires saved rational timing metadata; no elapsed intervals can be inferred")
    if _fraction(timing.get("output_fps"),"checkpoint output_fps") != fps:
        raise ValueError("checkpoint output_fps mismatch; resume must retain the declared display clock")
    next_pts = _fraction(timing.get("next_pts"),"checkpoint next_pts",zero=True)
    try:
        elapsed = float.fromhex(checkpoint["capacity_state"]["elapsed_ms_hex"])
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise ValueError("checkpoint requires a finite exact elapsed-time boundary") from exc
    if not math.isclose(float(next_pts*1000),elapsed,rel_tol=1e-12,abs_tol=1e-9):
        raise ValueError("checkpoint rational PTS timestamp gap; replay every elapsed interval")
    return next_pts


def _gallery(out: Path, trials: list[dict], reference: float) -> None:
    blocks = []
    for trial in trials:
        cells = []
        for sample in trial["samples"]:
            cells.append(f'<figure><img src="{escape(trial["trial_id"])}/{escape(sample["preview_file"])}">'
                         f'<figcaption>{escape(sample["label"])}; t={escape(sample["right_pts"])} s; '
                         f'Y={sample["center_y_nits"]:.2f} nits</figcaption></figure>')
        blocks.append(f'<h2>{escape(trial["trial_id"])}</h2><img class="trace" src="{escape(trial["trial_id"])}/trace.png">'
                      '<div class="samples">'+"".join(cells)+'</div>')
    html = ('<!doctype html><meta charset="utf-8"><title>P OLED dynamics experiment</title>'
            '<style>body{font:15px system-ui;background:#eee;color:#222;margin:30px}.trace{max-width:100%}'
            '.samples{display:flex;flex-wrap:wrap}figure{margin:10px}figure img{width:384px;max-width:100%}'
            'figcaption{max-width:384px}</style><h1>Synthetic OLED capacity dynamics</h1>'
            f'<p>All constants are P placeholders. D traces under the P model; measured dynamics are NR. '
            f'All previews share sRGB exposure: {reference:g} nits maps to white. No named TV is calibrated.</p>'
            +"".join(blocks))
    with (out/"index.html").open("x", encoding="utf-8") as handle:
        handle.write(html+"\n")


def run_experiment(profile: TVProfile, config, protocol: dict, out: Path, *, sources=None,
                   trials=None, output_fps=None, state_in: Path | None = None,
                   state_out: Path | None = None, gallery: bool = False) -> dict:
    """Render selected independent histories into an exclusively new directory.

    State input/output is deliberately limited to one trial/source. A resumed
    protocol is a declared continuation, starting at the restored tick boundary;
    it cannot insert an unknown timestamp gap. All configuration admission and
    path checks finish before any display state advances or output is created.
    """
    from sim.abl_dynamics import ABLDynamicsConfig

    validate_protocol(protocol, output_fps=output_fps)
    if not isinstance(config, ABLDynamicsConfig) or config.model != "capacity_attack_release_v1":
        raise ValueError("oled-dynamics requires explicit --abl-dynamics capacity_attack_release_v1 and both taus")
    settings = protocol["settings"]
    fps = _fraction(output_fps if output_fps is not None else settings["output_fps"], "output_fps")
    dt = Fraction(1000, 1)/fps
    selected = ["demand", "emitted"] if sources is None else list(sources)
    if not selected or len(set(selected)) != len(selected) or any(s not in ("demand", "emitted") for s in selected):
        raise ValueError("sources must be unique demand/emitted domains")
    wanted = [trial["trial_id"] for trial in protocol["trials"]] if trials is None else list(trials)
    known = {trial["trial_id"] for trial in protocol["trials"]}
    if not wanted or len(set(wanted)) != len(wanted) or set(wanted)-known:
        raise ValueError("trials must be unique known protocol trial IDs")
    ordered = [t for t in protocol["trials"] if t["trial_id"] in wanted]
    if (state_in is not None or state_out is not None) and len(ordered)*len(selected) != 1:
        raise ValueError("state-in/state-out require exactly one trial and one load source")
    if state_in is not None and config.initial != "resume":
        raise ValueError("state-in requires initial=resume; reject competing initialization owners")
    if state_in is None and config.initial == "resume":
        raise ValueError("initial=resume requires state-in")
    destination = _output_path(out)
    if state_out is not None:
        state_out = Path(state_out).resolve()
        protected = profile_path(available_profiles()[0]).parent.resolve()
        if (state_out.exists() or state_out.name.endswith(".fit.json")
                or protected == state_out or protected in state_out.parents
                or (state_out.suffix != ".json")):
            raise ValueError("state-out must be a new .json checkpoint outside profiles/fits")
        if destination == state_out or destination in state_out.parents:
            raise ValueError("state-out must be outside the new experiment directory (all internal checkpoints are automatic)")
    restored = None
    if state_in is not None:
        if str(state_in).endswith(".fit.json"):
            raise ValueError("M9 schema-1 .fit.json cannot compose with active capacity dynamics")
        restored = json.loads(Path(state_in).read_text(encoding="utf-8"), object_pairs_hook=_unique_json)
        restored_pts = _resume_pts(restored,fps)
    # All changes are P runtime experiment overrides on a copied profile.
    experiment_profile = replace(profile, input=replace(profile.input, eotf="pq"),
        ambient=replace(profile.ambient, lux=settings["ambient_lux"]),
        temporal=replace(profile.temporal, bfi_duty=settings["bfi_duty"], bfi_preserve_mean=False,
                         overdrive_gain=settings["overdrive_gain"], motion_px_per_frame=settings["motion_px_per_frame"]))
    if experiment_profile.processing.scale_factor != 1 or experiment_profile.panel.viewing_angle_deg != 0:
        raise ValueError("schema 1 requires scale_factor=1 and on-axis panel settings")
    pipelines = {}
    for trial in ordered:
        for source in selected:
            key = f'{protocol["protocol_id"]}_{trial["trial_id"]}_{source}'
            candidate = Pipeline(replace(experiment_profile, hdr=replace(experiment_profile.hdr, abl_source=source)),
                                 abl_dynamics=config)
            if restored is not None:
                candidate.restore_checkpoint(restored, shape=(settings["height"], settings["width"], 3), dtype="float32")
            pipelines[key] = candidate
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1, "model": config.model, "parameter_status": "placeholder",
        "disclaimer": "P synthetic experiment, D outputs under a P model; measured TV dynamics/calibration remain NR.",
        "evidence": {"protocol_and_overrides": "P", "trace_and_metrics": "D", "measurement": "NR"},
        "protocol": deepcopy(protocol), "protocol_sha256": _hash(protocol),
        "runtime_config": asdict(config), "runtime_config_sha256": _hash(asdict(config)),
        "profile_original": asdict(profile), "profile_effective_base": asdict(experiment_profile),
        "profile_yaml_sha256": sha256(profile_path(profile.name).read_bytes()).hexdigest(),
        "code_sha256": {name:sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                        for name in ("abl_dynamics.py", "abl_history.py", "pipeline.py", "oled_dynamics_experiment.py", "stages/tonemap.py", "stages/temporal.py")},
        "timing": {"output_fps": str(fps), "dt_s": str(1/fps), "dt_ms": str(dt),
                   "pts_units": "seconds; left boundary; right_pts names capacity/output sampling boundary"},
        "preview": {"eotf": "srgb", "reference_nits": settings["preview_reference_nits"], "exposure": "shared fixed exposure across every trial/frame"},
        "capacity_exposure": "P endpoint approximation: updated C is held through this tick's temporal exposure",
        "initial_state_file": None if state_in is None else {"path":str(state_in), "sha256":sha256(Path(state_in).read_bytes()).hexdigest()},
        "trials": [],
    }
    width, height = settings["width"], settings["height"]
    preview_output = replace(profile.output, eotf="srgb", reference_nits=settings["preview_reference_nits"])
    final_checkpoint = None
    for trial in ordered:
        for source in selected:
            trial_id = f'{protocol["protocol_id"]}_{trial["trial_id"]}_{source}'
            pipeline = pipelines[trial_id]
            folder = destination/trial_id
            folder.mkdir()
            rows, samples, segments = [], [], []
            elapsed = restored_pts if restored is not None else Fraction(0)
            origin = elapsed
            count = 0
            if restored is not None:
                _json(folder/"initial.state.json", _checkpoint(pipeline,elapsed,fps,manifest["protocol_sha256"],trial_id))
            for seg_index, segment in enumerate(trial["segments"]):
                ticks = int(_fraction(segment["duration_s"], "duration_s", zero=True)*fps)
                segment_start = count
                if ticks == 0:
                    segments.append({**segment, "ticks":0, "start_pts":str(elapsed), "end_pts":str(elapsed),
                                     "meaning":"adjacent display ticks; no zero-duration update"})
                    continue
                encoded, bounds, actual, requested_apl = _stimulus(width, height, segment["fraction"], settings["level_nits"])
                prepared = pipeline.prepare_content(encoded)
                processed_apl = demand_apl(prepared.rgb)
                source_hash = _array_hash(encoded)
                prepared_hash = _array_hash(prepared.rgb)
                onset_tick = min(ticks-1, max(0, math.ceil(_fraction(settings["onset_interval_s"], "onset_interval_s")*fps)-1))
                sample_ticks = {0:"onset", onset_tick:"onset_interval_end", ticks-1:"late"}
                segment_samples = []
                for local in range(ticks):
                    frame = pipeline.display_content(prepared, frame_time_ms=float(dt), timestamp_ms=float(elapsed*1000))
                    before = pipeline.last_pre_temporal
                    center_rgb, center_y = _center(frame.rgb)
                    pre_rgb, pre_y = _center(before.rgb)
                    right = origin+Fraction(count+1, 1)/fps
                    row = {"tick":count, "pts":str(elapsed), "right_pts":str(right), "dt_s":str(1/fps),
                           "segment_index":seg_index, "segment_label":segment["label"],
                           "nominal_fraction":segment["fraction"], "actual_fraction":actual, "bounds_y0_y1_x0_x1":bounds,
                           "level_nits":settings["level_nits"], "requested_apl_nits":requested_apl,
                           "processed_apl_nits":processed_apl, "source_sha256":source_hash,
                           "prepared_sha256":prepared_hash, "capacity":deepcopy(pipeline.last_capacity_trace),
                           "center_pre_temporal_rgb_nits":pre_rgb, "center_pre_temporal_y_nits":pre_y,
                           "center_rgb_nits":center_rgb, "center_y_nits":center_y,
                           "full_mean_y_nits":demand_apl(frame.rgb)}
                    rows.append(row)
                    if local in sample_ticks:
                        stem = f"segment_{seg_index:02d}_{sample_ticks[local]}"
                        np.save(folder/f"{stem}.npy", frame.rgb, allow_pickle=False)
                        np.save(folder/f"{stem}.pre_temporal.npy", before.rgb, allow_pickle=False)
                        Image.fromarray(encode_frame(frame, preview_output)).save(folder/f"{stem}.png")
                        _json(folder/f"{stem}.state.json", _checkpoint(pipeline,right,fps,manifest["protocol_sha256"],trial_id))
                        sample = {"label":f'{segment["label"]}: {sample_ticks[local]}', "right_pts":str(right),
                                  "center_y_nits":center_y, "linear_file":f"{stem}.npy",
                                  "pre_temporal_file":f"{stem}.pre_temporal.npy", "preview_file":f"{stem}.png",
                                  "checkpoint_file":f"{stem}.state.json", "sha256":_array_hash(frame.rgb)}
                        samples.append(sample)
                        segment_samples.append(sample)
                    count += 1
                    elapsed = right
                segment_info = {**segment, "ticks":ticks, "start_pts":rows[segment_start]["pts"], "end_pts":str(elapsed),
                                "actual_fraction":actual, "bounds_y0_y1_x0_x1":bounds,
                                "metrics":_metrics(rows, segment_start, count, fps, settings), "samples":segment_samples}
                segments.append(segment_info)
            final_checkpoint = _checkpoint(pipeline,elapsed,fps,manifest["protocol_sha256"],trial_id)
            _json(folder/"final.state.json", final_checkpoint)
            trace = {"schema_version":1, "trial_id":trial_id, "evidence":{
                "tick":"D", "pts":"D", "right_pts":"D", "dt_s":"D under P output_fps",
                "segment_index":"D", "segment_label":"P", "nominal_fraction":"P",
                "actual_fraction":"D under P rasterization", "bounds_y0_y1_x0_x1":"D under P rasterization",
                "level_nits":"P", "requested_apl_nits":"D", "processed_apl_nits":"D",
                "source_sha256":"D", "prepared_sha256":"D", "capacity":{
                    "source":"P", "apl_nits":"D", "reference_nits":"P", "load_fraction":"D",
                    "target_nits":"D under P target map", "before_nits":"D under P initialization/history",
                    "after_nits":"D under P controller", "branch":"D", "attack_ms":"P", "release_ms":"P",
                    "dt_ms":"D under P output_fps", "elapsed_ms":"D", "ticks":"D"},
                "center_pre_temporal_rgb_nits":"D", "center_pre_temporal_y_nits":"D",
                "center_rgb_nits":"D", "center_y_nits":"D", "full_mean_y_nits":"D"}, "ticks":rows}
            _json(folder/"trace.json", trace)
            if gallery:
                _plot(folder/"trace.png", rows, trial_id)
            info = {"trial_id":trial_id, "protocol_trial_id":trial["trial_id"], "family":trial["family"],
                    "load_source":source, "viewing_angle":{"model":"on_axis", "horizontal_deg":0, "vertical_deg":0, "evidence":"P"},
                    "pipeline_identity":pipeline.identity(), "profile_effective":asdict(pipeline.profile),
                    "drive_model":"unchanged_profile_drive; no M9 fit", "ticks":count, "trace_file":"trace.json",
                    "trace_sha256":sha256((folder/"trace.json").read_bytes()).hexdigest(),
                    "initial_checkpoint_file":"initial.state.json" if restored is not None else None,
                    "initial_history":"restored complete display checkpoint" if restored is not None else "fresh history; initialization declared in runtime_config",
                    "final_checkpoint_file":"final.state.json",
                    "capacity_domain_times_ms":{"attack_e_fold":config.attack_ms, "release_e_fold":config.release_ms,
                        "attack_10_90":math.log(9)*config.attack_ms, "release_10_90":math.log(9)*config.release_ms,
                        "evidence":"D from P taus; distinct from output-domain dynamics"},
                    "segments":segments, "samples":samples}
            manifest["trials"].append(info)
    if state_out is not None:
        state_out.parent.mkdir(parents=True, exist_ok=True)
        _json(state_out, final_checkpoint)
    if gallery:
        _gallery(destination, manifest["trials"], settings["preview_reference_nits"])
    _json(destination/"manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=available_profiles())
    parser.add_argument("--abl-dynamics", choices=("off", "capacity_attack_release_v1"), default="off")
    parser.add_argument("--abl-attack-ms", type=float)
    parser.add_argument("--abl-release-ms", type=float)
    parser.add_argument("--abl-initial", choices=("cold", "settled_first_tick", "explicit", "resume"), default=None)
    parser.add_argument("--abl-initial-capacity-nits", type=float)
    parser.add_argument("--state-in", type=Path)
    parser.add_argument("--state-out", type=Path)
    parser.add_argument("--abl-source", choices=("demand", "emitted"), default=None,
                        help="Select one independent load-domain trial; omitted runs both with distinct IDs")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--trials", nargs="+", help="Protocol trial IDs; omitted runs every independent trial")
    parser.add_argument("--output-fps", help="Positive rational display rate; each duration must be whole ticks")
    parser.add_argument("--gallery", action="store_true", help="Add offline shared-exposure gallery and trace PNG charts")
    parser.add_argument("--out", type=Path, required=True, help="New exclusive output directory outside profiles/fits")
    return parser


def main(argv: list[str] | None = None) -> None:
    from sim.abl_dynamics import ABLDynamicsConfig

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.abl_dynamics == "off" and any(value is not None for value in (
            args.abl_attack_ms, args.abl_release_ms, args.abl_initial, args.abl_initial_capacity_nits,
            args.state_in, args.state_out, args.abl_source)):
            raise ValueError("dynamic CLI options require active abl-dynamics; off cannot own capacity history")
        config = ABLDynamicsConfig(model=args.abl_dynamics, attack_ms=args.abl_attack_ms,
            release_ms=args.abl_release_ms, initial=args.abl_initial or "cold",
            initial_capacity_nits=args.abl_initial_capacity_nits)
        manifest = run_experiment(load_profile(args.profile), config, load_protocol(args.protocol), args.out,
            sources=None if args.abl_source is None else [args.abl_source], trials=args.trials,
            output_fps=args.output_fps, state_in=args.state_in, state_out=args.state_out, gallery=args.gallery)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(f'Wrote {len(manifest["trials"])} synthetic P histories to {args.out / "manifest.json"}')


if __name__ == "__main__":
    main()
