# ADR 0005: Use a PM-driven milestone and review workflow

Status: accepted from M0; formalized in M16.

Context: research, model implementation, numerical acceptance, and integration
have different evidence needs. Multiple workers historically handed off changes
to one product owner/PM.

Decision: the PM defines milestone scope and compatibility requirements. Workers
produce a focused implementation, research/decision records where needed, exact
verification results, and a reviewable working tree. The PM reviews evidence,
chooses logical commits, and authorizes integration or publication. For M16,
workers leave changes uncommitted and never push.

Consequences: defaults, provenance, and golden-output changes receive an explicit
review boundary. Status snapshots remain historical reports rather than the
primary user guide. New work records what changed, how it was checked, limitations,
and suggested commit organization.

Evidence: [original plan](../reports/PLAN.md),
[milestone status](../reports/STATUS.md), and
[contribution guide](../../CONTRIBUTING.md).
