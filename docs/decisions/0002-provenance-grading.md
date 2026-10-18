# ADR 0002: Keep evidence grades and unknowns explicit

Status: accepted in M5/M6; enforced by versioned sidecars from M8 onward.

Context: review measurements apply to a named specimen and protocol. A nearby
peak-window number cannot calibrate every mechanism of a generic TV preset.

Decision: label named measurements `M`, calculations `D`, synthetic/model/fitting
choices `P`, and unavailable or unidentified quantities `NR`. Preserve conditions,
source locators, support, and interpolation. `NR` is never zero; interpolation
between measurements is a P result. Strict lookup rejects extrapolation.

Consequences: profile snapshots and experiment records remain inspectable and
validators reject stale or incomplete evidence. Exact mathematics does not
promote placeholder inputs to measured device parameters.

Evidence: [schema and grading](../profiles.md),
[M5 fidelity](../research/m5-fidelity.md), and
[M6 wiring](../research/m6-profile-wiring.md).
