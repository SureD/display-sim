# M18 — Sub-frame temporal emission

M18 implements a separate, default-off `SubframeConfig` for LC response,
overdrive and timed illumination/OLED blanking. The
[research note](../research/m18-subframe-temporal.md) preceded model design and
uses LCD compensation patents, SID/IEEE motion studies, VESA explanations,
IEEE 1789 and original reviewer measurements. Published specimen measurements
remain separate from generic runtime settings. Every shipped model/protocol
choice is P; clocks, waveforms and metrics are D under those inputs; matched
device LUTs, scanout, crosstalk and calibration remain NR.

## Model and state ownership

LCD history is float64 physical transmission, bounded by native leakage and
full opening. OLED history is ungated emitted RGB nits. Independent explicit
rise/fall e-fold times drive an analytic first-order response. An optional small
command-level table interpolates taus; an optional bilinear LCD LUT maps actual
starting transmission and target to a finite OD prefix, then returns to target.
This is an optical surrogate rather than a voltage/temperature model. It can
produce gray overshoot/undershoot and inverse contours without inventing
unbounded transmission.

Each display tick is divided into N exact rational bins. Response is integrated
analytically over the intersections of rectangular PWM/strobe/BFI pulses and
OD command segments. PWM uses absolute phase; strobe/BFI phase is relative to
the tick, with wrapped pulses supported. Even a pulse narrower than a bin
retains its correct emitted energy. Samples retain exact left PTS/duration,
mean emission, ungated response endpoint and illuminated fraction. Float64
endpoint state is independent of gating, pursuit integration and bin count.
Ambient reflection is added after gating. There is no automatic peak boost.

HDR/static ABL defines the steady target once before response. Physically
unrealizable LCD targets below leakage/above full transmission reject; bounded
float32 roundoff is clipped. OD transients can exceed that steady target within
physical transmission bounds. M17 owns one zone update/optical reconstruction
per tick and holds actual illumination within the tick. M13 owns one OLED
capacity update before response/BFI. Candidate states commit together only
after successful emission. Scene cuts can reset zones without resetting LC.

All MEMC modes reconstruct content before one display update and pass exact
output-rate fractions; off mode preserves the profile's decimal tick duration.
`SequenceOutput.subframes` exposes resolved light. Full display checkpoints
preserve exact pixel/zone/capacity array bytes, float hex scalars, rational clock,
geometry, original initialization values and effective source/config identity.
Fresh resume requires every active owner to select resume. Clock gaps, partial
histories, corrupted checkpoints, changed configuration and external state
mutation reject atomically. Reconstructing MEMC source buffers/estimator history
remains the caller's independent responsibility when continuing a sequence.

Legacy response/OD/drive ceiling/motion must explicitly be zero, legacy BFI
duty one, preserve-mean off and integration one. Active M10/M15, legacy off-axis
or nonidentity color transforms, smoothed APL, backlight tracking, channel-power
proxy and M9 schema-1 fits reject. OLED LCD-OD/PWM/strobe and LCD OLED-BFI reject.
M13 and M17 retain their panel-specific mutual exclusion. See
[usage](../usage.md#sub-frame-response-and-emission-opt-in-m18) and
[the protocol contract](../profiles.md#sub-frame-temporal-protocol-schema-version-1-m18).

## Experiment and visual review

Reproduce the [saved gallery](../../reports/subframe-m18/index.html) into a new
directory using the worktree-only installation:

```sh
PYTHONUSERBASE=/tmp/m18-user /tmp/m18-user/bin/tv-sim subframe \
  --out reports/subframe-example
```

The P protocol uses 128×24 pixels, 60 Hz ticks and 32 bins per tick. Moving
edges and bars run at 120/360/720 px/s. Six directed steps cover the three-level
20/100/300-nit matrix; diagonal cells have no transition. Flashing and constant
patches separate requested-content modulation from emission modulation. Six
independent arms compare LCD hold/OD/strobe/PWM and OLED hold/BFI.

The isolated experiment fixes P illumination at 1000 nits and LCD contrast at
4000, deriving a 0.25-nit floor. Its HDR map is identity across admitted gray
references (0.25–1000 nits); both limits are tested. LCD rise/fall taus are
P 5/8 ms; OLED zero tau isolates duty. The aggressive P OD table uses
`clip(new + 2*(new-old), 0, 1)` for a quarter tick. Strobe/BFI duty is P one
quarter; PWM is P 240 Hz/half duty. All previews share a P 500-nit white
reference and preserve brightness cost.

The artifacts contain 1620 complete display ticks across arms, 39,168 observed
rational CSV bins plus 11,520 constant-patch bins in JSON, and six ignored NPZ
archives. The 36 mean-output array hashes, rational boundaries, full per-arm
display identities and experiment-source hashes were independently verified.
All 22 JSON files are compact; the largest is 177,914 bytes. Ungated endpoint
waveforms and exact endpoint PTS permit independent response-metric replay.
Response and flicker metrics were recomputed from saved traces.

Selected D results under these P inputs:

| Quantity | Hold | OD/impulse |
|---|---:|---:|
| LCD 100→300-nit 10–90 response | 10.988 ms | OD 1.615 ms |
| LCD 100→300-nit 2% settling | 19.792 ms | OD 30.208 ms |
| LCD 100→300-nit overshoot | 0% | OD 69.621%, 139.241 nits |
| LCD normalized MPRT at 720 px/s | 28.024 ms | Strobe 23.141 ms |
| OLED normalized MPRT at 720 px/s | 16.659 ms | BFI 4.496 ms |
| Constant-patch mean | 300 nits | Strobe/BFI 75; PWM 150 nits |
| Constant-patch flicker percent/index | 0% / 0 | Strobe/BFI 100% / 0.75; PWM 100% / 0.5 |
| Constant-patch dominant frequency | None | Strobe/BFI 60 Hz; PWM 240 Hz |

All six motion contact sheets and the gray-step/constant-modulation plots were
visually inspected. OLED BFI has a narrower, dimmer pursuit edge. LCD strobing
retains a secondary edge from incomplete LC settling. OD creates a bright bar
contour and a strong response overshoot; the faster crossing has worse final
settling. Pulse phase and LC history can make low-speed strobe width exceed
hold width. The [artifact notes](../../reports/subframe-m18/README.md) describe
the complete metric conventions and interpretation.

Synthetic normalized MPRT is rising 10–90 edge width divided by `0.8*speed`.
Tracking images use bin-mean light and midpoint displacement over one tick;
finite raster/bin resolution remains visible. Unresolved fast response reports
an upper bound, and finite observations can censor settling. Flicker percent,
area index and strongest non-DC FFT bin describe the saved uniform bin means,
with explicit Nyquist/bin-width metadata. Exact pulse energy does not imply
resolved flicker/pursuit shape. Global simultaneous updates omit row scanout
and rolling shutters. These outputs are neither ClearMR certification nor an
IEEE 1789 biological risk classification or a measurement of host luminance.

## Verification environment and preserved defaults

The editable dev installation used only `PYTHONUSERBASE=/tmp/m18-user`, with
`--user --break-system-packages -e '.[dev]'`. Neither `/tmp/m16-user` nor
`/tmp/m17-user` was used. The reference environment was Python 3.13.5 and NumPy
2.5.4. The pre-M18 test set passed **1366 tests in 224.67s**. No pre-existing
test, golden fixture, profile YAML/sidecar or saved prior-milestone artifact was
modified. Disabled arrays, image assets, substantive traces and histories retain
the existing exact parity checks. Truthful implementation fingerprints reflect
the new source, as in earlier opt-in milestones.

Final verification after the custom-protocol endpoint fixes:

- `PYTHONUSERBASE=/tmp/m18-user python3 -m pytest -q`:
  **1680 passed in 253.51s (0:04:13)**, comprising all 1366 existing tests
  unchanged plus 314 M18 tests.
- `python3 -m ruff check .`: **All checks passed!**
- `python3 -m ruff format --check .`: **111 files already formatted**.
- `python3 -m mypy`: **Success: no issues found in 59 source files**.
- `python3 scripts/check_docs.py`: **Documentation links: all local targets
  and anchors passed**.
- `python3 -m tv_sim provenance --check`: **OK for 4 profiles**, including
  baseline/angular/colorimetry/OLED-dynamics/motion/zone-temporal/subframe
  schema version 1. Restricted-profile checking also passed from `/tmp`.
- `/tmp/m18-user/bin/tv-sim subframe --help`: passed from `/tmp`.
- `python3 -m build --wheel --outdir /tmp/m18-wheel`: succeeded with the
  isolated build backend. Wheel contents include all six M18 modules and the
  packaged protocol, with no bulk NumPy arrays.
- `git diff --check`: clean. Six generated NPZ archives are confirmed ignored.

All Python commands above used `PYTHONUSERBASE=/tmp/m18-user`. New tests cover
analytical ODE/gate integrals, sub-bin pulses, wrapped/absolute phase, tau/OD
tables, endpoint independence from N, brightness/leakage/ambient composition,
all MEMC modes with M13/M17 update counts, exact full-state continuation,
malformed/rehashed checkpoint and configuration/clock rejection, disabled
parity, strict protocol evidence, CLI/artifact determinism and metric replay.
The custom protocol's maximum gray target and exact leakage-floor reference
have dedicated regression checks.

## Suggested commit split

1. Primary-source research note and research index.
2. LC/emission runtime, full-history continuation, pipeline/MEMC integration,
   public config and M9 rejection, with low-level/ownership/continuation tests.
3. Strict P protocol/provenance, CLI experiment/metrics, artifact tests and saved
   compact gallery/traces; omit ignored full-precision NPZ arrays.
4. Usage/architecture/profile/development/index/README/changelog/status/plan
   documentation and this verification report.

All changes remain in the working tree for PM review. No git metadata writes,
commit, merge or push were performed.
