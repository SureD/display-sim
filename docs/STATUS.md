# Status — 2026-10-16 06:25 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: MOSTLY DONE.
  - Codex reference ranges + report draft committed by PM (`56e5fed`).
  - Cursor validation harness merged (`091eb42`): `python3 -m sim validate --out reports/` writes `reports/metrics.json`, `metrics.csv` and preview PNGs per profile (ANSI checker, window sweep 1–100%, on/off, grey/PQ ramps, moving edge with BFI/overdrive probes). Re-run on main is deterministic (no diff). **44/44 pytest passing on main**.
  - Remaining: calibration sanity pass and the filled sim-vs-published comparison in `docs/REPORT.md` (assigned this cycle).

## Findings from the first harness run (placeholder profiles)
- LCD profiles have ABL off, so window peak does not fall with area; published VA mini-LED sample (QN95B) shows ~1,774 nits at 10% vs ~591 at full white.
- Zoned backlights turn off on full-field black, so sequential contrast is undefined; OLED black is 0, so OLED ratios are undefined (consistent with published "unmeasurable").
- IPS edge-lit backlight spread dominates the moving-edge width (still edge ~68 px), so pursuit width there mostly measures backlight spread, not temporal blur.
- OLED PSF map is computed but not consumed by the emissive branch (OK physically, but config fields are misleading).
- APL for ABL is computed from panel-stage output, not source demand.

## Workers (this cycle)
- Cursor (`cursor_run4.log`, branch `cursor/m4-calibration`, worktree `/workspace/tv-sim-cursor`): nudge placeholder profiles toward the cited anchors in `research/m4-reference-ranges.md` (still labeled placeholders), make `validate` also write `reports/comparison.md` (sim metric vs published anchor/envelope, in/out flag, source IDs), separate temporal blur from backlight spread in the moving-edge metric, keep tests green.
- Codex (`codex_run4.log`): finish `docs/REPORT.md` — results, interpretation vs reference ranges, limitations, recommended next steps. Writes only `docs/REPORT.md` and `research/`; PM commits.

## Drift / risks
- Profile numbers are placeholders, not measurements; report must keep saying so. Calibration must not be presented as emulating a specific TV.
- Stubbed: MEMC, measured overdrive LUTs and BFI/PWM waveforms, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, backlight/LCD power solver.
- No remote origin configured; all work is local.

## Next
1. After both land: PM merges `cursor/m4-calibration`, re-runs `validate`, makes sure REPORT tables match the regenerated `reports/comparison.md`, closes M4.
2. Post-M4 candidate (needs user OK): GPU path (PyTorch) on the RTX 3070 box (dscs2pc) for realtime preview.
