# Status — 2026-10-16 00:20 CST

## Milestone progress
- **M1 research docs**: DONE. Six notes in `research/` (panel, backlight/FALD, color/HDR, temporal, image processing, sim architecture). Committed on main as `37cc504` (Codex finished earlier but could not commit while `.git` was read-only; PM committed this cycle).
- **M2 pipeline skeleton + TV profiles**: DONE. Merged `cursor/skeleton` into `main` (`f0d7e05`). Four YAML profiles (VA FALD mini-LED, IPS edge, WOLED, QD-OLED), linear-light stage pipeline, still-image CLI, test patterns. **23/23 pytest passing**.
- **M3 local dimming + HDR + temporal**: DONE on `cursor/m3-ld-hdr-temporal`. Zone max/percentile pooling, separable two-Gaussian PSF (edge strips kept), float32 soft shoulder plus APL peak curve and optional channel-power gain, overdrive prefix and BFI duty on top of lag and sample-and-hold. Profile numbers remain labeled placeholders. **31/31 pytest passing**.
- **M4 validation + report**: not started.

## Workers
- Codex (`codex_run1.log`): idle / finished M1. Previously blocked on git write; research files recovered and committed.
- Cursor (`cursor_run1.log`): idle / finished M2 on `cursor/skeleton`.

## Drift / risks
- Profile numbers are labeled placeholders, not measurements.
- Stubbed: MEMC, measured overdrive LUTs and BFI/PWM waveforms (duty/gain hooks only), measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing and the backlight/LCD power solver.
- No remote origin configured; all work is local.

## Next (M4)
1. Validation patterns and a report against the research notes. Do not treat placeholder YAML numbers as measurements.
2. Still out of scope until a later milestone: MEMC, CRT/plasma, GPU path.
