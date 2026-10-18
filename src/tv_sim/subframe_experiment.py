"""P synthetic sub-frame clips, D waveform metrics and shared-exposure previews.

Each arm owns a separate complete pipeline. A fixed LCD illumination isolates
LC response and pulse timing. Camera images integrate actual emitted samples;
PNG previews retain one common exposure and never compensate pulse brightness.
The generated diagnostics do not calibrate or certify any physical display.
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
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from tv_sim.color import luminance
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import TVProfile, available_profiles, load_profile, profile_path
from tv_sim.stages.encode import encode_frame
from tv_sim.subframe import SubframeConfig
from tv_sim.subframe_metrics import (
    flicker_metrics,
    pursuit_image,
    pursuit_metrics,
    response_metrics,
)
from tv_sim.subframe_provenance import (
    LCD_ILLUMINATION_NITS,
    LCD_NATIVE_CONTRAST,
    PROTOCOL_PATH,
    load_protocol,
    validate_protocol,
)

ARMS = ("lcd_hold", "lcd_overdrive", "lcd_strobe", "lcd_pwm", "oled_hold", "oled_bfi")
FIXTURE_VERSION = "subframe_clips_v1"


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, separators=(",", ":"), allow_nan=False)
        handle.write("\n")


def _destination(out: Path) -> Path:
    path = Path(out).resolve()
    protected = profile_path(available_profiles()[0]).parent.resolve()
    if path.exists() or path.suffix or path == protected or protected in path.parents:
        raise ValueError("out must be a new experiment directory outside profiles")
    if any((parent / "manifest.json").is_file() for parent in path.parents):
        raise ValueError("out cannot be nested in an existing experiment")
    return path


def _profiles() -> dict[str, TVProfile]:
    result = {}
    for kind, name in (("lcd", "generic_va_fald_miniled"), ("oled", "generic_woled")):
        p = load_profile(name)
        result[kind] = replace(
            p,
            backlight=replace(
                p.backlight,
                zones_x=1,
                zones_y=1,
                peak_nits=LCD_ILLUMINATION_NITS,
                floor_nits=LCD_ILLUMINATION_NITS if kind == "lcd" else 0,
                psf_sigma_zones=0,
                psf_sigma_y_zones=0,
                psf_tail_weight=0,
            ),
            hdr=replace(
                p.hdr,
                panel_peak_nits=LCD_ILLUMINATION_NITS,
                knee_ratio=1,
                abl_enabled=False,
                abl_response_ms=0,
            ),
            panel=replace(
                p.panel,
                native_contrast=LCD_NATIVE_CONTRAST if kind == "lcd" else p.panel.native_contrast,
            ),
            ambient=replace(p.ambient, lux=0),
            temporal=replace(
                p.temporal,
                response_time_ms=0,
                sample_and_hold=False,
                motion_px_per_frame=0,
                overdrive_gain=0,
                overdrive_ms=0,
                overdrive_ceiling_nits=0,
                bfi_duty=1,
                bfi_preserve_mean=False,
                integration_samples=1,
            ),
        )
    return result


def _configs(protocol: dict[str, Any]) -> dict[str, SubframeConfig]:
    s, d = protocol["settings"], protocol["demonstration"]
    base = SubframeConfig(
        model="subframe_emission_v1",
        substeps=s["substeps"],
        rise_tau_ms=d["rise_tau_ms"],
        fall_tau_ms=d["fall_tau_ms"],
    )
    levels = tuple(
        sorted({0.0, 1.0, *(float(v) / LCD_ILLUMINATION_NITS for v in s["gray_levels_nits"])})
    )
    commands = tuple(
        tuple(float(np.clip(new + d["overdrive_gain"] * (new - old), 0, 1)) for new in levels)
        for old in levels
    )
    oled = replace(base, rise_tau_ms=0, fall_tau_ms=0)
    return {
        "lcd_hold": base,
        "lcd_overdrive": replace(
            base,
            overdrive_levels=levels,
            overdrive_commands=commands,
            overdrive_fraction=d["overdrive_fraction"],
        ),
        "lcd_strobe": replace(base, strobe_duty=d["strobe_duty"], strobe_phase=d["strobe_phase"]),
        "lcd_pwm": replace(base, pwm_hz=d["pwm_hz"], pwm_duty=d["pwm_duty"]),
        "oled_hold": oled,
        "oled_bfi": replace(oled, bfi_duty=d["bfi_duty"], bfi_phase=d["bfi_phase"]),
    }


def _pipelines(
    profiles: dict[str, TVProfile], configs: dict[str, SubframeConfig]
) -> dict[str, Pipeline]:
    return {arm: Pipeline(profiles[arm.split("_")[0]], subframe=configs[arm]) for arm in ARMS}


def _motion_content(name: str, settings: dict[str, Any], speed: float) -> np.ndarray:
    fps = Fraction(settings["output_fps"])
    count = int(Fraction(settings["motion_duration_s"]) * fps)
    width, height = settings["width"], settings["height"]
    x = np.arange(width, dtype=np.float64)
    frames = np.empty((count, height, width, 3), dtype=np.float32)
    bar_width = max(4, width // 8)
    for i in range(count):
        edge = width / 2 + speed * float(Fraction(i - count // 2, 1) / fps)
        coverage = np.clip(x + 1 - edge, 0, 1)
        if name == "moving_bar":
            coverage -= np.clip(x + 1 - edge - bar_width, 0, 1)
        elif name != "moving_edge":
            raise ValueError(f"unknown moving fixture {name!r}")
        level = settings["dark_nits"] + coverage * (settings["level_nits"] - settings["dark_nits"])
        frames[i] = level[None, :, None]
    return frames


def _row(arm: str, tick: int, substep: int, sample: Any) -> list[Any]:
    return [
        arm,
        tick,
        substep,
        str(sample.pts),
        str(sample.pts + sample.duration),
        str(sample.duration),
        float(np.mean(luminance(sample.rgb))),
        float(luminance(sample.rgb)[sample.rgb.shape[0] // 2, sample.rgb.shape[1] // 2]),
        float(np.mean(sample.panel[sample.panel.shape[0] // 2, sample.panel.shape[1] // 2]))
        * (LCD_ILLUMINATION_NITS if arm.startswith("lcd") else 1),
    ]


def _csv(path: Path, rows: list[list[Any]]) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "arm",
                "tick",
                "substep",
                "pts",
                "right_pts",
                "duration_s",
                "mean_y_nits",
                "probe_y_nits",
                "panel_endpoint_probe_nits",
            ]
        )
        writer.writerows(rows)


def _contact(
    path: Path,
    images: dict[str, tuple[np.ndarray, np.ndarray]],
    reference: float,
    title: str,
    profiles: dict[str, TVProfile],
) -> None:
    first = next(iter(images.values()))[0]
    height, width = first.shape[:2]
    scale, label = 3, 150
    canvas = Image.new(
        "RGB", (label + width * scale * 2, 55 + len(images) * (height * scale + 25)), "#171b24"
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 8), title, fill="white")
    draw.text((label, 30), "Fixed camera / tick mean", fill="#d7dce6")
    draw.text((label + width * scale, 30), "Tracking camera / one-tick shutter", fill="#d7dce6")
    for row, (arm, pair) in enumerate(images.items()):
        top = 55 + row * (height * scale + 25)
        draw.text((8, top + 8), arm, fill="white")
        for column, rgb in enumerate(pair):
            output = replace(
                profiles[arm.split("_")[0]].output, eotf="srgb", reference_nits=reference
            )
            image = Image.fromarray(encode_frame(Frame(rgb), output)).resize(
                (width * scale, height * scale), Image.Resampling.NEAREST
            )
            canvas.paste(image, (label + column * width * scale, top))
    canvas.save(path)


def _plot(
    path: Path, traces: dict[str, list[float]], dt: Fraction, title: str, *, limit: int = 960
) -> None:
    canvas = Image.new("RGB", (1000, 360), "#171b24")
    draw = ImageDraw.Draw(canvas)
    draw.text((15, 10), title + " | P inputs; D output", fill="white")
    colors = ("#e2e8f0", "#fc8181", "#63b3ed", "#f6c453", "#a7f3d0", "#c4a1ff")
    peak = max(max(v) for v in traces.values()) or 1
    count = min(limit, max(len(v) for v in traces.values()))
    draw.rectangle((55, 45, 980, 295), outline="#667085")
    for j, (arm, values) in enumerate(traces.items()):
        points = [
            (55 + i * 925 / max(1, count - 1), 295 - values[i] / peak * 245)
            for i in range(min(count, len(values)))
        ]
        if len(points) > 1:
            draw.line(points, fill=colors[j], width=2)
        draw.text((55 + j * 155, 320), arm, fill=colors[j])
    draw.text(
        (60, 300), f"0 to {float(dt * count):g} seconds; Y 0 to {peak:.2f} nits", fill="white"
    )
    canvas.save(path)


def run_experiment(protocol: dict[str, Any], out: Path) -> dict[str, Any]:
    """Generate exclusive deterministic artifacts from an explicit P protocol."""
    validate_protocol(protocol)
    destination = _destination(out)
    profiles, configs = _profiles(), _configs(protocol)
    # Validate all compositions before creating the destination.
    admission = _pipelines(profiles, configs)
    s = protocol["settings"]
    fps = Fraction(s["output_fps"])
    dt, subdt = 1 / fps, 1 / (fps * s["substeps"])
    destination.mkdir(parents=True)
    _write_json(destination / "protocol.json", protocol)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "fixture_version": FIXTURE_VERSION,
        "implementation_sha256": {
            name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in (
                "subframe.py",
                "subframe_pipeline.py",
                "subframe_metrics.py",
                "subframe_experiment.py",
            )
        },
        "evidence": "D under P model/protocol; measured calibration and certification NR",
        "protocol_sha256": sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest(),
        "profiles": {name: asdict(p) for name, p in profiles.items()},
        "configs": {arm: asdict(config) for arm, config in configs.items()},
        "display_identity": {arm: pipeline.identity() for arm, pipeline in admission.items()},
        "preview": {
            "reference_nits": s["preview_reference_nits"],
            "exposure": "shared sRGB mapping; no per-arm normalization",
        },
        "sampling": "exact rational bin PTS/durations; emitted values are bin means; tracking uses midpoint spatial quadrature of those means",
        "clips": [],
        "gray_steps": [],
    }
    for name in ("moving_edge", "moving_bar"):
        for speed in s["speeds_px_s"]:
            key = f"{name}_{speed:g}"
            folder = destination / key
            folder.mkdir()
            content = _motion_content(name, s, speed)
            pipelines = _pipelines(profiles, configs)
            selected = len(content) // 2
            outputs: dict[str, np.ndarray] = {}
            camera: dict[str, np.ndarray] = {}
            images: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            metrics: dict[str, Any] = {}
            rows: list[list[Any]] = []
            for arm, pipeline in pipelines.items():
                shown = []
                for i, rgb in enumerate(content):
                    result = pipeline.display_subframes(Frame(rgb), pts=i * dt, duration=dt)
                    shown.append(result.mean)
                    rows.extend(_row(arm, i, j, sample) for j, sample in enumerate(result.samples))
                    if i == selected:
                        camera[arm] = pursuit_image(
                            [sample.rgb for sample in result.samples],
                            [sample.pts for sample in result.samples],
                            [sample.duration for sample in result.samples],
                            speed,
                            i * dt + dt / 2,
                        )
                outputs[arm] = np.stack(shown)
                images[arm] = (outputs[arm][selected], camera[arm])
                metrics[arm] = (
                    pursuit_metrics(camera[arm], speed)
                    if name == "moving_edge"
                    else {"mean_pursuit_nits": float(np.mean(luminance(camera[arm])))}
                )
            baseline = float(np.mean(luminance(camera["lcd_hold"])))
            for arm in ARMS:
                own_baseline = (
                    baseline
                    if arm.startswith("lcd")
                    else float(np.mean(luminance(camera["oled_hold"])))
                )
                metrics[arm]["brightness_retention"] = (
                    float(np.mean(luminance(camera[arm]))) / own_baseline
                )
                metrics[arm]["brightness_cost_percent"] = 100 * (
                    1 - metrics[arm]["brightness_retention"]
                )
            _csv(folder / "waveforms.csv", rows)
            _write_json(folder / "metrics.json", metrics)
            archive: dict[str, Any] = {
                "content": content,
                **outputs,
                **{f"pursuit_{arm}": image for arm, image in camera.items()},
            }
            np.savez_compressed(folder / "linear.npz", **archive)
            _contact(
                folder / "contact.png",
                images,
                s["preview_reference_nits"],
                f"{name}, {speed:g} px/s | shared {s['preview_reference_nits']:g}-nit reference",
                profiles,
            )
            manifest["clips"].append(
                {
                    "fixture": name,
                    "speed_px_s": speed,
                    "ticks": len(content),
                    "selected_tick": selected,
                    "contact_sheet": f"{key}/contact.png",
                    "waveform_file": f"{key}/waveforms.csv",
                    "metrics_file": f"{key}/metrics.json",
                    "linear_file": f"{key}/linear.npz",
                    "metrics": metrics,
                    "array_sha256": {
                        arm: sha256(outputs[arm].tobytes()).hexdigest() for arm in ARMS
                    },
                }
            )
    # Each GtG cell starts a fresh pipeline settled at its old level. The one
    # preparation tick is excluded from the rational response-relative times.
    count = int(Fraction(s["step_duration_s"]) * fps)
    for old in s["gray_levels_nits"]:
        for new in s["gray_levels_nits"]:
            if old == new:
                continue
            key = f"gray_{old:g}_{new:g}"
            folder = destination / key
            folder.mkdir()
            metrics, traces, rows = {}, {}, []
            panel_traces: dict[str, list[float]] = {}
            for arm, pipeline in _pipelines(profiles, configs).items():
                pipeline.display_subframes(
                    Frame(np.full((8, 8, 3), old, dtype=np.float32)), pts=Fraction(0), duration=dt
                )
                panel_values: list[float] = []
                times: list[float] = []
                light: list[float] = []
                for i in range(count):
                    result = pipeline.display_subframes(
                        Frame(np.full((8, 8, 3), new, dtype=np.float32)),
                        pts=(i + 1) * dt,
                        duration=dt,
                    )
                    for j, sample in enumerate(result.samples):
                        rows.append(_row(arm, i, j, sample))
                        light.append(float(np.mean(luminance(sample.rgb))))
                        panel_values.append(
                            float(np.mean(sample.panel[4, 4]))
                            * (LCD_ILLUMINATION_NITS if arm.startswith("lcd") else 1)
                        )
                        times.append(float(sample.pts + sample.duration - dt))
                metrics[arm] = response_metrics(
                    panel_values, times, old, new, settling_fraction=s["settling_fraction"]
                )
                metrics[arm]["sampling"] = (
                    "physical panel bin endpoints, un-gated; linear first crossings; emitted waveform saved separately"
                )
                traces[arm] = light
                panel_traces[arm] = panel_values
            _write_json(folder / "metrics.json", metrics)
            _csv(folder / "waveforms.csv", rows)
            _write_json(
                folder / "waveforms.json",
                {
                    "evidence": "D under P model",
                    "absolute_start_pts": str(dt),
                    "panel_endpoint_time": "pts + duration; response relative time subtracts absolute_start_pts",
                    "panel_endpoint_y_nits": panel_traces,
                    "sample_duration_s": str(subdt),
                    "emitted_mean_y_nits": traces,
                },
            )
            _plot(folder / "waveforms.png", traces, subdt, f"Gray step {old:g} to {new:g} nits")
            manifest["gray_steps"].append(
                {
                    "initial_nits": old,
                    "target_nits": new,
                    "waveform_plot": f"{key}/waveforms.png",
                    "waveform_file": f"{key}/waveforms.csv",
                    "metrics_file": f"{key}/metrics.json",
                    "metrics": metrics,
                }
            )
    folder = destination / "flashing_patch"
    folder.mkdir()
    count = int(Fraction(s["flash_duration_s"]) * fps)
    traces, static, rows = {}, {}, []
    for arm, pipeline in _pipelines(profiles, configs).items():
        light = []
        for i in range(count):
            on = (Fraction(i, 1) / fps * Fraction(str(s["flash_hz"]))) % 1 < Fraction(1, 2)
            rgb = np.full((s["height"], s["width"], 3), s["dark_nits"], dtype=np.float32)
            rgb[s["height"] // 4 : 3 * s["height"] // 4, s["width"] // 4 : 3 * s["width"] // 4] = (
                s["level_nits"] if on else s["dark_nits"]
            )
            result = pipeline.display_subframes(Frame(rgb), pts=i * dt, duration=dt)
            for j, sample in enumerate(result.samples):
                row = _row(arm, i, j, sample)
                rows.append(row)
                light.append(row[7])
        traces[arm] = light
        # A constant patch separates modulation from the requested flash.
        constant_pipeline = _pipelines(profiles, configs)[arm]
        constant: list[float] = []
        for i in range(count):
            result = constant_pipeline.display_subframes(
                Frame(np.full((8, 8, 3), s["level_nits"], dtype=np.float32)),
                pts=i * dt,
                duration=dt,
            )
            constant.extend(float(np.mean(luminance(sample.rgb))) for sample in result.samples)
        static[arm] = constant
    metrics = {
        arm: {
            "flashing_patch": flicker_metrics(traces[arm], subdt),
            "constant_patch": flicker_metrics(static[arm], subdt),
        }
        for arm in ARMS
    }
    for arm in ARMS:
        baseline = metrics["lcd_hold" if arm.startswith("lcd") else "oled_hold"]["constant_patch"][
            "mean_nits"
        ]
        retention = metrics[arm]["constant_patch"]["mean_nits"] / baseline
        metrics[arm]["constant_patch"].update(
            brightness_retention=retention, brightness_cost_percent=100 * (1 - retention)
        )
    _csv(folder / "waveforms.csv", rows)
    _write_json(
        folder / "waveforms.json",
        {
            "evidence": "D under P model",
            "absolute_start_pts": "0/1",
            "sample_duration_s": str(subdt),
            "emitted_mean_y_nits": traces,
            "constant_patch_mean_y_nits": static,
        },
    )
    _write_json(folder / "metrics.json", metrics)
    _plot(
        folder / "waveforms.png",
        traces,
        subdt,
        "Flashing patch; requested 5 Hz plus emission modulation",
    )
    _plot(
        folder / "constant.png",
        static,
        subdt,
        "Constant patch; PWM/strobe/BFI emission modulation",
        limit=192,
    )
    manifest["flicker"] = {
        "metrics": metrics,
        "waveform_file": "flashing_patch/waveforms.csv",
        "waveform_plot": "flashing_patch/waveforms.png",
        "constant_plot": "flashing_patch/constant.png",
    }
    _write_json(destination / "manifest.json", manifest)
    sections = "".join(
        f'<h2>{escape(clip["fixture"])}: {clip["speed_px_s"]:g} px/s</h2><img src="{clip["contact_sheet"]}"><p><a href="{clip["metrics_file"]}">Metrics</a> · <a href="{clip["waveform_file"]}">Exact rational PTS and waveforms</a></p>'
        for clip in manifest["clips"]
    )
    sections += "<h2>Gray-to-gray matrix: all six directed steps</h2>" + "".join(
        f'<img src="{cell["waveform_plot"]}"><a href="{cell["metrics_file"]}">Response/settling/overshoot metrics</a>'
        for cell in manifest["gray_steps"]
    )
    sections += '<h2>Flicker: flashing and constant patches</h2><img src="flashing_patch/waveforms.png"><img src="flashing_patch/constant.png"><a href="flashing_patch/metrics.json">Flicker and brightness metrics</a>'
    (destination / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Synthetic sub-frame temporal emission</title><style>body{font:15px system-ui;background:#eee;margin:30px;color:#222}img{max-width:100%;display:block;margin:15px 0}</style><h1>Synthetic sub-frame temporal emission</h1><p>P placeholders; D computed outputs; measured TV calibration NR. Shared exposure, no pulse brightness compensation. Fixed LCD illumination isolates response. Pursuit uses one display-tick tracking shutter and actual emitted bin means. Normalized MPRT = 10–90 width/(0.8 × speed); finite raster and quadrature contribute. These are not VESA certification or IEEE 1789 safety classifications. Static PNGs do not reproduce perceived flicker or host display luminance.</p>'
        + sections
        + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run explicit P sub-frame motion, GtG and flicker experiments"
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--out", type=Path, default=Path("reports/subframe-m18"))
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the isolated M18 diagnostic CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = run_experiment(load_protocol(args.protocol), args.out)
    except (OSError, ValueError, ZeroDivisionError) as exc:
        parser.error(str(exc))
    print(
        f"Saved {len(manifest['clips'])} P sub-frame motion clips, {len(manifest['gray_steps'])} gray steps and flicker waveforms to {args.out}"
    )


if __name__ == "__main__":
    main()
