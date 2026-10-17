"""M15 opt-in tristimulus colorimetry and synthetic color-volume model.

Standard xy definitions and matrices derived from them are D. Assigning a
triangle to a generic panel, the radial compressor, and RGBW capacity law are
P. No spectra, measured display calibration, chromatic adaptation, or vendor
gamut mapper are implied. Legacy code does not call this module when disabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from numbers import Real

import numpy as np

from sim.frame import Frame

D65 = (0.3127, 0.3290)
STANDARD_PRIMARIES = {
    "bt709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "display_p3": ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
    "bt2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
}
RGB_SPACES = STANDARD_PRIMARIES


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be finite")
    try:
        if math.isfinite(value):
            return float(value)
    except (OverflowError, TypeError):
        pass
    raise ValueError(f"{name} must be finite")


def _xy(values, name):
    try:
        xy = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must contain two finite chromaticities") from exc
    if (xy.shape != (2,) or not np.isfinite(xy).all() or np.any(xy <= 0)
            or xy.sum() > 1.0 + 1e-12):
        raise ValueError(f"{name} requires x > 0, y > 0, x+y <= 1")
    return xy


def rgb_to_xyz_matrix(primaries_xy, white_xy=D65) -> np.ndarray:
    """Derive a float64 RGB→XYZ matrix, with neutral RGB=(1,1,1) at Y=1.

    Columns are the primary XYZ vectors scaled by the unique solution for
    the declared white. Require positive primary scales: the reference white
    must lie inside a nondegenerate primary triangle.
    """

    try:
        primary = np.asarray(primaries_xy, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("primaries_xy must contain finite xy pairs") from exc
    if primary.shape != (3, 2):
        raise ValueError("primaries_xy must be three xy pairs in R,G,B order")
    primary = np.array([_xy(xy, "primary xy") for xy in primary])
    white = _xy(white_xy, "white_xy")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        columns = np.stack((primary[:, 0] / primary[:, 1], np.ones(3),
                            (1.0 - primary.sum(axis=1)) / primary[:, 1]))
        target = np.array((white[0] / white[1], 1.0,
                           (1.0 - white.sum()) / white[1]))
    if not np.isfinite(columns).all() or not np.isfinite(target).all():
        raise ValueError("chromaticities produce nonfinite XYZ coordinates")
    condition = np.linalg.cond(columns)
    if not np.isfinite(condition) or condition > 1e10:
        raise ValueError("primaries must define a nondegenerate triangle")
    scales = np.linalg.solve(columns, target)
    if not np.isfinite(scales).all() or np.any(scales <= 0):
        raise ValueError("white_xy must be strictly inside the primary triangle")
    return columns * scales[None, :]


def xyz_to_rgb_matrix(primaries_xy, white_xy=D65) -> np.ndarray:
    """Float64 inverse of :func:`rgb_to_xyz_matrix`."""

    return np.linalg.inv(rgb_to_xyz_matrix(primaries_xy, white_xy))


@dataclass(frozen=True)
class ColorimetryConfig:
    """Explicit source declarations and P mapping policy; disabled by default."""

    enabled: bool = False
    source_primaries: str = "bt709"
    source_white_xy: tuple[float, float] = D65
    gamut_mapping: str = "compress"
    compression_knee: float = 0.8

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("colorimetry enabled must be a boolean")
        if self.source_primaries not in STANDARD_PRIMARIES:
            raise ValueError("source_primaries must be bt709, display_p3, or bt2020")
        white = tuple(_xy(self.source_white_xy, "source_white_xy"))
        object.__setattr__(self, "source_white_xy", white)
        rgb_to_xyz_matrix(STANDARD_PRIMARIES[self.source_primaries], white)
        if self.gamut_mapping not in ("clip", "compress"):
            raise ValueError("gamut_mapping must be clip or compress")
        knee = _finite(self.compression_knee, "compression_knee")
        if not 0.0 <= knee < 1.0:
            raise ValueError("compression_knee must be finite in [0,1)")

    @property
    def active(self):
        return self.enabled


@dataclass(frozen=True)
class PanelColorimetry:
    """P panel basis and RGBW envelope, separate from the unchanged TVProfile."""

    primaries_xy: tuple[tuple[float, float], ...]
    white_xy: tuple[float, float] = D65
    woled_rgb_peak_ratio: float = 1.0
    woled_white_exponent: float = 2.0

    def __post_init__(self):
        rgb_to_xyz_matrix(self.primaries_xy, self.white_xy)
        object.__setattr__(self, "primaries_xy", tuple(tuple(float(v) for v in xy)
                                                       for xy in self.primaries_xy))
        object.__setattr__(self, "white_xy", tuple(float(v) for v in self.white_xy))
        for name in ("woled_rgb_peak_ratio", "woled_white_exponent"):
            value = _finite(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if self.woled_rgb_peak_ratio > 1.0:
            raise ValueError("woled_rgb_peak_ratio must be in (0,1]")


def source_to_panel_matrix(config: ColorimetryConfig, panel: PanelColorimetry) -> np.ndarray:
    """Preserve absolute XYZ; differing whites receive no implicit adaptation."""

    source = rgb_to_xyz_matrix(STANDARD_PRIMARIES[config.source_primaries],
                               config.source_white_xy)
    return xyz_to_rgb_matrix(panel.primaries_xy, panel.white_xy) @ source


def convert_rgb(rgb: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Apply a float64 matrix; store float32 RGB/XYZ coordinates without clipping."""

    return (np.asarray(rgb, dtype=np.float64) @ np.asarray(matrix, dtype=np.float64).T).astype(np.float32)


def panel_luminance(rgb: np.ndarray, panel: PanelColorimetry) -> np.ndarray:
    """XYZ Y from exact declared panel coefficients, in the input's nit units."""

    coefficients = rgb_to_xyz_matrix(panel.primaries_xy, panel.white_xy)[1]
    return np.asarray(rgb, dtype=np.float64) @ coefficients


def decode_source(encoded, params, config: ColorimetryConfig) -> Frame:
    """Decode HLG with the declared source Y; all other EOTFs use legacy decode."""

    from sim.stages.decode import as_code_values, decode_encoded

    if params.eotf.lower() != "hlg":
        return decode_encoded(encoded, params)
    from sim.color import hlg_scene_linear

    peak = float(params.hlg_peak_nits)
    if not math.isfinite(peak) or peak <= 0:
        raise ValueError("HLG peak_nits must be positive and finite")
    source = rgb_to_xyz_matrix(STANDARD_PRIMARIES[config.source_primaries], config.source_white_xy)
    scene = np.asarray(hlg_scene_linear(as_code_values(encoded)), dtype=np.float64)
    y = scene @ source[1]
    gamma = 1.2 + 0.42 * np.log10(peak / 1000.0)
    scale = np.zeros_like(y)
    nonzero = y > 0
    scale[nonzero] = np.power(y[nonzero], gamma - 1.0)
    return Frame((peak * scene * scale[..., None]).astype(np.float32))


def gamut_map(rgb: np.ndarray, panel: PanelColorimetry, method="compress", knee=0.8):
    """Map into the nonnegative panel RGB cone, leaving brightness to HDR.

    Compression preserves exact XYZ Y and the straight CIE u′v′ ray from
    declared panel white. This geometric hue definition is P, not perceptual
    uniformity. The exponential radial knee is P. Clip independently sets
    negative channels to zero and may alter hue/Y. There is no upper clamp.
    """

    color = np.asarray(rgb, dtype=np.float64)
    if color.ndim < 1 or color.shape[-1] != 3 or color.size == 0 or not np.isfinite(color).all():
        raise ValueError("gamut input must be finite RGB")
    if method not in ("clip", "compress"):
        raise ValueError("gamut method must be clip or compress")
    knee = _finite(knee, "compression knee")
    if not 0 <= knee < 1:
        raise ValueError("compression knee must be finite in [0,1)")
    # A small absolute tolerance excludes float32 roundoff at exact boundaries.
    outside = np.any(color < -1e-6, axis=-1)
    if method == "clip":
        mapped = np.maximum(color, 0.0)
        changed = np.any(color < 0, axis=-1)
    else:
        y = panel_luminance(color, panel)
        nonblack = y > 0
        if np.any((~nonblack) & np.any(np.abs(color) > 1e-6, axis=-1)):
            raise ValueError("nonblack gamut input must have positive XYZ Y")
        # rho=1-min(rgb)/Y is the inverse neutral-ray distance to the cone.
        rho = np.zeros_like(y)
        np.divide(y - np.min(color, axis=-1), y, out=rho, where=nonblack)
        rho = np.maximum(rho, 0.0)
        compressed = np.where(rho <= knee, rho,
                              knee + (1.0-knee) * (-np.expm1(-np.maximum(rho-knee, 0)/(1.0-knee))))
        scale = np.ones_like(rho)
        np.divide(compressed, rho, out=scale, where=rho > 0)
        mapped = y[..., None] + (color-y[..., None]) * scale[..., None]
        mapped = np.maximum(mapped, 0.0)  # Roundoff only; the ray already fits.
        changed = rho > knee
    return mapped.astype(np.float32), {
        "input_out_of_gamut_mask": outside,
        "input_out_of_gamut_fraction": float(np.mean(outside)),
        "gamut_changed_mask": changed,
        "gamut_changed_fraction": float(np.mean(changed)),
        "gamut_domain": "panel_nonnegative_rgb_cone_before_capacity",
    }


def joint_tone_map(frame: Frame, params, panel: PanelColorimetry, *, capacity_nits: float):
    """One P shoulder owner for global HDR/ABL and RGBW color capacity.

    Convert the combined channel-cube capacity to attainable XYZ Y along
    the input RGB ray, then apply a single common gain. No post-map chroma
    projection or independent white-subpixel limiter follows this operation.
    """

    if params.tone_map != "soft_clip":
        raise ValueError("M15 colorimetry requires soft_clip tone mapper")
    capacity = float(capacity_nits)
    peak = float(params.panel_peak_nits)
    if not math.isfinite(capacity) or capacity <= 0 or not math.isfinite(peak) or peak <= 0:
        raise ValueError("global and panel capacities must be positive and finite")
    if float(params.abl_power_budget_nits) != 0:
        raise ValueError("M15 joint capacity conflicts with abl_power_budget_nits")
    rgb = np.asarray(frame.rgb, dtype=np.float64)
    if not np.isfinite(rgb).all() or np.any(rgb < 0):
        raise ValueError("joint capacity input must be finite nonnegative panel RGB")
    maximum = np.max(rgb, axis=-1)
    neutral = np.ones_like(maximum)
    np.divide(np.min(rgb, axis=-1), maximum, out=neutral, where=maximum > 0)
    color_cap = peak * (panel.woled_rgb_peak_ratio
                        + (1.0-panel.woled_rgb_peak_ratio)*neutral**panel.woled_white_exponent)
    cube_cap = np.minimum(capacity, color_cap)
    y = panel_luminance(rgb, panel)
    y_cap = np.full_like(y, capacity)
    np.divide(cube_cap*y, maximum, out=y_cap, where=maximum > 0)
    knee = y_cap * float(np.clip(params.knee_ratio, 0, 1))
    span = y_cap-knee
    excess = np.maximum(y-knee, 0)
    normalized = np.zeros_like(y)
    np.divide(excess, span, out=normalized, where=span > 1e-12)
    shoulder = knee + span * (-np.expm1(-np.minimum(normalized, 745)))
    shoulder = np.where(span > 1e-12, shoulder, np.minimum(y, y_cap))
    y_out = np.where(y <= knee, y, np.minimum(shoulder, y_cap))
    scale = np.ones_like(y)
    np.divide(y_out, y, out=scale, where=y > 0)
    result = (rgb*scale[..., None]).astype(np.float32)
    exceeded = maximum > cube_cap
    return Frame(result, frame.backlight), {
        "global_capacity_nits": capacity,
        "volume_exceeded_mask": exceeded,
        "volume_exceeded_fraction": float(np.mean(exceeded)),
        "color_capacity_nits": color_cap.astype(np.float32),
        "joint_capacity_nits": cube_cap.astype(np.float32),
        "luminance_capacity_nits": y_cap.astype(np.float32),
        "capacity_owner": "joint_hdr_abl_rgbw_v1",
    }


def metadata(config: ColorimetryConfig, panel: PanelColorimetry) -> dict:
    """JSON-compatible declarations; no measurement status is inferred."""

    source = rgb_to_xyz_matrix(STANDARD_PRIMARIES[config.source_primaries], config.source_white_xy)
    destination = rgb_to_xyz_matrix(panel.primaries_xy, panel.white_xy)
    return {
        "schema_version": 1,
        "source": {"primaries": config.source_primaries,
                   "primaries_xy": STANDARD_PRIMARIES[config.source_primaries],
                   "white_xy": config.source_white_xy, "declaration_evidence": "P",
                   "standard_primaries_evidence": "D", "mastering_gamut": "NR"},
        "panel": {**asdict(panel), "evidence": "P", "spectra": "NR", "measured_color_volume": "NR"},
        "rgb_to_xyz_source": source.tolist(), "rgb_to_xyz_panel": destination.tolist(),
        "source_to_panel": source_to_panel_matrix(config, panel).tolist(),
        "matrix_evidence": "D from declared inputs; panel inputs P",
        "chromatic_adaptation": "none_absolute_xyz",
        "gamut_mapping": {"model": "neutral_axis_compress_v1" if config.gamut_mapping == "compress" else "hard_clip_v1",
                          "method": config.gamut_mapping, "compression_knee": config.compression_knee,
                          "hue_definition": "CIE1976_uv_straight_ray_from_panel_white", "evidence": "P"},
        "capacity_model": {"model": "joint_hdr_abl_rgbw_v1", "evidence": "P",
                           "white_subpixel_allocation": "neutral_fraction_min_over_max"},
        "linear_units": "nit-scaled RGB coordinates; XYZ Y is cd/m^2",
    }
