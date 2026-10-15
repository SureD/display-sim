# Status — 2026-10-16 00:20 CST

## Milestone progress
- **M1 research docs**: DONE. Six notes in `research/` (panel, backlight/FALD, color/HDR, temporal, image processing, sim architecture). Committed on main as `37cc504` (Codex finished earlier but could not commit while `.git` was read-only; PM committed this cycle).
- **M2 pipeline skeleton + TV profiles**: DONE. Merged `cursor/skeleton` into `main` (`f0d7e05`). Four YAML profiles (VA FALD mini-LED, IPS edge, WOLED, QD-OLED), linear-light stage pipeline, still-image CLI, test patterns. **23/23 pytest passing**.
- **M3 local dimming + HDR + temporal**: IN PROGRESS (assigned this cycle).
- **M4 validation + report**: not started.

## Workers
- Codex (`codex_run1.log`): idle / finished M1. Previously blocked on git write; research files recovered and committed.
- Cursor (`cursor_run1.log`): idle / finished M2 on `cursor/skeleton`.

## Drift / risks
- Profile numbers are labeled placeholders, not measurements.
- Stubbed: MEMC, BFI, overdrive tables, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path.
- No remote origin configured; all work is local.

## Next (M3)
1. Cursor: deepen `sim/stages/backlight.py`, `tonemap.py`, `temporal.py` using `research/*` (realistic zone PSF/bloom, HDR shoulder + ABL, response/overdrive/BFI); keep tests green; branch `cursor/m3-ld-hdr-temporal`.
2. Codex: turn research into implementable M3 parameter tables + blooming/HDR/temporal validation cases under `research/` and/or `tests/`; cite sources; commit on main (or `codex/m3-params`).
