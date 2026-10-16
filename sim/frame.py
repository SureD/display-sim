"""Container for a linear-light image and the maps that accompany it."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Frame:
    """One simulator frame.

    ``rgb`` is display-referred linear light in cd/m^2 (nits), not an encoded
    code value. ``backlight`` is a non-negative nit map (``H x W``) once the
    backlight stage has run; earlier stages leave it as ``None``.

    Timing is separate: ``sim.sequence.SequenceOutput`` carries source and
    presentation PTS so source buffers never share panel-response history.
    """

    rgb: np.ndarray
    backlight: np.ndarray | None = None

    def __post_init__(self) -> None:
        self.rgb = np.asarray(self.rgb, dtype=np.float32)
        if self.rgb.ndim != 3 or self.rgb.shape[-1] != 3:
            raise ValueError(f"rgb must have shape (H, W, 3), got {self.rgb.shape}")
        if self.backlight is not None:
            self.backlight = np.asarray(self.backlight, dtype=np.float32)
            if self.backlight.shape != self.rgb.shape[:2]:
                raise ValueError(
                    "backlight shape "
                    f"{self.backlight.shape} does not match image {self.rgb.shape[:2]}"
                )

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.rgb.shape  # type: ignore[return-value]

    def copy(self) -> Frame:
        backlight = None if self.backlight is None else self.backlight.copy()
        return Frame(self.rgb.copy(), backlight)
