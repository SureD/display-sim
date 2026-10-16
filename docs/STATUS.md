# Status — 2026-10-17 (M7 phase 1)

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (merge `c7dbf01` + REPORT refresh `cc71643`).
- **M5 mechanism fidelity**: DONE (merge `1baa2e1` + fidelity research).
- **M5 macOS EDR research**: DONE (`research/m5-mac-display.md`).
- **M6 profile wiring research**: DONE (`research/m6-profile-wiring.md`).
- **M6 visual gallery**: DONE (merge `30f8e97`).
- **M7 MEMC/motion research**: DONE (`research/m7-memc-motion.md`).
- **M8 profile provenance sidecar**: DONE (merge `94f248b` of `codex/m8-provenance`, commit `d0ca06f`). Four versioned `sim/profiles/*.provenance.yaml` sidecars cover all 220 effective profile values (M/D/P/NR, source locators, conditions, support ranges); strict lookup fails out of support; `python3 -m sim provenance --check`; schema in `docs/PROVENANCE.md`. Runtime YAMLs unchanged, parity tested.
- **M7 MEMC implementation phase 1**: DONE in `codex/m7-memc` (uncommitted). Captured pre-change hashes; independent rational source/output PTS and repeat cadence (D); analytic translation/known-layer reconstruction (P), exact endpoints, declared cuts and safe source-hold fallback; separate opt-in `motion` CLI/runtime configuration, default off. Added a 24p repeat/interpolated gallery comparison with exact position traces. TV profile YAMLs unchanged; vendor algorithms/calibration remain NR.
- **M9 opt-in window replay / drive fitting**: IN PROGRESS (Cursor, worktree `/workspace/tv-sim-cursor`, branch `cursor/m9-window-replay`).

## Workers (this cycle)
- Cursor run10: **failed at start** (`RetriableError: Connection stalled repeatedly`), no work done; stale empty `cursor/m7-memc` branch deleted.
- Codex run10: **finished** M8 (uncommitted → PM committed + merged).
- Codex run11: **finished** M7 MEMC phase 1; Cursor run11 → M9 window replay.

## Tests
- **230/230 pytest** on `main` after the M8 merge (115 existing + 115 provenance).
- **315/315 pytest** in the M7 worktree (`python3 -m pytest -q`, 87.93 s). Golden parity covers all four profiles' RGB/backlight/previews/final states, full default validation JSON/CSV/previews, and every pre-M7 gallery sheet/setting. Default-size eight-sheet gallery generated; provenance check passes for all four profiles.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- MEMC must be off by default and leave the MEMC-off path bit-identical.
- M9 must be opt-in with a separate dataset ID; defaults and original generic YAMLs unchanged; no double limiting.
- Cursor CLI connection stalls are recurring; if run11 also fails, move remaining work to Codex.
- Still stubbed: measured OD/BFI/PWM waveforms, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full watt solver, angular leakage LUTs, OLED attack/release, block-estimation MEMC.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.

## Next (assigned this cycle)
1. **M7 phase 1 review**: implementation complete; block estimation, automatic cut detection, vendor calibration, video/audio plumbing and full observer integration remain deferred per the research boundary.
2. **M9 window replay (Cursor, `cursor/m9-window-replay`)**: per `research/m6-profile-wiring.md` §8 item 2 — opt-in window replay/drive fitting using M8 provenance measurement records, explicit amplitude/color/time matching, separate dataset ID, no double limiting; defaults unchanged; tests.
3. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm.
