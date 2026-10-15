"""Add reflected room light.

A Lambertian surface lit by ``lux`` illuminance returns
``reflectance * lux / pi`` nits. The reflection is neutral, so the same
offset is added to R, G, and B. This is a single-bounce placeholder: it does
not model glare spread or colored walls.
"""

from __future__ import annotations

import numpy as np

from sim.frame import Frame
from sim.profile import AmbientParams


def reflected_nits(params: AmbientParams) -> float:
    return float(params.reflectance) * float(params.lux) / np.pi


def add_ambient(frame: Frame, params: AmbientParams) -> Frame:
    offset = reflected_nits(params)
    if offset == 0.0:
        return frame
    rgb = frame.rgb + np.float32(offset)
    return Frame(rgb, frame.backlight)
