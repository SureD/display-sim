# Status — 2026-10-16 12:25 CST

## Milestone progress
- **M1 research docs**: DONE (`37cc504`).
- **M2 pipeline skeleton + TV profiles**: DONE (merge `f0d7e05`).
- **M3 local dimming + HDR + temporal**: DONE (merge `477685d`).
- **M4 validation + report**: DONE (merge `c7dbf01` + REPORT refresh `cc71643`).
- **M5 mechanism fidelity**: DONE this cycle (merge `1baa2e1`).
  - Cursor `cursor/m5-fidelity`: source-demand ABL load (`sim/load.py`), OLED emissive PSF in panel stage, shaped zone PSFs / LSF table hook / edge policies (reflect|zero|all-on-norm). Defaults keep prior profile output.
  - Codex wrote `research/m5-fidelity.md` (ABL curves, angle leakage, halo/PSF, subpixel, temporal, perceptual params; NR marked; 34+ sources).
  - PM merged + **79/79 pytest** on main (was 47).

## Workers (this cycle)
- Codex (`codex_run6.log`): **finished / idle**. Delivered uncommitted `research/m5-fidelity.md`; PM committed.
- Codex (`codex_run5.log`): **finished early / incomplete**. Mac EDR research task; no `research/m5-mac-display.md` left behind.
- Cursor (`cursor_run6.log` / worktree `cursor/m5-fidelity`): **finished code then stalled** (connection stalled ~10:32 CST after 3 commits). Work was already committed on the branch; merge succeeded.
- Cursor (`cursor_run5.log`): empty / no useful output.
- No `codex exec` or `agent -p` processes running at check time. **Not starting new long-running workers** until the user picks the next milestone.

## Drift / risks
- Profile numbers remain placeholders; do not present as emulating a specific TV.
- M5 knobs default off / Gaussian+reflect so M4 harness numbers should still match unless profiles opt in.
- Still stubbed: MEMC, measured OD/BFI/PWM waveforms, measured PSFs/zone maps wired into YAML, spectral subpixels, gamut mapping, glare, CRT/plasma, GPU path, zone temporal smoothing, full backlight/LCD watt solver, angular leakage LUTs.
- No remote origin configured; all work is local.
- Cursor agent transport remains flaky (stalls on long runs).

## Next (assigned — awaiting user OK before kicking workers)
1. **GPU path (PyTorch) on RTX 3070 box `dscs2pc`**: realtime preview + numerical parity vs CPU harness. Needs user confirm + local machine approval.
2. **M5 follow-through from research**: wire measured window tables / provenance, angular leakage model, consume LSF/PSF tables in profiles, attack/release ABL on OLED profiles — research-only until prioritized.
3. **Optional**: finish macOS EDR preview research (`m5-mac-display.md`) that Codex run5 did not deliver.
