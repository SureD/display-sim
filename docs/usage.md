# CLI usage

Install the package from a checkout with `python -m pip install -e '.[dev]'`.
Every command below also works as `python -m tv_sim …`. Run a subcommand with
`--help` for all options. `python -m sim` is a deprecated compatibility entry
point; Python imports use `tv_sim`.

## Still images and Python API

```sh
tv-sim --profile generic_woled --input input.png --output output.png
tv-sim --profile generic_va_fald_miniled --input input.png --output angle.png \
  --input-eotf srgb --ambient-lux 20 \
  --viewing-angle-horizontal 45 --viewing-angle-vertical 0
```

The available profiles are `generic_ips_edge`, `generic_va_fald_miniled`,
`generic_woled`, and `generic_qdoled`. Input EOTF defaults to the profile setting;
`srgb`, `pq`, and `hlg` are supported. PNG output is a preview at the profile's
reference exposure and can clip HDR. Angles opt into a synthetic model over a
combined center-ray angle of 0–45°; zero/omitted angles retain the baseline.

```python
import numpy as np

from tv_sim import Pipeline, load_profile

pipeline = Pipeline(load_profile("generic_woled"))
encoded_rgb = np.full((72, 128, 3), 0.5, dtype=np.float32)
linear_nits = pipeline.run_linear(encoded_rgb).rgb
```

Reuse the pipeline for a continuing display history; construct a fresh instance
for an independent trial. `run()` returns an encoded uint8 preview. Optional
`ColorimetryConfig`, `ViewingAngleConfig`, `ABLDynamicsConfig`, `MotionConfig`,
and `ZoneTemporalConfig` are separate runtime controls. The
[architecture](architecture.md) explains the state and units.

## Validation, provenance, and gallery

```sh
tv-sim provenance --check
tv-sim validate --out reports
tv-sim gallery --out reports/gallery
```

Validation writes metrics JSON/CSV, `comparison.md`, and PNGs. The comparison is a
plausibility check against conditional published anchors, not calibration. The
preserved [M4 comparison](reports/comparison.md) and
[gallery interpretation](reports/REPORT.md#visual-gallery-m6) explain the limits.
Generated outputs remain under `reports/`; historical prose lives in
`docs/reports/`. Use a separate output directory when comparing regenerated
results with the saved artifacts.

The gallery writes an offline HTML page, shared-exposure contact sheets, profile
hashes, settings, output statistics, and a motion trace. Optional rows use
`gallery --viewing-angle` or `gallery --colorimetry`; ordinary gallery output
keeps its existing comparison protocol.

## Colorimetry and color volume (opt-in)

```sh
tv-sim --profile generic_woled --input input.png --output color.png \
  --colorimetry --source-primaries display_p3 --gamut-mapping compress
tv-sim colorimetry --out reports/colorimetry-example
tv-sim export-web --out web/data --colorimetry \
  --source-primaries bt2020 --colorimetry-output bt2020
```

Primaries are declared independently of the EOTF; PQ/HLG do not imply BT.2020.
Source white defaults to D65; `--source-white x y` preserves absolute XYZ without
chromatic adaptation. M15 supports clip or straight white-centered CIE u′v′
hue-ray compression, which does not promise constant perceived hue. The WOLED
color envelope and global ABL/M13 capacity share one limiter. Panel coordinates
and envelope constants are P placeholders; spectra and measured color-volume
fits remain NR. See [the full contract](profiles.md#colorimetry-schema-version-1-m15).

## Motion sequences (opt-in)

```sh
tv-sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc repeat --out reports/motion-repeat
tv-sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc analytic --translation-px 20 0 \
  --out reports/motion-analytic
tv-sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc mci --motion-debug \
  --preview-reference-nits 1000 --out reports/motion-mci
tv-sim motion validate --seed 7 --gallery --out reports/motion-tests
```

Quote the input glob; files use lexical order, so pad frame numbers. `off` is the
default and makes one original call per source; omit `--output-fps` in that mode.
`repeat` schedules half-open holds, `analytic` requires known translation/layers,
and `mci` is the P-only reduced-resolution block proxy. Declare cuts with
`--cut-before INDEX ...`. Unsafe/ambiguous reconstruction uses source-hold
fallback and records reasons. Traces retain independent rational source/output
PTS, original endpoints, source lookahead assumptions, and hashes. Browser
playback and static sheets do not measure perceived smoothness or TV latency.

## OLED capacity dynamics (opt-in)

```sh
tv-sim oled-dynamics --profile generic_woled \
  --abl-dynamics capacity_attack_release_v1 \
  --abl-attack-ms 100 --abl-release-ms 1000 --abl-initial cold \
  --trials one_full_one --output-fps 60 --gallery \
  --out reports/oled-dynamics/example
```

The bundled protocol loads from package data automatically. Both e-fold times
are explicit P experiment inputs. A new output directory contains demand/emitted
trials, rational PTS, capacity/luminance traces, linear arrays, and history
checkpoints. `--abl-source demand` or `emitted` selects one load source.
`--state-in`/`--state-out` require one trial and one load source; continuation
requires `--abl-initial resume`. See [the protocol contract](profiles.md#oled-dynamics-protocol-schema-version-1-m13)
for initialization and incompatible legacy controls.

## LCD zone backlight dynamics (opt-in)

```sh
tv-sim zone-temporal --profile generic_va_fald_miniled \
  --attack-s 0.05 --release-s 0.15 --out reports/zone-temporal-m17
```

Both e-fold times are explicit P inputs in seconds: attack increases zone light
and release decreases it. This command runs moving-object, APL step up/down,
flashing-highlight and subtitle clips with independent feature-off/on histories.
Use a fresh output directory; existing experiment directories are not overwritten.
The bundled P-only protocol loads from package data. Use `--protocol PATH` for
an explicitly supplied schema-compatible record and `--fixtures NAME ...` to
select clips.

Optional `--slew-nits-per-tick` caps each zone's change after the IIR update;
this bound intentionally depends on refresh rate. `--initial` selects `cold`
or `settled_first_tick`. Declared cuts normally reset zone commands only;
`--no-scene-cut-reset` preserves them. `--cut-detection-threshold` enables a P
heuristic comparing bounded zone-target grids; flashes and APL steps can cause
false detections. No detector runs by default.

The default diagnostic uses prepared float32 linear BT.709 RGB nits, bypasses
input decoding/spatial processing, and sets pixel lag/overdrive/pursuit/BFI and
ambient to neutral values. `--pixel-response profile` retains the profile's
pixel-response tau for a separately identified comparison. The original TV
profile file is unchanged. This emitted-RGB response cascade does not resolve
within-tick LC transmittance or synchronized LED/PWM timing.

The paired diagnostic requires the highlight level not to exceed the selected
backlight peak, keeping off/on target bounds comparable. For `generic_ips_edge`,
provide an explicit P protocol with `level_nits` at or below its 400-nit peak
using `--protocol`; the bundled 800-nit protocol targets the VA profile.

The output contains `manifest.json`, `protocol.json` and an offline `index.html`.
Each clip has `trace.json` with rational PTS and per-zone grids, `probes.csv`,
`metrics.json`, `trace.png`, and `contact.png`. The bundled protocol uses one
shared 1000-nit reference; `shadows.png` uses a shared 1-nit reference to amplify
leakage. Reproducible `linear.npz` arrays are gitignored. Metrics distinguish ordinary spatial halo
from positive on-minus-off trails, command/output settling, direction-correct
overshoot, probe variation/pumping and highlight retention. They are D under P
assumptions, not measured TV dynamics or perceptual flicker scores.

Python callers can attach the separate controller to a continuing pipeline:

```python
import numpy as np

from tv_sim import Pipeline, ZoneTemporalConfig, load_profile

config = ZoneTemporalConfig(
    model="zone_attack_release_v1",
    attack_s=0.05,
    release_s=0.15,
    initial="cold",
)
pipeline = Pipeline(load_profile("generic_va_fald_miniled"), zone_temporal=config)
encoded_rgb = np.full((72, 128, 3), 0.5, dtype=np.float32)
content = pipeline.prepare_content(encoded_rgb)
linear_nits = pipeline.display_content(content, frame_time_ms=1000 / 60).rgb
trace = pipeline.last_zone_trace
```

`prepare_content()` does not advance history. For a declared new shot, pass
`scene_cut=True` to its first `display_content()` call. Sequence off/repeat/
analytic/MCI modes advance zones once per displayed tick and apply declared
source cuts when the new source is actually shown, including skipped source
indices. MCI's estimated pair cuts keep their reconstruction/confidence role;
M17's optional detector independently owns detected zone resets. Cold,
settled-first and explicit-grid policies start fresh histories; API
`initial="explicit"` requires a complete immutable
zone grid in `initial_zones_nits`. Exact continuation uses `initial="resume"`
and `restore_checkpoint()` with the complete `checkpoint()` record, preserving
zone/detector array bytes, pixel/load histories and configuration/clock identity.
A grid alone cannot resume history. The synthetic CLI keeps trials independent
and exposes cold/settled-first initialization; it has no resume flag.

M17 accepts LCD FALD/edge profiles only. Active M13 OLED capacity, legacy APL
smoothing/backlight tracking/power limits and M9 schema-1 fit composition reject.
M10 angles, static HDR/ABL and M15 colorimetry retain their existing owners.
The disabled path stays byte-identical. Active commands are bounded before PSF
spread; legacy demand is clipped after spread, so zero active taus can still
differ for sparse over-peak content. See the
[protocol and admission rules](profiles.md#lcd-zone-temporal-protocol-schema-version-1-m17)
and [research](research/m17-zone-temporal.md) for limits and evidence.

## Sub-frame response and emission (opt-in M18)

Run the separate synthetic experiment into a new directory:

```sh
tv-sim subframe --out reports/subframe-example
python -m tv_sim subframe --help
```

The [saved gallery](../reports/subframe-m18/index.html) compares LCD hold,
overdrive, strobe and PWM with OLED hold/BFI at one shared exposure. Moving
edges/bars at several speeds, directed gray steps, flashing patches and constant
patches produce rational sub-step CSV, compact waveform/metric JSON, linear
`.npz` arrays and simulated pursuit-camera images. Brightness loss is preserved
in every preview. The packaged P-only protocol supplies explicit demonstration
settings; ordinary rendering never loads these as TV defaults. `--protocol`
accepts an independently validated protocol with the same versioned schema.

For runtime use, explicitly remove the competing legacy response and emission
hooks before choosing a separate `SubframeConfig`:

```python
from dataclasses import replace
from fractions import Fraction
import numpy as np
from tv_sim import Frame, Pipeline, SubframeConfig, load_profile
from tv_sim.profile import TemporalParams

profile = load_profile("generic_va_fald_miniled")
profile = replace(profile, temporal=TemporalParams(response_time_ms=0))
config = SubframeConfig(
    model="subframe_emission_v1", substeps=32,
    rise_tau_ms=5, fall_tau_ms=8, initial="cold",
    strobe_duty="1/4", strobe_phase="5/8",
)
pipeline = Pipeline(profile, subframe=config)
tick = pipeline.display_subframes(
    Frame(np.full((24, 128, 3), 100, dtype=np.float32)),
    pts=Fraction(0), duration=Fraction(1001, 60000),
)
assert tick.samples[1].pts == Fraction(1001, 60000 * 32)
```

All numbers in this example are P choices. Rise/fall constants are e-fold
milliseconds, not measured GtG durations. LCD state is float64 transmission;
OLED state is ungated emitted RGB nits. Each sample contains its exact rational
left PTS/duration, mean emitted RGB, response endpoint and exact illuminated
fraction. The tick also returns an independent response endpoint and float32
mean RGB. PWM/strobe/BFI gates are intersected analytically with the exponential
response, including wrapped and sub-bin pulses. Ambient reflection stays outside
the emission gate. There is no scanout or rolling camera model.

`tau_table=((level, rise_ms, fall_ms), ...)` optionally interpolates constants
by command level. LCD levels cover transmission 0–1; OLED levels use nits and
must cover every requested command. Optional `overdrive_levels` and square
`overdrive_commands` provide a bilinear LCD LUT with actual starting transmission
on rows and target transmission on columns. Commands stay in 0–1 and use the
finite `overdrive_fraction` prefix before returning to target. This optical
surrogate can overshoot/undershoot gray targets; it is not a voltage LUT.

LCD `pwm_hz`, `pwm_duty`, `pwm_phase` use an absolute rational clock (zero Hz
means DC). LCD `strobe_duty`/`strobe_phase` and OLED `bfi_duty`/`bfi_phase` use
fractions of each display tick. Phase specifies pulse onset; a pulse may wrap
the tick boundary. Combined LCD PWM and strobe gates intersect; their duties
need not multiply. There is no automatic peak boost: a settled rectangular
pulse loses brightness in proportion to its effective duty.

HDR/static ABL establishes the steady target once before response. M17 can
update LCD zones once, then hold actual illumination during the resolved tick;
M13 can update OLED capacity once before BFI. A mapped LCD target outside
physical transmission/leakage bounds rejects (float32 roundoff is clipped).
Transient OD can exceed the steady mapped target within physical transmission
bounds. M17 scene cuts reset zones without resetting LC state. M13 and M17
remain mutually exclusive by panel technology.

Legacy response/OD/drive-ceiling/motion must explicitly be zero; legacy BFI
must be duty one, preserve-mean off and integration one. Active M10 viewing
angle, M15 colorimetry, legacy nonidentity panel matrix/off-axis law, smoothed
APL, backlight tracking, channel-power proxy and M9 schema-1 fits reject.
LCD BFI and OLED LCD-OD/PWM/strobe combinations reject. These domain limits
keep one owner for each state and emitted-light transformation.

All `MotionConfig` modes compose before one M18 update per output tick.
`SequenceOutput.subframes` retains the resolved samples; output frames contain
the mean emission without eye tracking. Repeat/analytic/MCI use exact output
rate fractions. Off mode retains the profile's decimal tick duration.
Direct `display_content`/`run_linear` also use the profile duration (or the
decimal spelling of an explicit millisecond override); use `display_subframes`
for exact fractional refresh rates and explicit PTS.

Cold and settled-first initialization start new histories. `checkpoint()`
records all LC/zone/capacity state bytes, original initialization, rational
clock, geometry and effective implementation/config identity. To continue,
create a fresh pipeline with `initial="resume"` for **every active owner**,
then call `restore_checkpoint(data)` and supply the exact next PTS. Configuration
changes, stale partial histories, clock gaps and externally edited state reject.
The checkpoint resumes display history; MEMC source buffers/estimator history
must independently reconstruct the same prepared targets and clocks.

Response metrics use ungated response endpoints, interpolation, and explicit
time-resolution/censoring fields. Pursuit images integrate emitted bin means
at bin midpoints over a declared shutter. Normalized synthetic MPRT is rising
10–90 edge width divided by `0.8 * speed`; finite raster and sub-step resolution
remain visible. Flicker percent/index and dominant non-DC FFT frequency describe
the saved bin-mean waveform, with Nyquist/bin-width metadata. Narrow pulses
retain exact mean energy, but coarse bins can suppress modulation and pursuit
detail. These metrics are not ClearMR certification or IEEE 1789 safety scores.
See [research](research/m18-subframe-temporal.md) and
[the protocol contract](profiles.md#sub-frame-temporal-protocol-schema-version-1-m18).

## Window drive fitting (opt-in)

```sh
tv-sim fit-windows --profile generic_woled \
  --source-dataset c2_42_hdr_standard_peak --dataset-id c2_exploratory_drive_v1 \
  --level-nits 1000 --settle-ms 100 --hold-ms 100 --exploratory \
  --out reports/window-fits/c2_exploratory_drive_v1.fit.json
```

Shipped named-sample records have unknown requested amplitude/timing, so this
example explicitly records exploratory P assumptions. Known mismatches and
out-of-support lookups always fail. Fits use new exclusive `.fit.json` files
outside the package profile tree; ordinary rendering never discovers or enables
them. A small residual does not establish a calibrated TV. See [M9 matching and
no-double-limiting rules](profiles.md#m9-window-replay-and-drive-fitting).

## Web preview and explainer

```sh
tv-sim export-web
python -m http.server 8000
# http://localhost:8000/web/
```

The viewer consumes linear-nit binary16 assets from `web/data/`, with extended
WebGPU presentation and SDR fallbacks. The browser and host own final light
output. Read the [calibration and HDR protocol](../web/README.md); use the
[offline explainer](../web-explainer/index.html) for the model's mechanisms.
