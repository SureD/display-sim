# Status — 2026-10-16 18:25 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (merge `c7dbf01` + REPORT refresh `cc71643`).
- **M5 mechanism fidelity**: DONE (merge `1baa2e1` + fidelity research).
- **M5 macOS EDR research**: DONE (`research/m5-mac-display.md`).
- **M6 profile wiring research**: DONE this cycle (`research/m6-profile-wiring.md`, Codex run8).
- **M6 visual gallery**: IN PROGRESS (Cursor `cursor/m6-gallery`; run8 stalled again with no commits).

## Workers (this cycle)
- Codex (`codex_run8.log`): **finished**. Delivered `research/m6-profile-wiring.md` (measured window tables, provenance/NR, supported vs proposed YAML, QD-OLED M4 parity exception; left uncommitted → PM committed).
- Cursor (`cursor_run8.log` / `cursor/m6-gallery`): **failed** — connection stalled repeatedly ~15:46 CST; branch still at `6116f8b` with no gallery code.
- TV-sim `codex exec` / `agent -p`: **idle** at check time.
- **Restarting workers**: Cursor → M6 gallery (retry #3); Codex → M7 MEMC/motion research (post-M6 prep; does not block gallery).

## Tests
- **79/79 pytest** on `main` at check time.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- M5 knobs default off / Gaussian+reflect so M4 harness numbers should still match unless profiles opt in.
- Still stubbed: MEMC, measured OD/BFI/PWM waveforms, measured PSFs/zone maps wired into YAML, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full backlight/LCD watt solver, angular leakage LUTs, gallery/subpixel macro view.
- Cursor agent transport remains flaky (stalls on long runs); gallery needs a successful retry. Codex is the backup research track only — do not duplicate gallery code on a second branch this cycle.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.
- Wiring research lists implementation handoffs (provenance sidecar, window replay, angular leakage, OLED attack/release); those await post-gallery code milestones.

## Next (assigned this cycle)
1. **M6 gallery (Cursor, `cursor/m6-gallery`)**: subpixel macro view + longer temporal histories; `python3 -m sim gallery` → `reports/gallery/` PNG contact sheets + HTML; pytest green; small commits.
2. **M7 MEMC research (Codex)**: write `research/m7-memc-motion.md` — motion estimation / frame interpolation models relevant to TV MEMC, artifacts to simulate, and what stays NR vs implementable in this NumPy pipeline (no code required).
3. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm before kicking that worker.
