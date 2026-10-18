"""Pipeline stages. Each function reads a :class:`~tv_sim.frame.Frame` and returns one."""

from tv_sim.stages.ambient import add_ambient
from tv_sim.stages.backlight import simulate_backlight
from tv_sim.stages.decode import decode_encoded
from tv_sim.stages.encode import encode_frame
from tv_sim.stages.panel import simulate_panel
from tv_sim.stages.process import process_image
from tv_sim.stages.temporal import TemporalState, apply_temporal
from tv_sim.stages.tonemap import tone_map

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
