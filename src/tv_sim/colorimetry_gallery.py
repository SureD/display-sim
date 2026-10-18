"""Synthetic M15 color-volume fixtures and a shared-exposure comparison.

All stimulus choices are P; XYZ and u'v' errors are D under the P panel model.
The source is declared BT.2020/D65. The skin/foliage-like patches are illustrative
linear colors, not measured reflectances or a ColorChecker dataset.
"""

from __future__ import annotations

import argparse
import colorsys
import json
from dataclasses import asdict
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any, cast

import numpy as np
from PIL import Image, ImageDraw

from tv_sim.color import pq_oetf, srgb_oetf
from tv_sim.gallery import PROFILE_LABELS, PROFILE_NAMES, _gallery_profile
from tv_sim.pipeline import Pipeline
from tv_sim.profile import load_profile, profile_path

REFERENCE_NITS = 2000.0  # P shared exposure, every profile/method/pattern.


def color_volume_patterns(width: int = 320, height: int = 180) -> dict[str, np.ndarray]:
    """P BT.2020 linear-nit source intents, with reproducible exact arrays."""
    if type(width) is not int or type(height) is not int or width < 24 or height < 16:
        raise ValueError("color-volume patterns require integer dimensions at least 24x16")
    from tv_sim.colorimetry import D65, RGB_SPACES, rgb_to_xyz_matrix

    colors = np.array(
        ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1), (1, 1, 1)),
        dtype=np.float32,
    )
    ramp = np.linspace(0, REFERENCE_NITS, width, dtype=np.float32)
    ramps = np.empty((height, width, 3), dtype=np.float32)
    for row in range(height):
        ramps[row] = ramp[:, None] * colors[min(6, row * 7 // height)]
    primaries = np.zeros_like(ramps)
    levels = (25.0, 100.0, 400.0, 1000.0, 2000.0)  # P channel-nit requests.
    for y in range(height):
        for x in range(width):
            # P separated windows occupy about half of the raster. This lowers
            # APL enough to expose RGBW color capacity as well as global ABL.
            if x * 7 % width < 0.7 * width and y * 5 % height < 0.7 * height:
                primaries[y, x] = colors[min(6, x * 7 // width)] * levels[min(4, y * 5 // height)]
    # P linear BT.709 colors, converted to BT.2020 to preserve their intent.
    rgb709 = np.array(
        (
            (0.58, 0.30, 0.20),
            (0.25, 0.105, 0.055),
            (0.07, 0.23, 0.045),
            (0.035, 0.10, 0.025),
            (0.18, 0.18, 0.18),
            (1, 1, 1),
        ),
        dtype=np.float64,
    )
    m709 = rgb_to_xyz_matrix(RGB_SPACES["bt709"], D65)
    m2020 = rgb_to_xyz_matrix(RGB_SPACES["bt2020"], D65)
    patch_colors = rgb709 @ (np.linalg.inv(m2020) @ m709).T
    patches = np.empty_like(ramps)
    for y in range(height):
        for x in range(width):
            patches[y, x] = patch_colors[min(5, x * 6 // width)] * (
                100.0 if y < height // 2 else 1000.0
            )
    hues = np.array([colorsys.hsv_to_rgb(x / width, 1, 1) for x in range(width)], dtype=np.float32)
    sweep = np.empty_like(ramps)
    for y in range(height):
        neutral = y / max(height - 1, 1)
        sweep[y] = (hues * (1 - neutral) + neutral) * 1000.0
    return {
        "saturated_ramps": ramps,
        "bt2020_rgb_cmy_white": primaries,
        "skin_foliage_like": patches,
        "hue_saturation_sweep": sweep,
    }


def xyz_uv(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """D CIE 1976 u'v'; black has no chromaticity and is masked, never scored."""
    xyz = np.asarray(xyz, dtype=np.float64)
    den = xyz[..., 0] + 15 * xyz[..., 1] + 3 * xyz[..., 2]
    valid = (den > 1e-12) & (xyz[..., 1] > 1e-6)
    uv = np.zeros(xyz.shape[:-1] + (2,), dtype=np.float64)
    np.divide(4 * xyz[..., 0], den, out=uv[..., 0], where=valid)
    np.divide(9 * xyz[..., 1], den, out=uv[..., 1], where=valid)
    return uv, valid


def color_errors(intent_xyz: np.ndarray, output_xyz: np.ndarray) -> dict:
    """D errors against source intent, excluding undefined black chromaticity."""
    uv0, valid0 = xyz_uv(intent_xyz)
    uv1, valid1 = xyz_uv(output_xyz)
    valid = valid0 & valid1
    distances = np.linalg.norm(uv1 - uv0, axis=-1)[valid]
    delta_y = np.asarray(output_xyz)[..., 1] - np.asarray(intent_xyz)[..., 1]
    return {
        "evidence": "D under P model",
        "metric": "CIE 1976 Euclidean u'v' chromaticity distance; not Delta E",
        "valid_chromaticity_pixels": int(valid.sum()),
        "excluded_pixels": int((~valid).sum()),
        "mean_delta_uv": float(distances.mean()) if distances.size else None,
        "max_delta_uv": float(distances.max()) if distances.size else None,
        "mean_signed_Y_error_nits": float(delta_y.mean()),
        "mean_absolute_Y_error_nits": float(np.abs(delta_y).mean()),
        "max_absolute_Y_error_nits": float(np.abs(delta_y).max()),
        "intent_mean_Y_nits": float(np.asarray(intent_xyz)[..., 1].mean()),
        "output_mean_Y_nits": float(np.asarray(output_xyz)[..., 1].mean()),
        "black_policy": "Exclude chromaticity when either XYZ Y <= 1e-6 nit or denominator <= 1e-12; retain Y error.",
    }


def diagnostic_summary(value: Any) -> Any:
    """Retain scalar diagnostics in JSON; masks are saved separately if needed."""
    if isinstance(value, np.ndarray):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "sha256": sha256(np.ascontiguousarray(value).tobytes()).hexdigest(),
        }
    if isinstance(value, dict):
        return {key: diagnostic_summary(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [diagnostic_summary(item) for item in value]
    return value.item() if isinstance(value, np.generic) else value


def generate_colorimetry_gallery(out: Path, width: int = 320, height: int = 180) -> dict:
    """Run both mappers on four panels; save XYZ truth, errors, SDR previews."""
    from tv_sim.colorimetry import D65, RGB_SPACES, ColorimetryConfig, rgb_to_xyz_matrix

    if width < 160 or height < 96:
        raise ValueError("colorimetry gallery resolution must be at least 160x96")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text(
        "# Reproducible full-precision intents, outputs and masks\n*.npy\n"
    )
    patterns = color_volume_patterns(width, height)
    source_matrix = rgb_to_xyz_matrix(RGB_SPACES["bt2020"], D65)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "synthetic_colorimetry_comparison",
        "parameter_evidence": "P",
        "calibrated_profile_fit": "NR",
        "spectra": "NR",
        "source": {
            "primaries": "bt2020",
            "white_xy": list(D65),
            "transfer": "float PQ to linear nits",
            "rgb_to_xyz": source_matrix.tolist(),
            "mastering_gamut": "NR",
        },
        "preview": {
            "reference_nits": REFERENCE_NITS,
            "evidence": "P",
            "space": "sRGB / BT.709 D65",
            "transform": "panel RGB to linear BT.709, shared division by reference, clip, sRGB OETF",
            "limitation": "SDR preview clipping can hide wide-gamut differences; raw XYZ and metrics remain authoritative.",
        },
        "stimuli": {
            "evidence": "P",
            "ramp_max_channel_nits": REFERENCE_NITS,
            "primary_secondary_channel_levels_nits": [25, 100, 400, 1000, 2000],
            "primary_secondary_window_cell_fill_per_axis": 0.7,
            "skin_foliage": "Illustrative BT.709-linear colors converted to BT.2020; not measured reflectances.",
            "patch_levels_nits": [100, 1000],
            "hue_sweep_channel_nits": 1000,
        },
        "profiles": [],
        "results": [],
        "sheets": [],
    }
    for name in PROFILE_NAMES:
        profile = load_profile(name)
        sidecar = profile_path(name).with_name(name + ".colorimetry.yaml")
        manifest["profiles"].append(
            {
                "name": name,
                "profile_sha256": sha256(profile_path(name).read_bytes()).hexdigest(),
                "sidecar_sha256": sha256(sidecar.read_bytes()).hexdigest(),
                "effective_settings": asdict(_gallery_profile(profile)),
            }
        )
    for identifier, source in patterns.items():
        intent_xyz = source.astype(np.float64) @ source_matrix.T
        np.save(out / f"{identifier}.intent_xyz.npy", intent_xyz)
        np.save(out / f"{identifier}.source_bt2020.npy", source)
        sheet = Image.new("RGB", (4 * width, 2 * (height + 70) + 54), "#111821")
        draw = ImageDraw.Draw(sheet)
        draw.text(
            (12, 10),
            f"M15 P color volume: {identifier} | all tiles: {REFERENCE_NITS:g} nit = preview white",
            fill="white",
        )
        draw.text(
            (12, 29),
            "Declared BT.2020/D65; SDR preview clips host gamut. No named TV calibration.",
            fill="#c6ccd5",
        )
        for row, method in enumerate(("clip", "compress")):
            for col, (name, label) in enumerate(zip(PROFILE_NAMES, PROFILE_LABELS)):
                config = ColorimetryConfig(
                    enabled=True, source_primaries="bt2020", gamut_mapping=method
                )
                pipeline = Pipeline(_gallery_profile(load_profile(name)), colorimetry=config)
                frame = pipeline.run_linear(pq_oetf(source))
                output_xyz = pipeline.output_in_space(frame, "xyz")
                rgb709 = pipeline.output_in_space(frame, "bt709")
                preview = np.round(srgb_oetf(rgb709 / REFERENCE_NITS) * 255).astype(np.uint8)
                x, y = col * width, 54 + row * (height + 70)
                sheet.paste(Image.fromarray(preview), (x, y + 22))
                metrics = color_errors(intent_xyz, output_xyz)
                draw.text((x + 6, y + 3), f"{label} / {method}", fill="white")
                draw.text(
                    (x + 6, y + height + 28),
                    f"mean duv {metrics['mean_delta_uv']:.5f}",
                    fill="#d1d6df",
                )
                draw.text(
                    (x + 6, y + height + 44),
                    f"mean Y {metrics['output_mean_Y_nits']:.1f} nit",
                    fill="#d1d6df",
                )
                stem = f"{identifier}.{name}.{method}"
                np.save(out / f"{stem}.xyz.npy", output_xyz)
                _, chromaticity_mask = xyz_uv(intent_xyz)
                np.save(out / f"{stem}.valid_uv.npy", chromaticity_mask & xyz_uv(output_xyz)[1])
                diagnostics = cast(dict, pipeline.last_colorimetry_diagnostics)
                for key, value in diagnostics.items():
                    if isinstance(value, np.ndarray):
                        np.save(out / f"{stem}.{key}.npy", value)
                manifest["results"].append(
                    {
                        "pattern": identifier,
                        "profile": name,
                        "method": method,
                        "source_sha256": sha256(source.tobytes()).hexdigest(),
                        "output_xyz_sha256": sha256(output_xyz.tobytes()).hexdigest(),
                        "colorimetry": pipeline.colorimetry_metadata(),
                        "diagnostics": diagnostic_summary(diagnostics),
                        "intent_errors": metrics,
                        "linear_xyz_file": f"{stem}.xyz.npy",
                    }
                )
        filename = f"{identifier}.png"
        sheet.save(out / filename)
        manifest["sheets"].append({"pattern": identifier, "file": filename})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    sections = "".join(
        f'<h2>{escape(s["pattern"])}</h2><a href="{s["file"]}"><img src="{s["file"]}" alt="{escape(s["pattern"])}"></a>'
        for s in manifest["sheets"]
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        "<title>M15 synthetic color volume</title><style>body{background:#111821;color:#eef;font:16px system-ui;margin:24px}img{width:100%;max-width:1600px}a{color:#9ee}</style>"
        "<h1>M15 synthetic color volume (P)</h1><p>Four placeholder panels, clip and CIE u′v′ hue-ray compression. "
        "Every tile uses one shared 2000-nit exposure. SDR clipping limits visual gamut assessment. "
        "Errors compare complete pipeline XYZ with declared BT.2020/D65 source intent; u′v′ distance excludes black and does not measure luminance error or perceptual ΔE. "
        "No named TV is calibrated. Spectra and measured color-volume fits remain NR.</p>"
        '<p><a href="manifest.json">Exact settings, color matrices, diagnostics and error metrics</a></p>'
        + sections
        + "</html>"
    )
    (out / "index.html").write_text(page)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("reports/colorimetry-m15"))
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        result = generate_colorimetry_gallery(args.out, args.width, args.height)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        f"Wrote {len(result['sheets'])} shared-exposure colorimetry sheets to {args.out / 'index.html'}"
    )
