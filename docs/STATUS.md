# Status — 2026-10-16 03:30 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE. Codex parameter notes + validation tests committed by PM (`976d377`, Codex sandbox cannot write `.git`). Cursor implementation on `cursor/m3-ld-hdr-temporal` merged (`477685d`): zone max/percentile pooling, two-Gaussian PSF, float32 HDR shoulder + APL-driven ABL, optional overdrive + BFI. Test conflicts resolved by keeping both sides; HDR ramp monotonicity check now allows ~1 ULP float32 wobble. **36/36 pytest passing on main**.
- **M4 validation + report**: IN PROGRESS (assigned this cycle).

## Workers
- Codex (`codex_run3.log`): M4 reference ranges + report text. Writes only `research/` and `docs/REPORT.md`; PM commits.
- Cursor (`cursor_run3.log`): M4 validation harness on branch `cursor/m4-validation` (worktree `/workspace/tv-sim-cursor`).

## Drift / risks
- Profile numbers are labeled placeholders, not measurements. Report must say so.
- Stubbed: MEMC, measured overdrive LUTs and BFI/PWM waveforms, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, backlight/LCD power solver.
- No remote origin configured; all work is local.

## Next (M4)
1. Cursor: `python3 -m sim validate` (or equivalent) that renders standard patterns per profile — ANSI checkerboard, window sweep 1/2/5/10/25/50/100% (blooming halo + ABL peak), grey/PQ ramps, moving edge (MPRT-style blur width) — and writes metrics JSON/CSV + preview PNGs under `reports/`. Tests for the metric functions; keep all tests green.
2. Codex: `research/m4-reference-ranges.md` with cited published measurement ranges per panel class (contrast, peak/full-field nits, ABL curve, blooming, response time) and `docs/REPORT.md` draft: method, what is modeled, what is placeholder, how sim metrics should be compared to the ranges.
3. After both land: PM merges, runs `validate`, fills the comparison table in `docs/REPORT.md`.
