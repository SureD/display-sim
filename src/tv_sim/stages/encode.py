"""Output encode: linear nits to an integer preview image.

For sRGB, ``reference_nits`` is the level that maps to code value 1. PQ ignores
that scale and encodes absolute nits (ST 2084). Either way this is an 8-bit
preview, not a file that stores linear nits. sRGB values above the reference clip.
"""

from __future__ import annotations

import numpy as np

from tv_sim.color import pq_oetf, srgb_oetf
from tv_sim.frame import Frame
from tv_sim.profile import OutputParams


def encode_frame(frame: Frame, params: OutputParams) -> np.ndarray:
    """Return a ``uint8`` RGB image encoded with the profile's output EOTF."""

    if params.reference_nits <= 0:
        raise ValueError("reference_nits must be positive")
    normalized = np.asarray(frame.rgb, dtype=np.float64) / float(params.reference_nits)
    which = params.eotf.lower()
    if which == "srgb":
        codes = srgb_oetf(normalized)
    elif which == "pq":
        codes = pq_oetf(np.clip(frame.rgb, 0.0, None))
    else:
        raise ValueError(f"Unsupported output EOTF {which!r}. Use srgb or pq.")
    return np.clip(np.round(codes * 255.0), 0, 255).astype(np.uint8)
