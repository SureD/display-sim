# ADR 0001: Use a linear-light reference pipeline

Status: accepted in M2; retained through M16.

Context: encoded RGB values cannot be averaged, blurred, or load-limited as
physical light. Preview exposure also must not rewrite simulated display output.

Decision: decode the EOTF first and keep optical, panel, HDR/ABL, ambient, and
temporal stages in linear nit-scaled RGB. Return linear output separately from
preview encoding. Declare source primaries independently; M15's opt-in path
retains explicit RGB/XYZ basis metadata and derived conversions.

Consequences: shared-exposure previews and numerical metrics can use the same
physical output. State updates and color conversions have explicit domains.
This is a reference RGB model, without a measured spectral/electrical solver.

Evidence: [original architecture](../research/06-sim-architecture.md),
[Mac output boundary](../research/m5-mac-display.md#1-preserve-the-simulators-physical-output),
and [current pipeline](../architecture.md).
