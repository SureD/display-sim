# Milestone reports

These records preserve the project's planning and review history. They can
contain conclusions superseded by later milestones; use the
[current architecture](../architecture.md), [usage](../usage.md), and
[profile guide](../profiles.md) for current behavior.

| Record | Purpose |
|---|---|
| [PLAN](PLAN.md) | Original workstreams, milestone plan, and M15 handoff snapshot. |
| [STATUS](STATUS.md) | Current milestone progress, PM checks and verification history. |
| [REPORT](REPORT.md) | M4 validation interpretation, mechanism limits, and M6 gallery report. |
| [M4 comparison](comparison.md) | Preserved comparison against published anchors. |
| [M16 repository engineering](M16-repo-engineering.md) | Repository migration, verification, and suggested commit split. |
| [M17 LCD zone dynamics](M17-zone-temporal.md) | Zone-controller model, synthetic artifacts, verification and suggested commit split. |

Generated assets remain under [`reports/`](../../reports/):
[default gallery](../../reports/gallery/index.html),
[M14 motion artifact notes](../../reports/motion-m14/README.md), and
[M15 colorimetry notes](../../reports/colorimetry-m15/README.md), and
[M17 LCD zone dynamics](../../reports/zone-temporal-m17/index.html).
`tv-sim validate --out reports` regenerates a new `reports/comparison.md` alongside
its metrics; the copy here preserves the earlier reviewed report.
