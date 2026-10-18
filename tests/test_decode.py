"""Input decode: sRGB, PQ, and HLG to linear nits."""

import numpy as np

from tv_sim.color import pq_eotf, pq_oetf, srgb_eotf, srgb_oetf
from tv_sim.profile import InputParams
from tv_sim.stages.decode import decode_encoded


def test_srgb_roundtrip_and_white_point():
    codes = np.array([0.0, 0.25, 0.5, 0.8, 1.0], dtype=np.float32)
    assert np.allclose(srgb_oetf(srgb_eotf(codes)), codes, atol=1e-5)
    frame = decode_encoded(np.ones((2, 2, 3), dtype=np.float32), InputParams(sdr_white_nits=100))
    assert np.allclose(frame.rgb, 100.0)
    black = decode_encoded(np.zeros((2, 2, 3), dtype=np.uint8), InputParams())
    assert np.allclose(black.rgb, 0.0)


def test_pq_roundtrip_is_absolute_nits():
    nits = np.array([0.0, 1.0, 100.0, 1000.0, 10000.0], dtype=np.float32)
    assert np.allclose(pq_eotf(pq_oetf(nits)), nits, rtol=1e-4, atol=1e-3)
    encoded = pq_oetf(np.full((4, 4, 3), 203.0, dtype=np.float32))
    frame = decode_encoded(encoded, InputParams(), eotf="pq")
    assert np.allclose(frame.rgb, 203.0, rtol=1e-4)


def test_hlg_endpoints():
    params = InputParams(eotf="hlg", hlg_peak_nits=1000.0)
    black = decode_encoded(np.zeros((2, 2, 3), dtype=np.float32), params)
    white = decode_encoded(np.ones((2, 2, 3), dtype=np.float32), params)
    assert np.allclose(black.rgb, 0.0)
    assert np.allclose(white.rgb, 1000.0, rtol=1e-3)
