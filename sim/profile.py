"""YAML TV profiles.

A profile is a labeled bag of placeholder parameters (see ``sim/profiles``).
Nothing in here is a measured panel. Stages read the dataclasses below and
do not parse YAML themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


@dataclass
class InputParams:
    """How encoded code values become linear nits."""

    eotf: str = "srgb"
    sdr_white_nits: float = 100.0
    hlg_peak_nits: float = 1000.0


@dataclass
class ProcessingParams:
    """Spatial image processing before the panel. MEMC is not modeled."""

    scale_factor: float = 1.0
    scale_mode: str = "bilinear"
    sharpen_amount: float = 0.0
    sharpen_sigma: float = 1.0


@dataclass
class BacklightParams:
    """Local-dimming or self-emissive drive.

    ``mode`` is ``fald`` (2D zone grid), ``edge`` (coarse zones, same math),
    or ``per_pixel`` (OLED). ``psf_sigma_zones`` is the light-spread sigma in
    units of one zone. ``floor_nits`` is a minimum LED drive.
    """

    mode: str = "fald"
    zones_x: int = 16
    zones_y: int = 12
    psf_sigma_zones: float = 0.7
    peak_nits: float = 1000.0
    floor_nits: float = 0.0


@dataclass
class PanelParams:
    """LCD transmission, subpixel mosaic, and a placeholder viewing-angle law."""

    native_contrast: float = 1000.0
    subpixel: str = "rgb_stripe"
    viewing_angle_deg: float = 0.0
    # Off-axis contrast/chroma loss: factor = 1 / (1 + k * degrees). Larger k
    # means a narrower viewing angle (typical of VA versus IPS).
    angle_loss_per_deg: float = 0.0
    color_matrix: list[float] = field(default_factory=lambda: list(_IDENTITY))


@dataclass
class HdrParams:
    """Highlight compression and a placeholder OLED ABL curve.

    Effective peak is ``panel_peak_nits`` when ABL is off. When ABL is on,
    average picture level slides that peak toward ``abl_full_field_nits``.
    """

    tone_map: str = "soft_clip"
    panel_peak_nits: float = 1000.0
    knee_ratio: float = 0.85
    abl_enabled: bool = False
    abl_full_field_nits: float = 1000.0
    abl_gamma: float = 2.0


@dataclass
class AmbientParams:
    """Lambertian room-light reflection added in nits."""

    lux: float = 0.0
    reflectance: float = 0.02


@dataclass
class TemporalParams:
    """Response time (exponential approach) and sample-and-hold blur."""

    response_time_ms: float = 8.0
    frame_time_ms: float = 1000.0 / 60.0
    sample_and_hold: bool = True
    motion_px_per_frame: float = 0.0


@dataclass
class OutputParams:
    """Preview encoding. ``reference_nits`` is the nit level mapped to code 1."""

    eotf: str = "srgb"
    reference_nits: float = 1000.0


@dataclass
class TVProfile:
    name: str
    technology: str
    description: str
    input: InputParams
    processing: ProcessingParams
    backlight: BacklightParams
    panel: PanelParams
    hdr: HdrParams
    ambient: AmbientParams
    temporal: TemporalParams
    output: OutputParams

    @property
    def self_emissive(self) -> bool:
        return self.backlight.mode == "per_pixel"

    def with_overrides(
        self,
        *,
        input_eotf: str | None = None,
        viewing_angle_deg: float | None = None,
        ambient_lux: float | None = None,
        motion_px: float | None = None,
    ) -> TVProfile:
        """Return a copy with CLI overrides applied."""

        updated = self
        if input_eotf is not None:
            updated = replace(updated, input=replace(updated.input, eotf=input_eotf))
        if viewing_angle_deg is not None:
            updated = replace(
                updated, panel=replace(updated.panel, viewing_angle_deg=viewing_angle_deg)
            )
        if ambient_lux is not None:
            updated = replace(updated, ambient=replace(updated.ambient, lux=ambient_lux))
        if motion_px is not None:
            updated = replace(
                updated, temporal=replace(updated.temporal, motion_px_per_frame=motion_px)
            )
        return updated


def available_profiles() -> list[str]:
    return sorted(path.stem for path in PROFILES_DIR.glob("*.yaml"))


def profile_path(name: str) -> Path:
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(available_profiles()) or "(none)"
        raise FileNotFoundError(f"Unknown profile {name!r}. Available: {known}")
    return path


def _section(cls, data: dict, key: str):
    raw = data.get(key) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"profile section {key!r} must be a mapping")
    return cls(**raw)


def load_profile(name: str) -> TVProfile:
    """Load ``sim/profiles/<name>.yaml``."""

    path = profile_path(name)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a mapping")
    return TVProfile(
        name=str(data.get("name", name)),
        technology=str(data["technology"]),
        description=str(data.get("description", "")),
        input=_section(InputParams, data, "input"),
        processing=_section(ProcessingParams, data, "processing"),
        backlight=_section(BacklightParams, data, "backlight"),
        panel=_section(PanelParams, data, "panel"),
        hdr=_section(HdrParams, data, "hdr"),
        ambient=_section(AmbientParams, data, "ambient"),
        temporal=_section(TemporalParams, data, "temporal"),
        output=_section(OutputParams, data, "output"),
    )
