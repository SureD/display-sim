"""Reproducible P LCD-zone clips, D metrics and shared-exposure artifacts.

The controller is deliberately separate from this diagnostic. Each arm owns a
fresh complete display history. Linear fixture content enters the display tail
once per rational output tick; no camera, TV calibration or flicker score is
implied by the saved output. The ordinary arm omits zone temporal configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, replace
from fractions import Fraction
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from tv_sim.color import luminance
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import TVProfile, available_profiles, load_profile, profile_path
from tv_sim.stages.backlight import pool_zones
from tv_sim.stages.encode import encode_frame
from tv_sim.zone_temporal import MODEL, ZoneTemporalConfig
from tv_sim.zone_temporal_provenance import PROTOCOL_PATH, load_protocol, validate_protocol

FIXTURE_VERSION = "zone_clips_v1"
ARMS = ("off", "on")


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _destination(out: Path) -> Path:
    path = Path(out).resolve()
    protected = profile_path(available_profiles()[0]).parent.resolve()
    if path.exists() or path.suffix or path == protected or protected in path.parents:
        raise ValueError("out must be a new experiment directory outside profiles")
    if any((parent / "manifest.json").is_file() for parent in path.parents):
        raise ValueError("out cannot be nested in an existing experiment")
    return path


def _fixture(name: str, settings: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Return all linear content, exact foreground masks and P raster definitions."""
    width, height = settings["width"], settings["height"]
    count = int(Fraction(settings["duration_s"]) * Fraction(settings["output_fps"]))
    level, dark = settings["level_nits"], settings["dark_scene_nits"]
    frames = np.zeros((count, height, width, 3), dtype=np.float32)
    masks = np.zeros((count, height, width), dtype=bool)
    begin, end = count // 10, 4 * count // 5
    details: dict[str, Any] = {
        "evidence": "P",
        "version": FIXTURE_VERSION,
        "foreground_bounds_yxyx": [],
        "event_indices": {"begin": begin, "end": end},
        "rounding": "integer floor ratios; object x uses round-to-even",
    }
    if name == "moving_object":
        object_w, object_h = max(2, width // 12), max(2, height // 8)
        y = (height - object_h) // 2
        positions = np.round(np.linspace(0, width - object_w, max(1, end - begin))).astype(int)
        for i in range(count):
            bounds = None
            if begin <= i < end:
                x = int(positions[i - begin])
                masks[i, y : y + object_h, x : x + object_w] = True
                bounds = [y, y + object_h, x, x + object_w]
            details["foreground_bounds_yxyx"].append(bounds)
        details["trajectory"] = "left-to-right at integer raster positions; black before/after"
    elif name == "apl_step":
        rise, fall = count // 5, 3 * count // 5
        frames[rise:fall] = level
        frames[fall:] = level / 10
        masks[rise:] = True
        details["event_indices"] = {"rise": rise, "fall": fall}
        details["levels_nits"] = [0, level, level / 10]
    elif name == "flashing_highlight":
        object_w, object_h = max(2, width // 12), max(2, height // 8)
        y, x = (height - object_h) // 2, (width - object_w) // 2
        period = 6
        for i in range(begin, end):
            if (i - begin) % period < period // 2:
                masks[i, y : y + object_h, x : x + object_w] = True
        details.update(
            flash_period_ticks=period,
            on_ticks_per_period=period // 2,
            highlight_bounds_yxyx=[y, y + object_h, x, x + object_w],
        )
    elif name == "subtitle":
        # A fixed dim scene above a black subtitle bar gives a nominally
        # unchanged black probe where finite LCD extinction exposes pumping.
        frames[:, : 3 * height // 4] = dark
        begin, end = count // 4, 3 * count // 4
        y, text_h = 4 * height // 5, max(1, height // 16)
        word_w, gap = max(2, width // 6), max(1, width // 30)
        x0 = (width - 3 * word_w - 2 * gap) // 2
        for word in range(3):
            x = x0 + word * (word_w + gap)
            masks[begin:end, y : y + text_h, x : x + word_w] = True
        details["event_indices"] = {"begin": begin, "end": end}
        details.update(
            dark_scene_nits=dark,
            black_bar_y=3 * height // 4,
            subtitle_word_bounds_yxyx=[
                [y, y + text_h, x0 + w * (word_w + gap), x0 + w * (word_w + gap) + word_w]
                for w in range(3)
            ],
        )
    else:
        raise ValueError(f"unknown fixture {name!r}")
    if name != "apl_step":
        frames[masks] = level
    details["probe_yx"] = [min(height - 1, 9 * height // 10), width // 2]
    return frames, masks, details


def _settling(
    values: np.ndarray, target: float, start: int, end: int, tolerance: float, fps: Fraction
) -> dict[str, Any]:
    """First tick endpoint that stays in-band for the remaining known hold."""
    within = np.abs(values[start:end] - target) <= tolerance
    reached = next((i for i in range(len(within)) if bool(np.all(within[i:]))), None)
    return {
        "target_nits": target,
        "tolerance_nits": tolerance,
        "hold_pts": [str(Fraction(start, 1) / fps), str(Fraction(end, 1) / fps)],
        "settling_s": None if reached is None else str(Fraction(reached + 1, 1) / fps),
        "reached": reached is not None,
        "sampling": "tick endpoints; remaining hold only; no sub-tick interpolation",
    }


def _metrics(
    name: str,
    outputs: dict[str, np.ndarray],
    masks: np.ndarray,
    content: np.ndarray,
    details: dict[str, Any],
    traces: dict[str, list[dict[str, Any]]],
    settings: dict[str, Any],
    backgrounds: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    fps = Fraction(settings["output_fps"])
    duration = float(1 / fps)
    ys = {arm: luminance(values) for arm, values in outputs.items()}
    py, px = details["probe_yx"]
    result: dict[str, Any] = {
        "evidence": "D under P model and P metric definitions",
        "definitions": {
            "trail": "positive excess Y behind moving rear edge in object-height band; exclude object; subtract independent matched black-only history for each arm",
            "trail_threshold_nits": settings["halo_threshold_nits"],
            "trail_energy": "sum positive excess Y * dt over trailing pixels; nit-pixel-seconds, not joules",
            "probe_variation": "max-minus-min Y at fixed probe over full clip; includes requested content changes outside subtitle fixture",
            "pumping_proxy": "subtitle unchanged black-bar probe only; not perceptual flicker or PWM",
            "zone_total_variation": "sum absolute successive zone-command differences; nits",
            "highlight_retention": "integrated output Y in foreground mask / integrated requested Y in that mask",
            "overshoot": "positive excursion beyond held target in transition direction; falling residual is not overshoot",
        },
        "arms": {},
    }
    for arm in ARMS:
        y = ys[arm]
        commands = np.array([r["zone"]["after_nits"] for r in traces[arm]])
        foreground = float(np.sum(y[masks], dtype=np.float64) * duration)
        requested = float(np.sum(luminance(content)[masks], dtype=np.float64)) * duration
        result["arms"][arm] = {
            "probe_yx": [py, px],
            "probe_peak_to_peak_nits": float(np.ptp(y[:, py, px])),
            "pumping_proxy_peak_to_peak_nits": float(np.ptp(y[:, py, px]))
            if name == "subtitle"
            else None,
            "output_mean_peak_to_peak_nits": float(np.ptp(np.mean(y, axis=(1, 2)))),
            "zone_total_variation_nits": float(np.sum(np.abs(np.diff(commands, axis=0)))),
            "highlight_energy_nit_pixel_s": foreground,
            "highlight_retention_ratio": foreground / requested if requested else None,
        }
    if name == "moving_object":
        threshold = settings["halo_threshold_nits"]
        if backgrounds is None:
            raise ValueError("moving trail metrics require matched black-only histories")
        halos = {arm: np.maximum(ys[arm] - luminance(backgrounds[arm]), 0) for arm in ARMS}
        result["matched_black_background"] = (
            "independent same-profile/config/clock/initialization black-only histories"
        )
        for label, y in (
            *halos.items(),
            ("positive_on_minus_off", np.maximum(halos["on"] - halos["off"], 0)),
        ):
            energy, length = 0.0, 0
            for i, bounds in enumerate(details["foreground_bounds_yxyx"]):
                if bounds is None:
                    continue
                y0, y1, rear, _ = bounds
                trailing = np.maximum(y[i, y0:y1, :rear], 0)
                energy += float(np.sum(trailing, dtype=np.float64)) * duration
                hit = np.nonzero(trailing > threshold)[1]
                if hit.size:
                    length = max(length, rear - int(hit.min()))
            result.setdefault("trails", {})[label] = {
                "max_length_px": length,
                "energy_nit_pixel_s": energy,
            }
    if name == "apl_step":
        rise, fall = details["event_indices"]["rise"], details["event_indices"]["fall"]
        end = len(masks)
        result["transitions"] = {}
        for event, start, stop, direction in (("rise", rise, fall, 1), ("fall", fall, end, -1)):
            target_commands = np.array(traces["on"][start]["zone"]["targets_nits"])
            target = float(np.mean(target_commands))
            tolerance = max(1e-12, abs(target) * settings["settling_fraction"])
            result["transitions"][event] = {}
            for arm in ARMS:
                command = np.array([np.mean(r["zone"]["after_nits"]) for r in traces[arm]])
                # Reducing spatial axes leaves one sample per output tick.
                output = cast(NDArray[np.float64], np.mean(ys[arm], axis=(1, 2), dtype=np.float64))
                output_target = float(np.mean(ys["off"][stop - 1]))
                result["transitions"][event][arm] = {
                    "zone": _settling(command, target, start, stop, tolerance, fps),
                    "output": _settling(
                        output,
                        output_target,
                        start,
                        stop,
                        max(1e-12, output_target * settings["settling_fraction"]),
                        fps,
                    ),
                    "direction": "increasing" if direction == 1 else "decreasing",
                    "zone_overshoot_nits": float(
                        max(0, np.max(direction * (command[start:stop] - target)))
                    ),
                    "output_overshoot_nits": float(
                        max(0, np.max(direction * (output[start:stop] - output_target)))
                    ),
                    "output_reference": "matched off-arm final tick in held segment; finite-clip equilibrium is not guaranteed",
                }
    return result


def _contact(
    path: Path,
    outputs: dict[str, np.ndarray],
    indices: list[int],
    profile: TVProfile,
    reference: float,
    title: str,
    fps: Fraction,
) -> None:
    scale, label_h, heading_h = 2, 24, 44
    height, width = outputs["off"].shape[1:3]
    image = Image.new(
        "RGB", (len(indices) * width * scale, heading_h + 2 * (height * scale + label_h)), "#222222"
    )
    draw = ImageDraw.Draw(image)
    draw.text((8, 6), title, fill="white")
    draw.text(
        (8, 23), f"Shared exposure: {reference:g} nits = white; P model / D output", fill="white"
    )
    for row, arm in enumerate(ARMS):
        for col, i in enumerate(indices):
            encoded = encode_frame(
                Frame(outputs[arm][i]),
                replace(profile.output, eotf="srgb", reference_nits=reference),
            )
            preview = Image.fromarray(encoded).resize(
                (width * scale, height * scale), Image.Resampling.NEAREST
            )
            x, y = col * width * scale, heading_h + row * (height * scale + label_h)
            image.paste(preview, (x, y))
            draw.text(
                (x + 4, y + height * scale + 4),
                f"{arm}; t={Fraction(i + 1, 1) / fps}s",
                fill="white",
            )
    image.save(path)


def _plot(path: Path, traces: dict[str, list[dict[str, Any]]], title: str, fps: Fraction) -> None:
    """Deterministic standalone probe plot; axes are shared across both arms."""
    image = Image.new("RGB", (1000, 420), "white")
    draw = ImageDraw.Draw(image)
    left, right, top, bottom = 65, 975, 65, 350
    draw.text((15, 12), title + " | D under P model; rational tick endpoints", fill="black")
    series = [
        (arm, metric, color)
        for arm, metric, color in (
            ("off", "mean_zone_nits", "#888888"),
            ("on", "mean_zone_nits", "#0060c0"),
            ("off", "mean_y_nits", "#d9984e"),
            ("on", "mean_y_nits", "#c02040"),
        )
    ]
    ymax = max(1.0, max(r[key] for arm, key, _ in series for r in traces[arm]))
    for i in range(6):
        y = bottom - i * (bottom - top) / 5
        draw.line((left, y, right, y), fill="#dddddd")
        draw.text((5, y - 5), f"{i * ymax / 5:.1f}", fill="black")
    count = len(traces["off"])
    for i, (arm, key, color) in enumerate(series):
        points = [
            (left + (right - left) * (n + 1) / count, bottom - (bottom - top) * row[key] / ymax)
            for n, row in enumerate(traces[arm])
        ]
        draw.line(points, fill=color, width=2)
        draw.text((15 + i * 245, 388), f"{arm}: {key}", fill=color)
    draw.rectangle((left, top, right, bottom), outline="black")
    draw.text((left, 365), "0 s", fill="black")
    draw.text((right - 90, 365), f"{float(Fraction(count, 1) / fps):g} s", fill="black")
    draw.text((left, 45), "nits", fill="black")
    image.save(path)


def run_experiment(
    profile: TVProfile,
    config: ZoneTemporalConfig,
    protocol: dict[str, Any],
    out: Path,
    *,
    fixtures: list[str] | None = None,
    pixel_response: str = "isolated",
) -> dict[str, Any]:
    """Render all admitted histories before writing an exclusively new artifact.

    Isolated diagnostics set pixel lag/OD/pursuit/BFI and ambient to their
    declared neutral values. ``pixel_response='profile'`` retains the profile's
    LCD response tau as a separately identified cascade comparison.
    """
    validate_protocol(protocol)
    if not isinstance(config, ZoneTemporalConfig) or not config.active:
        raise ValueError("zone-temporal experiment requires explicit active config and both taus")
    if config.initial == "resume":
        raise ValueError("independent synthetic fixtures cannot use resume initialization")
    if pixel_response not in ("isolated", "profile"):
        raise ValueError("pixel_response must be isolated or profile")
    wanted = protocol["fixtures"] if fixtures is None else list(fixtures)
    if not wanted or len(set(wanted)) != len(wanted) or set(wanted) - set(protocol["fixtures"]):
        raise ValueError("fixtures must be unique known protocol names")
    destination = _destination(out)
    settings = protocol["settings"]
    fps = Fraction(settings["output_fps"])
    experiment = replace(
        profile,
        ambient=replace(profile.ambient, lux=0),
        temporal=replace(
            profile.temporal,
            response_time_ms=0
            if pixel_response == "isolated"
            else profile.temporal.response_time_ms,
            frame_time_ms=float(1000 / fps),
            motion_px_per_frame=0,
            overdrive_gain=0,
            bfi_duty=1,
            bfi_preserve_mean=False,
            integration_samples=1,
        ),
    )
    # Validate LCD eligibility/conflicts before creating any artifact or advancing
    # any trial. Preserve forbidden profile terms so runtime admission rejects.
    admission = Pipeline(experiment, zone_temporal=config)
    if settings["level_nits"] > experiment.backlight.peak_nits:
        raise ValueError(
            "schema 1 diagnostic level must not exceed backlight peak (matched bounded targets)"
        )
    prepared = {name: _fixture(name, settings) for name in wanted}
    if config.initial_zones_nits is not None:
        expected_shape = (
            min(settings["height"], experiment.backlight.zones_y),
            min(settings["width"], experiment.backlight.zones_x),
        )
        if np.asarray(config.initial_zones_nits).shape != expected_shape:
            raise ValueError("explicit initialization grid does not match fixture rasterized zones")
    destination.mkdir(parents=True)
    _write_json(destination / "protocol.json", protocol)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": protocol["protocol_id"],
        "evidence": "D outputs under P synthetic protocol; measured dynamics NR",
        "protocol_sha256": _hash(protocol),
        "fixture_version": FIXTURE_VERSION,
        "implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_profile_sha256": _hash(asdict(profile)),
        "profile": asdict(experiment),
        "runtime_overrides_evidence": "P",
        "runtime_overrides": {
            "ambient_lux": 0,
            "pixel_response": pixel_response,
            "frame_time_ms": float(1000 / fps),
            "motion_px_per_frame": 0,
            "overdrive_gain": 0,
            "bfi_duty": 1,
            "bfi_preserve_mean": False,
            "integration_samples": 1,
        },
        "zone_temporal": asdict(config),
        "controller_identity": admission.identity(),
        "numpy_version": np.__version__,
        "input_domain": "prepared float32 linear BT.709 RGB nits; bypass decode/spatial processing",
        "pixel_response": pixel_response,
        "output_fps": str(fps),
        "preview": {
            "eotf": "srgb",
            "reference_nits": settings["preview_reference_nits"],
            "shadow_reference_nits": 1,
            "shared_between_arms_and_fixtures": True,
        },
        "clips": [],
    }
    for name, (content, masks, details) in prepared.items():
        folder = destination / name
        folder.mkdir()
        pipelines = {"off": Pipeline(experiment), "on": Pipeline(experiment, zone_temporal=config)}
        traces: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
        outputs = {arm: np.empty_like(content) for arm in ARMS}
        backgrounds = None
        if name == "moving_object":
            backgrounds = {arm: np.empty_like(content) for arm in ARMS}
            background_pipelines = {
                "off": Pipeline(experiment),
                "on": Pipeline(experiment, zone_temporal=config),
            }
            for i in range(len(content)):
                for arm in ARMS:
                    backgrounds[arm][i] = (
                        background_pipelines[arm]
                        .display_content(
                            Frame(np.zeros_like(content[i])),
                            frame_time_ms=float(1000 / fps),
                            timestamp_ms=float(Fraction(i, 1) / fps * 1000),
                        )
                        .rgb
                    )
        previous_off: list[list[float]] | None = None
        for i, rgb in enumerate(content):
            targets, _, _ = pool_zones(
                np.max(rgb, axis=-1),
                experiment.backlight.zones_y,
                experiment.backlight.zones_x,
                experiment.backlight.zone_percentile,
            )
            targets = np.clip(
                targets, experiment.backlight.floor_nits, experiment.backlight.peak_nits
            ).astype(np.float64)
            for arm in ARMS:
                pipeline = pipelines[arm]
                shown = pipeline.display_content(
                    Frame(rgb.copy()),
                    frame_time_ms=float(1000 / fps),
                    timestamp_ms=float(Fraction(i, 1) / fps * 1000),
                )
                outputs[arm][i] = shown.rgb
                zone = (
                    pipeline.last_zone_trace
                    if arm == "on"
                    else {
                        "targets_nits": targets.tolist(),
                        "before_nits": previous_off,
                        "after_nits": targets.tolist(),
                        "ticks": i + 1,
                        "policy": "instantaneous bounded pooled demand; feature omitted",
                    }
                )
                if not isinstance(zone, dict):
                    raise RuntimeError("active zone controller did not provide a trace")
                y = luminance(shown.rgb)
                py, px = details["probe_yx"]
                traces[arm].append(
                    {
                        "index": i,
                        "pts": str(Fraction(i, 1) / fps),
                        "right_pts": str(Fraction(i + 1, 1) / fps),
                        "duration_s": str(1 / fps),
                        "zone": zone,
                        "mean_zone_nits": float(np.mean(zone["after_nits"])),
                        "mean_y_nits": float(np.mean(y, dtype=np.float64)),
                        "probe_y_nits": float(y[py, px]),
                        "foreground_pixels": int(np.sum(masks[i])),
                        "foreground_y_nits": float(np.mean(y[masks[i]], dtype=np.float64))
                        if np.any(masks[i])
                        else None,
                    }
                )
            previous_off = targets.tolist()
        metrics = _metrics(name, outputs, masks, content, details, traces, settings, backgrounds)
        _write_json(folder / "trace.json", {"evidence": "D under P model", "arms": traces})
        _write_json(folder / "metrics.json", metrics)
        archive: dict[str, Any] = {
            "content": content,
            "foreground_mask": masks,
            "off": outputs["off"],
            "on": outputs["on"],
        }
        if backgrounds is not None:
            archive.update({f"black_{arm}": values for arm, values in backgrounds.items()})
        np.savez_compressed(folder / "linear.npz", **archive)
        with (folder / "probes.csv").open("x", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "arm",
                    "index",
                    "pts",
                    "right_pts",
                    "duration_s",
                    "mean_zone_nits",
                    "mean_y_nits",
                    "probe_y_nits",
                    "foreground_y_nits",
                ]
            )
            for arm in ARMS:
                for row in traces[arm]:
                    writer.writerow(
                        [
                            arm,
                            *(
                                row[key]
                                for key in (
                                    "index",
                                    "pts",
                                    "right_pts",
                                    "duration_s",
                                    "mean_zone_nits",
                                    "mean_y_nits",
                                    "probe_y_nits",
                                    "foreground_y_nits",
                                )
                            ),
                        ]
                    )
        count = len(content)
        events = details["event_indices"]
        if name == "apl_step":
            rise, fall = events["rise"], events["fall"]
            samples = [rise, rise + max(1, count // 40), fall - 1, fall, count - 1]
        else:
            begin, end = events["begin"], events["end"]
            if name == "moving_object":
                samples = [begin, (begin + end) // 2, end - 1, end, end + max(1, count // 12)]
            elif name == "flashing_highlight":
                samples = [begin, begin + 2, begin + 3, begin + 5, end + 1]
            else:
                samples = [begin, begin + max(1, count // 20), (begin + end) // 2, end, count - 1]
        indices = sorted({min(count - 1, max(0, i)) for i in samples})
        _contact(
            folder / "contact.png",
            outputs,
            indices,
            experiment,
            settings["preview_reference_nits"],
            name,
            fps,
        )
        _contact(
            folder / "shadows.png",
            outputs,
            indices,
            experiment,
            1,
            name + " / amplified shadows",
            fps,
        )
        _plot(folder / "trace.png", traces, name, fps)
        manifest["clips"].append(
            {
                "fixture": name,
                "ticks": count,
                "duration_s": str(Fraction(count, 1) / fps),
                "definitions": details,
                "metrics": metrics,
                "samples": indices,
                "trace_file": f"{name}/trace.json",
                "linear_file": f"{name}/linear.npz",
                "contact_sheet": f"{name}/contact.png",
                "shadow_sheet": f"{name}/shadows.png",
                "trace_plot": f"{name}/trace.png",
                "array_sha256": {arm: sha256(outputs[arm].tobytes()).hexdigest() for arm in ARMS},
            }
        )
    _write_json(destination / "manifest.json", manifest)
    sections = "".join(
        f'<h2>{escape(clip["fixture"])}</h2><img src="{escape(clip["contact_sheet"])}">'
        f'<details><summary>Amplified shadows: shared 1-nit reference</summary><img src="{escape(clip["shadow_sheet"])}"></details>'
        f'<img src="{escape(clip["trace_plot"])}"><p><a href="{escape(clip["trace_file"])}">Per-zone traces</a> · '
        f'<a href="{escape(clip["fixture"])}/metrics.json">Metric definitions and values</a></p>'
        for clip in manifest["clips"]
    )
    (destination / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Synthetic LCD zone temporal dynamics</title>'
        "<style>body{font:15px system-ui;background:#eee;margin:30px;color:#222}img{max-width:100%;display:block;margin:15px 0}details{margin:20px 0}</style>"
        "<h1>Synthetic LCD zone temporal dynamics</h1><p>P placeholders; D model results; measured TV dynamics NR. "
        f"Both arms use shared sRGB exposure: {settings['preview_reference_nits']:g} nits = white. "
        f"Pixel response: {escape(pixel_response)}. The off arm omits zone temporal configuration. "
        "The amplified shadow sheets use one shared 1-nit reference and clip highlights. "
        "Static sheets do not establish perceived flicker or host luminance.</p>" + sections + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run P LCD zone temporal clips with matched off/on histories."
    )
    parser.add_argument(
        "--profile", default="generic_va_fald_miniled", choices=available_profiles()
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--out", type=Path, default=Path("reports/zone-temporal-m17"))
    parser.add_argument(
        "--attack-s", type=float, required=True, help="Explicit increasing-light e-fold seconds (P)"
    )
    parser.add_argument(
        "--release-s",
        type=float,
        required=True,
        help="Explicit decreasing-light e-fold seconds (P)",
    )
    parser.add_argument("--slew-nits-per-tick", type=float)
    parser.add_argument("--initial", choices=("cold", "settled_first_tick"), default="cold")
    parser.add_argument("--cut-detection-threshold", type=float)
    parser.add_argument("--no-scene-cut-reset", action="store_true")
    parser.add_argument(
        "--fixtures",
        nargs="+",
        choices=("moving_object", "apl_step", "flashing_highlight", "subtitle"),
    )
    parser.add_argument("--pixel-response", choices=("isolated", "profile"), default="isolated")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = ZoneTemporalConfig(
            model=MODEL,
            attack_s=args.attack_s,
            release_s=args.release_s,
            initial=args.initial,
            slew_nits_per_tick=args.slew_nits_per_tick,
            cut_detection_threshold=args.cut_detection_threshold,
            reset_on_scene_cut=not args.no_scene_cut_reset,
        )
        manifest = run_experiment(
            load_profile(args.profile),
            config,
            load_protocol(args.protocol),
            args.out,
            fixtures=args.fixtures,
            pixel_response=args.pixel_response,
        )
    except (OSError, ValueError, ZeroDivisionError) as exc:
        parser.error(str(exc))
    print(f"Saved {len(manifest['clips'])} P LCD zone temporal clips to {args.out}")


if __name__ == "__main__":
    main()
