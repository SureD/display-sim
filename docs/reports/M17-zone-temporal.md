# M17 — LCD zone backlight temporal dynamics

M17 adds a separate, default-off `ZoneTemporalConfig` for the LCD backlight.
The [research note](../research/m17-zone-temporal.md) was written before runtime
implementation from primary patent/IEEE evidence and original RTINGS transition
observations. These support mechanisms, not a calibrated retail-TV time constant.
All controller/protocol choices are P; computed results are D under those
choices; matched measured controller/optical/compensation parameters remain NR.

## Model and state ownership

`zone_attack_release_v1` retains bounded float64 zone commands in nits. Rising
and falling commands use separately explicit `attack_s` and `release_s` e-fold
times in seconds, with `-expm1(-dt/tau)` evaluated per display tick. Explicit
zero tau follows the target immediately. Optional `slew_nits_per_tick` applies
after IIR and intentionally depends on refresh rate. A declared scene-cut reset
bypasses both IIR and slew. An optional P detector compares successive bounded
zone targets using mean absolute difference divided by backlight peak; it may
mistake an APL change/flash for a cut or miss a similar-looking shot.

Commands feed the existing PSF/LSF exactly once, then LCD compensation and the
existing panel/HDR/ambient/pixel temporal tail. The active controller bounds
zone demand before spatial spread; the legacy branch spreads then clips.
Consequently active zero-tau output need not match legacy for over-peak sparse
requests. The absent/off path retains the original arithmetic, profile files,
arrays, assets, substantive traces and existing golden expectations.

Cold initialization starts at the profile floor; settled-first installs the
first target; explicit initialization requires a complete immutable zone grid.
These start a new zone history. Resume requires a versioned full checkpoint
containing exact float64 command/detector bytes, float32 panel-history bytes,
load and clock state, effective rasterized zone edges, original initialization,
history/source hashes and effective profile/config/angle/colorimetry/implementation
identity. Bad checkpoints, clock gaps, stale partial states and external history
mutation reject before committing a tick. Zone, pixel and load histories commit
together after successful rendering.

M17 admits VA/IPS LCD zoned backlights only. OLED/per-pixel emission and active
M13 capacity reject. Nonzero legacy APL smoothing, backlight tracking and channel
power proxy reject; M9 schema-1 fitting/replay explicitly rejects active zone
dynamics. Static ABL remains the existing downstream limiter. M10 operates on
the actual filtered illumination; M15 converts into panel-domain demand before
pooling and retains its single joint HDR/color-capacity owner.

Off/repeat/analytic/MCI sequences advance zones once per output tick. Declared
cuts reach M17 only when the new shot is actually displayed, including skipped
source indices during downsampling. M14 estimated cuts retain their own
reconstruction/confidence role; M17's optional detector owns detected zone
resets. A zone reset preserves independent pixel/load history. Within-tick
LED waveforms multiplied by physical LC transmission are not resolved: the
existing emitted-RGB pixel response is a declared P cascade approximation.

## Experiment and visual review

The [saved gallery](../../reports/zone-temporal-m17/index.html) and
[artifact notes](../../reports/zone-temporal-m17/README.md) contain four complete
synthetic clips: a moving highlight, an APL rise/fall, a flashing small highlight,
and subtitle blocks over a dim scene. Independent off/on pipelines use the same
content and clocks. Reproduce into a new output directory:

```sh
PYTHONUSERBASE=/tmp/m17-user /tmp/m17-user/bin/tv-sim zone-temporal \
  --attack-s 0.05 --release-s 0.15 --out reports/zone-temporal-example
```

The versioned packaged P-only protocol supplies a 128×72 raster, 120 ticks at
60 Hz, 800-nit highlights, a 2-nit dim scene and explicit metric thresholds.
The CLI requires both taus; ordinary rendering never discovers demonstration
constants. Protocol JSON, full per-zone JSON, rational PTS/duration CSV, metrics,
trace plots, shared-exposure contact sheets and HTML are inspectable. Linear
output/content/mask `.npz` arrays remain gitignored. `provenance --check`
validates the strict ledger even with a restricted `--profiles` selection.

The main comparison uses zero pixel lag to isolate zone dynamics, no ambient,
overdrive, BFI or pursuit, and one 1000-nit preview reference for both arms and
all clips. Separate amplified-shadow sheets use a shared 1-nit reference and
clip the highlights. `--pixel-response profile` enables a separately identified
cascade comparison. All eight primary/shadow sheets were visually inspected:
the moving sheet shows a broader trailing glow, subtitle extinction leaves a
temporary bar of leakage, and onset samples show reduced early highlights.
The APL shadow sheet saturates its bright fields by design; its primary sheet
and trace provide the interpretable brightness comparison. Static images do
not measure perceived flicker, host luminance or actual TV latency.

Selected D results under the saved P inputs:

| Quantity | Off | On |
|---|---:|---:|
| Moving-object maximum absolute trail, threshold 0.05 nits | 10 px | 22 px |
| Trailing-region energy | 8.357650 nit-pixel-s | 24.318071 nit-pixel-s |
| APL rise zone/output settling, 5% target band | 1/60 s | 3/20 s |
| APL fall zone settling, 5% target band | 1/60 s | 47/60 s |
| APL fall emitted-output settling | 1/60 s | 1/60 s |
| APL held-step zone overshoot | 0 nits | 0 nits |
| Flashing-highlight summed zone total variation | 89600 nits | 25044.271384 nits |
| Flashing-highlight integrated retention | 0.543213 | 0.414582 |

Positive on-minus-off temporal trail alone reaches 21 px and 16.067170
nit-pixel-s. Energy here integrates linear Y over pixels and time, not joules.
The slower fall of backlight commands does not force slower full-field emitted
output: instantaneous ideal LCD compensation can still reduce transmission to
the new target. Flash smoothing reduces command variation while losing highlight
energy. The unchanged subtitle black-bar probe's peak-to-peak leakage remains
about 0.123 nits in both arms; the long hold preserves amplitude while changing
onset/extinction timing. None of these are measured flicker or quality scores.

## Verification

The worktree-only editable dev install used `PYTHONUSERBASE=/tmp/m17-user`
(the system-managed Python required pip's `--break-system-packages` with
`--user`). `/tmp/m16-user` was never used. The unchanged pre-implementation
baseline was **1145 passed in 203.83s**. No existing test or golden fixture was
modified. Final verification (worker run, then PM re-run before merge on
2026-10-18):

- `python3 -m pytest`: **1366 passed** (worker 324.79s; PM re-run 218.89s),
  i.e. the 1145 pre-existing tests unchanged plus 221 new M17 tests.
- `python3 -m ruff check .`: all checks passed; `python3 -m ruff format --check .`:
  99 files already formatted.
- `python3 -m mypy`: no issues found in 53 source files.
- `python3 scripts/check_docs.py`: all local targets and anchors passed.
- `tv-sim provenance --check`: OK for 4 profiles and baseline/angular/colorimetry/
  OLED-dynamics/motion/zone-temporal schema version 1. `git diff --check` clean.
- Saved artifacts: 4 clips, 960 output frames with matching hashes, valid
  rational tick clocks, current source identities; `.npz` arrays gitignored.
  The PM visually inspected the moving-object contact sheet.

## Suggested commit split

1. Research note and research index, preserving source/NR boundaries.
2. Controller/history/pipeline/sequence integration, public API, strict protocol
   provenance and M9 rejection, with runtime/continuation/parity tests.
3. CLI experiment, metrics/gallery/artifacts and artifact tests; omit ignored
   `.npz` arrays.
4. Usage/architecture/profile/changelog/status documentation and this report.

The worker left all changes in the working tree; the PM committed them in the
split above and merged to `main`.
