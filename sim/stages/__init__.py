"""Pipeline stages. Each function reads a :class:`~sim.frame.Frame` and returns one."""

from sim.stages.ambient import add_ambient
from sim.stages.backlight import simulate_backlight
from sim.stages.decode import decode_encoded
from sim.stages.encode import encode_frame
from sim.stages.panel import simulate_panel
from sim.stages.process import process_image
from sim.stages.temporal import TemporalState, apply_temporal
from sim.stages.tonemap import tone_map

__all__ = [
    "TemporalState",
    "add_ambient",
    "apply_temporal",
    "decode_encoded",
    "encode_frame",
    "process_image",
    "simulate_backlight",
    "simulate_panel",
    "tone_map",
]
