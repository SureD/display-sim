"""Input decode: encoded code values to linear-light nits."""

from __future__ import annotations

import numpy as np

from sim.color import hlg_eotf, pq_eotf, srgb_eotf
from sim.frame import Frame
from sim.profile import InputParams


def as_code_values(encoded: np.ndarray) -> np.ndarray:
    """Accept uint8 images or float code values in ``[0, 1]``."""

    array = np.asarray(encoded)
    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    if array.shape[-1] == 4:
        array = array[..., :3]
    if array.dtype == np.uint8:
        return array.astype(np.float32) / np.float32(255.0)
    if array.dtype == np.uint16:
        return array.astype(np.float32) / np.float32(65535.0)
    return array.astype(np.float32)


def decode_encoded(encoded: np.ndarray, params: InputParams, eotf: str | None = None) -> Frame:
    """Decode an image to linear nits.

    sRGB is scaled so code 1.0 equals ``sdr_white_nits`` (diffuse white, not the
    panel peak). PQ is absolute. HLG uses ``hlg_peak_nits`` for the OOTF.
    """

    which = (eotf or params.eotf).lower()
    codes = as_code_values(encoded)
    if which == "srgb":
        linear = srgb_eotf(codes) * np.float32(params.sdr_white_nits)
    elif which == "pq":
        linear = pq_eotf(codes)
    elif which == "hlg":
        linear = hlg_eotf(codes, params.hlg_peak_nits)
    else:
        raise ValueError(f"Unsupported input EOTF {which!r}. Use srgb, pq, or hlg.")
    return Frame(linear)
