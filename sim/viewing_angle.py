"""Opt-in angular experiments, separate from the unchanged TV profiles.

Every shipped endpoint is P (a synthetic placeholder), never a named-TV fit.
The versioned ``*.angular.yaml`` records snapshot these choices and preserve
the missing fits as NR. Ordinary profile loading does not read those records.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from sim.profile import TVProfile


def _finite(value: float, name: str) -> None:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite number")


@dataclass(frozen=True)
class ViewingAngleConfig:
    """Runtime center-ray rotations in degrees; off by default.

    The P geometry is a horizontal rotation followed by a vertical rotation,
    giving cos(theta) = cos(horizontal) * cos(vertical). The models assume
    unsigned symmetry and no azimuth dependence. They do not predict per-pixel
    angles, asymmetric films or IPS corner glow.
    """

    enabled: bool = False
    horizontal_deg: float = 0.0
    vertical_deg: float = 0.0

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        for name in ("horizontal_deg", "vertical_deg"):
            value = getattr(self, name)
            _finite(value, name)
            if abs(value) >= 90.0:
                raise ValueError(f"{name} must be strictly between -90 and 90 degrees")

    @property
    def active(self) -> bool:
        return self.enabled and (self.horizontal_deg != 0.0 or self.vertical_deg != 0.0)

    @property
    def angle_deg(self) -> float:
        # atan2 avoids acos cancellation at very small nonzero angles.
        h, v = math.radians(self.horizontal_deg), math.radians(self.vertical_deg)
        return math.degrees(math.atan2(math.hypot(math.sin(h), math.cos(h) * math.sin(v)),
                                       math.cos(h) * math.cos(v)))


def _validate_params(params, vector_names: tuple[str, ...]) -> None:
    _finite(params.max_angle_deg, "max_angle_deg")
    if not 0.0 < params.max_angle_deg <= 45.0:
        raise ValueError("max_angle_deg must be in (0, 45] degrees")
    for name in vector_names:
        vector = getattr(params, name)
        if not isinstance(vector, tuple) or len(vector) != 3:
            raise ValueError(f"{name} must be a tuple of three positive RGB values")
        for value in vector:
            _finite(value, name)
            if value <= 0.0:
                raise ValueError(f"{name} must contain positive RGB values")


@dataclass(frozen=True)
class LcdAngularParams:
    """Independent P endpoints at 45 degrees, interpolated only in support.

    ``black_gain_45`` is emitted black relative to on-axis black, rather than
    epsilon/epsilon0. ``gray_exponent_45`` acts on already-linearized aperture
    transmission, not encoded source values. Full current-profile fits are NR.
    """

    max_angle_deg: float = 45.0
    white_gain_45: tuple[float, float, float] = (1.0, 1.0, 1.0)
    black_gain_45: tuple[float, float, float] = (1.0, 1.0, 1.0)
    gray_exponent_45: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        _validate_params(self, ("white_gain_45", "black_gain_45", "gray_exponent_45"))


@dataclass(frozen=True)
class EmissiveAngularParams:
    """P angular RGB emission gains only; measured gains/spectra remain NR."""

    max_angle_deg: float = 45.0
    emission_gain_45: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        _validate_params(self, ("emission_gain_45",))


AngularParams = LcdAngularParams | EmissiveAngularParams


def angular_parameters(profile: TVProfile) -> AngularParams:
    """Select a synthetic demonstration, without changing/reading TV YAMLs."""

    if profile.self_emissive:
        gains = (0.95, 0.96, 0.94) if profile.technology == "qdoled" else (0.88, 0.92, 0.96)
        return EmissiveAngularParams(emission_gain_45=gains)
    if profile.technology == "va_lcd":
        return LcdAngularParams(white_gain_45=(0.65, 0.65, 0.65),
                                black_gain_45=(5.0, 5.0, 5.0),
                                gray_exponent_45=(0.80, 0.84, 0.90))
    return LcdAngularParams(white_gain_45=(0.80, 0.80, 0.80),
                            black_gain_45=(2.0, 2.0, 2.0),
                            gray_exponent_45=(0.98, 1.0, 1.02))


def angular_fraction(config: ViewingAngleConfig, params: AngularParams) -> float:
    """P sin-squared interpolation coordinate; reject extrapolation."""

    theta = config.angle_deg
    if theta > params.max_angle_deg + 1e-12:
        raise ValueError(f"viewing angle {theta:g} degrees outside angular model support "
                         f"[0, {params.max_angle_deg:g}] degrees")
    return min(1.0, (math.sin(math.radians(theta)) / math.sin(math.radians(45.0))) ** 2)


def validate_angular_path(config: ViewingAngleConfig, params: AngularParams,
                          *, self_emissive: bool, contrast: float) -> None:
    """Validate opt-in model type, support and LCD extinction before a tick."""

    if not config.active:
        return
    expected = EmissiveAngularParams if self_emissive else LcdAngularParams
    if not isinstance(params, expected):
        raise ValueError(f"angular model must use {expected.__name__} for this panel")
    angular_fraction(config, params)
    if not self_emissive:
        _finite(contrast, "native_contrast")
        if contrast <= 1.0:
            raise ValueError("native_contrast must be greater than 1")
        # Endpoints bound the log-interpolated extinction over all support.
        smax = (math.sin(math.radians(params.max_angle_deg)) / math.sin(math.radians(45.0))) ** 2
        if any((b / w) ** smax > contrast for b, w in zip(params.black_gain_45, params.white_gain_45)):
            raise ValueError("angular leakage epsilon exceeds 1 within model support")
