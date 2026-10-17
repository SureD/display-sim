# M11 OLED capacity attack/release: research and implementation design

Design completed **2026-10-17** on `codex/m11-oled-dynamics`. This fulfills
[M6 §8, handoff item 5](m6-profile-wiring.md#8-implementation-handoff-and-remaining-nr-data).
**Research/design only:** no runtime, tests, profile YAMLs, sidecars or saved M4
reports change in this milestone. Implementation remains future work.

The proposed optional model filters **allowed HDR capacity in nits**, using
separate attack and release e-fold times. It replaces the capacity selected for
the existing HDR shoulder. It defaults **off**, preserves the current path
exactly, and initially rejects combination with existing M9 fitted drives.
No measured dynamics preset is available for either generic OLED.

Evidence follows [M6](m6-profile-wiring.md) and
[PROVENANCE](../docs/PROVENANCE.md): **M** = published measurement on a named
specimen under recorded conditions; **D** = calculation from stated inputs;
**P** = proposed model, synthetic setting, interpolation or fitting choice;
**NR** = unverified numerical reference, unknown condition or unidentified
parameter. NR is not zero. Use `not_applicable` for an inapplicable mechanism.
All new interfaces, policies, equations and experiment settings below are
**P**; their calculated states, times and outputs are **D under that P model**.
Source measurements retain M without transferring that status to a generic
profile or inferred time constant.

## 1. Current implementation and compatibility boundary

Read with [README](../README.md), [STATUS](../docs/STATUS.md),
[PLAN](../docs/PLAN.md), [panel technologies](01-panel-tech.md),
[M3 HDR/ABL](m3-hdr-abl-params.md), [M5 fidelity](m5-fidelity.md), and
[M6 §5–6](m6-profile-wiring.md#5-oled-abl-attack-and-release). Current code,
rather than older skeleton descriptions in M3/M5, defines the baseline:

1. [Pipeline.prepare_content](../sim/pipeline.py) decodes to linear nits and
   processes spatially, without advancing any display history.
2. [display_content](../sim/pipeline.py) measures demand APL after processing,
   calls [smooth_apl](../sim/load.py), computes optional backlight derating,
   then runs backlight and panel stages.
3. [effective_peak](../sim/stages/tonemap.py) selects smoothed demand APL if
   `hdr.abl_source=demand`, or the current **post-panel, pre-HDR** picture's
   APL if `emitted`. Emitted here does not mean the previous final output.
4. One soft shoulder and peak-cube color projection use that capacity. The
   optional weighted-channel-nit gain follows. Ambient reflection and the
   separate pixel-response/BFI/exposure stage then produce the frame.

[LoadState.apl_nits](../sim/load.py) is an APL state, initially `None`.
The first frame is settled; `abl_response_ms` supplies one symmetric e-fold
time. With emitted APL and tracking zero, that smoother has no influence on
the OLED HDR threshold. It is not already a capacity attack/release model.

The current [WOLED](../sim/profiles/generic_woled.yaml) and
[QD-OLED](../sim/profiles/generic_qdoled.yaml) values, including effective
dataclass defaults, are **P placeholders**:

| Existing quantity | WOLED | QD-OLED | Meaning |
|---|---:|---:|---|
| HDR small-window capacity P0 / nits | 850 | 1100 | Synthetic parameter, not a measured onset peak |
| HDR full-load capacity F / nits | 170 | 199 | Synthetic asymptote parameter, not a timed sustained measurement |
| Capacity shape gamma / dimensionless | 2.4 | 1 | Synthetic curve shape, not an electrical exponent |
| ABL source | emitted | emitted | Effective default from HdrParams |
| Legacy APL tau / ms | 0 | 0 | Instantaneous compatibility setting |
| Reference override / nits | 0 | 0 | Sentinel: use P0; not a zero-nit reference |
| Backlight tracking / fraction | 0 | 0 | Disabled |
| Weighted-nit budget | 0 | 0 | Disabled; not measured watts |
| Pixel-response tau / ms | 0.2 | 0.1 | Separate P pixel lag; never an ABL tau |

The [WOLED provenance](../sim/profiles/generic_woled.provenance.yaml) and
[QD-OLED provenance](../sim/profiles/generic_qdoled.provenance.yaml) preserve
named measurements separately from those settings. The two
[WOLED angular](../sim/profiles/generic_woled.angular.yaml) /
[QD-OLED angular](../sim/profiles/generic_qdoled.angular.yaml) records contain
P angular gains, with measured spectra/fits NR; they supply no dynamics data.
The panel's WRGB `min(R,G,B)` mosaic is an energy-preserving geometric
illustration, not measured RGBW current allocation.

## 2. Public evidence and unavailable constants

Sources checked for this design are listed with their actual support. No
source below identifies an attack/release pair for the C2/S95B records.

| Source and locator | Available evidence | Limit for M11 |
|---|---|---|
| [TFTCentral LG 42C2 review](https://tftcentral.co.uk/reviews/lg-oled-42c2), HDR Standard / [original table](https://tftcentral.co.uk/wp-content/uploads/2022/04/HDR_standard_3.png) | **M:** DTM off, 717 nits at the reported small windows through 10%; M5/M8 preserve 396/243/192/152 nits at 25/50/75/100%. | HTML rechecked; detailed nodes inherit M5's image transcription, as the image could not be fetched in this pass. Requested amplitude, dwell, prior history, temperature and timed sustained trace remain **NR**. |
| [Sound & Vision S95B test bench](https://www.soundandvision.com/content/samsung-65-s95b-quantum-dot-oled-4k-tv-review-test-bench), HDR varying-window paragraph | **M:** 65-inch S95B, HDR10 Filmmaker; rounded 1000-nit 1–10% plateau, 600/300/200 nits at 25/50/100%. | Independent 2/5/75% readings and timing remain **NR**. A rounded plateau does not create measured nodes. |
| [DisplayMate 2015 comparison](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm), Brightness and Contrast, LG 65EG9600 factory Cinema | **M:** publisher-labeled 25/50/100% APL gives 242/157/91 nits. | Different specimen, SDR-era mode and APL axis; no verified time constants. Do not convert this axis to requested absolute APL without its missing reference. |
| [RTINGS HDR brightness methodology](https://www.rtings.com/tv/tests/picture-quality/hdr-peak-brightness), peak/sustained windows and ABL sections | Publisher protocol separates initial peak from later sustained readings; ABL score summarizes variation across sustained window sizes. | The current description uses an imprecise seconds-scale dwell. This score is not a tau; no precise duration or C2/S95B dynamics constant is imported. |
| [LG image-retention support](https://www.lg.com/us/support/help-library/troubleshooting-image-burn-in-on-an-lg-oled-tv-CT10000018-20152745607830), logo brightness adjustment | Manufacturer describes detection and dimming of static logos. | Qualitative controller evidence; detection thresholds, delay, gain, release and firmware policy are **NR**. |
| [Samsung OLED G6 manufacturer page](https://www.samsung.com/ca/monitors/gaming/odyssey-oled-g6-g60sf-27-inch-500hz-oled-qhd-ls27fg600snxza/), thermal modulation and logo/taskbar detection | Manufacturer distinguishes temperature-related brightness control from fixed-image detection. | A monitor example, not a TV calibration; thermal mapping, coefficients and controller timing are **NR**. |

A relevant primary experiment is
[Dimigen & Stein (2026), Methods and ABL results](https://pmc.ncbi.nlm.nih.gov/articles/PMC13161341/)
([DOI](https://doi.org/10.3758/s13428-026-03034-9)). Their ASUS PG27AQDM
WOLED tests used SDR Racing, MCM104 firmware and 240 Hz, with protection
features disabled. Published protocol conditions included 10-second windows
and separate onset versus 3–5-second readings. **M:** small white-on-black
patches (at most 10% area) lost up to about 5% over approximately 500 ms
even when settings prevented ABL; the
reported decay was linear to a plateau, not an exponential ABL fit. They
also observed spatial temperature artifacts after prolonged patterns.
These results motivate confound checks, but supply neither TV's ABL tau.

The parameter ledger for implementation is explicit:

| Quantity | Evidence / proposed value | Admission rule |
|---|---|---|
| Generic/C2/S95B measured attack and release taus / ms | **NR** for both technologies | No measured preset or inferred zero |
| Demonstration attack / release / ms | **P: 100 / 1000**, explicit experiment inputs only | Unmeasured example, not runtime defaults |
| Instantaneous-tau option / ms | **P: 0**, per direction | Mathematical bypass, not a measured fast controller |
| Prior exploration ranges from M3 | **P:** load 10–1000 ms; thermal 1–100 s | Historical unmeasured priors; not published bounds or new model parameters |
| Thermal state, heat capacity, equilibrium law, tau, temperature derating | **NR** | No thermal controller in this model |
| Static-image detection/delay/dimming/recovery constants | **NR** | No static-image controller in this model |
| RGBW allocation, channel maxima/spectra and color-dependent load fit | **NR** | Existing mosaic cannot fill them |
| Watt coefficients/exponents, idle watts and electrical budget | **NR** | Weighted nits cannot be relabeled W |
| Matched timed sustained endpoints / traces for C2/S95B | **NR** | A full-field peak node does not fill these cells |
| Calibrated capacity-target map for either generic profile | **NR** | Existing static maps remain P |
| State update, initialization policy, numerical bounds and validation rules | **P**, defined below | Computed results are D, with P assumptions retained |

## 3. State domain and discrete-time model

### Target capacity

Let `R_k` be the prepared requested RGB image in linear BT.709 nits for
display tick k. Let `E_k` be this tick's panel-stage RGB, including its fixed
emitter clip, PSF, matrix/mosaic and selected angular terms, but before HDR,
ambient reflection or temporal response. Choose the same source named by
`hdr.abl_source`:

~~~text
A_k = mean(Y(R_k))       if source = demand
A_k = mean(Y(E_k))       if source = emitted
P_ref = positive abl_reference_nits, otherwise P0 when the override is 0
a_k = clip(A_k / P_ref, 0, 1)
C_target,k = F + (P0 - F) * (1 - a_k)^gamma
~~~

This is the existing **P** static target map, evaluated on the instantaneous
selected picture. APL is in nits, normalized load a is dimensionless, and
`C_target` is a nit capacity. Use [demand_apl/abl_capacity](../sim/load.py)
for the existing semantics, with no legacy APL filtering in the active mode.
Require finite nonnegative APL and reject negative/nonfinite reference
overrides; only the exact zero sentinel selects P0.
For a neutral window, `A_request=f_actual*requested_level_nits` before
processing; area alone and mean PQ code are not absolute APL.

Demand remains the explicit source-domain experiment choice; emitted remains
the shipped compatibility choice. The new model never switches between them
automatically. Emitted load is a pre-HDR proxy, not feedback from its limited
output and not a measured current. With M10 active, its gains influence
emitted APL; demand APL does not include those gains. Record angle/model and
load source, and begin identification on-axis.

### Capacity state and attack/release

The only new physical-model state is `C_k`, the **available HDR shoulder
capacity in nits at the start of tick k**. It is a global scalar, not emitted
luminance, normalized gain, battery energy, watts, temperature, pixel lag or
an APL estimate. Model support is `0 < F <= C_k <= P0` with positive finite
P0/reference and positive finite gamma.

For tick duration `dt_k > 0` and finite nonnegative e-fold constants
`tau_attack_ms` and `tau_release_ms`:

~~~text
if C_target,k < C_k: tau = tau_attack_ms     # higher load reduces capacity
if C_target,k > C_k: tau = tau_release_ms    # lower load restores capacity
if C_target,k == C_k: C_next = C_k           # equality, no drift
otherwise:
    if tau == 0: C_next = C_target,k  # direct assignment, exact bypass
    else:
        alpha = -expm1(-dt_k / tau)
        C_next = C_k + alpha * (C_target,k - C_k)
C_(k+1) = C_next
~~~

For positive tau, the equivalent closed form is
`C_next=C_target+(C_k-C_target)*exp(-dt_k/tau)`. Milliseconds are used for
both dt and tau; convert to seconds together if an implementation uses
seconds internally. **P numerical choice:** retain the scalar in float64;
keep output images float32 as today. Clamp only roundoff at the declared
capacity bounds after validating inputs, never conceal an invalid state.

For a constant target, the exact state approaches it monotonically without
overshoot. **D:** one tau removes `1-exp(-1)` (about 63.2%) of the initial
capacity error; a capacity-domain 10–90% transition takes `ln(9)*tau`.
This is not a conversion from measured output-luminance 10–90% time: the
target map, shoulder, color projection and pixel response are nonlinear or
additional stages. Smoothing APL, capacity and output gain are different
models. Only capacity smoothing is proposed here.

### Update clock and output sampling

Update exactly once in `Pipeline.display_content` per displayed tick,
including repeated source pictures. Use its explicit `frame_time_ms` when
supplied; otherwise use the profile's existing interval. `run_linear` and
`run` each cause one such update. Preparing, decoding, computing a residual
from already-rendered outputs and inspecting a state must not advance it.
Each independent fitting forward replay still advances its own initialized
history; residual calculation adds no display update.

Active mode leaves the legacy `LoadState.apl_nits` untouched and unused.
The selected instantaneous APL is trace data, not a second smoothed state.
Do not switch an existing Pipeline between active and off modes mid-history.

[M7 repeat/analytic sequences](../sim/sequence.py) supply output-tick time.
Use that time, not source FPS or the number of unique pictures. MEMC-off
currently uses profile time per input picture even when source PTS exist;
do not silently change that contract. The new experiment runner must pass
explicit tick durations and save PTS. Reject nonpositive/nonfinite dt, or
missing elapsed-time intervals in a history; wall-clock execution speed is
irrelevant. Declared cuts preserve capacity and panel history.

**P exposure convention:** select `C_next` as this tick's HDR peak and hold
that scalar constant while the existing temporal stage renders this tick.
The updated state belongs to the tick's right boundary; no second update
occurs in `temporal.integration_samples` or a BFI pulse. This is an endpoint
approximation to within-tick capacity evolution. It does not simulate a
continuous controller or thermal response during a pulse.

**D property:** subdividing a duration with an unchanged target produces the
same final capacity within floating-point tolerance. Rendered frame exposure
need not be identical across subdivisions/refresh rates. If experiments
need faster dynamics, raise the declared simulation tick rate and test
convergence. A future time-resolved capacity waveform would require a new
exposure contract rather than multiplying dt by the number of temporal samples.

## 4. Initialization and prior history

Initialization is explicit metadata and does not identify a TV's actual
power-on or thermal condition.

| P initialization policy | Capacity at the first tick boundary | Panel history and interpretation |
|---|---|---|
| `cold`, proposed active-mode default | `C_0=P0`, the black-load equilibrium of this model | P fully available capacity assumption. With no panel history, the existing first-frame settled pixel convention still applies; this alone is not a complete dark-to-bright onset experiment. |
| `settled_first_tick` | Compute the first instantaneous target and set `C_0=C_target,0` before the first update | P still-image convention analogous to legacy first-frame settling. It deliberately erases the first capacity transient. |
| `explicit` | Caller supplies finite `C_0` in `[F,P0]` | P controlled initial capacity; it does not infer prior patterns, temperature or pixel state. |
| `resume` | Restore a validated tick-boundary checkpoint | Exact continuation requires complete display history, not just C. |

The active default is a deliberate refinement of M6's tentative
`settled_first_frame` proposal: a freshly enabled sequence exposes capacity
attack from P0. Ordinary/off rendering keeps its existing initialization.
Reports must distinguish these policies.

**Black pre-roll:** actually display black ticks through the same Pipeline
that will render the load sequence. This initializes pixel history and
allows capacity to recover with the release tau. For black, target capacity
is P0, while emission is zero with zero ambient and after pixel lag decays.
Continuing from a loaded state with positive release tau gives
`C_end=P0+(C_start-P0)*exp(-T_black/tau_release)` (**D**).
With release tau zero, the first positive-duration black tick sets C to P0
directly; no division by zero or extra reset is needed.
Finite black pre-roll need not recover exactly to P0. In the **P** example,
5 seconds of black with a 1000-ms release leaves **D** about 0.674% of the
initial capacity deficit. One black tick, as required by M9, is not a
universal capacity reset or laboratory thermal warm-up.

For prior history, either replay the complete ordered stimulus/duration
history through one Pipeline, or restore a checkpoint at a tick boundary.
The proposed versioned checkpoint contains model/evolution and effective
profile hashes, target-map identity, load-source/reference semantics, angle
config/parameters, geometry/dtype, elapsed simulation time, next tick index,
C, `LoadState.apl_nits` and `TemporalState.previous`. Retain exact float
representations/array bytes for reproducible continuation, plus history and
source hashes. Restoring C alone is a labeled partial initialization, never
an assertion of image-output parity.

The evolution fingerprint covers model/version, taus and parameter status,
alongside the separate profile/target/angle identities. Exclude one-shot
initialization and CLI state-file options from this fingerprint. Preserve
the original initialization policy/value and prehistory as provenance;
`initial=resume` selects restoration without changing the evolution hash.
Thus a checkpoint created under cold initialization can resume the same
dynamics without pretending that resume is a new physical controller.

Validate all identities and shapes before mutating live state. Reject stale,
out-of-range/nonfinite or mismatched checkpoints. A timestamp gap must be
filled by explicit held content or black ticks, or rejected; never advance
through an unknown gap. An explicit restart creates a fresh model history.
Changing config/profile/target domain mid-history requires a restart or a
future explicit state-conversion contract; it must not silently rescale C.

## 5. One capacity owner: static ABL and M9 precedence

The new capacity substitutes for `effective_peak` in the existing shoulder,
with one peak-cube projection, then the usual ambient and temporal stages.
The panel's existing fixed emitter peak clip and optical operations remain
upstream. They already form part of the forward model.

Do not apply `min(C_target,C_next)`: that would remove the proposed attack
transient. During attack, capacity can intentionally exceed its settled
target while remaining bounded by P0. Do not run a static shoulder followed
by a dynamic shoulder, multiply output by `C_next/C_target`, smooth a
measured target curve, or derive next load from final limited RGB.

All admission checks occur before any tick/history advances:

| Requested configuration | P rule / precedence |
|---|---|
| Dynamics omitted or `off` | Execute the current pipeline and history mutations exactly; no capacity allocation, data discovery, arithmetic or profile mutation. |
| Active capacity mode with a WOLED/QD-OLED profile, ABL enabled, soft_clip | Instantaneous selected APL → existing static target function → capacity update → one HDR shoulder with explicit capacity override. |
| Active mode with nonzero `hdr.abl_response_ms` | Reject; two smoothing domains cannot own the same transient. Do not silently zero the field. |
| Active mode with nonzero `abl_backlight_tracking` or `abl_power_budget_nits` | Reject in the first implementation. These existing P limits need a separately identified composition before dynamics can use them. Off mode keeps them exactly as today. |
| Active mode with ABL disabled, unsupported panel technology or tone mapper | Reject with the relevant conflict; never silently activate or ignore ABL. |
| Active mode with missing tau(s), invalid bounds or unknown source | Reject. Zero tau is allowed only when explicitly provided. |
| Any existing M9 schema-1 `.fit.json` + active dynamics | Reject, including exploratory use. Neither request takes precedence by silently disabling the other. |
| Dynamics off + existing M9 fit/fitting | Retain M9 loading, validation, timing, scale and output behavior exactly. |
| State input plus a competing initialization value/policy | Reject; resume is the sole initialization owner. |

[M9](../sim/window_replay.py) fits independent **P**
`per_window_normalized_drive_v1` scalars against **final** pipeline hold
outputs. The scale multiplies processed internal drive, backlight peak/floor,
HDR peak/full-field/reference/power budget and temporal ceiling; zero
sentinels remain zero. Optical shapes, dimensionless ABL settings and time
constants remain unchanged. Each trial starts fresh, then shares history
across black pre-roll, settling and hold. Its target enters only the residual,
never another limit. These semantics must stay intact.

A saved fit encodes its baseline and experiment timing but no new capacity
model, initialization or prior capacity state. Its independent window
scales cannot be interpolated or switched as area changes during a shared
history: doing so changes drive and capacity units between ticks and invents
an arbitrary-content model. Even if a particular static case happens to
match, a v1 drive scale is not evidence for peak/sustained separation or tau.
Do not copy measured C2/S95B output nodes into P0/F and then limit a fitted
output again.

A future dynamics-aware fitting milestone needs a **new model/schema and
dataset ID**, known matched stimulus/history/timing, full configuration and
state fingerprints, and a new fit of whole traces through the single
forward limiter. Define a consistent drive normalization over the sequence
before jointly fitting target-map and dynamics parameters; independent
per-window drives remain unsuitable. Measured traces are M, estimates and
fitting choices P, calculated residuals D, missing conditions NR. Assess
identifiability and withheld transitions; low static residuals cannot
identify attack/release. There is no automatic v1 migration.

Keep new runtime dataclasses **outside TVProfile/HdrParams**. M9 fingerprints
`asdict(profile)`, and baseline sidecars cover every effective profile leaf.
Adding even disabled HDR fields would change fingerprints and the provenance
leaf set. Separate optional configuration follows M10's established pattern
and preserves existing fit identities and sidecar coverage.

## 6. History-aware experiment and acquisition plan

Use a separate runner and report, with a **single Pipeline per complete
trial**, including pre-roll. Reinitialize only between explicitly independent
trials. Keep [the M4 harness](../sim/validate.py), its settings and saved
reports unchanged.

M4 uses fresh settled pipelines for static patterns. Its moving-edge helper
carries pixel TemporalState but recreates Pipeline/LoadState each frame.
It therefore cannot validate ABL history. Its windows/ANSI request PQ code
1 (10000 nits), with nominal windows 1/2/5/10/25/50/100% at the default
384×216 raster; it has no 75% case. These are existing **P** stimulus choices,
not source conditions for C2/S95B. Historical M4 QD-OLED zero optical halo
also predates M5's emitted PSF; preserve the M6 §6 parity exception.

### Reproducible synthetic demonstration

All settings in this paragraph/table are **P**, not proposed measured
constants: use requested neutral-white 1000 nits, float PQ/BT.709, a 384×216
raster, 60-Hz display ticks, attack 100 ms, release 1000 ms, `cold`
initialization, on-axis viewing, zero ambient, no BFI/OD/pursuit, and the
existing pixel-response and optical settings. **D:** tick duration is
1000/60 ms. Use the actual processed APL and rasterized bounds; record
nominal/actual areas separately. Run demand and emitted source variants as
separate trials with distinct IDs, keeping the static target map otherwise
unchanged. Enabling demand is a runtime experimental override, not a YAML edit.

| P sequence | P timing | Purpose |
|---|---|---|
| Black → 1% → 100% → 1% → black | 5 / 5 / 10 / 10 / 5 s | Establish small-window baseline, load attack, sustained output and recovery on the same bright probe |
| Black → 10% → 100% → 10% | 5 / 5 / 10 / 10 s | Check load dependence of the same model and release observable |
| Black → 100% → black → 1% | 5 / 10 / varied black gap / 5 s; gaps 0, 0.1, 1, 5 s | Measure recovery after a load drop, with black-only capacity evolution checked in state telemetry |
| Small → large → small step pairs | Windows 1/2/5/10/25/50/75/100%, fixed amplitude; 10-s plateaus | Separate target-map shape from history and retain the missing M4 area |
| Identical final 1% probe following black versus loaded history | Same probe duration and amplitude; histories above | Demonstrate history dependence without changing the final stimulus |

The last two rows describe a trial family: store the exact selected order and
durations in each manifest. A zero-duration black gap means adjacent ticks,
not a zero-duration update. Black alone cannot reveal luminance recovery;
use the fixed small bright window afterward. With long release, the window
can brighten over time even at constant final demand.

Additional **P** stress/holdout choices: requested levels 100/400/1000 nits;
equal absolute APL from differing area/amplitude pairs; mixed-color/RGB
patches and relocated windows; repeat the identical content timeline at
120 Hz as a discretization comparison. The model predicts identical C for
identical selected-APL histories, not necessarily identical images. Colored
trials test this proxy's limits without inventing RGBW/watt parameters.
Vary temporal integration sample count without changing capacity dt.
Include cuts and repeated/analytic output ticks in timing tests.

### Outputs, metrics and real measurement

Store a versioned protocol/manifest and per-tick trace outside the profile
tree: source/processing/drive identities, rational PTS and dt, nominal and
actual window bounds/areas, requested and processed APL, selected load
domain/APL, P_ref, a, C_target, C_before/C_after, attack/release/equal branch,
taus, center RGB/Y before and after temporal rendering, and full mean Y.
Retain linear-nit arrays at declared checkpoints, all state checkpoints,
code/profile/config hashes and every P override/NR condition. Preview all
frames with one fixed exposure; do not reuse M4's per-image normalization.

Report distinct quantities with declared intervals:

- **Peak:** maximum center Y over a specified onset/hold interval, with the
  timestamp of the maximum. M9's `max_center_over_hold_frame_outputs` remains
  a peak metric with its original definition.
- **Sustained:** mean/minimum/range of center Y over a declared late interval,
  plus final C and remaining slope. **P example:** the last 1 second of a
  10-second plateau. If it is still changing, call it late-interval output,
  not equilibrium or a measured sustained rating.
- **Dynamics:** capacity-domain e-fold/10–90% times from state telemetry
  separately from output-domain transition/recovery times. Save entire
  traces; do not equate panel GtG, ABL score and a fitted capacity tau.
- **History/release:** compare equal final probes after matched versus
  different prehistories, and check recovery after black gaps independently
  of the onset pixel transition.

For acquisition, record specimen/size/panel generation, firmware, picture
and input mode, processing/protection settings, encoding/primaries/codes,
requested luminance, geometry/position, refresh/VRR, warm-up and exact prior
patterns, ambient/viewing geometry, meter/photodiode calibration, sampling
rate and integration, timestamps and temperature. Unknowns stay NR.
Use synchronized fast photodiode traces with an absolute-luminance meter;
choose instrument bandwidth from the transition to be resolved and report
its limit rather than inventing a subframe time constant.

**P acquisition checkpoints:** onset and 0.1/1/10/60 seconds, with continuous
traces where possible, repeated load increases and decreases, varied rest
intervals, and counterbalanced trial order. These are requested observations,
not sourced device time constants. A scalar peak or late reading cannot
identify two taus. Hold out area/amplitude pairs and whole histories, and
repeat at the same documented temperature. Compare moving versus static
patterns at matched load and relocate probes to reveal local/static-image
effects; failure of one global exponential calls for a separate mechanism,
not an invented thermal coefficient or a technology-wide preset.

## 7. Concrete implementation handoff (future milestone)

The following names and flags are **P proposed interfaces**, not commands
available after this document.

| File | Proposed change |
|---|---|
| `sim/abl_dynamics.py` (new) | Frozen ABLDynamicsConfig, mutable ABLCapacityState, validation, instantaneous source selection/target wrapper, stable capacity update, trace records and versioned checkpoint validation. |
| `sim/pipeline.py` | Keyword-only optional `abl_dynamics` and `capacity_state`. Separate off branch retains every existing operation and history update. Active branch validates before mutation, bypasses legacy APL smoothing, and updates one capacity after the panel input for both source domains is available. |
| `sim/stages/tonemap.py` | Optional explicit `capacity_nits` input. With no override, retain current effective_peak call/arithmetic. With a validated override, use it directly for the existing shoulder/projection; do not recompute or take the minimum with static ABL. |
| `sim/oled_dynamics_experiment.py` (new) | Read a versioned protocol, validate all conditions/conflicts before execution, render all ticks in one Pipeline, write traces/linear arrays/manifest and optional checkpoints exclusively into a separate output directory. |
| `sim/cli.py` | Dispatch opt-in `oled-dynamics` subcommand; leave ordinary still/validate/gallery/motion/fit-windows defaults unchanged. |
| `sim/window_replay.py` | Preserve v1 fit schema/model/fingerprints and replay arithmetic. Expose no active-dynamics option; reject any attempted v1 composition in shared dispatch/API validation. |
| `tests/test_abl_dynamics.py`, `tests/test_oled_dynamics_experiment.py` (new), parity tests | Implement the acceptance cases below; no golden regeneration to accommodate off-path drift. |
| Documentation/provenance | Document experimental config and its P/NR ledger. A later dynamics dataset uses its own versioned artifact outside runtime profiles; do not add HdrParams leaves or reinterpret current sidecars. |

Suggested dataclass contract:

~~~text
ABLDynamicsConfig (frozen):
    model = "off"                  # P default; alternative capacity_attack_release_v1
    attack_ms = None              # absent, not zero; explicit finite >=0 when active
    release_ms = None             # same
    initial = "cold"              # P active-mode policy from section 4
    initial_capacity_nits = None  # required only with explicit
    parameter_status = "placeholder"  # P first implementation; no measured preset

ABLCapacityState:
    capacity_nits = None          # uninitialized; never interpreted as 0 nits
    elapsed_ms = 0                # D simulation clock after initialization
    ticks = 0                     # D number of successful display updates
~~~

Off mode must not allocate/update capacity history or discover artifacts.
Reject explicitly supplied dynamic CLI options with off mode; dataclass
initialization defaults are inert while off. Also reject nonfinite/negative taus,
unsupported model names, invalid initializer combinations, and stale state
before rendering. Domain/reference remain in existing HDR settings and are
fingerprinted; a runner override uses a copied profile. Checkpoints add
identity fields and full histories around the minimal state above. Trace
records carry evidence per field; they do not label synthetic outputs M.

Proposed flags: `--abl-dynamics {off,capacity_attack_release_v1}`
(default `off`), `--abl-attack-ms`, `--abl-release-ms`,
`--abl-initial {cold,settled_first_tick,explicit,resume}`,
`--abl-initial-capacity-nits`, `--state-in`, `--state-out`,
`--abl-source {demand,emitted}` (otherwise inherit),
`--protocol`, `--output-fps` and `--out`. Both taus are required with
active mode; there are no inferred numerical defaults. Require protocol
durations to be whole output ticks and preserve rational PTS, following M9/M7
timing conventions. Require resume with state-in; reject multiple
initialization owners. Output paths must not overwrite profiles, fits or
existing experiment artifacts.

An illustrative future command, all numerical choices **P**:

~~~sh
python3 -m sim oled-dynamics --profile generic_woled \
  --abl-dynamics capacity_attack_release_v1 \
  --abl-attack-ms 100 --abl-release-ms 1000 --abl-initial cold \
  --abl-source demand --protocol research/measurements/example-steps.json \
  --output-fps 60 --out reports/oled-dynamics/example
~~~

The example protocol path is proposed and is not created by M11. Do not add
these options to the settled M4 harness. Public API callers may use the
new runtime config with Pipeline or existing sequence scheduling, but must
retain a single pipeline and an explicit physical display clock.

### Acceptance tests and parity gate

1. **Numerics:** closed-form constant-target attack/release, equality, each
   direction at zero tau, bounds/monotonicity, extreme positive dt/tau and
   nonfinite/negative inputs. **P scalar comparison tolerance:** relative
   1e-12, absolute 1e-9 nits. Test split-duration final C under fixed target;
   do not require identical rendered exposure for different tick sizes.
2. **State/initialization:** distinguish cold and settled-first onset; black
   pre-roll recovery matches the analytic state; explicit C bounds; complete
   replay versus full-checkpoint continuation agrees byte-for-byte on the
   same runtime. Capacity-only initialization must not claim that parity.
   Reject mismatched profile/config/angle/geometry/model and unknown gaps
   without partially advancing histories.
3. **One limiter:** inspect one target/update/shoulder per displayed tick.
   Use a finite-attack high-load step where C_next is above C_target so an
   accidental min/static second pass fails. For explicit zero taus, compare
   both source domains with the legacy zero-smoothing/zero-tracking/zero-power
   forward outputs and panel state on the same timeline. Active mode leaves
   legacy LoadState unused; exact load-history equality belongs to the off
   parity tests. No target output enters rendering.
4. **Clock ownership:** preparation changes no state; repeated and analytic
   display ticks each update once using output dt; cuts retain history;
   changing temporal integration samples does not change C; no elapsed
   time is inferred from wall clock or MEMC-off source PTS.
5. **History behavior:** run the section 6 sequences; verify different
   prehistories affect the same probe, long holds approach their targets,
   black gaps recover capacity and the small-window release brightens.
   Account for independent pixel lag when asserting output monotonicity.
6. **Conflicts/fit identity:** reject the combinations in section 5 before
   mutation. Exercise v1 M9 fitting/save/load/replay unchanged; verify
   profile hashes, leaf coverage, source NR nodes and per-window drive
   separation survive. Never accept active dynamics plus a v1 fit, including
   zero-tau or exploratory requests.
7. **Default/off goldens:** capture current-tree bytes/hashes before runtime
   work. Exercise omitted and explicit off through stills, MEMC-off,
   repeat/analytic motion, validation, default/angular galleries and M9
   replay, including panel/load histories and profile bytes. Repeat after an
   enabled dynamics experiment to catch shared-state contamination.
   Reuse [existing parity fixtures](../tests/test_memc_parity.py) and
   [M9 goldens](../tests/fixtures/window_replay_off_baseline.json); capture
   missing current M10 baselines before implementation. Use exact equality
   for the off path, not relaxed tolerances. Do not rewrite saved M4 artifacts.
8. **Review checks:** full pytest and provenance validation; render new
   traces with shared exposure and inspect onset/late/recovery intervals.
   Acceptance is synthetic model correctness and default parity; a measured
   device claim additionally needs matched acquisition, identifiable fits
   and held-out history results.

## 8. Scope and remaining risks

This model can express delayed approach to the existing P capacity curve,
including recovery after load drops. It cannot distinguish electrical
limiting, thermal drift, static-image detection, spatial heating or RGBW
power allocation from a scalar brightness trace. Even settled output retains
the static target-map assumptions and the upstream emitter/tone-map limits.
Measured time constants and those separate mechanisms remain NR.

Implementation must preserve the exact off branch, keep v1 M9 datasets
isolated, and label synthetic constants and endpoint exposure approximation.
Default parity means the pre-implementation current tree, with M6's
documented historical M4/QD-PSF exception retained. Design completion is
not runtime implementation or calibration completion.

