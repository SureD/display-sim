# Status — 2026-10-16 (M6 gallery on cursor/m6-gallery)

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (merge `c7dbf01` + REPORT refresh `cc71643`).
- **M5 mechanism fidelity**: DONE (merge `1baa2e1` + fidelity research).
- **M5 macOS EDR research**: DONE (`research/m5-mac-display.md`).
- **M6 profile wiring research**: DONE this cycle (`research/m6-profile-wiring.md`, Codex run8).
- **M6 visual gallery**: DONE on `cursor/m6-gallery`. `python3 -m sim gallery` writes seven four-profile PNG contact sheets, offline HTML and a settings/statistics manifest under `reports/gallery/`.

## M6 gallery delivery
- Macro RGB stripe, R/W/B/G and staggered triangular QD-OLED apertures use equal logical pitch, a black matrix and area-normalized channel energy. Geometry, fill and white allocation are explicitly synthetic.
- Optional temporal subframe integration retains response state separately from pursuit/BFI output. Gallery uses 12 settled pre-roll + 36 moving frames, 16 subframe samples, full hold, LCD-only OD and fixed-peak 25%-duty BFI probes. Existing profiles and default temporal output remain unchanged.
- Shared preview exposure preserves brightness differences across TVs; amplified shadow rows make leakage visible. All sheets and HTML label placeholder parameters and scaled SDR previews of HDR.
- Visually checked generated PNGs for halos, window brightness/area dependence, ramps, motion trails and distinct macro geometry. See [gallery](../reports/gallery/index.html) and [report](REPORT.md#visual-gallery-m6).

## Workers (earlier cycle; historical)
- Codex (`codex_run8.log`): **finished**. Delivered `research/m6-profile-wiring.md` (measured window tables, provenance/NR, supported vs proposed YAML, QD-OLED M4 parity exception; left uncommitted → PM committed).
- Cursor (`cursor_run8.log` / `cursor/m6-gallery`): **failed** — connection stalled repeatedly ~15:46 CST; branch still at `6116f8b` with no gallery code.
- TV-sim `codex exec` / `agent -p`: **idle** at check time.
- **Restarting workers**: Cursor → M6 gallery (retry #3); Codex → M7 MEMC/motion research (post-M6 prep; does not block gallery).

## Tests
- **115/115 pytest** pass with the gallery changes (`python3 -m pytest -q`).
- `python3 -m sim gallery` completed; all seven PNGs were visually inspected, column captions stay inside their tiles, and every offline HTML reference resolves.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- M5 knobs default off / Gaussian+reflect so M4 harness numbers should still match unless profiles opt in.
- Still stubbed: MEMC, measured OD/BFI/PWM waveforms, measured PSFs/zone maps wired into YAML, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full backlight/LCD watt solver, angular leakage LUTs.
- The earlier Cursor retries stalled; this branch completes their gallery scope.
- GPU path on `dscs2pc` (RTX 3070) still **blocked on user OK** + local-machine approval.
- Wiring research lists implementation handoffs (provenance sidecar, window replay, angular leakage, OLED attack/release); those await post-gallery code milestones.

## Next (assigned this cycle)
1. **M6 gallery**: done on this branch (`reports/gallery/`).
2. **M7 MEMC research (Codex)**: write `research/m7-memc-motion.md` — motion estimation / frame interpolation models relevant to TV MEMC, artifacts to simulate, and what stays NR vs implementable in this NumPy pipeline (no code required).
3. **GPU path (PyTorch on dscs2pc)**: still awaiting user confirm before kicking that worker.
