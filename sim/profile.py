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
    """Spatial image processing before source reconstruction and the panel."""

    scale_factor: float = 1.0
    scale_mode: str = "bilinear"
    sharpen_amount: float = 0.0
    sharpen_sigma: float = 1.0


@dataclass
class PsfProfile:
    """A tabulated half-profile line-spread function, in zone pitches.

    ``x`` and ``y`` list the relative response at ``0, step_zones,
    2*step_zones, ...`` from a zone centre, which is the shape a symmetrized
    LSF measurement is normally reported in. Either axis may be omitted, in
    which case that axis keeps the parametric kernel. Nothing shipped in
    ``sim/profiles`` is measured; these tables are the hook a measurement
    would be loaded into, and they are labeled placeholders until then.
    """

    step_zones: float = 1.0
    x: list[float] | None = None
    y: list[float] | None = None


@dataclass
class BacklightParams:
    """Local-dimming or self-emissive drive.

    ``mode`` is ``fald`` (2D zone grid), ``edge`` (column strips when
    ``zones_y`` is 1), or ``per_pixel`` (OLED). Core PSF sigmas are in zone
    pitches for zoned modes and in pixels for ``per_pixel``. ``psf_sigma_y_*``
    left as ``None`` copies the horizontal sigma. Tail weight 0 is a single
    core component. ``zone_percentile`` 100 is a zone maximum. These are
    modeling knobs, not measured optical constants. ``floor_nits`` is a
    minimum drive.

    ``psf_shape`` picks the tail component: ``gaussian`` is the original
    two-Gaussian mixture, ``exponential_tail`` replaces the far term with a
    slower ``exp(-r/s)`` skirt. ``psf_profile`` overrides either axis with a
    tabulated LSF. ``psf_boundary`` is the edge policy: ``reflect`` mirrors
    light back in, ``zero`` lets a border zone lose the part of its footprint
    that falls off the panel, and ``calibrated_zero`` applies the all-on
    normalization ``B_i = Bmax_i (Σ_j H_ij d_j)/(Σ_j H_ij)`` from
    ``research/m3-local-dimming-params.md``.
    """

    mode: str = "fald"
    zones_x: int = 16
    zones_y: int = 12
    psf_sigma_zones: float = 0.7
    psf_sigma_y_zones: float | None = None
    psf_tail_sigma_zones: float = 2.0
    psf_tail_sigma_y_zones: float | None = None
    psf_tail_weight: float = 0.0
    psf_shape: str = "gaussian"
    psf_boundary: str = "reflect"
    psf_profile: PsfProfile | None = None
    zone_percentile: float = 100.0
    peak_nits: float = 1000.0
    floor_nits: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.psf_profile, dict):
            self.psf_profile = PsfProfile(**self.psf_profile)


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
    """Highlight compression and a placeholder load limiter.

    Effective peak is ``panel_peak_nits`` when ABL is off. When ABL is on,
    mean linear luminance (APL) slides that peak toward
    ``abl_full_field_nits``. ``abl_power_budget_nits`` is a separate global
    gain on weighted channel drive; 0 leaves it off.

    ``abl_source`` picks which picture the APL comes from. ``emitted`` is the
    frame handed to the tone map, which on an LCD is already past the panel.
    ``demand`` is the requested picture before the panel and before any
    limiting, which is the contract in ``research/m3-hdr-abl-params.md``.
    ``abl_reference_nits`` is ``P0`` in that contract; 0 uses
    ``panel_peak_nits``. ``abl_response_ms`` and ``abl_backlight_tracking``
    are described in :mod:`sim.load`; both default to off.
    """

    tone_map: str = "soft_clip"
    panel_peak_nits: float = 1000.0
    knee_ratio: float = 0.85
    abl_enabled: bool = False
    abl_full_field_nits: float = 1000.0
    abl_gamma: float = 2.0
    abl_source: str = "emitted"
    abl_reference_nits: float = 0.0
    abl_response_ms: float = 0.0
    abl_backlight_tracking: float = 0.0
    # Channel-power proxy in weighted nits (not watts). 0 disables the gain.
    # Weights are a placeholder, not a measured current budget.
    abl_power_budget_nits: float = 0.0
    abl_channel_weights: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])


@dataclass
class AmbientParams:
    """Lambertian room-light reflection added in nits."""

    lux: float = 0.0
    reflectance: float = 0.02


@dataclass
class TemporalParams:
    """Response lag, optional overdrive, sample-and-hold, and a BFI gate.

    ``overdrive_gain`` 0 or ``overdrive_ms`` 0 leaves the single first-order
    step. ``bfi_duty`` 1 is a continuous hold. ``overdrive_ceiling_nits`` 0
    means the overdriven command is only clipped at zero (no calibrated
    headroom). ``integration_samples`` 1 keeps the original endpoint plus
    seven-shift pursuit approximation. Values greater than 1 integrate
    response and a centered rectangular BFI pulse within each frame; 16 is
    useful for an 8-pixel/frame gallery pan. None of these defaults are a
    measured LUT or strobe waveform.
    """

    response_time_ms: float = 8.0
    frame_time_ms: float = 1000.0 / 60.0
    sample_and_hold: bool = True
    motion_px_per_frame: float = 0.0
    overdrive_gain: float = 0.0
    overdrive_ms: float = 0.0
    overdrive_ceiling_nits: float = 0.0
    bfi_duty: float = 1.0
    bfi_preserve_mean: bool = False
    integration_samples: int = 1


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
    return sorted(
        path.stem
        for path in PROFILES_DIR.glob("*.yaml")
        if not path.name.endswith(".provenance.yaml")
    )


def profile_path(name: str) -> Path:
    path = PROFILES_DIR / f"{name}.yaml"
    if name.endswith(".provenance") or not path.is_file():
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
