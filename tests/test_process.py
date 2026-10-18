"""Scale and unsharp-mask sharpen."""

import numpy as np

from tv_sim.frame import Frame
from tv_sim.profile import ProcessingParams
from tv_sim.stages.process import process_image


def test_scale_changes_shape_and_identity_scale_does_not():
    frame = Frame(np.ones((4, 6, 3), dtype=np.float32))
    same = process_image(frame, ProcessingParams(scale_factor=1.0, sharpen_amount=0.0))
    assert same.rgb.shape == (4, 6, 3)
    assert np.allclose(same.rgb, frame.rgb)
    doubled = process_image(
        frame, ProcessingParams(scale_factor=2.0, scale_mode="nearest", sharpen_amount=0.0)
    )
    assert doubled.rgb.shape == (8, 12, 3)
    assert np.allclose(doubled.rgb, 1.0)


def test_sharpen_raises_an_impulse():
    image = np.zeros((16, 16, 3), dtype=np.float32)
    image[8, 8] = 50.0
    out = process_image(
        Frame(image),
        ProcessingParams(sharpen_amount=1.0, sharpen_sigma=1.0),
    )
    assert out.rgb[8, 8, 0] > image[8, 8, 0]
    assert out.rgb.min() >= 0.0
