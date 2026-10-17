"""P angular transmission/emission laws; no named-TV calibration.

LCD white gain Fw, emitted-black gain Fb and gray response g are independent:
epsilon = epsilon0 * Fb/Fw; L = B*Fw*(epsilon + (1-epsilon)*g(q)).
Only emitter RGB gains apply to OLED. No cosine falloff is added to luminance.
"""

from __future__ import annotations

import numpy as np

from sim.stages.panel import lcd_transmit
from sim.viewing_angle import (
    EmissiveAngularParams, LcdAngularParams, ViewingAngleConfig,
    angular_fraction, validate_angular_path,
)


def _gain(endpoint: tuple[float, float, float], fraction: float) -> np.ndarray:
    return np.exp(np.log(np.asarray(endpoint, dtype=np.float64)) * fraction)


def lcd_angular_transmit(target: np.ndarray, backlight: np.ndarray, contrast: float,
                         config: ViewingAngleConfig, params: LcdAngularParams) -> np.ndarray:
    """Apply angular terms inside compensated LCD aperture transmission.

    Inactive calls delegate exactly to the original LCD function. Positive B
    uses q=clip((target/B-epsilon0)/(1-epsilon0),0,1), matching the original
    compensated target at normal incidence. B=0 emits zero in the active model.
    """

    if not config.active:
        return lcd_transmit(target, backlight, contrast)
    validate_angular_path(config, params, self_emissive=False, contrast=contrast)
    s = angular_fraction(config, params)
    white, black = _gain(params.white_gain_45, s), _gain(params.black_gain_45, s)
    gamma = 1.0 + s * (np.asarray(params.gray_exponent_45, dtype=np.float64) - 1.0)
    epsilon0 = 1.0 / contrast
    epsilon = epsilon0 * black / white
    b = np.asarray(backlight, dtype=np.float64)[..., None]
    relative = np.divide(target, b, out=np.zeros_like(target, dtype=np.float64), where=b > 0)
    q = np.clip((relative - epsilon0) / (1.0 - epsilon0), 0.0, 1.0)
    return (b * white * (epsilon + (1.0 - epsilon) * q**gamma)).astype(np.float32)


def emissive_angular_gain(rgb: np.ndarray, config: ViewingAngleConfig,
                          params: EmissiveAngularParams) -> np.ndarray:
    """Apply only angular luminance/color gains to already emitted RGB."""

    if not config.active:
        return np.asarray(rgb, dtype=np.float32)
    validate_angular_path(config, params, self_emissive=True, contrast=0.0)
    gain = _gain(params.emission_gain_45, angular_fraction(config, params))
    return (rgb * gain).astype(np.float32)
