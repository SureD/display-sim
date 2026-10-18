"""Opt-in synthetic MEMC experiments, separate from the historical M4 reports.

The scene, estimator settings and exposure are P placeholders. Analytic truth
is independently rendered from known opaque layers and piecewise lighting;
neither it nor the error scores calibrate a TV or a perceptual smoothness scale.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PIL import Image, ImageDraw

from tv_sim.frame import Frame
from tv_sim.motion import (
    AnalyticLayer,
    LayerScene,
    ReconstructionResult,
    _sample,
    as_fraction,
    fixed_rate_pts,
    rational_string,
    reconstruct,
    schedule,
)
from tv_sim.profile import OutputParams, TVProfile
from tv_sim.stages.encode import encode_frame

if TYPE_CHECKING:
    from tv_sim.abl_dynamics import ABLDynamicsConfig
    from tv_sim.block_motion import BlockMotionConfig, PairEstimate

PROTOCOL_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "measurements"
    / "motion_validation_synthetic_v1.json"
)
FIXTURE_NAMES = ("pan", "occlusion", "text", "cut", "repeating_texture", "large_motion", "flash")
MODES = ("repeat", "analytic", "mci")
LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], np.float64)


def _read_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"nonfinite JSON value {value}")

    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=invalid)


def validate_validation_protocol(data: dict) -> None:
    """Strict admission of the versioned P-only synthetic experiment ledger."""

    expected = {
        "schema_version",
        "protocol_id",
        "parameter_status",
        "evidence",
        "settings",
        "visual",
        "fixtures",
        "unavailable",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("motion validation protocol has missing or unknown keys")
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["protocol_id"] != "motion_validation_synthetic_v1"
        or data["parameter_status"] != "placeholder"
        or data["evidence"] != "P"
    ):
        raise ValueError("motion validation requires schema 1 and P placeholder evidence")
    settings = data["settings"]
    keys = {
        "width",
        "height",
        "source_count",
        "source_fps",
        "output_fps",
        "seed",
        "preview_reference_nits",
        "boundary_radius_px",
        "marker_threshold_nits",
    }
    if not isinstance(settings, dict) or set(settings) != keys:
        raise ValueError("motion validation settings have missing or unknown keys")
    for key in ("width", "height", "source_count", "seed", "boundary_radius_px"):
        if type(settings[key]) is not int or settings[key] < (
            0 if key in ("seed", "boundary_radius_px") else 1
        ):
            raise ValueError(f"invalid motion validation {key}")
    if min(settings["width"], settings["height"]) < 16 or settings["source_count"] < 4:
        raise ValueError("motion fixtures require at least 16 pixels and four sources")
    for key in ("source_fps", "output_fps"):
        if not isinstance(settings[key], str) or as_fraction(settings[key]) <= 0:
            raise ValueError(f"invalid rational {key}")
    for key in ("preview_reference_nits", "marker_threshold_nits"):
        value = settings[key]
        if type(value) not in (int, float) or not np.isfinite(value) or value <= 0:
            raise ValueError(f"invalid positive {key}")
    visual = data["visual"]
    vector_keys = {
        "reference_size_px": 2,
        "background_range_nits": 2,
        "marker_rgb_nits": 3,
        "marker_rect_fraction": 4,
        "rear_rgb_nits": 3,
        "rear_rect_fraction": 4,
        "text_rgb_nits": 3,
        "text_origin_fraction": 2,
        "second_shot_rgb_offset_nits": 3,
    }
    scalar_keys = {
        "texture_cell_px",
        "marker_texture_nits",
        "glyph_scale_px",
        "repeating_period_px",
        "cut_source_fraction",
        "flash_source_fraction",
        "flash_gain",
    }
    if not isinstance(visual, dict) or set(visual) != set(vector_keys) | scalar_keys:
        raise ValueError("motion visual parameters have missing or unknown keys")
    for key, length in vector_keys.items():
        values = visual[key]
        if (
            not isinstance(values, list)
            or len(values) != length
            or any(type(v) not in (int, float) or not np.isfinite(v) or v < 0 for v in values)
        ):
            raise ValueError(f"invalid visual vector {key}")
    for key in scalar_keys:
        value = visual[key]
        if type(value) not in (int, float) or not np.isfinite(value) or value <= 0:
            raise ValueError(f"invalid visual scalar {key}")
    if any(v <= 0 for v in visual["reference_size_px"]):
        raise ValueError("reference size must be positive")
    for key in ("cut_source_fraction", "flash_source_fraction"):
        if not 0 < visual[key] < 1:
            raise ValueError("event source fractions must be in (0,1)")
    for key in ("texture_cell_px", "glyph_scale_px", "repeating_period_px"):
        if type(visual[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    for key in ("marker_rect_fraction", "rear_rect_fraction"):
        x, y, width, height = visual[key]
        if width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError(f"{key} must fit the normalized canvas")
    if visual["background_range_nits"][0] >= visual["background_range_nits"][1]:
        raise ValueError("background range must be increasing")
    fixtures = data["fixtures"]
    if not isinstance(fixtures, dict) or set(fixtures) != set(FIXTURE_NAMES):
        raise ValueError("motion validation must declare all seven fixtures")
    for name, spec in fixtures.items():
        expected = {"background_velocity_px", "marker_velocity_px"}
        expected |= {"rear_velocity_px"} if name == "occlusion" else set()
        expected |= {"caption_velocity_px"} if name == "text" else set()
        if not isinstance(spec, dict) or set(spec) != expected:
            raise ValueError(f"{name}: missing or unknown fixture parameters")
        for value in spec.values():
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(type(v) not in (int, float) or not np.isfinite(v) for v in value)
            ):
                raise ValueError(f"{name}: velocities must be finite 2D vectors")
    unavailable = data["unavailable"]
    if (
        not isinstance(unavailable, dict)
        or set(unavailable)
        != {
            "named_tv_calibration",
            "vendor_memc_algorithm",
            "perceptual_soap_opera_scale",
            "measured_artifact_distribution",
        }
        or any(value != "NR" for value in unavailable.values())
    ):
        raise ValueError("unavailable calibration quantities must remain NR")


def default_validation_protocol() -> dict:
    data = _read_json(PROTOCOL_PATH)
    validate_validation_protocol(data)
    return data


def validate_motion_validation_provenance(path: Path | str | None = None) -> list[str]:
    """Provenance CLI hook; the runtime never implicitly activates this protocol."""

    path = PROTOCOL_PATH if path is None else Path(path)
    try:
        validate_validation_protocol(_read_json(path))
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        return [f"{path}: {exc}"]
    return []


def _rectangle(shape: tuple[int, int], rect: list[float]) -> np.ndarray:
    height, width = shape
    x, y, rw, rh = rect
    mask = np.zeros(shape, bool)
    mask[
        round(y * height) : max(round(y * height) + 1, round((y + rh) * height)),
        round(x * width) : max(round(x * width) + 1, round((x + rw) * width)),
    ] = True
    return mask


def _text_mask(shape: tuple[int, int], visual: dict) -> np.ndarray:
    # Explicit bitmap glyphs avoid platform fonts and keep thin strokes stable.
    glyphs = (
        "10001/11011/10101/10101/10001/10001/10001",
        "11111/10000/10000/11110/10000/10000/11111",
        "10001/11011/10101/10101/10001/10001/10001",
        "01111/10000/10000/10000/10000/10000/01111",
    )
    scale = visual["glyph_scale_px"]
    bitmap = np.concatenate(
        [np.array([[v == "1" for v in row] for row in glyph.split("/")]) for glyph in glyphs],
        axis=1,
    )
    bitmap = np.repeat(np.repeat(bitmap, scale, axis=0), scale, axis=1)
    mask = np.zeros(shape, bool)
    x, y = (round(v * size) for v, size in zip(visual["text_origin_fraction"], shape[::-1]))
    bh, bw = min(bitmap.shape[0], shape[0] - y), min(bitmap.shape[1], shape[1] - x)
    if bh > 0 and bw > 0:
        mask[y : y + bh, x : x + bw] = bitmap[:bh, :bw]
    return mask


@dataclass(frozen=True)
class MotionFixture:
    name: str
    scene: LayerScene
    settings: dict
    visual: dict

    @property
    def cut_index(self) -> int | None:
        return self.event_index("cut_source_fraction") if self.name == "cut" else None

    def event_index(self, fraction_key: str) -> int:
        count = self.settings["source_count"]
        return min(count - 1, max(1, round(count * self.visual[fraction_key])))

    def render(self, phase: float | Fraction) -> Frame:
        time = float(phase)
        local_time = (
            time - self.cut_index if self.cut_index is not None and time >= self.cut_index else time
        )
        frame = self.scene.render(local_time)
        if self.cut_index is not None and time >= self.cut_index:
            frame = Frame(
                frame.rgb + np.asarray(self.visual["second_shot_rgb_offset_nits"], np.float32)
            )
        if self.name == "flash" and int(np.floor(time)) == self.event_index(
            "flash_source_fraction"
        ):
            frame = Frame(frame.rgb * self.visual["flash_gain"])
        return frame

    def labels_and_velocity(self, phase: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.cut_index is not None and phase >= self.cut_index:
            phase -= self.cut_index
        shape = self.scene.background.shape[:2]
        labels, fractional = np.zeros(shape, np.int16), np.zeros(shape, bool)
        velocity = np.zeros((*shape, 2), np.float32)
        for index, layer in enumerate(sorted(self.scene.layers, key=lambda item: item.depth), 1):
            coverage, _ = _sample(
                layer.mask.astype(np.float32), *(np.asarray(layer.velocity) * phase), zero_pad=True
            )
            visible = coverage >= 0.5
            labels[visible] = index
            velocity[visible] = layer.velocity
            fractional = (fractional & (coverage < 1)) | ((coverage > 0) & (coverage < 1))
        return labels, velocity, fractional

    def regions(self, phase: float, source_index: int) -> dict[str, np.ndarray]:
        labels, velocity, fractional = self.labels_and_velocity(phase)
        left_labels, _, _ = self.labels_and_velocity(float(source_index))
        boundary = fractional.copy()
        boundary[:-1] |= labels[:-1] != labels[1:]
        boundary[1:] |= labels[:-1] != labels[1:]
        boundary[:, :-1] |= labels[:, :-1] != labels[:, 1:]
        boundary[:, 1:] |= labels[:, :-1] != labels[:, 1:]
        for _ in range(self.settings["boundary_radius_px"]):
            old = boundary.copy()
            boundary[:-1] |= old[1:]
            boundary[1:] |= old[:-1]
            boundary[:, :-1] |= old[:, 1:]
            boundary[:, 1:] |= old[:, :-1]
        # Compare the current material point with its left-source visibility,
        # rather than comparing unrelated material at the same screen pixel.
        yy, xx = np.indices(labels.shape, dtype=np.float64)
        delta = phase - source_index
        source_x, source_y = xx - delta * velocity[..., 0], yy - delta * velocity[..., 1]
        supported = (
            (source_x >= 0)
            & (source_x <= labels.shape[1] - 1)
            & (source_y >= 0)
            & (source_y <= labels.shape[0] - 1)
        )
        source_x = np.rint(np.clip(source_x, 0, labels.shape[1] - 1)).astype(np.intp)
        source_y = np.rint(np.clip(source_y, 0, labels.shape[0] - 1)).astype(np.intp)
        disoccluded = ~supported | (left_labels[source_y, source_x] > labels)
        # Disocclusion gets priority so the three regions partition the raster.
        return {
            "interior": ~(boundary | disoccluded),
            "boundary": boundary & ~disoccluded,
            "disoccluded": disoccluded,
        }


def make_fixture(name: str, protocol: dict | None = None) -> MotionFixture:
    if name == "thin_text":
        name = "text"
    if name not in FIXTURE_NAMES:
        raise ValueError(f"unknown motion fixture {name!r}")
    data = default_validation_protocol() if protocol is None else protocol
    validate_validation_protocol(data)
    settings, visual, spec = data["settings"], data["visual"], data["fixtures"][name]
    height, width = settings["height"], settings["width"]
    shape = (height, width)
    rng = np.random.default_rng(settings["seed"] + FIXTURE_NAMES.index(name))
    yy, xx = np.indices(shape)
    low, high = visual["background_range_nits"]
    cell = visual["texture_cell_px"]
    small = rng.uniform(low, high, ((height + cell - 1) // cell, (width + cell - 1) // cell))
    texture = np.repeat(np.repeat(small, cell, axis=0), cell, axis=1)[:height, :width]
    if name == "repeating_texture":
        texture = np.where((xx // visual["repeating_period_px"]) % 2, high, low)
    background = np.repeat(texture[..., None], 3, axis=-1).astype(np.float32)
    base = np.full_like(background, low)
    scale = np.array([width, height]) / visual["reference_size_px"]

    def velocity(key: str) -> tuple[float, float]:
        return tuple(np.asarray(spec[key], np.float64) * scale)

    layers = [
        AnalyticLayer(background, np.ones(shape, bool), velocity("background_velocity_px"), 0)
    ]
    if name == "occlusion":
        rear = np.full_like(background, visual["rear_rgb_nits"])
        layers.append(
            AnalyticLayer(
                rear,
                _rectangle(shape, visual["rear_rect_fraction"]),
                velocity("rear_velocity_px"),
                1,
            )
        )
    marker = np.full_like(background, visual["marker_rgb_nits"])
    marker += (((xx + yy) % 2) * visual["marker_texture_nits"])[..., None]
    layers.append(
        AnalyticLayer(
            marker,
            _rectangle(shape, visual["marker_rect_fraction"]),
            velocity("marker_velocity_px"),
            2,
        )
    )
    if name == "text":
        layers.append(
            AnalyticLayer(
                np.full_like(background, visual["text_rgb_nits"]),
                _text_mask(shape, visual),
                velocity("caption_velocity_px"),
                3,
            )
        )
    return MotionFixture(
        name, LayerScene(base, tuple(layers)), deepcopy(settings), deepcopy(visual)
    )


class _IntervalScene:
    """Use phase-1 analytic reconstruction with a global synthetic scene clock."""

    def __init__(self, fixture: MotionFixture, index: int) -> None:
        self.fixture, self.index, self.layers = fixture, index, fixture.scene.layers

    def render(self, phase: float | Fraction) -> Frame:
        return self.fixture.render(self.index + float(phase))


def _centroid(rgb: np.ndarray, threshold: float) -> np.ndarray | None:
    weights = np.maximum(rgb[..., 0] - np.maximum(rgb[..., 1], rgb[..., 2]) - threshold, 0).astype(
        np.float64
    )
    total = float(weights.sum())
    if total <= 0:
        return None
    yy, xx = np.indices(weights.shape)
    return np.array([(weights * xx).sum() / total, (weights * yy).sum() / total])


def _frame_metrics(
    frame: Frame, truth: Frame, regions: dict[str, np.ndarray], threshold: float
) -> dict:
    difference = np.abs((frame.rgb.astype(np.float64) - truth.rgb) @ LUMA_WEIGHTS)
    region_metrics = {}
    for name, mask in regions.items():
        count = int(mask.sum())
        region_metrics[name] = {
            "pixels": count,
            "absolute_luma_error_sum_nits": float(difference[mask].sum()),
            "linear_luma_mae_nits": float(difference[mask].mean()) if count else None,
        }
    observed, expected = _centroid(frame.rgb, threshold), _centroid(truth.rgb, threshold)
    return {
        "regions": region_metrics,
        "trajectory_error_px": float(np.linalg.norm(observed - expected))
        if observed is not None and expected is not None
        else None,
        "observed_marker_centroid_px": observed.tolist() if observed is not None else None,
        "truth_marker_centroid_px": expected.tolist() if expected is not None else None,
        "missing_visible_marker": expected is not None and observed is None,
        "spurious_visible_marker": expected is None and observed is not None,
    }


def _summary(records: list[dict], mode: str) -> dict:
    assessed = [record for record in records if record["assessed_intermediate"]]
    trajectory = [
        record["modes"][mode]["metrics"]["trajectory_error_px"]
        for record in assessed
        if record["modes"][mode]["metrics"]["trajectory_error_px"] is not None
    ]
    reasons: dict[str, float] = {}
    for record in assessed:
        result = record["modes"][mode]
        for reason, fraction in result["reason_fractions"].items():
            reasons[reason] = reasons.get(reason, 0.0) + fraction
    regions = {}
    for region in ("interior", "boundary", "disoccluded"):
        values = [r["modes"][mode]["metrics"]["regions"][region] for r in assessed]
        count = sum(v["pixels"] for v in values)
        error = sum(v["absolute_luma_error_sum_nits"] for v in values)
        regions[region] = {
            "pixels": count,
            "linear_luma_mae_nits": error / count if count else None,
        }
    return {
        "assessed_intermediate_ticks": len(assessed),
        "regions": regions,
        "trajectory": {
            "metric": "red-marker weighted centroid of actual rendered RGB versus analytic truth",
            "samples": len(trajectory),
            "mean_error_px": float(np.mean(trajectory)) if trajectory else None,
            "max_error_px": max(trajectory) if trajectory else None,
            "missing_visible_marker_ticks": sum(
                r["modes"][mode]["metrics"]["missing_visible_marker"] for r in assessed
            ),
            "spurious_visible_marker_ticks": sum(
                r["modes"][mode]["metrics"]["spurious_visible_marker"] for r in assessed
            ),
        },
        "fallback_fraction": float(
            np.mean([r["modes"][mode]["fallback_fraction"] for r in assessed])
        )
        if assessed
        else 0.0,
        "fallback_reason_mean_fractions": {
            key: value / len(assessed) for key, value in sorted(reasons.items())
        },
    }


def _hash_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _save_array(path: Path, value: np.ndarray) -> str:
    np.save(path, value, allow_pickle=False)
    return _hash_file(path)


def _write_gallery(out: Path, fixture_reports: list[dict], output_fps: Fraction) -> None:
    """Offline playback follows saved output PTS; sheets show spatial artifacts."""

    sections, playback = [], []
    for fixture in fixture_reports:
        if fixture["fixture"] not in ("occlusion", "text"):
            continue
        records = fixture["frames"]
        chosen = [r for r in records if r["assessed_intermediate"]]
        chosen = (
            [
                chosen[index]
                for index in np.linspace(0, len(chosen) - 1, min(4, len(chosen)), dtype=int)
            ]
            if chosen
            else records[:1]
        )
        first = Image.open(out / chosen[0]["modes"]["repeat"]["preview_file"])
        width, height = first.size
        sheet = Image.new("RGB", (width * len(MODES), (height + 30) * len(chosen)), "#161a20")
        draw = ImageDraw.Draw(sheet)
        for row, record in enumerate(chosen):
            for column, mode in enumerate(MODES):
                with Image.open(out / record["modes"][mode]["preview_file"]) as preview:
                    sheet.paste(preview, (column * width, row * (height + 30) + 30))
                draw.text(
                    (column * width + 3, row * (height + 30) + 3),
                    f"{mode} t={record['output_pts']} a={record['phase']}",
                    fill="white",
                )
        sheet_path = f"{fixture['fixture']}/contact-sheet.png"
        sheet.save(out / sheet_path)
        playback.append(
            {
                "fixture": fixture["fixture"],
                "duration": fixture["duration_seconds"],
                "frames": [
                    {
                        "pts": float(Fraction(r["output_pts"])),
                        "files": [r["modes"][mode]["preview_file"] for mode in MODES],
                    }
                    for r in records
                ],
            }
        )
        sections.append(
            f'<section><h2>{fixture["fixture"]}</h2><img class="sheet" src="{sheet_path}" alt="Repeat analytic MCI spatial comparison"><div class="playback" id="{fixture["fixture"]}"><figure><figcaption>repeat</figcaption><img></figure><figure><figcaption>analytic</figcaption><img></figure><figure><figcaption>block MCI</figcaption><img></figure></div></section>'
        )
    payload = json.dumps(playback, separators=(",", ":"))
    html = (
        '<!doctype html><meta charset="utf-8"><title>M14 synthetic MEMC comparison</title>'
        "<style>body{background:#15191f;color:#eee;font:16px system-ui;margin:2em;max-width:1200px}img{image-rendering:auto;max-width:100%}.sheet{width:100%}.playback{display:flex;gap:1em}figure{margin:0;flex:1}figure img{width:100%}figcaption{margin:.5em 0}button{font:inherit}</style>"
        "<h1>Synthetic MEMC artifact comparison (P)</h1><p>Repeat / known analytic model / block MCI. "
        "One recorded shared reference is used across each clip and comparison mode. "
        "Sheets show spatial artifacts; browser playback does not validate panel cadence or perceived smoothness. "
        f"Output PTS: {rational_string(output_fps)} fps; linear arrays, masks and scores are in motion-validation.json. "
        'No named TV or vendor algorithm is calibrated.</p><button id="toggle">Pause</button>'
        + "".join(sections)
        + "<script>const clips="
        + payload
        + ";let paused=false,start=null;"
        'document.querySelector("#toggle").onclick=()=>{paused=!paused;document.querySelector("#toggle").textContent=paused?"Play":"Pause";start=null};'
        'function tick(now){if(start===null)start=now;if(!paused){for(const clip of clips){const t=((now-start)/1000)%clip.duration;let f=clip.frames[0];for(const candidate of clip.frames){if(candidate.pts<=t)f=candidate;else break;}document.querySelectorAll(`#${clip.fixture} figure img`).forEach((img,i)=>{if(img.getAttribute("src")!==f.files[i])img.src=f.files[i]})}}requestAnimationFrame(tick)}requestAnimationFrame(tick);</script>'
    )
    (out / "index.html").write_text(html)


def run_validation(
    out: Path | str,
    *,
    fixtures: tuple[str, ...] | list[str] = FIXTURE_NAMES,
    protocol: dict | None = None,
    width: int | None = None,
    height: int | None = None,
    source_count: int | None = None,
    seed: int | None = None,
    source_fps: Fraction | str | int | None = None,
    output_fps: Fraction | str | int | None = None,
    preview_reference_nits: float | None = None,
    block_config: BlockMotionConfig | None = None,
    gallery: bool = False,
    profile: TVProfile | None = None,
    abl_dynamics: ABLDynamicsConfig | None = None,
) -> dict:
    """Render streamed adjacent pairs and save pre-display linear-nit evidence.

    If a profile is explicitly supplied, each comparison mode has one persistent
    Pipeline and makes exactly one display_content call per output tick. Content
    reconstruction never reads back a physical display history.
    """

    from tv_sim.block_motion import MODEL, BlockMotionConfig, estimate_pair, reconstruct_block

    data = deepcopy(default_validation_protocol() if protocol is None else protocol)
    validate_validation_protocol(data)
    settings = data["settings"]
    for key, value in {
        "width": width,
        "height": height,
        "source_count": source_count,
        "seed": seed,
        "preview_reference_nits": preview_reference_nits,
    }.items():
        if value is not None:
            settings[key] = value
    for key, rate in (("source_fps", source_fps), ("output_fps", output_fps)):
        if rate is not None:
            settings[key] = rational_string(as_fraction(rate))
    validate_validation_protocol(data)
    fixture_names = tuple("text" if name == "thin_text" else name for name in fixtures)
    if (
        not fixture_names
        or len(set(fixture_names)) != len(fixture_names)
        or any(name not in FIXTURE_NAMES for name in fixture_names)
    ):
        raise ValueError("choose unique known motion fixtures")
    config = BlockMotionConfig() if block_config is None else block_config
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("motion validation output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    source_rate, output_rate = (
        as_fraction(settings["source_fps"]),
        as_fraction(settings["output_fps"]),
    )
    pts = fixed_rate_pts(settings["source_count"], source_rate)
    ticks = schedule(pts, 1 / source_rate, output_rate)
    output = OutputParams(eotf="srgb", reference_nits=settings["preview_reference_nits"])
    report = {
        "schema_version": 1,
        "report_kind": "motion_validation_v1",
        "evidence": "P",
        "protocol": data,
        "protocol_sha256": sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
        "estimator": {"model": MODEL, "evidence": "P", "parameters": asdict(config)},
        "domains": {
            "source": "linear RGB nits",
            "reconstruction": "linear RGB nits before display stages",
            "error": "absolute BT.709-weighted linear luma difference in nits",
            "luma_weights": LUMA_WEIGHTS.tolist(),
            "regions": "visible layer boundaries; disocclusion uses material-point backprojection and nearest categorical visibility",
            "preview": "sRGB with one fixed reference per clip",
            "observer": "natural playback; zero pursuit blur",
        },
        "preview_reference_nits": settings["preview_reference_nits"],
        "timing_evidence": "D",
        "reconstruction_evidence": "P",
        "unavailable": data["unavailable"],
        "implementation_sha256": {
            path.name: _hash_file(path)
            for path in (
                Path(__file__),
                Path(__file__).with_name("block_motion.py"),
                Path(__file__).with_name("motion.py"),
            )
        },
        "fixtures": [],
    }
    if profile is not None:
        from dataclasses import replace

        from tv_sim.pipeline import Pipeline
        from tv_sim.profile import profile_path

        profile = replace(profile, temporal=replace(profile.temporal, motion_px_per_frame=0.0))
        path = profile_path(profile.name)
        report["display"] = {
            "profile": profile.name,
            "profile_sha256": _hash_file(path),
            "effective_profile": asdict(profile),
            "abl_dynamics": asdict(abl_dynamics) if abl_dynamics is not None else {"model": "off"},
        }
    elif abl_dynamics is not None:
        raise ValueError("ABL dynamics requires an explicit display profile")
    for name in fixture_names:
        fixture = make_fixture(name, data)
        folder = out / name
        folder.mkdir()
        sources = []
        # Only the current adjacent source pair and estimator history are live.
        left = fixture.render(0)
        right: Frame | None = fixture.render(1)
        for index in range(settings["source_count"]):
            frame = fixture.render(index)
            path = folder / f"source_{index:03d}.npy"
            sources.append(
                {
                    "source_index": index,
                    "source_pts": rational_string(pts[index]),
                    "linear_file": str(path.relative_to(out)),
                    "sha256": _save_array(path, frame.rgb),
                }
            )
        records: list[dict[str, Any]] = []
        pair_records: list[dict[str, Any]] = []
        previous, estimate, pair_index = None, None, -1
        previous_masks: dict[str, np.ndarray | None] = {mode: None for mode in MODES}
        switches = {mode: {"pixel_decision_changes": 0, "output_tick_changes": 0} for mode in MODES}
        pipelines = (
            {mode: Pipeline(profile, abl_dynamics=abl_dynamics) for mode in MODES}
            if profile is not None
            else {}
        )
        for tick in ticks:
            index = tick.source_index
            if index != pair_index:
                left = fixture.render(index)
                right = fixture.render(index + 1) if tick.next_source_index is not None else None
                declared_cut = fixture.cut_index == index + 1
                if right is not None:
                    estimate = estimate_pair(
                        left, right, config, declared_cut=declared_cut, previous=previous
                    )
                    previous = None if estimate.scene_cut else estimate
                    maps_file = folder / f"pair_{index:03d}_maps.npz"
                    cast(Any, np.savez_compressed)(maps_file, **estimate.debug_arrays())
                    expected_velocity = fixture.labels_and_velocity(float(index))[1]
                    field = estimate.dense_field(estimate.forward)
                    confidence = estimate.dense_field(estimate.forward_confidence)
                    valid = confidence > 0
                    epe = np.linalg.norm(field - expected_velocity, axis=-1)
                    pair_records.append(
                        {
                            "source_index": index,
                            "declared_cut": declared_cut,
                            "scene_cut": bool(estimate.scene_cut),
                            "detected_cut": estimate.cut_reason == "scene_cut_detected",
                            "cut_reason": estimate.cut_reason,
                            "false_cut": bool(
                                estimate.cut_reason == "scene_cut_detected" and not declared_cut
                            ),
                            "maps_file": str(maps_file.relative_to(out)),
                            "diagnostics": estimate.diagnostics,
                            "vector_endpoint_error_px": {
                                "metric": "forward vector versus visible-layer truth, output pixels per source interval",
                                "all_blocks_dense_mean": float(epe.mean())
                                if not declared_cut
                                else None,
                                "positive_confidence_dense_mean": float(epe[valid].mean())
                                if valid.any() and not declared_cut
                                else None,
                            },
                        }
                    )
                else:
                    estimate = None
                pair_index = index
            phase = index + tick.alpha if right is not None else float(index)
            truth = fixture.render(phase)
            truth_file = folder / f"truth_{tick.output_index:04d}.npy"
            truth_hash = _save_array(truth_file, truth.rgb)
            regions = fixture.regions(phase, index)
            masks_file = folder / f"regions_{tick.output_index:04d}.npz"
            cast(Any, np.savez_compressed)(masks_file, **regions)
            zero_mask = np.zeros(left.shape[:2], bool)
            repeat = ReconstructionResult(
                left, "original" if tick.phase == 0 else "repeated", [], 0.0, zero_mask
            )
            analytic = reconstruct(
                left,
                right,
                tick.phase,
                scene=cast(LayerScene, _IntervalScene(fixture, index)),
                cut=fixture.cut_index == index + 1,
            )
            mci = (
                reconstruct_block(left, right, tick.phase, cast("PairEstimate", estimate), config)
                if right is not None
                else reconstruct(left, None, tick.phase)
            )
            record: dict[str, Any] = tick.to_dict()
            record.update(
                {
                    "assessed_intermediate": bool(tick.phase > 0 and right is not None),
                    "mci_assumed_lookahead_seconds": rational_string(1 / source_rate)
                    if right is not None
                    else "0/1",
                    "frame_time_ms": float(1000 / output_rate),
                    "truth_file": str(truth_file.relative_to(out)),
                    "truth_sha256": truth_hash,
                    "regions_file": str(masks_file.relative_to(out)),
                    "modes": {},
                }
            )
            for mode, result in zip(MODES, (repeat, analytic, mci)):
                stem = f"{mode}_{tick.output_index:04d}"
                linear_file, preview_file = folder / f"{stem}.npy", folder / f"{stem}.png"
                linear_hash = _save_array(linear_file, result.frame.rgb)
                Image.fromarray(encode_frame(result.frame, output)).save(preview_file)
                fallback_file = folder / f"{stem}_fallback.npy"
                _save_array(fallback_file, result.fallback_mask)
                # Count only intermediate decisions in the same shot; originals,
                # tail holds and cuts must not manufacture confidence pumping.
                if record["assessed_intermediate"] and not (
                    estimate is not None and estimate.scene_cut
                ):
                    old = previous_masks[mode]
                    if old is not None:
                        changes = int(np.count_nonzero(old != result.fallback_mask))
                        switches[mode]["pixel_decision_changes"] += changes
                        switches[mode]["output_tick_changes"] += int(changes > 0)
                    previous_masks[mode] = result.fallback_mask.copy()
                elif estimate is not None and estimate.scene_cut:
                    previous_masks[mode] = None
                reason_fractions = getattr(result, "reason_fractions", None)
                if reason_fractions is None:
                    reason_fractions = {
                        reason: result.fallback_fraction for reason in result.fallback_reasons
                    }
                details: dict[str, Any] = result.to_dict()
                details.update(
                    {
                        "linear_file": str(linear_file.relative_to(out)),
                        "linear_sha256": linear_hash,
                        "preview_file": str(preview_file.relative_to(out)),
                        "fallback_file": str(fallback_file.relative_to(out)),
                        "reason_fractions": reason_fractions,
                        "metrics": _frame_metrics(
                            result.frame, truth, regions, settings["marker_threshold_nits"]
                        ),
                    }
                )
                if getattr(result, "reason_map", None) is not None:
                    reason_file = folder / f"{stem}_reasons.npy"
                    _save_array(reason_file, cast(Any, result).reason_map)
                    details["reason_map_file"] = str(reason_file.relative_to(out))
                if profile is not None:
                    displayed = pipelines[mode].display_content(
                        result.frame, frame_time_ms=float(1000 / output_rate)
                    )
                    display_file = folder / f"{stem}_display.npy"
                    details["display_file"] = str(display_file.relative_to(out))
                    details["display_sha256"] = _save_array(display_file, displayed.rgb)
                    capacity_trace = getattr(pipelines[mode], "last_capacity_trace", None)
                    if capacity_trace is not None:
                        details["capacity_trace"] = deepcopy(capacity_trace)
                record["modes"][mode] = details
            records.append(record)
        summaries = {mode: _summary(records, mode) for mode in MODES}
        for mode in MODES:
            summaries[mode]["temporal_fallback_switching"] = switches[mode]
        fixture_report = {
            "fixture": name,
            "evidence": "P",
            "source_frames": sources,
            "duration_seconds": float(Fraction(settings["source_count"], 1) / source_rate),
            "declared_cut_before": fixture.cut_index,
            "pairs": pair_records,
            "frames": records,
            "false_cut_pairs": sum(pair["false_cut"] for pair in pair_records),
            "summary": summaries,
        }
        report["fixtures"].append(fixture_report)
        (folder / "pts-trace.json").write_text(
            json.dumps(records, indent=2, allow_nan=False) + "\n"
        )
    validate_validation_sidecar(report)
    (out / "motion-validation.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    if gallery:
        _write_gallery(out, report["fixtures"], output_rate)
    return report


def validate_validation_sidecar(data: dict) -> None:
    """Reject report identity/evidence/domain drift before saving artifacts."""

    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data.get("report_kind") != "motion_validation_v1"
        or data.get("evidence") != "P"
    ):
        raise ValueError("unsupported motion validation report or evidence")
    expected = {
        "schema_version",
        "report_kind",
        "evidence",
        "protocol",
        "protocol_sha256",
        "estimator",
        "domains",
        "preview_reference_nits",
        "timing_evidence",
        "reconstruction_evidence",
        "unavailable",
        "implementation_sha256",
        "fixtures",
    }
    if set(data) not in (expected, expected | {"display"}):
        raise ValueError("motion validation report has missing or unknown keys")
    validate_validation_protocol(cast(dict, data.get("protocol")))
    if (
        not isinstance(data.get("estimator"), dict)
        or set(data["estimator"]) != {"model", "evidence", "parameters"}
        or data["estimator"].get("evidence") != "P"
    ):
        raise ValueError("motion estimator settings must retain P evidence")
    from tv_sim.block_motion import MODEL, BlockMotionConfig

    if data["estimator"]["model"] != MODEL:
        raise ValueError("unsupported motion estimator model")
    BlockMotionConfig(**data["estimator"]["parameters"])
    if data.get("domains", {}).get("source") != "linear RGB nits":
        raise ValueError("motion validation source must remain linear RGB nits")
    if not isinstance(data.get("fixtures"), list) or not data["fixtures"]:
        raise ValueError("motion validation report must contain fixtures")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures", nargs="+", choices=(*FIXTURE_NAMES, "thin_text"), default=list(FIXTURE_NAMES)
    )
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument(
        "--motion-config", type=Path, default=None, help="Versioned P block-estimator configuration"
    )
    parser.add_argument("--source-fps", default=None)
    parser.add_argument("--output-fps", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--source-count", type=int, default=None)
    parser.add_argument("--preview-reference-nits", type=float, default=None)
    parser.add_argument(
        "--gallery",
        action="store_true",
        help="Offline occlusion/text contact sheets and PTS playback",
    )
    parser.add_argument("--out", type=Path, default=Path("reports/motion-tests"))
    args = parser.parse_args(argv)
    try:
        from tv_sim.motion_provenance import load_block_config

        protocol = _read_json(args.protocol)
        block_config = (
            load_block_config(args.motion_config) if args.motion_config is not None else None
        )
        report = run_validation(
            args.out,
            fixtures=args.fixtures,
            protocol=protocol,
            source_fps=args.source_fps,
            output_fps=args.output_fps,
            seed=args.seed,
            width=args.width,
            height=args.height,
            source_count=args.source_count,
            preview_reference_nits=args.preview_reference_nits,
            gallery=args.gallery,
            block_config=block_config,
        )
    except (OSError, ValueError, TypeError, ZeroDivisionError) as exc:
        parser.error(str(exc))
    for fixture in report["fixtures"]:
        metrics = fixture["summary"]["mci"]
        print(
            f"{fixture['fixture']}: trajectory mean={metrics['trajectory']['mean_error_px']} px; "
            f"fallback={metrics['fallback_fraction']:.3f}; false cuts={fixture['false_cut_pairs']}"
        )


if __name__ == "__main__":
    main()
