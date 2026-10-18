"""Opt-in P LC response and emission gates on exact rational sub-step clocks.

LCD state is physical RGB transmission, multiplied by the actual illumination
map only after response. OLED state is emitted RGB nits before BFI. A first-order
rise/fall surrogate and optional old-state/new-target command LUT are proposed
models, not measured voltage or gray-to-gray curves. The LUT prefix returns to
the requested target; it can produce overshoot without changing state ownership.

Each output sample stores the exact mean emitted light over its rational bin.
Exponential response is integrated analytically over intersections of PWM and
strobe/BFI windows, so narrow pulses cannot disappear between quadrature points.
The independent endpoint is never blurred or emission-gated. Pursuit integration
of these bin means is a separate, explicitly finite-resolution experiment.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any, cast

import numpy as np

from tv_sim.abl_dynamics import finite_number
from tv_sim.motion import as_fraction, rational_string
from tv_sim.profile import TVProfile

MODEL = "subframe_emission_v1"
MAX_GATE_WINDOWS = 100_000


@dataclass(frozen=True)
class SubframeConfig:
    """Separate default-off P policy with explicit active response constants.

    Tau-table rows are ``(command_level, rise_tau_ms, fall_tau_ms)``. LCD levels
    and OD commands use transmission in [0, 1]; OLED tau levels use nits. The
    square OD command grid is indexed by the actual initial state and requested
    target, with old levels on rows. Interpolation is bilinear without
    extrapolation. PWM phase is absolute cycles from PTS zero; strobe/BFI phase
    is a fraction of the current display tick. Rectangular pulses may wrap.
    """

    model: str = "off"
    substeps: int = 16
    rise_tau_ms: float | None = None
    fall_tau_ms: float | None = None
    tau_table: tuple[tuple[float, float, float], ...] | None = None
    overdrive_levels: tuple[float, ...] | None = None
    overdrive_commands: tuple[tuple[float, ...], ...] | None = None
    overdrive_fraction: str = "0/1"
    pwm_hz: str = "0/1"
    pwm_duty: str = "1/1"
    pwm_phase: str = "0/1"
    strobe_duty: str = "1/1"
    strobe_phase: str = "0/1"
    bfi_duty: str = "1/1"
    bfi_phase: str = "0/1"
    initial: str = "settled_first_tick"
    parameter_status: str = "placeholder"

    def __post_init__(self) -> None:
        if self.model not in ("off", MODEL):
            raise ValueError(f"unsupported subframe model {self.model!r}")
        if self.parameter_status != "placeholder":
            raise ValueError("subframe parameter_status must be placeholder (P); calibration is NR")
        if self.initial not in ("cold", "settled_first_tick", "resume"):
            raise ValueError("unknown subframe initialization policy")
        if type(self.substeps) is not int or not 1 <= self.substeps <= 4096:
            raise ValueError("substeps must be a positive integer at most 4096")
        for name in (
            "overdrive_fraction",
            "pwm_hz",
            "pwm_duty",
            "pwm_phase",
            "strobe_duty",
            "strobe_phase",
            "bfi_duty",
            "bfi_phase",
        ):
            # Canonical strings keep asdict/JSON identities rational and stable.
            object.__setattr__(self, name, rational_string(as_fraction(getattr(self, name))))
        if not self.active:
            defaults = {
                "substeps": 16,
                "rise_tau_ms": None,
                "fall_tau_ms": None,
                "tau_table": None,
                "overdrive_levels": None,
                "overdrive_commands": None,
                "overdrive_fraction": "0/1",
                "pwm_hz": "0/1",
                "pwm_duty": "1/1",
                "pwm_phase": "0/1",
                "strobe_duty": "1/1",
                "strobe_phase": "0/1",
                "bfi_duty": "1/1",
                "bfi_phase": "0/1",
                "initial": "settled_first_tick",
            }
            if any(getattr(self, name) != value for name, value in defaults.items()):
                raise ValueError("subframe options require an active model, not off")
            return
        for name in ("rise_tau_ms", "fall_tau_ms"):
            if finite_number(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        for name in ("pwm_duty", "strobe_duty", "bfi_duty"):
            if not 0 < Fraction(getattr(self, name)) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        for name in ("pwm_phase", "strobe_phase", "bfi_phase"):
            if not 0 <= Fraction(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be in [0, 1)")
        if Fraction(self.pwm_hz) < 0:
            raise ValueError("pwm_hz must be nonnegative; zero means DC")
        if Fraction(self.pwm_hz) == 0 and (
            Fraction(self.pwm_duty) != 1 or Fraction(self.pwm_phase) != 0
        ):
            raise ValueError("PWM duty/phase require positive pwm_hz")
        self._validate_tables()

    def _validate_tables(self) -> None:
        if self.tau_table is not None:
            if (
                not isinstance(self.tau_table, tuple)
                or not 2 <= len(self.tau_table) <= 32
                or any(not isinstance(row, tuple) or len(row) != 3 for row in self.tau_table)
            ):
                raise ValueError("tau_table requires 2..32 immutable (level, rise, fall) rows")
            for row in self.tau_table:
                if any(finite_number(value, "tau_table") < 0 for value in row):
                    raise ValueError("tau_table levels and taus must be nonnegative")
            if any(right[0] <= left[0] for left, right in zip(self.tau_table, self.tau_table[1:])):
                raise ValueError("tau_table levels must be strictly increasing")
        prefix = Fraction(self.overdrive_fraction)
        if not 0 <= prefix <= 1:
            raise ValueError("overdrive_fraction must be in [0, 1]")
        if self.overdrive_levels is None and self.overdrive_commands is None:
            if prefix != 0:
                raise ValueError("overdrive_fraction requires an explicit command LUT")
            return
        levels, commands = self.overdrive_levels, self.overdrive_commands
        if (
            not isinstance(levels, tuple)
            or not 2 <= len(levels) <= 32
            or not isinstance(commands, tuple)
            or len(commands) != len(levels)
            or any(not isinstance(row, tuple) or len(row) != len(levels) for row in commands)
        ):
            raise ValueError(
                "overdrive requires immutable levels and a matching square command LUT"
            )
        if any(not 0 <= finite_number(value, "overdrive_levels") <= 1 for value in levels):
            raise ValueError("overdrive_levels must be in [0, 1]")
        if (
            levels[0] != 0
            or levels[-1] != 1
            or any(right <= left for left, right in zip(levels, levels[1:]))
        ):
            raise ValueError("overdrive_levels must strictly increase from zero through one")
        for command_row in commands:
            if any(
                not 0 <= finite_number(value, "overdrive_commands") <= 1 for value in command_row
            ):
                raise ValueError("overdrive_commands must be in [0, 1]")
        if any(commands[index][index] != level for index, level in enumerate(levels)):
            raise ValueError("overdrive diagonal commands must equal their declared levels")
        if prefix <= 0:
            raise ValueError("overdrive LUT requires positive overdrive_fraction")

    @property
    def active(self) -> bool:
        return self.model != "off"


@dataclass
class SubframeState:
    """Ungated float64 response endpoint and exact next-tick boundary."""

    previous: np.ndarray | None = None
    ticks: int = 0
    next_pts: Fraction | None = None


@dataclass(frozen=True)
class SubframeSample:
    """Mean emission in a half-open rational bin and its response endpoint."""

    pts: Fraction
    duration: Fraction
    rgb: np.ndarray
    panel: np.ndarray
    gate_fraction: Fraction


@dataclass(frozen=True)
class SubframeResult:
    """Pure tick result; the pipeline commits endpoint/clock atomically."""

    samples: tuple[SubframeSample, ...]
    endpoint: np.ndarray
    mean: np.ndarray


def evolution(config: SubframeConfig) -> dict[str, Any]:
    """Initialization is recorded separately from continuation identity."""
    return {key: value for key, value in asdict(config).items() if key != "initial"}


def validate_path(profile: TVProfile, config: SubframeConfig) -> None:
    """Reject competing pixel/emission owners before any display update."""
    if not isinstance(config, SubframeConfig):
        raise ValueError("subframe configuration must be a SubframeConfig")
    if not config.active:
        return
    if profile.technology not in ("va_lcd", "ips_lcd", "woled", "qdoled"):
        raise ValueError("subframe emission supports LCD or OLED profiles")
    temporal = profile.temporal
    for name in (
        "response_time_ms",
        "overdrive_gain",
        "overdrive_ms",
        "overdrive_ceiling_nits",
        "motion_px_per_frame",
    ):
        if finite_number(getattr(temporal, name), name) != 0:
            raise ValueError(f"subframe emission conflicts with legacy temporal {name}")
    if temporal.bfi_duty != 1 or temporal.bfi_preserve_mean or temporal.integration_samples != 1:
        raise ValueError("subframe emission conflicts with legacy BFI or integration_samples")
    # sample_and_hold has no numerical effect when the rejected legacy motion
    # parameter is zero. Both bool values therefore retain explicit hold emission.
    if type(temporal.sample_and_hold) is not bool:
        raise ValueError("legacy sample_and_hold must be bool")
    if profile.self_emissive:
        if config.overdrive_levels is not None:
            raise ValueError("OLED subframe emission does not support LCD overdrive LUTs")
        if (
            Fraction(config.pwm_hz) != 0
            or Fraction(config.strobe_duty) != 1
            or Fraction(config.strobe_phase) != 0
        ):
            raise ValueError("OLED subframe emission requires BFI rather than LCD PWM/strobe")
    else:
        if Fraction(config.bfi_duty) != 1 or Fraction(config.bfi_phase) != 0:
            raise ValueError("LCD subframe emission requires backlight strobe rather than OLED BFI")
        if config.tau_table is not None and (
            config.tau_table[0][0] != 0 or config.tau_table[-1][0] != 1
        ):
            raise ValueError("LCD tau_table must cover transmission levels zero through one")


def validate_state(state: SubframeState) -> None:
    """Validate endpoint and exact clock without changing either."""
    if not isinstance(state, SubframeState):
        raise ValueError("subframe state must be a SubframeState")
    if type(state.ticks) is not int or state.ticks < 0:
        raise ValueError("subframe ticks must be a nonnegative integer")
    if state.previous is None:
        if state.ticks != 0 or state.next_pts is not None:
            raise ValueError("uninitialized subframe state cannot have elapsed history")
        return
    previous = state.previous
    if (
        not isinstance(previous, np.ndarray)
        or previous.dtype != np.float64
        or previous.ndim != 3
        or previous.shape[-1] != 3
        or min(previous.shape[:2]) < 1
        or not np.isfinite(previous).all()
        or np.any(previous < 0)
    ):
        raise ValueError("subframe previous must be finite nonnegative float64 RGB")
    if state.ticks <= 0 or not isinstance(state.next_pts, Fraction):
        raise ValueError("continued subframe state requires a successful exact clock boundary")


def _pulse_windows(
    start: Fraction,
    end: Fraction,
    period: Fraction,
    duty: Fraction,
    phase: Fraction,
) -> list[tuple[Fraction, Fraction]]:
    if duty == 1:
        return [(start, end)]
    offset = phase * period
    first, last = (start - offset) // period, (end - offset) // period
    if last - first + 1 > MAX_GATE_WINDOWS:
        raise ValueError("too many PWM gate windows in one display tick")
    result = []
    for index in range(first, last + 1):
        pulse_start = offset + index * period
        left, right = max(start, pulse_start), min(end, pulse_start + duty * period)
        if right > left:
            result.append((left, right))
    return result


def _intersections(
    left: list[tuple[Fraction, Fraction]], right: list[tuple[Fraction, Fraction]]
) -> list[tuple[Fraction, Fraction]]:
    result = []
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        a, b = left[left_index]
        c, d = right[right_index]
        if min(b, d) > max(a, c):
            result.append((max(a, c), min(b, d)))
        if b <= d:
            left_index += 1
        else:
            right_index += 1
    return result


def _gates(
    pts: Fraction, duration: Fraction, config: SubframeConfig, self_emissive: bool
) -> list[tuple[Fraction, Fraction]]:
    end = pts + duration
    duty = Fraction(config.bfi_duty if self_emissive else config.strobe_duty)
    phase = Fraction(config.bfi_phase if self_emissive else config.strobe_phase)
    # Translate tick-relative pulses into an absolute periodic representation.
    windows = _pulse_windows(pts, end, duration, duty, phase + pts / duration)
    if not self_emissive and Fraction(config.pwm_hz) > 0:
        pwm = _pulse_windows(
            pts,
            end,
            1 / Fraction(config.pwm_hz),
            Fraction(config.pwm_duty),
            Fraction(config.pwm_phase),
        )
        windows = _intersections(windows, pwm)
    return windows


def _taus(before: np.ndarray, command: np.ndarray, config: SubframeConfig) -> np.ndarray:
    if config.tau_table is None:
        rise = np.full(command.shape, cast(float, config.rise_tau_ms), dtype=np.float64)
        fall = np.full(command.shape, cast(float, config.fall_tau_ms), dtype=np.float64)
    else:
        table = np.asarray(config.tau_table, dtype=np.float64)
        if np.any(command < table[0, 0]) or np.any(command > table[-1, 0]):
            raise ValueError("command outside declared tau_table support; extrapolation rejected")
        rise = np.interp(command, table[:, 0], table[:, 1])
        fall = np.interp(command, table[:, 0], table[:, 2])
    return np.where(command >= before, rise, fall) / 1000


def _endpoint(
    before: np.ndarray, command: np.ndarray, tau: np.ndarray, seconds: float
) -> np.ndarray:
    result = command.copy()
    positive = tau > 0
    alpha = -np.expm1(-seconds / tau[positive])
    result[positive] = before[positive] + alpha * (command[positive] - before[positive])
    return result


def _integral(
    before: np.ndarray,
    command: np.ndarray,
    tau: np.ndarray,
    start: float,
    seconds: float,
) -> np.ndarray:
    result = command * seconds
    positive = tau > 0
    x = seconds / tau[positive]
    # Stable convex integral weights also cover very slow declared response:
    # d - tau*(1-exp(-d/tau)) loses all useful precision when d/tau is tiny.
    transition_weight = np.empty(x.shape, dtype=np.float64)
    small = x < 0.001
    z = x[small]
    transition_weight[small] = (
        seconds * z * (0.5 + z * (-1 / 6 + z * (1 / 24 + z * (-1 / 120 + z / 720))))
    )
    transition_weight[~small] = seconds - tau[positive][~small] * (-np.expm1(-x[~small]))
    start_level = _endpoint(before, command, tau, start)[positive]
    result[positive] = (
        start_level * (seconds - transition_weight) + command[positive] * transition_weight
    )
    return result


def _command(previous: np.ndarray, target: np.ndarray, config: SubframeConfig) -> np.ndarray:
    levels = np.asarray(config.overdrive_levels, dtype=np.float64)
    table = np.asarray(config.overdrive_commands, dtype=np.float64)
    old_index = np.clip(np.searchsorted(levels, previous, side="right") - 1, 0, len(levels) - 2)
    new_index = np.clip(np.searchsorted(levels, target, side="right") - 1, 0, len(levels) - 2)
    old_weight = (previous - levels[old_index]) / (levels[old_index + 1] - levels[old_index])
    new_weight = (target - levels[new_index]) / (levels[new_index + 1] - levels[new_index])
    lower = (
        table[old_index, new_index] * (1 - new_weight)
        + table[old_index, new_index + 1] * new_weight
    )
    upper = (
        table[old_index + 1, new_index] * (1 - new_weight)
        + table[old_index + 1, new_index + 1] * new_weight
    )
    # An unchanged settled pixel never receives a synthetic OD pulse, including
    # levels lying between diagonal nodes of the declared table.
    return np.where(previous == target, target, lower * (1 - old_weight) + upper * old_weight)


def simulate_tick(
    target: np.ndarray,
    illumination: np.ndarray | None,
    ambient: float | np.ndarray,
    state: SubframeState,
    pts: Fraction,
    duration: Fraction,
    config: SubframeConfig,
    *,
    self_emissive: bool = False,
    floor: float = 0.0,
) -> SubframeResult:
    """Pure analytical tick: no input/state changes occur, even on failure.

    The owner must commit ``result.endpoint``, increment ``state.ticks`` and
    set ``state.next_pts = pts + duration`` only after its whole display tick
    succeeds. The float64 endpoint is independent of ``substeps``. LCD cold
    initialization uses ``floor`` transmission; OLED uses zero emitted nits.
    """
    if not isinstance(config, SubframeConfig) or not config.active:
        raise ValueError("subframe tick requires an active SubframeConfig")
    if type(self_emissive) is not bool:
        raise ValueError("self_emissive must be bool")
    validate_state(state)
    if not isinstance(pts, Fraction) or not isinstance(duration, Fraction) or duration <= 0:
        raise ValueError("subframe pts/duration must be exact Fractions with positive duration")
    if not math.isfinite(float(duration)) or float(duration) <= 0:
        raise ValueError("subframe duration must be representable as positive finite seconds")
    if state.next_pts is not None and state.next_pts != pts:
        raise ValueError("subframe timestamp gap; replay every elapsed interval")
    if (
        not isinstance(target, np.ndarray)
        or target.dtype != np.float64
        or target.ndim != 3
        or target.shape[-1] != 3
        or min(target.shape[:2]) < 1
        or not np.isfinite(target).all()
        or np.any(target < 0)
    ):
        raise ValueError("subframe target must be finite nonnegative float64 RGB")
    floor = finite_number(floor, "floor")
    if not 0 <= floor <= 1 or (self_emissive and floor != 0):
        raise ValueError("LCD transmission floor must be in [0,1]; OLED floor must be zero")
    if not self_emissive and (np.any(target < floor) or np.any(target > 1)):
        raise ValueError("LCD target transmission must be within floor and one")
    ambient_array = np.asarray(ambient, dtype=np.float64)
    if (
        ambient_array.shape not in ((), target.shape)
        or not np.isfinite(ambient_array).all()
        or np.any(ambient_array < 0)
    ):
        raise ValueError("ambient must be a finite nonnegative scalar or matching RGB array")
    if self_emissive:
        if illumination is not None:
            raise ValueError("OLED emission must not have a backlight illumination owner")
        if (
            config.overdrive_levels is not None
            or Fraction(config.pwm_hz) != 0
            or (Fraction(config.strobe_duty) != 1 or Fraction(config.strobe_phase) != 0)
        ):
            raise ValueError("OLED emission rejects LCD overdrive/PWM/strobe settings")
        light: float | np.ndarray = 1.0
    else:
        if Fraction(config.bfi_duty) != 1 or Fraction(config.bfi_phase) != 0:
            raise ValueError("LCD emission rejects OLED BFI settings")
        if (
            not isinstance(illumination, np.ndarray)
            or illumination.dtype != np.float64
            or illumination.shape not in (target.shape[:2], target.shape)
            or not np.isfinite(illumination).all()
            or np.any(illumination < 0)
        ):
            raise ValueError("LCD illumination requires a matching finite nonnegative float64 map")
        light = illumination[..., None] if illumination.ndim == 2 else illumination
    if state.previous is None:
        if config.initial == "resume":
            raise ValueError("resume requires a complete validated subframe checkpoint")
        previous = (
            target.copy() if config.initial == "settled_first_tick" else np.full_like(target, floor)
        )
    else:
        previous = state.previous
        if previous.shape != target.shape:
            raise ValueError("subframe history geometry changed; use a new pipeline")
        if not self_emissive and (np.any(previous < floor) or np.any(previous > 1)):
            raise ValueError("LCD history transmission must be within floor and one")
    command = _command(previous, target, config) if config.overdrive_levels is not None else target
    if not self_emissive:
        command = np.clip(command, floor, 1)
    prefix = duration * Fraction(config.overdrive_fraction)
    segments: list[tuple[Fraction, Fraction, np.ndarray, np.ndarray, np.ndarray]] = []
    before = previous
    for start, end, drive in (
        (pts, pts + prefix, command),
        (pts + prefix, pts + duration, target),
    ):
        if end > start:
            tau = _taus(before, drive, config)
            segments.append((start, end, before, drive, tau))
            before = _endpoint(before, drive, tau, float(end - start))
    endpoint = before.copy()
    gates = _gates(pts, duration, config, self_emissive)
    step = duration / config.substeps
    samples = []
    accumulated = np.zeros(target.shape, dtype=np.float64)
    for index in range(config.substeps):
        start, end = pts + index * step, pts + (index + 1) * step
        windows = _intersections([(start, end)], gates)
        integrated = np.zeros(target.shape, dtype=np.float64)
        for left, right in windows:
            for seg_start, seg_end, seg_before, drive, tau in segments:
                a, b = max(left, seg_start), min(right, seg_end)
                if b > a:
                    integrated += _integral(
                        seg_before, drive, tau, float(a - seg_start), float(b - a)
                    )
        panel = endpoint
        for seg_start, seg_end, seg_before, drive, tau in segments:
            if seg_start < end <= seg_end:
                panel = _endpoint(seg_before, drive, tau, float(end - seg_start))
                break
        emitted = integrated * light / float(step) + ambient_array
        if not np.isfinite(emitted).all() or not np.isfinite(panel).all():
            raise ValueError("subframe emission exceeds finite numerical range")
        accumulated += emitted
        samples.append(
            SubframeSample(
                start,
                step,
                emitted,
                panel.copy(),
                sum((right - left for left, right in windows), Fraction(0)) / step,
            )
        )
    mean = (accumulated / config.substeps).astype(np.float32)
    if not np.isfinite(mean).all():
        raise ValueError("subframe mean exceeds finite float32 output range")
    return SubframeResult(tuple(samples), endpoint, mean)
