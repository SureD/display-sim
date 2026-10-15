"""Preview encode from linear nits."""

import numpy as np

from sim.frame import Frame
from sim.profile import OutputParams
from sim.stages.encode import encode_frame


def test_srgb_preview_maps_reference_white_and_black():
    white = encode_frame(Frame(np.full((2, 2, 3), 100.0, np.float32)), OutputParams(reference_nits=100))
    black = encode_frame(Frame(np.zeros((2, 2, 3), np.float32)), OutputParams(reference_nits=100))
    assert white.dtype == np.uint8
    assert np.all(white == 255)
    assert np.all(black == 0)


def test_pq_preview_roundtrip_level():
    from sim.color import pq_eotf, pq_oetf

    level = pq_oetf(np.array(500.0))
    encoded = encode_frame(
        Frame(np.full((1, 1, 3), 500.0, np.float32)),
        OutputParams(eotf="pq", reference_nits=10000),
    )
    # 8-bit quantization, then back through the continuous EOTF.
    recovered = pq_eotf(encoded.astype(np.float32) / 255.0)
    assert abs(float(recovered[0, 0, 0]) - 500.0) < 15.0
    assert encoded[0, 0, 0] == int(round(float(level) * 255.0))
