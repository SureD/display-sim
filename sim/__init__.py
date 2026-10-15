"""Reference TV display simulator.

Images move through the pipeline as linear-light RGB in nits (``float32``,
shape ``H x W x 3``). Each stage is a pure function plus a :class:`sim.frame.Frame`
so backlight maps and temporal state can travel beside the pixels.
"""

__version__ = "0.1.0"
