"""Pattern harness: ``python -m sim validate``.

Renders ANSI contrast, a white-window sweep, full-field white and black,
a grey ramp, a PQ ramp, and a moving edge through :class:`sim.pipeline.Pipeline`.
Profile YAML is not modified. PQ windows and the PQ ramp force the input
EOTF to PQ for that pattern only. BFI and overdrive comparisons are harness
stimuli: they are omitted when the profile cannot engage that hook, and a
non-zero probe gain is never written back as a profile value.

Numbers are simulator outputs on placeholder profiles, not measurements.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from sim.color import luminance, pq_eotf, srgb_eotf
from sim.metrics import (
    abl_ratios,
    ansi_contrast,
    blur_width_ms,
    contrast_ratio,
    eotf_tracking,
    motion_blur_px,
    moving_edge_blur_px,
    window_bloom,
)
from sim.patterns import window_bounds
from sim.pipeline import Pipeline
from sim.profile import TVProfile, available_profiles, load_profile
from sim.stages.encode import encode_frame
from sim.stages.temporal import TemporalState

WINDOW_FRACTIONS = (0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 1.0)
PQ_WHITE = 1.0
# Harness stimuli. These are not profile fields.
BFI_COMPARISON_DUTY = 0.5
OVERDRIVE_PROBE_GAIN = 0.5

DISCLAIMER = (
    "Simulator outputs from placeholder profiles. Not laboratory measurements. "
    "Do not compare these figures to a retail set without saying they are synthetic."
)


def _require_grid(height: int, width: int, cells: int = 4) -> None:
    if height < cells or width < cells or height % cells or width % cells:
        raise ValueError(f"resolution {width}x{height} must be divisible by {cells}")


def ansi_pattern(height: int, width: int, cells: int = 4) -> np.ndarray:
    """4×4 checker of code 0 and 1. Top-left is black."""

    _require_grid(height, width, cells)
    yy, xx = np.indices((height, width))
    cell_h, cell_w = height // cells, width // cells
    white = ((yy // cell_h) + (xx // cell_w)) % 2 == 1
    image = np.zeros((height, width, 3), dtype=np.float32)
    image[white] = 1.0
    return image


def solid(height: int, width: int, code: float) -> np.ndarray:
    return np.full((height, width, 3), np.float32(code), dtype=np.float32)


def pq_window(height: int, width: int, fraction: float) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    image = np.zeros((height, width, 3), dtype=np.float32)
    y0, y1, x0, x1 = window_bounds(width, height, fraction)
    image[y0:y1, x0:x1] = np.float32(PQ_WHITE)
    return image, (y0, y1, x0, x1)


def grey_ramp(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    """uint8 sRGB ramp and the code values actually stored in it."""

    row = np.linspace(0, 255, width)
    codes = (row.astype(np.uint8).astype(np.float64)) / 255.0
    plane = np.broadcast_to(row.astype(np.uint8), (height, width))
    return np.stack([plane, plane, plane], axis=-1), codes


def pq_ramp(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    codes = np.linspace(0.0, 1.0, width, dtype=np.float64)
    plane = np.broadcast_to(codes.astype(np.float32), (height, width))
    return np.stack([plane, plane, plane], axis=-1), codes


def moving_edge_frame(height: int, width: int, x_edge: float) -> np.ndarray:
    """sRGB black/white step. Columns at and to the right of ``x_edge`` are white."""

    image = np.zeros((height, width, 3), dtype=np.uint8)
    start = int(np.ceil(x_edge))
    if start < width:
        image[:, max(0, start) :] = 255
    return image


def ideal_ramp_nits(codes: np.ndarray, eotf: str, sdr_white_nits: float) -> np.ndarray:
    which = eotf.lower()
    if which == "srgb":
        return np.asarray(srgb_eotf(codes), dtype=np.float64) * float(sdr_white_nits)
    if which == "pq":
        decoded = np.asarray(pq_eotf(codes), dtype=np.float64)
        return decoded
    raise ValueError(f"ramp ideal is implemented for srgb and pq, not {eotf!r}")


def _render(profile: TVProfile, encoded: np.ndarray, state: TemporalState | None = None):
    return Pipeline(profile, state).run_linear(encoded)


def _column_nits(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(luminance(rgb), dtype=np.float64).mean(axis=0)


def _preview(frame_rgb: np.ndarray, profile: TVProfile) -> np.ndarray:
    """sRGB preview scaled so this frame's maximum maps to code 1."""

    peak = float(np.max(frame_rgb))
    reference = max(peak, 1e-3)
    output = replace(profile.output, eotf="srgb", reference_nits=reference)
    from sim.frame import Frame

    return encode_frame(Frame(frame_rgb), output)


def _save_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, mode="RGB").save(path)


def _save_montage(path: Path, images: list[np.ndarray], thumb_height: int = 72) -> None:
    thumbs: list[Image.Image] = []
    for image in images:
        picture = Image.fromarray(image, mode="RGB")
        thumb_w = max(1, int(round(image.shape[1] * thumb_height / image.shape[0])))
        thumbs.append(picture.resize((thumb_w, thumb_height), Image.Resampling.BOX))
    canvas = Image.new("RGB", (sum(item.width for item in thumbs), thumb_height))
    x = 0
    for item in thumbs:
        canvas.paste(item, (x, 0))
        x += item.width
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _ring_px(height: int, width: int) -> tuple[int, int]:
    far = max(6, min(height, width) // 18)
    near = max(2, far // 4)
    if far <= near:
        far = near + 1
    return near, far


def _edge_blur(profile: TVProfile, height: int, width: int, frames: int, motion_px: float) -> dict:
    start = width / 5.0
    end = start + (frames - 1) * motion_px
    if end >= width - width / 5.0:
        raise ValueError(
            f"moving edge exits the {width}px frame "
            f"(start {start:.1f}, motion {motion_px}, frames {frames})"
        )
    state = TemporalState()
    last = None
    x_final = start + (frames - 1) * motion_px
    for index in range(frames):
        encoded = moving_edge_frame(height, width, start + index * motion_px)
        last = _render(profile, encoded, state)
    assert last is not None
    y0 = height // 3
    y1 = height - y0
    profile_1d = np.asarray(luminance(last.rgb[y0:y1]), dtype=np.float64).mean(axis=0)
    blur_px = moving_edge_blur_px(profile_1d)
    # Same edge, settled, no pursuit. This is the optical/processing width.
    still_profile = _with_temporal(profile, motion_px_per_frame=0.0)
    still = _render(still_profile, moving_edge_frame(height, width, x_final))
    still_1d = np.asarray(luminance(still.rgb[y0:y1]), dtype=np.float64).mean(axis=0)
    still_px = moving_edge_blur_px(still_1d)
    added_px = motion_blur_px(blur_px, still_px)
    return {
        "blur_px": blur_px,
        "blur_ms": blur_width_ms(blur_px, motion_px, profile.temporal.frame_time_ms),
        "still_blur_px": still_px,
        "motion_blur_px": added_px,
        "motion_blur_ms": blur_width_ms(added_px, motion_px, profile.temporal.frame_time_ms),
        "overdrive_gain": float(profile.temporal.overdrive_gain),
        "overdrive_ms": float(profile.temporal.overdrive_ms),
        "bfi_duty": float(profile.temporal.bfi_duty),
        "motion_px_per_frame": float(motion_px),
        "frames": int(frames),
        "preview_rgb": last.rgb,
    }


def _with_temporal(profile: TVProfile, **kwargs: float) -> TVProfile:
    return replace(profile, temporal=replace(profile.temporal, **kwargs))


def evaluate_profile(
    profile: TVProfile,
    *,
    height: int,
    width: int,
    motion_px: float,
    edge_frames: int,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Metrics for one profile and the preview images (uint8 RGB)."""

    _require_grid(height, width)
    near_px, far_px = _ring_px(height, width)
    hdr = profile.with_overrides(input_eotf="pq")
    moving = profile.with_overrides(motion_px=motion_px)

    black = _render(hdr, solid(height, width, 0.0))
    white = _render(hdr, solid(height, width, PQ_WHITE))
    black_y = luminance(black.rgb)
    white_y = luminance(white.rgb)
    on_white = float(np.mean(white_y))
    on_black = float(np.mean(black_y))

    ansi = _render(hdr, ansi_pattern(height, width))
    ansi_metrics = ansi_contrast(luminance(ansi.rgb))

    windows = []
    window_previews: list[np.ndarray] = []
    for fraction in WINDOW_FRACTIONS:
        if fraction >= 1.0 - 1e-9:
            frame = white
            bounds = (0, height, 0, width)
        else:
            encoded, bounds = pq_window(height, width, fraction)
            frame = _render(hdr, encoded)
        y0, y1, x0, x1 = bounds
        bloom = window_bloom(
            luminance(frame.rgb),
            y0,
            y1,
            x0,
            x1,
            near_px=near_px,
            far_px=far_px,
            black_luminance=None if fraction >= 1.0 - 1e-9 else black_y,
        )
        actual = ((y1 - y0) * (x1 - x0)) / float(height * width)
        windows.append(
            {
                "area_fraction_requested": fraction,
                "area_fraction_actual": actual,
                **bloom,
            }
        )
        window_previews.append(_preview(frame.rgb, profile))
    ratios = abl_ratios([float(item["peak_nits"]) for item in windows])
    for item, ratio in zip(windows, ratios):
        item["abl_ratio_vs_smallest"] = ratio

    grey_image, grey_codes = grey_ramp(height, width)
    grey = _render(profile, grey_image)
    grey_ideal = ideal_ramp_nits(grey_codes, profile.input.eotf, profile.input.sdr_white_nits)
    grey_metrics = eotf_tracking(_column_nits(grey.rgb), grey_ideal, grey_codes)
    grey_metrics["input_eotf"] = profile.input.eotf

    pq_image, pq_codes = pq_ramp(height, width)
    pq = _render(hdr, pq_image)
    pq_ideal = ideal_ramp_nits(pq_codes, "pq", profile.input.sdr_white_nits)
    pq_metrics = eotf_tracking(_column_nits(pq.rgb), pq_ideal, pq_codes)
    pq_metrics["input_eotf"] = "pq"

    as_configured = _edge_blur(moving, height, width, edge_frames, motion_px)
    temporal = profile.temporal
    if temporal.bfi_duty < 1.0 - 1e-6:
        bfi_profile = _with_temporal(moving, bfi_duty=1.0)
        bfi_note = "profile duty is below 1; comparison is duty 1 (BFI off)"
        bfi_duty = 1.0
    else:
        bfi_profile = _with_temporal(moving, bfi_duty=BFI_COMPARISON_DUTY, bfi_preserve_mean=False)
        bfi_note = (
            f"profile duty is 1; comparison duty {BFI_COMPARISON_DUTY} is a harness "
            "stimulus, not a profile setting"
        )
        bfi_duty = BFI_COMPARISON_DUTY
    bfi_case = _edge_blur(bfi_profile, height, width, edge_frames, motion_px)

    overdrive: dict
    if temporal.overdrive_ms > 0.0:
        if temporal.overdrive_gain > 0.0:
            probe = _with_temporal(moving, overdrive_gain=0.0)
            probe_note = "profile gain is already positive; comparison sets gain to 0"
            probe_gain = 0.0
        else:
            probe = _with_temporal(moving, overdrive_gain=OVERDRIVE_PROBE_GAIN)
            probe_note = (
                f"profile gain is 0; probe gain {OVERDRIVE_PROBE_GAIN} is a harness "
                "stimulus, not a profile value"
            )
            probe_gain = OVERDRIVE_PROBE_GAIN
        probed = _edge_blur(probe, height, width, edge_frames, motion_px)
        overdrive = {
            "supported": True,
            "note": probe_note,
            "profile_gain": float(temporal.overdrive_gain),
            "comparison_gain": probe_gain,
            "blur_px_profile": as_configured["blur_px"],
            "motion_blur_px_profile": as_configured["motion_blur_px"],
            "blur_px_comparison": probed["blur_px"],
            "motion_blur_px_comparison": probed["motion_blur_px"],
        }
    else:
        overdrive = {
            "supported": False,
            "note": "overdrive_ms is 0, so the overdrive prefix cannot run",
            "profile_gain": float(temporal.overdrive_gain),
            "comparison_gain": None,
            "blur_px_profile": as_configured["blur_px"],
            "motion_blur_px_profile": as_configured["motion_blur_px"],
            "blur_px_comparison": None,
            "motion_blur_px_comparison": None,
        }

    metrics = {
        "technology": profile.technology,
        "disclaimer": DISCLAIMER,
        "resolution": [width, height],
        "ansi": ansi_metrics,
        "on_off": {
            "white_nits": on_white,
            "black_nits": on_black,
            "contrast_ratio": contrast_ratio(on_white, on_black),
            "input_eotf": "pq",
            "white_code": PQ_WHITE,
        },
        "windows": windows,
        "window_ring_px": {"near": near_px, "far": far_px},
        "grey_ramp": grey_metrics,
        "pq_ramp": pq_metrics,
        "mprt": {
            "motion_px_per_frame": motion_px,
            "frame_time_ms": float(temporal.frame_time_ms),
            "definition": (
                "blur_px is the 10-90 percent width of the pursuit-integrated edge "
                "after the full pipeline, so backlight spread is included. "
                "motion_blur_px removes the still-edge width in quadrature."
            ),
            "as_configured": {
                key: value for key, value in as_configured.items() if key != "preview_rgb"
            },
            "bfi": {
                "note": bfi_note,
                "profile_duty": float(temporal.bfi_duty),
                "comparison_duty": bfi_duty,
                "blur_px_profile_duty": as_configured["blur_px"],
                "blur_ms_profile_duty": as_configured["blur_ms"],
                "motion_blur_px_profile_duty": as_configured["motion_blur_px"],
                "motion_blur_ms_profile_duty": as_configured["motion_blur_ms"],
                "blur_px_comparison_duty": bfi_case["blur_px"],
                "blur_ms_comparison_duty": bfi_case["blur_ms"],
                "motion_blur_px_comparison_duty": bfi_case["motion_blur_px"],
                "motion_blur_ms_comparison_duty": bfi_case["motion_blur_ms"],
            },
            "overdrive": overdrive,
        },
    }
    previews = {
        "checkerboard": _preview(ansi.rgb, profile),
        "window_sweep": window_previews,
        "moving_edge": _preview(as_configured["preview_rgb"], profile),
    }
    return metrics, previews


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.floating, float)):
        value = float(value)
        if not np.isfinite(value):
            return None
        return float(f"{value:.6g}")
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.bool_, bool)) or value is None or isinstance(value, str):
        return bool(value) if isinstance(value, np.bool_) else value
    raise TypeError(f"cannot serialize {type(value)!r}")


def _flatten(prefix: str, value, rows: list[tuple[str, str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            _flatten(child, item, rows)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, rows)
    else:
        if isinstance(value, float):
            text = f"{value:.6g}"
        elif value is None:
            text = ""
        else:
            text = str(value)
        rows.append((prefix, text, "" if value is None else type(value).__name__))


def write_reports(out_dir: Path, payload: dict, previews: dict[str, dict[str, np.ndarray]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    document = _json_ready(payload)
    (out_dir / "metrics.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    rows: list[tuple[str, str, str, str]] = []
    for name, metrics in document["profiles"].items():
        flat: list[tuple[str, str, str]] = []
        _flatten("", metrics, flat)
        for metric, text, kind in flat:
            rows.append((name, metric, text, kind))
    with (out_dir / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["profile", "metric", "value", "python_type"])
        writer.writerows(rows)
    for name, images in previews.items():
        _save_png(out_dir / f"{name}_checkerboard.png", images["checkerboard"])
        _save_png(out_dir / f"{name}_moving_edge.png", images["moving_edge"])
        _save_montage(out_dir / f"{name}_window_sweep.png", images["window_sweep"])


def run_validation(
    profiles: list[str],
    out_dir: Path,
    *,
    height: int = 216,
    width: int = 384,
    motion_px: float = 8.0,
    edge_frames: int = 6,
) -> dict:
    payload: dict = {
        "disclaimer": DISCLAIMER,
        "resolution": [width, height],
        "window_fractions": list(WINDOW_FRACTIONS),
        "preview": (
            "PNGs are sRGB previews with each frame scaled so its maximum nit "
            "maps to code 1. They are not radiometric images."
        ),
        "profiles": {},
    }
    previews: dict[str, dict[str, np.ndarray]] = {}
    for name in profiles:
        profile = load_profile(name)
        metrics, images = evaluate_profile(
            profile,
            height=height,
            width=width,
            motion_px=motion_px,
            edge_frames=edge_frames,
        )
        payload["profiles"][name] = metrics
        previews[name] = images
    write_reports(out_dir, payload, previews)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render validation patterns through each TV profile and write "
            "metrics plus preview PNGs. Results are simulator outputs, not measurements."
        )
    )
    parser.add_argument(
        "--profiles",
        nargs="*",
        default=None,
        help="Profile names (default: every YAML file in sim/profiles)",
    )
    parser.add_argument("--out", type=Path, default=Path("reports"), help="Output directory")
    parser.add_argument("--width", type=int, default=384)
    parser.add_argument("--height", type=int, default=216)
    parser.add_argument("--motion-px", type=float, default=8.0, help="Pursuit speed in pixels per frame")
    parser.add_argument("--edge-frames", type=int, default=6, help="Moving-edge sequence length")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    names = list(args.profiles) if args.profiles else available_profiles()
    if not names:
        raise SystemExit("no profiles selected")
    run_validation(
        names,
        args.out,
        height=args.height,
        width=args.width,
        motion_px=args.motion_px,
        edge_frames=args.edge_frames,
    )
