# Status — 2026-10-16 15:30 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (merge `c7dbf01` + REPORT refresh `cc71643`).
- **M5 mechanism fidelity**: DONE (merge `1baa2e1` + fidelity research).
- **M5 macOS EDR research**: DONE this cycle (`research/m5-mac-display.md`, Codex run7).
- **M6 visual gallery**: IN PROGRESS (Cursor `cursor/m6-gallery`; prior run7 stalled with no commits).

## Workers (this cycle)
- Codex (`codex_run7.log`): **finished**. Delivered `research/m5-mac-display.md` (EDR/Metal/XDR, calibration, host-limit strategies, MPS caveats, Mac validation protocol; 39 sources; left uncommitted → PM committed).
- Cursor (`cursor_run7.log` / `cursor/m6-gallery`): **failed** — connection stalled repeatedly ~13:21 CST; branch still at `1a533de` with no gallery code.
- TV-sim `codex exec` / `agent -p`: **idle** at check time. Unrelated Codex jobs (`theory_last.md`, `embed_last.md`) are running elsewhere and are not part of this project.
- **Restarting workers**: Cursor → M6 gallery (retry); Codex → M5 follow-through parameter wiring research.

## Tests
- **79/79 pytest** on `main` at check time.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- M5 knobs default off / Gaussian+reflect so M4 harness numbers should still match unless profiles opt in.
- Still stubbed: MEMC, measured OD/BFI/PWM waveforms, measured PSFs/zone maps wired into YAML, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full backlight/LCD watt solver, angular leakage LUTs, gallery/subpixel macro view.
- Cursor agent transport remains flaky (stalls on long runs); gallery needs a successful retry.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.

## Next (assigned this cycle)
1. **M6 gallery (Cursor, `cursor/m6-gallery`)**: subpixel macro view + longer temporal histories; `python3 -m sim gallery` → `reports/gallery/` PNG contact sheets + HTML; pytest green; small commits.
2. **M5 follow-through research (Codex)**: from `research/m5-fidelity.md`, write `research/m6-profile-wiring.md` — concrete YAML/parameter tables to wire measured window tables, angular leakage, LSF/PSF hooks, attack/release ABL into profiles (mark NR; no code required).
3. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm before kicking that worker.
