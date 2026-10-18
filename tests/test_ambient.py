"""Lambertian ambient reflection."""

import numpy as np

from tv_sim.frame import Frame
from tv_sim.profile import AmbientParams
from tv_sim.stages.ambient import add_ambient, reflected_nits


def test_zero_lux_is_unchanged_and_light_adds_a_neutral_offset():
    frame = Frame(np.zeros((2, 2, 3), dtype=np.float32))
    assert add_ambient(frame, AmbientParams(lux=0.0, reflectance=0.02)) is frame
    params = AmbientParams(lux=100.0, reflectance=0.02)
    lit = add_ambient(frame, params)
    assert np.allclose(lit.rgb, reflected_nits(params))
    assert np.allclose(lit.rgb[..., 0], lit.rgb[..., 1])
