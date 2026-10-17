# Status — 2026-10-17 (M11 design done)

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
- **M10 opt-in viewing-angle model**: DONE (merge of `codex/m10-viewing-angle`, commit `d392f9e`). Separate horizontal/vertical runtime configuration; independent LCD white transmission, emitted-black leakage and RGB gray-response terms; OLED emission gains only. Four versioned `*.angular.yaml` records label all numeric choices `P` placeholders, with current full fits, IPS leakage fits and OLED measured gains/spectra `NR`; the provenance CLI validates both sidecar schemas. CLI angle options and opt-in `gallery --viewing-angle` add a shared-exposure 0°/+45° comparison. Original runtime YAMLs and baseline provenance sidecars are unchanged; disabled/zero-angle paths and existing goldens remain bit-identical.
- **M11 OLED capacity attack/release design**: DONE (research only; [design](../research/m11-oled-dynamics.md), uncommitted for PM review). Defines nit-capacity state, asymmetric e-fold updates per display tick, initialization/pre-roll/full-history restore, one capacity owner, rejection of legacy-smoother and M9 v1 fit conflicts, a separate history-aware experiment, source/NR ledger, and implementation/parity acceptance tests. Default off; runtime implementation and measured calibration remain future work. No code, tests, profile YAMLs, sidecars or saved reports changed.

## Workers (this cycle)
- Cursor run10: **failed at start** (`RetriableError: Connection stalled repeatedly`), no work done; stale empty `cursor/m7-memc` branch deleted.
- Codex run10: **finished** M8 (uncommitted → PM committed + merged).
- Codex run11: **finished** M7 MEMC phase 1 (uncommitted → PM committed + merged).
- Cursor run11: **failed at start** (`RetriableError: Connection stalled repeatedly`), no work done. Cursor worker paused until the CLI connection is fixed.
- Codex run12: **finished** M9 window replay / drive fitting (uncommitted → PM committed + merged).
- Codex run13: **finished** M10 opt-in viewing-angle model (uncommitted → PM committed `d392f9e` + merged; PM re-ran 534/534 pytest + provenance check).
- Cursor run12 (M11 OLED attack/release research): **failed at start** again (`RetriableError: Connection stalled repeatedly`) despite an OK probe at 06:25; no work done. Cursor worker paused; empty `cursor/m11-oled-dynamics` branch left unused.
- Codex run14: **finished** M11 OLED capacity attack/release design research (reassigned from Cursor; worktree `/workspace/tv-sim-codex`, branch `codex/m11-oled-dynamics`; uncommitted for PM review).

## Tests
- **M11 research-only verification:** `python3 -m pytest -q` → **534 passed in 52.18s**. No runtime or test changes.
- **534/534 pytest** after the M10 merge (PM re-run on worktree: `534 passed in 51.80s`).
- `python3 -m sim provenance --check` → **OK**, all four profiles, baseline/angular schema version 1. `git diff --check` passes.
- M10 coverage includes exact disabled/on-axis output and history parity, LCD monotonic contrast collapse, independent white/leakage/gray and RGB color terms, OLED isolation from LCD terms, signed/combined-angle support and invalid-coordinate rejection, strict provenance labeling, CLI behavior and the optional gallery comparison. The generated comparison sheet was visually inspected.
- Existing coverage includes synthetic fit convergence with active demand/emitted ABL, strict amplitude/color/time/support rejection, preserved `P`/`NR` targets, dataset/file separation, one limiter pass per display tick, timing/history and malformed/stale fit rejection. Default pipeline/validation/gallery/MEMC-off static goldens remain bit-identical after M9 fit save/load/replay; complete default gallery manifest and M7 timing trace hashes also match. The opt-in angular gallery retains all eight previous sheets and trace hashes.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- MEMC must be off by default and leave the MEMC-off path bit-identical.
- M10 uses P synthetic endpoints over a center-ray angle of 0–45°, with unsigned symmetry and azimuth independence. It does not model per-pixel viewing geometry or IPS corner glow. Angular panel terms precede the existing HDR/ABL/temporal stages, so emitted-load ABL can interact with angular gains; the gallery isolates the terms with fixed-backlight SDR and disabled load limiting. No named TV is calibrated.
- M9 is opt-in with separate fitted dataset IDs. Shipped records have `NR` amplitude/timing, so exploratory assumptions are required; low fitting residuals do not establish a calibrated TV, sustained capability or arbitrary-content replay. Strict geometry rejects raster area mismatch; exploratory rounding remains `P`.
- M11 is a completed design, not an implemented controller. Its single capacity state and example attack/release constants are `P`; measured C2/S95B dynamics, timed sustained traces, thermal/static-image controllers, RGBW allocation and watt coefficients remain `NR`. Proposed implementation must replace the existing HDR capacity once, reject nonzero legacy smoothing/tracking/power-proxy conflicts and M9 v1 fit composition, and preserve current-tree off-path goldens. Endpoint capacity held per tick is an explicit exposure approximation; full checkpoint continuation also needs panel/load history.
- Cursor CLI connection stalls are recurring (runs 6, 8, 10, 11, 12; run12 failed even after an OK probe). All work goes to Codex until Cursor connectivity is fixed.
- Still stubbed: measured OD/BFI/PWM waveforms, measured PSFs/zone maps, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full watt solver, measured full angular leakage/RGB LUTs, OLED attack/release runtime implementation (M11 design done), block-estimation MEMC.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.

## Next (assigned this cycle)
1. **PM review M11 design** (`codex/m11-oled-dynamics`, uncommitted): review `research/m11-oled-dynamics.md` against M6 §8 item 5. Design is done; schedule runtime implementation separately using its file/API/CLI and golden-parity handoff.
2. **M7 follow-ups (deferred)**: block estimation, automatic cut detection, vendor calibration, video/audio plumbing and full observer integration remain deferred per the research boundary.
3. **Measurement follow-ups**: acquire matched amplitude/color/time and sustained traces before any named-TV calibration or independent dynamics fit; current source gaps remain `NR`.
4. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm.
5. **Cursor worker**: paused until CLI connection stalls are fixed.
