# ADR 0004: Separate Mac EDR presentation from simulated light

Status: plan accepted in M5; native implementation and physical validation pending.
M12a provides a browser preview with qualified HDR capability and SDR fallbacks.

Context: EDR components are relative to the host SDR reference white. Available
headroom, OS compositing, display mode, host dimming, and calibration affect
emitted light. A successful HDR surface request is not a nit measurement.

Decision: preserve simulator output as linear nits and keep renderer transforms
separate. A future native Mac renderer should use a floating-point Metal EDR
surface, explicit color space and SDR-white/headroom mapping. Validate a neutral
wedge and RGB patches with a luminance/color meter on a real target Mac, recording
preset, brightness, area, timing, and display conditions before accuracy claims.

Consequences: PNG and browser previews remain useful comparisons, with shared
mapping and explicit clipping/scaling. Physical HDR/EDR output remains NR until
measured; the simulator cannot make a dimmer host emit a brighter TV's light.

Evidence: [Mac research and validation protocol](../research/m5-mac-display.md),
[Chrome HDR research](../research/m12a-web-hdr.md), and
[browser calibration protocol](../../web/README.md).
