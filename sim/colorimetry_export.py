"""Explicit linear-color export adapter, used only with export-web --colorimetry."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from sim.color import pq_oetf
from sim.colorimetry import D65, RGB_SPACES, rgb_to_xyz_matrix
from sim.colorimetry_gallery import color_volume_patterns, diagnostic_summary
from sim.export_web import MACRO_SCALE, STILL_SCENES, _snapshot_profiles
from sim.frame import Frame
from sim.gallery import (DISCLAIMER, INTEGRATION_SAMPLES, MACRO_REFERENCE, MOTION_REFERENCE,
                         PAN_SPEED, PRE_ROLL, PROFILE_NAMES, _gallery_profile, scenes)
from sim.macro import render_macro
from sim.pipeline import Pipeline
from sim.profile import load_profile, profile_path


def _write_frames(out, relative, frames, matrix):
    """FP16 may be signed: e.g. QD-OLED output lies outside Display P3."""
    destination = out / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    count, shape, digest = 0, None, sha256()
    minimum, maximum, ysum, error = float("inf"), float("-inf"), 0.0, 0.0
    with destination.open("wb") as handle:
        for frame in frames:
            frame = np.asarray(frame, dtype=np.float32)
            if (frame.ndim != 3 or frame.shape[-1] != 3 or min(frame.shape[:2]) < 1
                    or not np.isfinite(frame).all() or np.max(np.abs(frame)) > np.finfo(np.float16).max):
                raise ValueError("colorimetric export requires finite HxWx3 FP16-representable linear coordinates")
            if shape is not None and shape != frame.shape:
                raise ValueError("export frame geometry changed")
            shape = frame.shape
            packed = frame.astype("<f2")
            decoded = packed.astype(np.float64)
            payload = packed.tobytes()
            handle.write(payload)
            digest.update(payload)
            minimum, maximum = min(minimum, float(decoded.min())), max(maximum, float(decoded.max()))
            ysum += float((decoded @ matrix[1]).sum())
            error = max(error, float(np.max(np.abs(decoded - frame))))
            count += 1
    if shape is None:
        raise ValueError("export needs at least one frame")
    height, width, _ = shape
    return {"file": relative, "width": width, "height": height, "frame_count": count,
            "frame_stride_bytes": width * height * 6, "byte_length": count * width * height * 6,
            "sha256": digest.hexdigest(), "statistics": {
                "source": "decoded FP16; XYZ Y from declared output matrix",
                "peak_channel_nits": maximum, "minimum_channel_nits": minimum,
                "mean_luminance_nits": ysum / (count * width * height),
                "float16_max_absolute_error_nits": error}}


def generate_colorimetric_export(out, width, height, *, motion_frames, config, output_space):
    if type(width) is not int or type(height) is not int or width < 160 or height < 96:
        raise ValueError("web export resolution must be integers at least 160x96")
    if type(motion_frames) is not int or motion_frames < 1:
        raise ValueError("motion_frames must be a positive integer")
    if output_space not in ("xyz", "bt709", "display_p3", "bt2020"):
        raise ValueError("unsupported linear output space")
    matrix = np.eye(3) if output_space == "xyz" else rgb_to_xyz_matrix(RGB_SPACES[output_space], D65)
    to709 = np.linalg.inv(rgb_to_xyz_matrix(RGB_SPACES["bt709"], D65)) @ matrix
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    profiles = [load_profile(name) for name in PROFILE_NAMES]
    sources = scenes(width, height)
    # The old procedural scenes use the explicitly declared source basis.
    # New wide-gamut fixtures retain their native BT.2020/D65 declaration.
    source_matrix = rgb_to_xyz_matrix(RGB_SPACES[config.source_primaries], config.source_white_xy)
    fixtures = color_volume_patterns(width, height)
    # A narrower RGB container cannot encode every BT.2020 primary with positive
    # PQ channels. Keep the native BT.2020 fixtures only for that declaration.
    if config.source_primaries == "bt2020" and tuple(config.source_white_xy) == tuple(D65):
        sources.update(fixtures)
    frame_time_ms = profiles[0].temporal.frame_time_ms
    root = Path(__file__).resolve().parent
    manifest = {
        "schema_version": 1, "generator": "python3 -m sim export-web --colorimetry",
        "disclaimer": DISCLAIMER, "resolution": [width, height],
        "format": {"dtype": "float16", "byte_order": "little", "channels": 3,
                   "layout": "frame-major HWC XYZ" if output_space == "xyz" else "frame-major HWC RGB", "units": "linear-nit", "alpha": "none",
                   "color_space": {"xyz": "linear-xyz", "bt709": "linear-srgb", "bt2020": "linear-bt2020", "display_p3": "linear-display-p3"}[output_space],
                   "coordinate_labels": ["X", "Y", "Z"] if output_space == "xyz" else ["R", "G", "B"],
                   "primaries": output_space, "white_point": "D65", "white_xy": list(D65),
                   "primaries_xy": None if output_space == "xyz" else [list(xy) for xy in RGB_SPACES[output_space]],
                   "transfer": "linear absolute XYZ or nit-scaled RGB coordinates; XYZ Y is cd/m²",
                   "row_order": "top-to-bottom", "header_bytes": 0, "signed_components": True,
                   "rgb_to_xyz": matrix.tolist(), "to_linear_srgb": to709.tolist(),
                   "colorimetry_status": "D matrix calculations under P panel primaries/white/volume; calibration NR",
                   "presentation": "Shared browser exposure and host gamut clipping follow color conversion; no exposure is baked in."},
        "colorimetry": {"config": asdict(config), "source_rgb_to_xyz": source_matrix.tolist(),
                        "mastering_gamut": "NR", "calibrated_profile_fit": "NR"},
        "profile_overrides": {"input_eotf": "pq", "viewing_angle_deg": 0, "ambient_lux": 0,
                              "integration_samples": INTEGRATION_SAMPLES},
        "temporal_protocol": {"pre_roll_frames": PRE_ROLL, "pan_frames": motion_frames,
                              "pan_px_per_frame": PAN_SPEED, "frame_time_ms": frame_time_ms,
                              "fps": 1000 / frame_time_ms,
                              "history": "One persistent display pipeline per profile; held pre-roll then wrapped pan.",
                              "loop_boundary": "Not a continuous loop; saved history jumps at loop boundary."},
        "implementation_sha256": {f"sim/{path.relative_to(root).as_posix()}": sha256(path.read_bytes()).hexdigest()
                                  for path in sorted(root.rglob("*.py"))},
        "profiles": _snapshot_profiles(out, profiles), "scenes": [],
    }
    for profile, record in zip(profiles, manifest["profiles"]):
        pipeline = Pipeline(_gallery_profile(profile), colorimetry=config)
        record["colorimetry"] = pipeline.colorimetry_metadata()
        sidecar = profile_path(profile.name).with_name(profile.name + ".colorimetry.yaml")
        payload = sidecar.read_bytes()
        relative = f"metadata/{sidecar.name}"
        (out / relative).write_bytes(payload)
        record["snapshots"]["colorimetry"] = {"file": relative, "byte_length": len(payload),
                                               "sha256": sha256(payload).hexdigest(), "source": f"sim/profiles/{sidecar.name}"}

    def scene(identifier, title, description, kind, reference, w=width, h=height, count=1):
        result = {"id": identifier, "title": title, "description": description, "kind": kind,
                  "reference_nits": reference, "width": w, "height": h, "frame_count": count,
                  "fps": 1000 / frame_time_ms if kind == "motion" else 0, "assets": {}}
        if identifier in sources:
            result["source_linear_float32_sha256"] = sha256(sources[identifier].tobytes()).hexdigest()
        manifest["scenes"].append(result)
        return result

    for identifier, title, description, reference in STILL_SCENES:
        record = scene(identifier, title, description, "still", reference)
        for profile in profiles:
            pipeline = Pipeline(_gallery_profile(profile), colorimetry=config)
            frame = pipeline.run_linear(pq_oetf(sources[identifier]))
            asset = _write_frames(out, f"frames/{identifier}/{profile.name}.f16",
                                  [pipeline.output_in_space(frame, output_space)], matrix)
            asset["colorimetry_diagnostics"] = diagnostic_summary(pipeline.last_colorimetry_diagnostics)
            record["assets"][profile.name] = asset
    if config.source_primaries == "bt2020" and tuple(config.source_white_xy) == tuple(D65):
        for identifier in fixtures:
            record = scene(identifier, "M15 · " + identifier.replace("_", " "),
                           "P synthetic BT.2020/D65 color-volume intent; illustrative patches, calibration NR.", "still", 2000)
            for profile in profiles:
                pipeline = Pipeline(_gallery_profile(profile), colorimetry=config)
                frame = pipeline.run_linear(pq_oetf(sources[identifier]))
                record["assets"][profile.name] = _write_frames(
                    out, f"frames/{identifier}/{profile.name}.f16", [pipeline.output_in_space(frame, output_space)], matrix)
                record["assets"][profile.name]["colorimetry_diagnostics"] = diagnostic_summary(pipeline.last_colorimetry_diagnostics)

    record = scene("macro_apertures", "Synthetic subpixel apertures", "P panel-basis apertures converted to declared output coordinates.",
                   "macro", MACRO_REFERENCE, 16 * MACRO_SCALE, 8 * MACRO_SCALE)
    cy, cx = height // 2 - 4, width // 2 - 8
    for profile in profiles:
        pipeline = Pipeline(_gallery_profile(profile), colorimetry=config)
        logical = pipeline.run_linear(pq_oetf(sources["macro_subpixel"])).rgb[cy:cy+8, cx:cx+16]
        macro = Frame(render_macro(logical, profile.panel.subpixel, scale=MACRO_SCALE))
        record["assets"][profile.name] = _write_frames(out, f"frames/macro_apertures/{profile.name}.f16",
                                                       [pipeline.output_in_space(macro, output_space)], matrix)
    record = scene("motion_pan", "Pan · persistent response history", "P wrapped pursuit; one display tick per output, color conversion after motion.",
                   "motion", MOTION_REFERENCE, count=motion_frames)
    record["pts_seconds"] = [index * frame_time_ms / 1000 for index in range(motion_frames)]
    record["frame_time_ms"] = frame_time_ms
    for profile in profiles:
        def frames(profile=profile):
            pipeline = Pipeline(_gallery_profile(profile, motion=PAN_SPEED), colorimetry=config)
            encoded = pq_oetf(sources["motion_pan"])
            for _ in range(PRE_ROLL):
                pipeline.run_linear(encoded)
            for index in range(1, motion_frames + 1):
                yield pipeline.output_in_space(pipeline.run_linear(np.roll(encoded, int(index * PAN_SPEED), axis=1)), output_space)
        record["assets"][profile.name] = _write_frames(out, f"frames/motion_pan/{profile.name}.f16", frames(), matrix)
    manifest["asset_bytes"] = sum(asset["byte_length"] for record in manifest["scenes"] for asset in record["assets"].values())
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return manifest
