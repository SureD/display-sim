"""Optional P OLED capacity controller (M11/M13), separate from TV profiles.

The scalar is allowed HDR capacity in nits. It is neither a power/thermal
estimate nor pixel response. No measured constants or implicit taus exist.
The shipped synthetic experiment ledger lives outside the profile tree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from numbers import Real

from sim.load import abl_capacity, load_fraction
from sim.profile import HdrParams, TVProfile

MODEL = "capacity_attack_release_v1"
TARGET_MAP = "instantaneous_abl_capacity_v1"


def finite_number(value, name: str) -> float:
    try:
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc


@dataclass(frozen=True)
class ABLDynamicsConfig:
    """P runtime policy; absent taus are unknown, never interpreted as zero."""

    model: str = "off"
    attack_ms: float | None = None
    release_ms: float | None = None
    initial: str = "cold"
    initial_capacity_nits: float | None = None
    parameter_status: str = "placeholder"

    def __post_init__(self):
        if self.model not in ("off", MODEL):
            raise ValueError(f"unsupported ABL dynamics model {self.model!r}")
        if self.parameter_status != "placeholder":
            raise ValueError("ABL dynamics parameter_status must be placeholder (P); calibration is NR")
        if self.initial not in ("cold", "settled_first_tick", "explicit", "resume"):
            raise ValueError("unknown ABL initialization policy")
        if not self.active:
            if (self.attack_ms is not None or self.release_ms is not None
                    or self.initial != "cold" or self.initial_capacity_nits is not None):
                raise ValueError("ABL dynamics options require an active model, not off")
            return
        for name in ("attack_ms", "release_ms"):
            if finite_number(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.initial == "explicit":
            finite_number(self.initial_capacity_nits, "initial_capacity_nits")
        elif self.initial_capacity_nits is not None:
            raise ValueError("initial_capacity_nits requires explicit initialization; resume is the sole owner")

    @property
    def active(self) -> bool:
        return self.model != "off"


@dataclass
class ABLCapacityState:
    """Float64 scalar and simulation clock at the last successful tick boundary."""

    capacity_nits: float | None = None
    elapsed_ms: float = 0.0
    ticks: int = 0


def validate_bounds(peak_nits: float, floor_nits: float) -> tuple[float, float]:
    peak = finite_number(peak_nits, "panel_peak_nits")
    floor = finite_number(floor_nits, "abl_full_field_nits")
    if not 0 < floor <= peak:
        raise ValueError("capacity bounds require 0 < abl_full_field_nits <= panel_peak_nits")
    return peak, floor


def validate_state(state: ABLCapacityState, peak_nits: float, floor_nits: float) -> None:
    peak, floor = validate_bounds(peak_nits, floor_nits)
    if finite_number(state.elapsed_ms, "elapsed_ms") < 0:
        raise ValueError("elapsed_ms must be nonnegative")
    if type(state.ticks) is not int or state.ticks < 0:
        raise ValueError("ticks must be a nonnegative integer")
    if state.capacity_nits is None:
        if state.ticks != 0 or state.elapsed_ms != 0:
            raise ValueError("uninitialized capacity cannot have elapsed history")
    elif not floor <= finite_number(state.capacity_nits, "capacity_nits") <= peak:
        raise ValueError("capacity_nits outside declared capacity bounds")
    if (state.ticks == 0) != (state.elapsed_ms == 0):
        raise ValueError("capacity clock and tick history are inconsistent")


def validate_dynamics(profile: TVProfile, config: ABLDynamicsConfig) -> None:
    """Admission checks before any display history can change."""
    if not config.active:
        return
    if profile.technology not in ("woled", "qdoled") or not profile.self_emissive:
        raise ValueError("ABL capacity dynamics supports only WOLED/QD-OLED emissive panels")
    hdr = profile.hdr
    if not hdr.abl_enabled:
        raise ValueError("ABL capacity dynamics requires abl_enabled")
    if hdr.tone_map != "soft_clip":
        raise ValueError("ABL capacity dynamics requires soft_clip tone mapper")
    for name in ("abl_response_ms", "abl_backlight_tracking", "abl_power_budget_nits"):
        if finite_number(getattr(hdr, name), name) != 0:
            raise ValueError(f"ABL capacity dynamics conflicts with nonzero {name}")
    peak, floor = validate_bounds(hdr.panel_peak_nits, hdr.abl_full_field_nits)
    if finite_number(hdr.abl_gamma, "abl_gamma") <= 0:
        raise ValueError("abl_gamma must be positive")
    if finite_number(hdr.abl_reference_nits, "abl_reference_nits") < 0:
        raise ValueError("abl_reference_nits must be nonnegative; only zero selects P0")
    if str(hdr.abl_source).lower() not in ("demand", "emitted"):
        raise ValueError("unknown abl_source; use demand or emitted")
    if config.initial == "explicit" and not floor <= config.initial_capacity_nits <= peak:
        raise ValueError("initial_capacity_nits outside capacity bounds")


def instantaneous_target(apl_nits: float, params: HdrParams) -> float:
    """Use the unchanged static P map, without legacy APL filtering."""
    if finite_number(apl_nits, "APL") < 0:
        raise ValueError("APL must be nonnegative")
    return abl_capacity(apl_nits, params)


def initial_capacity(state: ABLCapacityState, target_nits: float,
                     peak_nits: float, config: ABLDynamicsConfig) -> float:
    if state.capacity_nits is not None:
        return float(state.capacity_nits)
    if config.initial == "resume":
        raise ValueError("resume requires a complete validated checkpoint before rendering")
    if config.initial == "explicit":
        return float(config.initial_capacity_nits)
    return float(target_nits if config.initial == "settled_first_tick" else peak_nits)


def update_capacity(state: ABLCapacityState, target_nits: float, peak_nits: float,
                    floor_nits: float, dt_ms: float, config: ABLDynamicsConfig) -> float:
    """One stable asymmetric e-fold update; invalid inputs never mutate state."""
    if not config.active:
        raise ValueError("capacity update requires active ABL dynamics")
    peak, floor = validate_bounds(peak_nits, floor_nits)
    validate_state(state, peak, floor)
    target = finite_number(target_nits, "target_nits")
    dt = finite_number(dt_ms, "dt_ms")
    if dt <= 0 or not math.isfinite(state.elapsed_ms + dt):
        raise ValueError("dt_ms must be positive with a finite elapsed clock")
    if not floor <= target <= peak:
        raise ValueError("target_nits outside capacity bounds")
    before = initial_capacity(state, target, peak, config)
    if not floor <= before <= peak:
        raise ValueError("initial_capacity_nits outside capacity bounds")
    if target == before:
        after = before
    else:
        tau = float(config.attack_ms if target < before else config.release_ms)
        after = target if tau == 0 else before + (-math.expm1(-dt / tau)) * (target - before)
    # All inputs are valid and the update is convex: only roundoff is clamped.
    state.capacity_nits = float(min(peak, max(floor, after)))
    state.elapsed_ms = float(state.elapsed_ms + dt)
    state.ticks += 1
    return state.capacity_nits


def digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def evolution(config: ABLDynamicsConfig) -> dict:
    """Initialization/state-file options do not alter controller identity."""
    return {key: value for key, value in asdict(config).items()
            if key not in ("initial", "initial_capacity_nits")}


def target_semantics(params: HdrParams) -> dict:
    return {"model": TARGET_MAP, "source": str(params.abl_source).lower(),
            "reference_nits": params.abl_reference_nits,
            "zero_reference": "panel_peak_nits", "peak_nits": params.panel_peak_nits,
            "full_field_nits": params.abl_full_field_nits, "gamma": params.abl_gamma}


def target_trace(apl: float, params: HdrParams) -> dict:
    return {"source": str(params.abl_source).lower(), "apl_nits": apl,
            "reference_nits": float(params.abl_reference_nits) or float(params.panel_peak_nits),
            "load_fraction": load_fraction(apl, params),
            "target_nits": instantaneous_target(apl, params)}


def reject_fit_composition(config: ABLDynamicsConfig | None) -> None:
    if config is not None and config.active:
        raise ValueError("M9 schema-1 .fit.json / per_window_normalized_drive_v1 cannot compose with active ABL dynamics")
