"""Average-picture-level load limiting (ABL).

``research/m3-hdr-abl-params.md`` fixes the contract this module implements:

``a = clip(mean(Y_request) / P0, 0, 1)``, ``P(a) = F + (P0 - F) (1 - a)^g``

with ``P0`` the small-window capacity, ``F`` the full-field capacity, and ``g``
a synthetic shape parameter. The note is explicit that the load must be
computed *before* mapping and never from post-limit output, because feeding the
limiter its own output creates a feedback loop. ``demand_apl`` is therefore
taken from the requested picture (decode plus image processing), not from the
light the panel ends up emitting.

Two further knobs are placeholders with research-stated ranges but no fit:

* ``abl_response_ms`` is the limiter attack/release time constant. The note
  gives a 10–1000 ms prior and says the present skeleton is instantaneous;
  0 keeps that instantaneous behavior. Thermal state (1–100 s) and
  static-logo dimming are separate controllers and are still not modeled.
* ``abl_backlight_tracking`` passes part of the capacity drop back to the
  backlight drive cap, which is how an LCD limits power (research/02:
  ``Σ_j p_j d_j ≤ P_budget`` "can alter both zone output and pixel
  compensation"). 0 leaves the backlight alone. This is a single global
  derate, not a per-zone power solver.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sim.color import luminance
from sim.profile import HdrParams


@dataclass
class LoadState:
    """Smoothed demand APL carried between frames.

    ``apl_nits`` is ``None`` until the first frame, which is shown with the
    limiter already settled (the same convention as the temporal stage).
    """

    apl_nits: float | None = None


def demand_apl(rgb: np.ndarray) -> float:
    """Mean linear BT.709 luminance in nits of the requested picture."""

    return float(np.mean(luminance(rgb), dtype=np.float64))


def load_fraction(apl_nits: float, params: HdrParams) -> float:
    """``a`` in ``[0, 1]``: demand APL over the small-window capacity."""

    reference = float(params.abl_reference_nits) or float(params.panel_peak_nits)
    if reference <= 0.0 or not np.isfinite(reference):
        raise ValueError("ABL reference must be a positive finite nit level")
    return float(np.clip(float(apl_nits) / reference, 0.0, 1.0))


def abl_capacity(apl_nits: float, params: HdrParams) -> float:
    """Allowed peak ``P(a)`` for a demand APL, in nits."""

    peak = float(params.panel_peak_nits)
    if peak <= 0.0 or not np.isfinite(peak):
        raise ValueError("panel_peak_nits must be a positive finite value")
    if not params.abl_enabled:
        return peak
    full = float(params.abl_full_field_nits)
    if not 0.0 < full <= peak:
        raise ValueError("abl_full_field_nits must be in (0, panel_peak_nits]")
    gamma = float(params.abl_gamma)
    if gamma <= 0.0:
        raise ValueError("abl_gamma must be positive")
    allowed = full + (peak - full) * (1.0 - load_fraction(apl_nits, params)) ** gamma
    if not np.isfinite(allowed) or allowed <= 0.0:
        raise ValueError("ABL produced a non-positive peak")
    return float(allowed)


def smooth_apl(
    state: LoadState | None,
    apl_nits: float,
    params: HdrParams,
    frame_time_ms: float,
) -> float:
    """First-order attack/release on the demand APL.

    ``abl_response_ms`` 0, a missing state, or an unseen first frame all return
    the instantaneous value.
    """

    target = float(apl_nits)
    tau_ms = float(params.abl_response_ms)
    if state is None:
        return target
    if tau_ms <= 0.0 or state.apl_nits is None or frame_time_ms <= 0.0:
        state.apl_nits = target
        return target
    alpha = 1.0 - float(np.exp(-float(frame_time_ms) / tau_ms))
    smoothed = state.apl_nits + (target - state.apl_nits) * alpha
    state.apl_nits = float(smoothed)
    return float(smoothed)


def backlight_derate(apl_nits: float, params: HdrParams) -> float:
    """Multiplier in ``(0, 1]`` for the backlight drive cap."""

    tracking = float(params.abl_backlight_tracking)
    if tracking <= 0.0 or not params.abl_enabled:
        return 1.0
    if tracking > 1.0:
        raise ValueError("abl_backlight_tracking must be in [0, 1]")
    ratio = abl_capacity(apl_nits, params) / float(params.panel_peak_nits)
    # F + (P - F) can round a fraction of an ulp above P at zero load.
    # Keep the documented (0, 1] scale contract; valid scales are unchanged.
    return float(min(1.0, 1.0 - tracking * (1.0 - ratio)))
