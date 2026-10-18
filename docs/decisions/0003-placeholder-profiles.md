# ADR 0003: Ship generic profiles as explicit placeholders

Status: accepted from M2; retained through M16.

Context: the project has mechanism research and isolated published anchors,
but no complete matched calibration dataset for a named television.

Decision: ship four `generic_*` presets for VA mini-LED, IPS edge-lit, WOLED, and
QD-OLED. Keep the placeholder label in profiles, provenance, UI, and generated
artifacts. New fitted drives and runtime experiments are explicit opt-ins stored
separately from baseline YAMLs. Unknown timing, spectra, optical kernels, angular
fits, and electrical coefficients remain NR.

Consequences: comparisons illustrate mechanisms without claiming named-TV
accuracy. Default parity can be reviewed independently of experimental features.
Calibration will need new matched evidence and a reviewed schema/model change.

Evidence: [profile guide](../profiles.md),
[M4 reference limitations](../research/m4-reference-ranges.md), and
[M6 handoff](../research/m6-profile-wiring.md#8-implementation-handoff-and-remaining-nr-data).
