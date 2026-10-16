# Status — 2026-10-16 21:34 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (merge `c7dbf01` + REPORT refresh `cc71643`).
- **M5 mechanism fidelity**: DONE (merge `1baa2e1` + fidelity research).
- **M5 macOS EDR research**: DONE (`research/m5-mac-display.md`).
- **M6 profile wiring research**: DONE (`research/m6-profile-wiring.md`).
- **M6 visual gallery**: DONE (merge `30f8e97` of `cursor/m6-gallery`, 5 commits `adf6bd4`..`5685b4b`). `python3 -m sim gallery` → `reports/gallery/` (7 PNG contact sheets, `index.html`, `manifest.json`): subpixel macro (RGB stripe / WRGB / QD-OLED triangle), pursuit pan with response/overdrive/BFI, starfield, subtitles, bright windows, gradients across all 4 profiles.
- **M7 MEMC/motion research**: DONE (`research/m7-memc-motion.md`, Codex run9; PM committed).
- **M7 MEMC implementation phase 1**: IN PROGRESS (Cursor, `cursor/m7-memc`).
- **M8 profile provenance sidecar**: DONE in worktree `/workspace/tv-sim-codex`, branch `codex/m8-provenance` (uncommitted: git metadata is read-only). Four versioned sidecars cover all 220 effective profile values, with separate named-sample measurements, strict support lookup, and `python3 -m sim provenance --check`. Runtime YAMLs unchanged; pipeline parity tested.

## Workers (this cycle)
- Cursor run9: **finished** — gallery committed after a transient reconnect; 115/115 tests.
- Codex run9: **finished** — M7 MEMC research (uncommitted → PM committed).
- Restarted: Cursor run10 → M7 MEMC phase 1; Codex run10 → **finished M8 provenance** (code; git staging failed on read-only metadata, so changes remain uncommitted for PM review/commit).

## Tests
- **115/115 pytest** on `main` after the gallery merge.
- **230/230 pytest** on `codex/m8-provenance`: 115 existing + 115 provenance tests. All four sidecars pass validation; tests prove byte-identical linear/encoded output and temporal history with sidecars present, absent, or malformed.

## Drift / risks
- Profile numbers remain placeholders; gallery labels say so. Do not present as emulating a specific TV.
- MEMC must be off by default and leave the current MEMC-off path bit-identical (M7 research §9; QD-OLED historical-M4 PSF exception documented in M6 wiring research).
- MEMC (`sim/pipeline.py`, `sim/stages/temporal.py`, CLI) and provenance (`sim/profiles*`, YAML loading, validation) should touch mostly different files; PM resolves any merge conflicts.
- Still stubbed: measured OD/BFI/PWM waveforms, measured PSFs/zone maps in YAML, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full watt solver, angular leakage LUTs, OLED attack/release, block-estimation MEMC.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.

## Next (assigned this cycle)
1. **M7 MEMC phase 1 (Cursor, `cursor/m7-memc`)**: per `research/m7-memc-motion.md` handoff order — capture MEMC-disabled baselines; source/output PTS separation with a rational repeat (judder) scheduler + diagnostics; analytic-translation / layer reconstruction at intermediate times with cut/fallback flags; opt-in CLI/profile switch (default off); tests proving MEMC-off parity; gallery row comparing 24p repeat vs interpolated pan.
2. **M8 provenance sidecar (Codex)**: complete in this worktree; ready for PM review/commit. Schema/API and preserved measurement limits documented in `docs/PROVENANCE.md`.
3. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm.
