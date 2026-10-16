"""Offline, reproducible visual comparisons: ``python3 -m sim gallery``.

Sources are procedural linear-nit RGB patterns, PQ encoded before entering the
ordinary pipeline. Every row uses one declared preview transform for all TVs.
This is a mechanism demonstration on synthetic profiles, not TV calibration.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from html import escape
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sim.color import luminance, pq_oetf, srgb_oetf
from sim.pipeline import Pipeline
from sim.profile import TVProfile, load_profile, profile_path


PROFILE_NAMES = (
    "generic_va_fald_miniled", "generic_ips_edge", "generic_woled", "generic_qdoled",
)
PROFILE_LABELS = ("VA mini-LED / FALD", "IPS / edge strips", "WOLED / RGBW", "QD-OLED / triangular")
DISCLAIMER = "PLACEHOLDER PARAMETERS - synthetic mechanisms, not measured TVs."
HDR_REFERENCE = 2000.0
SHADOW_REFERENCE = 10.0
MOTION_REFERENCE = 100.0
MACRO_REFERENCE = 1000.0
PRE_ROLL = 12
PAN_FRAMES = 36
PAN_SPEED = 8.0
INTEGRATION_SAMPLES = 16


def preview(rgb: np.ndarray, reference_nits: float) -> np.ndarray:
    """Shared linear exposure then sRGB; no per-image normalization."""
    if not np.isfinite(reference_nits) or reference_nits <= 0:
        raise ValueError("reference_nits must be positive and finite")
    if not np.isfinite(rgb).all():
        raise ValueError("gallery output contains nonfinite values")
    return np.round(srgb_oetf(np.maximum(rgb, 0) / reference_nits) * 255).astype(np.uint8)


def _font(size: int = 14):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 10.0 has only the fixed-size bundled font.
        return ImageFont.load_default()


def _text_mask(width: int, height: int, text: str, size: int) -> np.ndarray:
    mask = Image.new("L", (width, height))
    draw = ImageDraw.Draw(mask)
    box = draw.textbbox((0, 0), text, font=_font(size))
    draw.text(((width - box[2]) // 2, (height - box[3]) // 2), text, fill=255, font=_font(size))
    return np.asarray(mask, dtype=np.float32) / 255.0


def scenes(width: int, height: int) -> dict[str, np.ndarray]:
    """Deterministic absolute-nit stimuli; the same arrays feed every TV."""
    stars = np.zeros((height, width, 3), np.float32)
    # Sparse stars leave dark FALD zones, unlike a screen-filling random field.
    for fx, fy, radius, level in (
        (.18, .24, 1, 2000), (.31, .40, 0, 1600), (.23, .66, 1, 1000),
        (.63, .22, 0, 2000), (.75, .54, 1, 1600), (.67, .70, 0, 800),
        (.83, .32, 0, 1200), (.43, .19, 0, 600),
    ):
        x, y = int(width * fx), int(height * fy)
        stars[y-radius:y+radius+1, x-radius:x+radius+1] = level
    subtitles = np.zeros_like(stars)
    subtitle_h = max(20, height // 4)
    mask = _text_mask(width, subtitle_h, "A light in the dark.", max(12, width // 17))
    y0 = height * 2 // 3
    subtitles[y0:y0+subtitle_h] = 1000 * mask[..., None]
    window = np.zeros_like(stars)
    y0, y1 = int(height * .25), int(height * .65)
    x0, x1 = int(width * .34), int(width * .64)
    window[y0:y1, x0:x1] = 2000  # ~12% of the raster.
    wide = np.zeros_like(stars)
    wide[height//8:height*7//8, width//8:width*7//8] = 2000  # ~56%.
    gradients = np.zeros_like(stars)
    x = np.linspace(0, 1, width, dtype=np.float32)
    ramps = (
        np.repeat((100 * x)[:, None], 3, axis=1),
        np.repeat((2000 * x)[:, None], 3, axis=1),
        np.repeat((2 * x)[:, None], 3, axis=1),
        np.stack((1000*x, 1000*(1-x), 500*np.ones_like(x)), axis=1),
    )
    for index, ramp in enumerate(ramps):
        gradients[height*index//4:height*(index+1)//4] = ramp[None]
    motion = np.full_like(stars, 1.0)
    for fraction, thickness, level in ((.16, 2, 100), (.25, 4, 100), (.36, 8, 70), (.51, 16, 100)):
        x0 = int(width * fraction)
        motion[height//9:height*5//9, x0:x0+thickness] = level
    motion[height//8:height//2, width*7//10:width*9//10] = 60
    # A dark cutout exposes slow bright-to-dark decay as well as rising edges.
    motion[height//5:height*2//5, width*3//4:width*4//5] = 0
    mask = _text_mask(width, height//3, "PAN 60 fps", max(14, width//14))
    motion[height*2//3:height*2//3+height//3] += 99 * mask[..., None]
    macro = np.full_like(stars, 60)
    # Central logical 16x8 crop: neutral top, saturated RGBW bars below.
    cy, cx = height//2-4, width//2-8
    patch = macro[cy:cy+8, cx:cx+16]
    patch[:4] = 100
    for i, color in enumerate(((100, 0, 0), (0, 100, 0), (0, 0, 100), (100, 100, 100))):
        patch[4:, i*4:(i+1)*4] = color
    for i in range(4):
        patch[i, i:i+2] = 0
    return {"starfield": stars, "subtitles": subtitles, "bright_window": window,
            "wide_window": wide, "gradients": gradients, "motion_pan": motion,
            "macro_subpixel": macro}


def _gallery_profile(profile: TVProfile, *, motion: float = 0) -> TVProfile:
    return replace(
        profile, input=replace(profile.input, eotf="pq"),
        panel=replace(profile.panel, viewing_angle_deg=0),
        ambient=replace(profile.ambient, lux=0),
        temporal=replace(profile.temporal, motion_px_per_frame=motion,
                         integration_samples=INTEGRATION_SAMPLES),
    )


def render_still(profile: TVProfile, source: np.ndarray) -> np.ndarray:
    return Pipeline(_gallery_profile(profile)).run_linear(pq_oetf(source)).rgb


def render_pan(profile: TVProfile, source: np.ndarray, mode: str) -> dict[int, np.ndarray]:
    """Pre-roll, then advance one persistent pipeline through the whole pan."""
    configured = _gallery_profile(profile, motion=PAN_SPEED)
    temporal = configured.temporal
    if mode == "overdrive" and not profile.self_emissive:
        temporal = replace(temporal, overdrive_gain=.8, overdrive_ms=4.0)
    elif mode == "bfi":
        temporal = replace(temporal, bfi_duty=.25, bfi_preserve_mean=False)
    elif mode not in ("hold", "overdrive"):
        raise ValueError(f"unknown pan mode {mode!r}")
    pipeline = Pipeline(replace(configured, temporal=temporal))
    encoded = pq_oetf(source)
    for _ in range(PRE_ROLL):
        pipeline.run_linear(encoded)
    captures = {}
    for index in range(1, PAN_FRAMES + 1):
        panned = np.roll(encoded, int(index * PAN_SPEED), axis=1)
        result = pipeline.run_linear(panned).rgb
        if index in (1, 12, PAN_FRAMES):
            captures[index] = result
    return captures


@dataclass
class Row:
    title: str
    note: str
    images: list[np.ndarray]
    reference: float
    captions: list[str] | None = None


def contact_sheet(path: Path, title: str, rows: list[Row]) -> None:
    """Four TV columns with transform labels retained in the PNG itself."""
    width = rows[0].images[0].shape[1]
    gap, header, row_label = 12, 104, 46
    caption_font = _font(12)

    def wrap(text: str) -> list[str]:
        lines, line = [], ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and caption_font.getlength(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        return lines + [line]

    caption_rows = []
    for row in rows:
        captions = row.captions or [f"Peak channel {rgb.max():.1f} | mean Y {luminance(rgb).mean():.2f} nit" for rgb in row.images]
        lines = [wrap(caption) for caption in captions]
        caption_rows.append((lines, max(28, 6 + 16*max(map(len, lines)))))
    total_h = header + sum(r.images[0].shape[0] + row_label + c[1] + gap for r, c in zip(rows, caption_rows)) + 28
    sheet = Image.new("RGB", (4 * width + 5 * gap, total_h), "#11171e")
    draw = ImageDraw.Draw(sheet)
    draw.text((gap, 10), title, fill="#f5f7fa", font=_font(19))
    draw.text((gap, 37), DISCLAIMER, fill="#f1bc79", font=_font(13))
    draw.text((gap, 57), "SDR preview; common scale across TVs in each row. 0 lux. No per-TV normalization.", fill="#b6c3d1", font=_font(13))
    for i, label in enumerate(PROFILE_LABELS):
        draw.text((gap + i*(width+gap), 82), label, fill="#73d5ce", font=_font(14))
    y = header
    for row, (captions, caption_h) in zip(rows, caption_rows):
        draw.text((gap, y), row.title, fill="#f5f7fa", font=_font(15))
        draw.text((gap, y+22), row.note, fill="#b6c3d1", font=_font(12))
        y += row_label
        for i, rgb in enumerate(row.images):
            if rgb.shape != row.images[0].shape or rgb.shape[1] != width:
                raise ValueError("contact sheet tiles must share dimensions")
            x = gap + i*(width+gap)
            sheet.paste(Image.fromarray(preview(rgb, row.reference)), (x, y))
            for line, caption in enumerate(captions[i]):
                draw.text((x, y+rgb.shape[0]+6+16*line), caption, fill="#b6c3d1", font=caption_font)
        y += row.images[0].shape[0] + caption_h + gap
    draw.text((gap, total_h-24), "HDR is scaled into sRGB. Shadow rows amplify leakage; macro rows show synthetic apertures.", fill="#f1bc79", font=_font(12))
    sheet.save(path)


def _stats(images: list[np.ndarray]) -> list[dict[str, float]]:
    return [{"peak_channel_nits": float(rgb.max()), "mean_luminance_nits": float(luminance(rgb).mean())} for rgb in images]


def _html(out: Path, manifest: dict) -> None:
    sections = []
    for item in manifest["sheets"]:
        filename = escape(item["file"], quote=True)
        sections.append(f'<section id="{escape(item["id"])}"><h2>{escape(item["title"])}</h2>'
                        f'<p>{escape(item["description"])}</p><a href="{filename}">'
                        f'<img src="{filename}" alt="{escape(item["title"])}; all four TV profiles side by side" loading="lazy"></a></section>')
    profiles = "".join(
        f'<tr><td>{escape(label)}</td><td>{p["temporal"]["response_time_ms"]} ms</td>'
        f'<td>{p["backlight"]["peak_nits"]} nit</td><td>{escape(p["panel"]["subpixel"])}</td></tr>'
        for label, p in zip(PROFILE_LABELS, manifest["profiles"])
    )
    page = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TV simulator · visual gallery</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0c1118;color:#e8eef5;font:16px/1.6 system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:32px 24px}h1{font-size:36px;letter-spacing:-1px;margin:8px 0}
h2{font-size:24px;margin-bottom:4px}p{max-width:1000px;color:#bac7d5}a{color:#7edbd3}
.notice{border-left:3px solid #efb773;padding:12px 20px;background:#192029;color:#f4d4ab}
nav{display:flex;gap:18px;flex-wrap:wrap;margin:24px 0}section{padding:12px 0 28px;border-top:1px solid #283442}
img{width:100%;height:auto;display:block;border:1px solid #2d3c4c;border-radius:6px}table{border-collapse:collapse}
td,th{text-align:left;border-bottom:1px solid #283442;padding:8px 20px 8px 0}code{color:#c5e5e1}
</style><main>
<small>TV DISPLAY SIMULATOR / CPU NUMPY REFERENCE</small><h1>Four TVs, one source.</h1>
<p class="notice"><strong>Placeholder parameters, not measurements or retail-TV emulations.</strong>
HDR is scaled into an SDR sRGB preview. Your screen cannot reproduce the simulated peak or black level.
Every comparison row uses a shared exposure; there is no per-TV auto-normalization.</p>
<p>Click a contact sheet for its full-size PNG. This folder works offline with relative image paths.
The default columns are VA mini-LED, IPS edge LCD, WOLED, QD-OLED. All receive identical float PQ sources;
ambient is 0 lux, on-axis, and profile spatial processing stays enabled.</p>
<nav>__NAV__</nav>
<details><summary>Protocol, scales and profile settings</summary>
<p>HDR rows: 2,000 simulated nits maps to preview white. Shadow diagnostics: 10 nits maps to white
(200× exposure); brighter pixels clip. Motion: 100 nits maps to white. Macro apertures: 1,000 maps to white.
These are exposure choices, not a calibrated observer model or HDR encoding.</p>
<table><tr><th>Placeholder profile</th><th>Response tau (not GtG)</th><th>Emitter/backlight peak</th><th>Layout</th></tr>__PROFILES__</table>
<p>Motion uses 12 settled pre-roll frames plus 36 advancing pan frames at approximately 60 Hz,
8 pixels/frame (~480 pixels/s), 16 subframe integration samples. Each mode starts with fresh state.
The final-frame snapshots model pursuit integration, not a stationary-camera photograph.
OD is an explicit LCD-only probe (gain 0.8, 4-ms prefix); OLED columns repeat full hold.
BFI is an assumed centered 25%-duty single pulse at fixed peak, without brightness compensation.
Neither probe claims a supported retail mode. No MEMC, scanout, PWM or measured response LUT is modeled.</p>
<p>Macro masks have a black matrix, equal logical-pixel pitch and arbitrary aperture dimensions.
RGBW allocation and staggered triangular QD geometry are synthetic, not micrographs or a measured
Pentile resolution model. Aperture amplitudes are area-normalized, so their peaks are not measured emitter nits.
QD-OLED has a placeholder 0.45-pixel optical PSF; WOLED has none. The two OLED previews can therefore differ in edge softness.</p>
<p>Exact settings, YAML hashes, row scales and linear output statistics: <a href="manifest.json">manifest.json</a>.</p>
</details>__SECTIONS__
<p>Reproduce: <code>python3 -m sim gallery</code>. In the source repository, docs/REPORT.md
and research/m5-fidelity.md describe validation and model boundaries.</p></main></html>'''
    nav = "".join(f'<a href="#{escape(s["id"])}">{escape(s["title"])}</a>' for s in manifest["sheets"])
    (out / "index.html").write_text(page.replace("__NAV__", nav).replace("__PROFILES__", profiles).replace("__SECTIONS__", "\n".join(sections)), encoding="utf-8")


def generate_gallery(out: Path, width: int = 320, height: int = 180) -> dict:
    """Render all four shipped profiles without modifying their YAML files."""
    from sim.macro import render_macro

    if width < 160 or height < 96:
        raise ValueError("gallery resolution must be at least 160x96")
    out.mkdir(parents=True, exist_ok=True)
    profiles = [load_profile(name) for name in PROFILE_NAMES]
    sources = scenes(width, height)
    manifest = {"disclaimer": DISCLAIMER, "source_encoding": "float PQ from procedural absolute-nit RGB",
                "resolution": [width, height], "ambient_lux": 0, "viewing_angle_deg": 0,
                "preview": "shared row exposure, then sRGB; no per-TV normalization",
                "profile_overrides": {"input_eotf": "pq", "viewing_angle_deg": 0, "ambient_lux": 0,
                                      "integration_samples": INTEGRATION_SAMPLES,
                                      "motion_px_per_frame": {"stills": 0, "pan": PAN_SPEED}},
                "temporal_protocol": {"pre_roll_frames": PRE_ROLL, "pan_frames": PAN_FRAMES,
                                      "pan_px_per_frame": PAN_SPEED, "integration_samples": INTEGRATION_SAMPLES,
                                      "overdrive_probe": {"gain": .8, "prefix_ms": 4, "lcd_only": True},
                                      "bfi_probe": {"duty": .25, "preserve_mean": False}},
                "profiles": [dict(asdict(p), yaml_sha256=sha256(profile_path(p.name).read_bytes()).hexdigest()) for p in profiles],
                "sheets": []}

    def save(identifier: str, title: str, description: str, rows: list[Row]):
        filename = f"{identifier}.png"
        contact_sheet(out / filename, title, rows)
        manifest["sheets"].append({"id": identifier, "title": title, "description": description,
                                    "file": filename, "rows": [dict(title=r.title, note=r.note,
                                     reference_nits=r.reference, statistics=_stats(r.images), captions=r.captions) for r in rows]})

    descriptions = {
        "starfield": ("Starfield", "Sparse 600-2,000-nit stars expose highlight retention, local LCD leakage and optical softness."),
        "subtitles": ("Subtitles on black", "1,000-nit subtitle glyphs reveal local FALD halos versus the IPS full-height strip lift."),
        "bright_window": ("Bright window on dark", "2,000-nit windows at roughly 12% and 56% area show brightness limits and area dependence."),
        "gradients": ("Gradients", "Top to bottom: neutral 0-100, 0-2,000, 0-2 nits, then a synthetic RGB mixture. No gamut calibration."),
    }
    for identifier, (title, description) in descriptions.items():
        rendered = [render_still(p, sources[identifier]) for p in profiles]
        rows = [Row("Shared HDR exposure", "2,000 simulated nits -> SDR white; no per-TV normalization", rendered, HDR_REFERENCE)]
        if identifier == "bright_window":
            wide = [render_still(p, sources["wide_window"]) for p in profiles]
            rows.append(Row("Larger window / same 2,000-nit request", "About 56% area, versus about 12% above; shared HDR exposure", wide, HDR_REFERENCE))
        rows.append(Row("Shadow diagnostic / amplified exposure", "10 simulated nits -> white (200x HDR exposure); highlights clip", rendered, SHADOW_REFERENCE))
        save(identifier, title, description, rows)

    pan = {"hold": [render_pan(p, sources["motion_pan"], "hold") for p in profiles]}
    pan["overdrive"] = [pan["hold"][i] if p.self_emissive else render_pan(p, sources["motion_pan"], "overdrive")
                        for i, p in enumerate(profiles)]
    pan["bfi"] = [render_pan(p, sources["motion_pan"], "bfi") for p in profiles]
    final_source = np.roll(sources["motion_pan"], int(PAN_FRAMES*PAN_SPEED), axis=1)
    still = [render_still(p, final_source) for p in profiles]
    save("motion_pan", "Motion pan", "Compare final-frame pursuit views after a long persistent history. Slow response adds trails; even fast OLED has full-hold blur.", [
        Row("Settled final position / no eye motion", "100 simulated nits -> SDR white for every motion row", still, MOTION_REFERENCE),
        Row("Pan / profile response + full sample-and-hold", "36 pan frames after 12 settled frames; 8 px/frame, 16 subframe samples", [r[PAN_FRAMES] for r in pan["hold"]], MOTION_REFERENCE),
        Row("Pan / synthetic LCD overdrive probe", "LCD gain 0.8 for 4 ms; OLED repeats full hold (user OD not assumed)", [r[PAN_FRAMES] for r in pan["overdrive"]], MOTION_REFERENCE,
            ["OD probe: gain 0.8 / 4 ms", "OD probe: gain 0.8 / 4 ms", "OD not modeled; full hold", "OD not modeled; full hold"]),
        Row("Pan / synthetic 25%-duty BFI probe", "Fixed peak, no mean boost: shorter persistence and lower brightness", [r[PAN_FRAMES] for r in pan["bfi"]], MOTION_REFERENCE),
    ])
    save("motion_history", "Motion history", "The same persistent pipelines at pan frames 1, 12 and 36. Translation wraps at the image boundary; each source frame is a new position.", [
        Row(f"Full hold / pan frame {i}", f"{PRE_ROLL} settled pre-roll frames; common 100-nit exposure", [r[i] for r in pan["hold"]], MOTION_REFERENCE) for i in (1, 12, PAN_FRAMES)
    ])
    cy, cx = height//2-4, width//2-8
    crops = [render_still(p, sources["macro_subpixel"])[cy:cy+8, cx:cx+16] for p in profiles]
    scale = max(10, width//16)
    enlarged = [np.repeat(np.repeat(crop, scale, axis=0), scale, axis=1) for crop in crops]
    apertures = [render_macro(crop, p.panel.subpixel, scale=scale) for crop, p in zip(crops, profiles)]
    save("macro_subpixel", "Macro subpixel crop", "A 16x8 logical-pixel crop enlarged at equal pitch. Neutral top and RGBW bars below expose RGB stripes, white allocation and QD triangular geometry.", [
        Row("Logical output / nearest-neighbor enlargement", f"{scale} preview pixels per logical pixel; common 100-nit exposure", enlarged, 100),
        Row("Synthetic subpixel apertures / black matrix", "Area-normalized aperture energy; 1,000 -> white, arbitrary fill and geometry", apertures, MACRO_REFERENCE,
            ["RGB stripes / synthetic", "RGB stripes / synthetic", "R/W/B/G + white allocation / synthetic", "Staggered triangular RGB / synthetic"]),
    ])
    manifest["macro"] = {"crop_yxhw": [cy, cx, 8, 16], "scale": scale, "fill_factor": .72,
                         "white_fraction": .65, "geometry_status": "synthetic, unmeasured"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    _html(out, manifest)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("reports/gallery"))
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    args = parser.parse_args(argv)
    if args.width < 160 or args.height < 96:
        parser.error("resolution must be at least 160x96")
    result = generate_gallery(args.out, args.width, args.height)
    print(f"Wrote {len(result['sheets'])} contact sheets and {args.out / 'index.html'}")


if __name__ == "__main__":
    main()
