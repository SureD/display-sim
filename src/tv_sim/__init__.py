"""Reference TV display simulator with explicit placeholder profiles.

Frames carry linear-light RGB nits as float32 H × W × 3 arrays. ``Pipeline``
owns display history; optional runtime configurations preserve baseline defaults.
Stage functions and experiment adapters live in their documented submodules.
"""

from tv_sim.abl_dynamics import ABLDynamicsConfig
from tv_sim.colorimetry import ColorimetryConfig
from tv_sim.frame import Frame
from tv_sim.pipeline import Pipeline
from tv_sim.profile import TVProfile, available_profiles, load_profile
from tv_sim.sequence import MotionConfig
from tv_sim.viewing_angle import ViewingAngleConfig

__version__ = "0.1.0"
__all__ = [
    "ABLDynamicsConfig",
    "ColorimetryConfig",
    "Frame",
    "MotionConfig",
    "Pipeline",
    "TVProfile",
    "ViewingAngleConfig",
    "available_profiles",
    "load_profile",
]
