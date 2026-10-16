# Status — 2026-10-17 06:30 CST

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
- **M7 MEMC implementation phase 1**: DONE (merge `c311510` of `codex/m7-memc`, commit `1600d8a`). Captured pre-change hashes; independent rational source/output PTS and repeat cadence (D); analytic translation/known-layer reconstruction (P), exact endpoints, declared cuts and safe source-hold fallback; separate opt-in `motion` CLI/runtime configuration, default off. Added a 24p repeat/interpolated gallery comparison with exact position traces. TV profile YAMLs unchanged; vendor algorithms/calibration remain NR.
- **M9 opt-in window replay / drive fitting**: DONE (merge `f89047a` of `codex/m9-window-replay`, commit `202dbff`). `python3 -m sim fit-windows` fits independent `P` internal-drive scales against final pipeline luminance using strict M8 lookup. Explicit amplitude/color/settling/hold matching, black pre-roll, `P` exploratory assumptions for `NR` conditions, separate new `.fit.json` dataset IDs, preserved source evidence/placeholders, baseline fingerprints and no double limiting. Generic profile YAMLs and sidecars are unchanged. Default pipeline, validation, complete gallery and MEMC-off parity are protected by static goldens, including a current-main gallery capture.

## Workers (this cycle)
- Cursor run10: **failed at start** (`RetriableError: Connection stalled repeatedly`), no work done; stale empty `cursor/m7-memc` branch deleted.
- Codex run10: **finished** M8 (uncommitted → PM committed + merged).
- Codex run11: **finished** M7 MEMC phase 1 (uncommitted → PM committed + merged).
- Cursor run11: **failed at start** (`RetriableError: Connection stalled repeatedly`), no work done. Cursor worker paused until the CLI connection is fixed.
- Codex run12: **finished** M9 window replay / drive fitting (uncommitted → PM committed + merged).
- Started: Codex run13 → M10 opt-in viewing-angle model (worktree `/workspace/tv-sim-codex`, branch `codex/m10-viewing-angle`).
- **M10 opt-in viewing-angle model**: IN PROGRESS (Codex).

## Tests
- **387/387 pytest** on `main` after the M9 merge (PM re-run: `387 passed in 42.52s`).
- `python3 -m sim provenance --check` → **OK**, all four profiles, schema version 1.
- Coverage includes synthetic fit convergence with active demand/emitted ABL, strict amplitude/color/time/support rejection, preserved `P`/`NR` targets, dataset/file separation, one limiter pass per display tick, timing/history, malformed/stale fit rejection and CLI behavior. Default pipeline/validation/gallery/MEMC-off static goldens remain bit-identical after fit save/load/replay; current-main gallery manifest and M7 timing trace hashes also match.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- MEMC must be off by default and leave the MEMC-off path bit-identical.
- M9 is opt-in with separate fitted dataset IDs. Shipped records have `NR` amplitude/timing, so exploratory assumptions are required; low fitting residuals do not establish a calibrated TV, sustained capability or arbitrary-content replay. Strict geometry rejects raster area mismatch; exploratory rounding remains `P`.
- Cursor CLI connection stalls are recurring (4 of the last 6 runs); all work now goes to Codex until Cursor connectivity is fixed.
- Still stubbed: measured OD/BFI/PWM waveforms, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full watt solver, angular leakage LUTs, OLED attack/release, block-estimation MEMC.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.

## Next (assigned this cycle)
1. **M7 follow-ups (deferred)**: block estimation, automatic cut detection, vendor calibration, video/audio plumbing and full observer integration remain deferred per the research boundary.
2. **M10 viewing-angle model (Codex, `codex/m10-viewing-angle`)**: per `research/m6-profile-wiring.md` §8 item 4 — opt-in LCD angular transmission with independently identified white/leakage/gray terms (VA sparse endpoints as labeled demonstrations, IPS leakage/full fits NR), OLED angular gains NR/placeholder; default off, existing outputs bit-identical; tests + one gallery row.
3. **Measurement follow-ups**: acquire matched amplitude/color/time and sustained traces before any named-TV calibration or independent dynamics fit; current source gaps remain `NR`.
4. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm.
