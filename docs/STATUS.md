# Status — 2026-10-16 09:25 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (this cycle).
  - Codex filled `docs/REPORT.md` against pre-cal harness; PM committed (`e5f39eb`).
  - Cursor `cursor/m4-calibration` merged (`c7dbf01`): placeholder HDR ceiling nudge, `temporal_blur_*`, `reports/comparison.md`, anchors module.
  - PM re-ran `python3 -m sim validate --out reports/` (no artifact drift vs merge) and **47/47 pytest** on main.
  - PM refreshed `docs/REPORT.md` tables to post-cal numbers and pointed scored cells at `reports/comparison.md`.

## Post-cal highlights (placeholders only)
- VA ABL on: 10% ~1702 nits (**in** ~1300–1774), 100% ~620 nits (**in** 591–almost 650).
- WOLED 10% ~690 nits (**in** 667–717); QD-OLED 10% ~980 / 100% 199 (**in** vs Q1).
- IPS ANSI ~1134:1 (**in** ~764–1290); IPS temporal-only edge ~14.4 px (pursuit still ~74.7 / still ~67.7).
- Many 2/25/50%, sustained, MPRT/GtG cells remain **NR**.

## Workers (this cycle)
- Codex (`codex_run4.log`): **finished / idle**. Wrote uncommitted `docs/REPORT.md` (pre-cal); PM committed then refreshed post-merge.
- Cursor (`cursor_run4.log`, worktree `/workspace/tv-sim-cursor` on `cursor/m4-calibration`): **finished / idle**. Two commits merged (`1562e32`, `f1c655a`).
- No `codex exec` or `agent -p` processes running at check time. Tooling (`codex`, `agent`) is installed but PM is **not** starting new long-running workers.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- Stubbed: MEMC, measured overdrive LUTs and BFI/PWM waveforms, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, backlight/LCD power solver.
- No remote origin configured; all work is local.
- REPORT pre-cal snapshot is preserved in git history (`e5f39eb`); tip report is post-cal.

## Next (assigned — awaiting user OK before kicking workers)
1. **Post-M4 candidate: GPU path (PyTorch) on RTX 3070 box `dscs2pc`** for realtime preview, with numerical parity against the CPU reference on the same harness patterns. **Do not start Codex/Cursor workers until the user confirms this milestone.**
2. Optional fidelity follow-ups (also need prioritization): measured LUTs/PSFs, source-demand APL, consume OLED PSF in emissive path, longer temporal histories.
