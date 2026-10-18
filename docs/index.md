# Documentation

TV Display Simulator is a Python/NumPy research prototype for comparing display
mechanisms. All shipped TV presets remain synthetic placeholders. Start with
[the project README](../README.md) for installation and example images.

| Guide | Contents |
|---|---|
| [Architecture](architecture.md) | Stage order, units, state, and module map. |
| [Usage](usage.md) | CLI examples, sequences, OLED capacity and LCD zone dynamics, and opt-in colorimetry. |
| [Profiles and provenance](profiles.md) | Runtime schema, packaged loading, evidence grades, and experiment contracts. |
| [Development](development.md) | Setup, tests, code checks, regeneration, and release. |
| [Decisions](decisions/README.md) | Short records of the design and workflow choices. |
| [Research history](research/README.md) | M1–M18 questions, findings, sources, and implementation handoffs. |
| [Reports](reports/README.md) | Historical plan/status, validation interpretation, and engineering reports. |

The [offline gallery](../reports/gallery/index.html),
[web comparison protocol](../web/README.md), and
[interactive principles explainer](../web-explainer/index.html) make the model
inspectable. A browser's HDR capability is separate from verified emitted nits.
Read the [Mac EDR decision](decisions/0004-mac-edr-plan.md) before interpreting a
preview as a physical display experiment.
