# Profile and experiment provenance (M8, M10, M13, M14)

Each runtime profile has a separate `sim/profiles/<name>.provenance.yaml`
record with `schema_version: 1`. These records document the current generic
presets and preserve published measurements from the existing research.
They do not calibrate a generic preset to a named television.

```sh
python3 -m sim provenance --check
python3 -m sim provenance --check --profiles generic_woled generic_qdoled
```

The check reports invalid or missing records and exits unsuccessfully when
validation fails. M10 adds `sim/profiles/<name>.angular.yaml` records to this
same check; `--profiles` selects both baseline and angular records. The default
check also rejects orphan sidecars of either kind with no
corresponding runtime profile. Runtime loading and the rendering pipeline do not read the
sidecars. Profile discovery excludes `*.provenance.yaml` and `*.angular.yaml`, so adding a record
does not create another selectable TV profile. The four original runtime
YAML files remain unchanged.

M13 also checks the separate [synthetic OLED dynamics protocol](../research/measurements/oled_dynamics_synthetic_v1.json)
on every invocation, including checks restricted by `--profiles`. This protocol
is outside the profile tree and is never discovered by ordinary rendering.
M14 checks the separate block motion config and synthetic validation protocol
on every invocation, including `--profiles` selections.

## Evidence and unknowns

The labels follow [M5 fidelity](../research/m5-fidelity.md) and
[M6 profile wiring](../research/m6-profile-wiring.md):

| Label | Meaning |
|---|---|
| `M` | A published measurement on the named specimen under the recorded conditions. |
| `D` | A calculation from stated inputs, with its method and source retained. |
| `P` | A proposed model, synthetic preset, fitting choice, or interpolation. |
| `NR` | No verified numerical reference, an unidentified parameter, or an unknown condition. |

`NR` never means zero. Use `not_applicable` where a mechanism or field does
not apply, rather than where its value is merely unknown. A measured
luminance can have `M` evidence while its dwell, uncertainty, firmware, or
requested stimulus amplitude remains `NR`. Those gaps prevent a claim of
matched experimental conditions.

The shipped generic settings are documented as synthetic choices or values
without a matched measurement. A nearby published peak, contrast ratio, or
response result does not make a profile parameter measured. In particular,
panel response time constants are not published GtG averages, optical
spreading knobs are not measured TV kernels, and weighted-nit power knobs
are not electrical watt measurements.

## Schema version 1

| Top-level field | Meaning |
|---|---|
| `schema_version` | Integer `1`; unsupported versions fail validation. |
| `profile` | The corresponding runtime profile name. |
| `entries` | Provenance for every supported effective profile leaf. |
| `datasets` | Separate named measurement records, keyed by dataset ID. |

The `entries` mapping uses dotted profile paths. Each entry records an exact
`value` snapshot, evidence, source location, conditions, interpolation, and
support. Paths cover every leaf of the loaded profile, including defaults
from [the profile dataclasses](../sim/profile.py), not only keys explicitly
written in the runtime YAML. Lists are atomic: for example,
`panel.color_matrix` and `hdr.abl_channel_weights` each have one entry.
An absent optional table is recorded at `backlight.psf_profile` with a null
value; a supplied table uses its supported nested fields instead.

The validator compares entry paths against supported dataclass fields and
compares each stored value against the loaded value. Missing entries,
unsupported paths, and stale snapshots fail validation. This makes a later
default or runtime-profile change require an explicit provenance update.

| Entry field | Contents |
|---|---|
| `value` | The exact loaded scalar, null, or atomic list. |
| `evidence` | `M`, `D`, `P`, or `NR`. |
| `source` | A `locator` and `sample`; published sources also retain their URL. |
| `conditions` | Explicit experimental context, with unknowns retained as `NR`. |
| `interpolation` | `method` and `evidence`. |
| `support` | `range`, `unit`, and `outside: reject`. |
| `notes` | Interpretation, assumptions, or reasons a setting is synthetic. |

Each source retains a locator and sample identity. Local synthetic values
point to the runtime YAML or dataclass default and the relevant research;
published records retain the original review URL and table, asset, or
paragraph locator. Conditions preserve unknown values explicitly, including
mode, source encoding and requested amplitude, stimulus geometry, refresh
and VRR, white point, viewing geometry, instrument, warm-up, dwell, pattern
history, ambient light, temperature, and uncertainty where relevant.

`interpolation` records the method and evidence. An unchanged scalar uses
`method: none` with interpolation evidence `not_applicable`. A numerical
support interval records its unit and an `outside: reject` policy.
`range: NR` means that the measurement support is unknown; `range: not_applicable`
is reserved for values without a meaningful measurement axis. Neither is a
permission to extrapolate. Synthetic settings do not acquire measured
support merely because the simulator accepts a wider parameter range.

The separate `datasets` mapping stores named measurement records. Each
record has `kind` (`window_curve` or `unlocated_peak`), `specimen`, `source`,
`conditions`, `axis`, `metric`, `nodes`, `interpolation`, and `support`.
Each window node records `fraction`, `luminance_nits`, and `evidence`.
An unlocated scalar uses an `unlocated_peak` block rather than a fabricated
numeric node. `calibrated_profile_fit` and `timed_sustained_trace` remain
`NR` in these records. They are candidate evidence for future work; they
are not assignments to `hdr` parameters or active output curves.

## Preserved measurement records

The sidecars transcribe the values already documented in M5/M6; M8 performs
no new measurement or source acquisition.

| Sidecar | Named record | Preserved limits |
|---|---|---|
| `generic_woled` | LG 42C2 HDR Standard, dynamic tone mapping off; 1–100% peak-window table. | C2 values inherit the M5 table-image transcription; M6 records its unsuccessful refetch. Dwell and sustained traces remain `NR`. |
| `generic_qdoled` | Samsung 65-inch S95B HDR10 Filmmaker peak windows. | Independent 2%, 5%, and 75% readings remain `NR`; the publisher's rounded 1–10% plateau does not create extra measurements. |
| `generic_va_fald_miniled` | TCL 98X955 Theatre HDR peak-window table. | Numeric support begins at 2%; the 1% point is `NR`. The low-window suppression is retained and no monotonic OLED fit is imposed. |
| `generic_ips_edge` | LG 55UH770V 455-nit peak, window unlocated. | Window fraction and dwell remain `NR`; this scalar cannot supply a window curve or a supported fraction lookup. |

The original sources and per-node evidence remain in each record. These
samples are not interchangeable technology curves. A 100% peak entry does
not establish 10-second or 60-second sustained output, and another screen
size or picture mode is a different experiment.

## Angular schema version 1 (M10)

The opt-in angular stage keeps its synthetic parameters in
[`sim/viewing_angle.py`](../sim/viewing_angle.py), separately from the unchanged
runtime profile YAML. Each `.angular.yaml` sidecar records every effective
parameter, including the support bound, with an exact scalar or atomic RGB-list
snapshot and the same `value`, `evidence`, `source`, `conditions`,
`interpolation`, `support`, and `notes` fields described above. Missing labels,
unknown fields, nonfinite values, stale snapshots, missing records and duplicate
YAML keys fail `python3 -m sim provenance --check`. Ordinary profile loading and
rendering do not parse angular sidecars.

All shipped angular numeric values have **P** evidence and
`parameter_status: placeholder`. Schema 1 requires this label; a placeholder
cannot acquire measured status by changing its evidence field. Source specimen
is `NR`; `full_angular_fit` and `calibrated_profile_fit` remain `NR` for all four
profiles. LCD `black_leakage_fit` remains `NR`, including IPS. OLED
`angular_spectra` remains `NR`; its emitted RGB gains are synthetic placeholders,
with no verified numerical angular gain reference. OLED LCD leakage and LCD
angular spectra are explicitly `not_applicable`. These records calibrate no
named television. The older sparse VA endpoints in M5/M6 remain mechanism
demonstrations and are not assigned to the current presets.

| Model | Parameter | Definition |
|---|---|---|
| Both | `max_angle_deg` | P exploration bound of 45°, not measured angular support. |
| `lcd_transmission` | `white_gain_45` | Independent RGB white transmission relative to on-axis white. |
| `lcd_transmission` | `black_gain_45` | Independent emitted-black gain relative to on-axis black. This is not leakage relative to same-angle white. |
| `lcd_transmission` | `gray_exponent_45` | RGB exponent on already-linearized transmission, preserving the black/white endpoints. |
| `emissive_gain` | `emission_gain_45` | Emitter/film RGB gain only; no LCD leakage or gray exponent is applied. |

Horizontal and vertical runtime angles produce the center-ray effective angle
`theta = acos(cos(horizontal) * cos(vertical))`. Signed symmetry and independence
from azimuth are P assumptions. They do not model per-pixel eye geometry or IPS
corner glow. Every entry declares the numerical exploration support
`[0, max_angle_deg]` in `radial_angle_deg` and `outside: reject`; this is not a
claim of measured support. An out-of-support combined angle rejects even when
the individual horizontal and vertical values lie within 45°.

For `s = sin²(theta) / sin²(45°)`, the gain terms interpolate as
`exp(log(gain_45) * s)` (`log_gain_sin2_v1`, P), and gray exponents interpolate
as `1 + (exponent_45 - 1) * s` (`linear_sin2_v1`, P). The support bound itself
uses `none/not_applicable` interpolation. These model choices and synthetic RGB
differences provide independently adjustable contrast collapse, gray wash-out
and color shift; they are not additional measurements or an angular spectrum.

For positive LCD backlight `B`, the active model uses on-axis compensation
`q = clip((target/B - epsilon0)/(1-epsilon0), 0, 1)`, where
`epsilon0 = 1/native_contrast`. The independent interpolated white and emitted-black
gains give `epsilon = epsilon0 * Fblack/Fwhite` and
`L = B*Fwhite*(epsilon + (1-epsilon)*q**gray_exponent)`. Zero backlight emits
zero; extinction above one is rejected over the model's whole support.
An emissive model multiplies emitted RGB by its gains without LCD terms.
Disabled and exactly on-axis configurations bypass this arithmetic and retain
the original pipeline bit-for-bit. Angular terms precede the existing HDR/ABL
and temporal stages; use the gallery's fixed-backlight SDR protocol to compare
the angular mechanisms independently of emitted-load limiting.

## Measurement lookup

`sim.provenance.lookup_measurement(data, dataset_id, fraction)` is an
explicit research lookup. It returns the fraction, luminance in nits,
evidence, and whether the result was interpolated. It does not modify a
profile or run a rendering stage.

A lookup at a known numeric node retains that node's evidence. Between
known nodes, the declared piecewise-linear method returns `P`, including
when both endpoints are `M`. An `NR` node is preserved in the record and
does not become a measured value; any interpolation across its position is
still a proposed result. No lookup may leave the declared numeric support,
and an unknown support range fails explicitly. For example, an X955 lookup
below 0.02 fails, and the IPS unlocated peak cannot be looked up at any
window fraction.

Interpolation here is exploratory. It does not fill missing requested
amplitudes or timing, certify condition-matched replay, or activate replay.
M8 implements the sidecars and validation from §8 item 1; the separate M9
entry point below implements §8 item 2.

## M9 window replay and drive fitting

`python3 -m sim fit-windows --help` explicitly selects a source measurement
dataset, a **new** fitted dataset ID and a new `.fit.json` file. No defaults,
profile dataclasses or generic YAMLs change. Ordinary rendering, validation,
gallery generation and MEMC-off sequences never discover or load a fit file.
Fits are written outside the runtime profile directory and never overwrite
an existing file. A baseline hash over all effective profile values prevents
reusing drives after the baseline changes.

`sim.window_replay.fit_windows` performs strict M8 lookup before any fitting.
Both nominal and rasterized fractions must be inside source support. Numeric
source nodes are selected by default; `NR` nodes are skipped and retained in
the complete embedded source record. Explicit gap queries use the existing
piecewise-linear `P` lookup, including at an `NR` position. No extrapolation,
unlocated-peak substitution, monotonic-curve assumption, or fit-scale
interpolation is allowed. The saved fit supports only its listed experiments.

The matching rules are explicit:

- **Amplitude:** `level_nits` is requested max-channel linear nits in `(0,
  10000]`, independently of measured output. Neutral white has equal RGB
  channels at this level, so its requested Y equals the level. For a colored
  window, requested Y uses the simulator's BT.709 coefficients. Input is
  float PQ, with no preview quantization. Requested APL is computed on the
  actual raster before processing; processed source APL and internal drive
  APL are recorded separately. Measured output never supplies requested APL.
- **Color:** linear BT.709 `color_rgb` has three components in `[0,1]` with
  maximum 1. Source encoding, primaries, stimulus identity and PQ RGB codes
  must match. A known white-window sweep cannot supply colored targets,
  even in exploratory mode. Other primaries/encodings require a separate
  implementation and dataset.
- **Geometry:** a centered window retains the raster aspect ratio, with
  each extent rounded up to whole pixels. The intended fraction, actual
  fraction and raster resolution are retained. Source aspect ratio and
  intended position must match. Strict mode requires actual and nominal
  area fractions to agree within `1e-12`; exploratory mode records any
  difference as a separate `P` raster assumption. Each window must span at
  least two pixels per axis so the center probe lies within it. The aspect
  ratio matching field describes the intended window/screen ratio; rounded
  pixel extents are the declared `P` rasterization choice.
  Spatial scale must be 1 and eye motion 0 for the static center metric.
- **Time:** pre-roll is at least one black tick. Settling is zero or more
  ticks; hold is at least one tick. All durations must be integral multiples
  of the declared frame time. One fresh pipeline is initialized per trial,
  then the same panel and load histories advance throughout pre-roll,
  settling and hold. Dwell is settling plus hold, excluding black pre-roll.
  The metric is the **maximum center luminance over hold frame outputs**,
  matching M8's peak-center metric; the center is the central one/two pixels
  on each axis. Every hold sample is retained. The profile's temporal
  exposure/integration model applies; these are discrete frame outputs,
  not a measured continuous peak or a sustained-output trace.

Strict mode requires known matching values for these fields, refresh rate,
ambient lux and viewing angle. Numeric comparisons allow `1e-6` relative or
`1e-7` absolute tolerance. Timing requires `dwell_s`, `settling_s`, `hold_s`,
`hold_statistic: max_center_over_hold_frame_outputs` and a
`prior_pattern_and_duration: {stimulus: black, duration_s: ...}` record.
`measurement_conditions()` returns the canonical field representation for
synthetic experiments. Missing fields are `NR`; only an explicit
`--exploratory` / `exploratory=True` permits them, recording every assumed
value as `P` without changing the source. A known mismatch always rejects.
Other specimen/source conditions are retained; passing this match does not
certify complete laboratory equivalence. All shipped M8 records need the
exploratory option because their amplitude and timing are unknown.

The model `per_window_normalized_drive_v1` fits one positive scalar per
experiment using bracketed geometric bisection in `[1e-6, 1e4]`. That scalar
multiplies processed internal drive, backlight peak/floor, HDR peak/full-field/
reference/power budget and the temporal drive ceiling. Zero disable/fallback
sentinels stay zero. Optical shapes, contrast, dimensionless ABL parameters,
time constants and ambient light remain those of the baseline. This
normalization is deliberately a **P model**: scalar center targets cannot
uniquely identify physical peak limits, electrical power or vendor controls.
It can preserve nonmonotonic X955 window targets through independent fits.

**No double limiting:** each trial drives the original backlight → panel →
tone map/ABL → ambient → temporal path exactly once per tick, with all active
generic limits included in the forward model. The measured target enters
only the residual against final output. No measured output curve, target
gain, or second ABL/peak/local-dimming operation follows that output.
In particular, measured 717/152-nit values are never copied into generic
peak/full-field parameters and then limited again. ABL is evaluated on the
appropriate internal request/emitted picture according to the unchanged
baseline's `abl_source`; its configuration and histories are not silently
disabled. Unreachable targets or nonconvergence fail explicitly.

Fitted drive scales, assumptions and model/raster choices are `P`. Source
targets retain `M`, `D` or `P`; placeholder targets and interpolated targets
stay `P`. Raw `NR` nodes remain `NR`. Forward outputs, APL and residuals are
`D` calculations under the stated `P` model, not measurements.
`calibrated_profile_fit` and `timed_sustained_trace` remain `NR`. A low fitting
residual does not establish dynamics, color power, sustained capability,
arbitrary-content replay, or a calibrated named television.

## OLED dynamics protocol schema version 1 (M13)

The synthetic protocol/config uses `schema_version: 1`, a distinct
`protocol_id`, `parameter_status: placeholder`, and `evidence: P`. Its
`settings` declare the raster, PQ/BT.709 requested level, rational output rate,
fixed preview exposure, onset/late reporting intervals and explicit ambient,
BFI, overdrive, pursuit and angle overrides. `demonstration` supplies the
explicit **P** attack/release e-fold times and initialization policy; these
are experiment inputs, never runtime defaults. Each named trial saves its
complete ordered window fractions and rational segment durations. Durations
must contain whole display ticks; a zero-duration gap contributes no tick.
Unknown fields, nonfinite values, conflicting conditions and invalid timing
fail validation. The provenance check uses the same strict protocol validator
as the experiment runner.

All protocol choices and constants, including the example 100/1000-ms taus,
are **P placeholders**. The `unavailable` ledger keeps measured attack/release,
thermal/static-image controllers and calibrated-profile fitting **NR**. It
does not transfer named-sample measurements or estimate a TV controller.
Runtime profile values retain their baseline provenance, and all original
runtime YAMLs and baseline/angular sidecars remain unchanged.

Generated manifests preserve the effective profile/config identities,
overrides, initialization and history. Traces identify instantaneous selected
APL, target capacity and endpoint capacity in nits, with **D under P** output
and state values. Shared-exposure previews never normalize individual frames.
Capacity timing is separate from the existing pixel-response tau. The model
holds each updated endpoint capacity constant for that tick's temporal
exposure; this is a P approximation, not continuous within-tick evolution.
Full checkpoints retain exact scalar/array representations and profile,
evolution, target-map, angle and geometry identities. Resume preserves the
original initialization provenance; restoring capacity alone is only partial
initialization. Unknown elapsed-time gaps and mismatched histories reject.

Active dynamics replace the HDR capacity once and reject nonzero legacy APL
smoothing, backlight tracking, weighted-nit power limits and every M9 schema-1
`.fit.json` composition. A future fitted dynamics dataset needs a new schema,
consistent whole-sequence drive units and matched timed history; no v1 fit
migration or measured-device claim is provided here.

## Block motion config and validation schema version 1 (M14)

[`motion_block_synthetic_v1.json`](../research/measurements/motion_block_synthetic_v1.json)
records `kind: block_motion_proxy_v1`, integer `schema_version: 1`,
`evidence: P`, `parameter_status: placeholder`, a synthetic source locator and
`sample: NR`. `parameters` covers every `BlockMotionConfig` field with an exact
`value`, `evidence: P` and unit. The provenance check rejects missing/unknown
fields, invalid types, nonfinite or unsupported values, duplicate keys and a
stale bundled default snapshot. Custom `--motion-config` files use the same
schema and admission checks; their values are saved in the motion sidecar.
The complete `unavailable` ledger retains measured thresholds, vendor
algorithm, calibrated profile fitting and measured latency as `NR`.

The declared P budget caps estimation at 320×180 without upscaling, with 8/16
estimation-pixel blocks, a factor-two pyramid, coarse and refinement search
radii and fractional refinement steps. Matching divides linear BT.709 luma by
one fixed reference in nits, independent of each frame's peak. Histograms clip
normalized luma to [0, 1]; SAD uses the unclipped values. SAD, texture,
appearance-only distinct-match margin and forward/backward consistency feed
confidence. Vectors are converted to output raster pixels per source interval.
The confidence threshold and re-enabling margin, whole-frame fallback fraction,
cut histogram/SAD/changed-area gates, exposure-change correlation gate, splat
support and collision thresholds are all explicit P settings. Visibility is
separate from texture/match confidence. Ambiguous collisions and holes hold the
left source; normalized splat accumulation does not establish depth order.

Enabled MCI motion manifests use schema 2 and embed the versioned config,
source/profile hashes, domains, independent rational source/output PTS,
estimation scale, assumed adjacent-frame lookahead, fallback reason fractions
and per-pair detector/confidence summaries. `--motion-debug` writes block-vector,
confidence, visibility and reason maps, plus per-tick fallback masks/reasons.
Cuts clear confidence history and skip matching; the new shot never enters
reconstructed content before its PTS. Physical panel and load histories remain
continuous. Static pairs and exact source endpoints retain their original
content. Phase-1 off/repeat/analytic manifests remain schema 1 with their
original fields and exact output bytes.

[`motion_validation_synthetic_v1.json`](../research/measurements/motion_validation_synthetic_v1.json)
is a separate P-only protocol: seed, raster, rational rates, clip length,
shared preview exposure, synthetic textures/colors/geometry, layer velocities,
cut/flash placement and region/trajectory metric parameters. It retains named-TV
calibration, vendor algorithms, perceptual soap-opera scale and measured
artifact distributions as `NR`. The provenance command uses the experiment's
strict protocol validator. It never changes the M4 report schema or TV YAMLs.
Generated `motion-validation.json` and per-fixture PTS traces save analytic
intermediate truth, pre-display linear-nit results, hashes, interior/boundary/
disoccluded masks, actual rendered-marker trajectory error, separate vector
endpoint error, fallback fractions/reasons and temporal switching counts.
Errors and timing are D calculations under the declared P experiment.
Short-clip previews share one fixed exposure, so flashes remain visible.
