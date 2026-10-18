# M18 — Sub-frame response, emission and pursuit

Research date: 2026-10-18. This note precedes the M18 runtime design. It builds on
[the original temporal note](04-temporal.md), [M3's parameter definitions](m3-temporal-params.md),
[MEMC scheduling](m7-memc-motion.md), [OLED capacity ownership](m11-oled-dynamics.md)
and [M17 zone dynamics](m17-zone-temporal.md). Sources below were searched again
for M18; access restrictions and missing conditions remain explicit.

The useful extension is a history of **emitted light within each display tick**.
LC response, LED timing, OLED blanking and tracking-eye exposure have different
owners. A waveform sampled from a proposed model is not a measured TV waveform.
All shipped generic TV presets remain placeholders.

## Evidence grades and numeric scope

`M` means a publisher's measured specimen result under its stated conditions;
`D` means a calculation from declared inputs; `P` means a proposed model,
experimental setting or normative recommendation; `NR` means not reported or
not established for this simulator. Every parameter, threshold and numerical
example below is graded in its paragraph or table. Constants in equations and
unit conversions are **D mathematical definitions**. Source years, page/section
numbers, milestone names, patent identifiers and schema versions are locators,
not ungraded physical parameters. A published recommended-practice boundary is
labeled **P (normative)**, never M. None of the M examples is copied into a
runtime profile or asserted as a technology-wide bound.

## What the existing implementation establishes

Inspected before proposing the extension: `stages/temporal.py`, `sequence.py`
(`MotionConfig` and sequence scheduling), `pipeline.py`, `abl_dynamics.py`,
`zone_temporal.py`, `zone_history.py`, and the M17 report. The legacy temporal
stage filters final emitted RGB with a single exponential and optional short
boost, then applies a mean BFI/pursuit approximation. Its first frame is settled;
its persistent history is the unblurred endpoint. Its existing midpoint exposure
path samples an analytic emitted-RGB response inside a centered illuminated
interval. Those are useful **P** demonstrations, but they do not expose an LCD
transmission state multiplied by an independently timed LED waveform.

MEMC reconstructs content before the display tail and advances physical histories
once per output tick. M13 owns global OLED capacity; M17 owns bounded LCD zone
commands before optical spread/compensation. These tick-level histories should
not be advanced again for each new emission sample. M18 must have a separate
runtime configuration and explicit admission rules. The absent/off path must
retain the current arithmetic and legacy artifacts exactly.

## LC relaxation and response-time compensation

Liquid-crystal orientation changes under electric torque and elastic restoring
forces; viscosity, cell geometry, voltage endpoints and temperature affect the
trajectory. Rising optical luminance is not universally the field-on direction:
LCD mode and polarizer arrangement matter. Kumar, Biswas and Nguyen analyze a
first-order, gray-dependent response-time compensation model and the distinction
between over-driving and under-driving in
[their EUSIPCO paper](https://eurasip.org/Proceedings/Eusipco/Eusipco2005/defevent/html/abstract/a2003.htm).
The [indexed author-hosted PDF](https://www.ee.bilkent.edu.tr/~signal/defevent/papers/cr2003.pdf)
provided mechanism text in search; direct retrieval timed out. It is mechanism
evidence, not a fully acquired measurement dataset.

A defensible **P effective optical surrogate** is a bounded transmission state
`q`, a commanded transmission `u`, and separate declared e-fold times:

```text
q(t + dt) = u + (q(t) - u) exp(-dt / tau)
tau = tau_rise or tau_fall according to the declared optical direction
```

Use an analytic update, not an unstable Euler step. Explicit **P zero tau** means
instantaneous response; absent tau means **NR**, not zero. A small declared
start/target-level table can select the effective tau, with a specified
interpolation or nearest-cell rule and no extrapolation. Frozen transition-start
selection and continuously reselected tau are different models; choose and
version one. A native monotonic first-order step has **D**
`t10–90 = ln(9) tau ≈ 2.197225 tau`, while settling within **P 1%** of the full
transition amplitude takes **D** `ln(100) tau ≈ 4.605170 tau` from onset. An
asymptotic endpoint has no finite mathematical “100% response time.”

A **P two-stage** model can use a finite boost segment followed by target
relaxation. A separate **P two-pole** optical model could instead use fast and
slow exponential states and a declared mixture; it adds an unidentifiable degree
of freedom without matched traces. Two drive segments do not establish two
physical molecular relaxation modes. Temperature-dependent material simulation,
voltage-to-transmission response, channel differences, near-black transients and
real second-pole parameters remain **NR**.

Overdrive is a temporary alternate command selected from previous/target levels,
not an additive glow painted onto the final image. The patent
[US20080231624A1](https://patents.google.com/patent/US20080231624A1/en)
explicitly describes transition-indexed LUTs and temperature adaptation. The later
[US11488554B2](https://patents.google.com/patent/US11488554B2/en), description around
its response-curve figure and native-curve equations, describes a boost followed
by target relaxation and the trade-off between lag and overshoot/undershoot.
Its symbol named tau uses a response-time normalization; it must not be copied
as this note's e-fold tau. Patent examples are disclosed designs, not validation
of a generic panel or evidence that a retail TV implements a particular LUT.

For M18, a **P** LUT may return a normalized effective optical command for a
finite pulse, followed by `u`. The LUT axes, bounds, interpolation, diagonal
behavior, pulse duration and refresh support must be explicit. A boost exceeding
the final gray can reduce first-crossing response while leaving a brighter or
darker trail after the target is passed. This is inverse ghosting. Optical
transmission remains bounded: an effective optical LUT cannot reproduce every
voltage-driven rail transition. Do not invent negative light or extra unbounded
peak emission. Overshoot and settling should be reported together; a short
first-crossing time alone rewards an objectionable waveform.

## Hold, impulse emission and pursuit integration

An instantaneous state response still blurs when the image is held while the eye
tracks the moving object. [Kurita's SID study](https://sid.onlinelibrary.wiley.com/doi/10.1889/1.1832037)
uses a special CRT to investigate hold-type image degradation; only the
publisher's abstract was available here. [Becker's SID paper](https://www.display-messtechnik.de/fileadmin/template/main/docs/SID07-26.1.PDF)
compares moving-pattern imaging with stationary step/impulse methods and explains
why processing/lateral effects make the methods differ. It evaluates rising and
falling blurred edges separately. These mechanisms motivate a moving-pattern
experiment rather than deriving all motion claims from one gray-step number.

The IEEE ICME paper [Chan and Nguyen, LCD Motion Blur Modeling and Simulation](https://engineering.purdue.edu/ChanGroup/publication/C2010_Chan_Nguyen.pdf)
examines the display → tracking → temporal-filter chain and the assumptions
needed to exchange spatial averaging and temporal integration. Its author-hosted
PDF was search-indexed with the paper's text, but a direct fetch returned an
error; the full paper was not independently acquired. No numerical panel claim
is taken from it.

For declared **P** constant tracking velocity `v`, integrate emitted luminance in
tracking coordinates, after LC/backlight and OLED blanking:

```text
I_pursuit(x) = integral[L(x + v*t, t) w(t) dt] / integral[w(t) dt]
```

The coordinate sign must be verified against an ideal translating pattern.
Here `w` is a declared **P** camera exposure, not an empirically fitted model of
human vision. Integrate black intervals too; normalizing only by illuminated
time hides the brightness penalty. Retain emitted samples and unblurred state
separately. A synthetic pursuit image includes the declared interpolation,
spatial raster aperture and boundary policy; these can limit a very narrow
measured edge width.

For an ideal edge, constant emission over duration `T` gives **D** full blur
support `|v|T` and **D** 10–90 edge width `0.8|v|T`. The distinction matters:

| Declared input (P) | Full support (D) | 10–90 width (D) |
|---|---:|---:|
| Speed 960 px/s; full hold at 60 Hz | 16 px | 12.8 px |
| Speed 960 px/s; full hold at 120 Hz | 8 px | 6.4 px |
| Speed 960 px/s; rectangular pulse of 2 ms | 1.92 px | 1.536 px |

Report `edge_width_10_90_px / |v|` as a **D effective 10–90 blur time**, with the
exact formula. If reporting equivalent rectangular persistence, divide that
quantity by **D 0.8** and label the normalization. Neither is a complete motion
quality rating. Repeated source frames retain their source hold duration even
when display refresh is higher; pulsing the same source position repeatedly can
create multiple pursuit images. Interpolation changes the displayed motion
trajectory and must precede the same emission model.

[Blur Busters' pursuit-camera method](https://static.blurbusters.com/motion-tests/pursuit-camera/)
uses a moving camera and an embedded tracking-accuracy pattern. It is evidence
for controlling tracking/exposure, not permission to call a numerical reprojected
image a physical camera measurement. Real pursuit photos require matched speed,
exposure, focus, camera response, tracking verification and display settings;
these physical-camera conditions remain **NR** for this repository.

## LCD PWM, strobe phase, OLED BFI and brightness

LCD emission factors into actual backlight illumination and LC transmission.
M17's zone output supplies the former amplitude once per tick. A **P** rectangular
PWM carrier supplies declared frequency, duty and phase; a **P** frame-synchronous
strobe supplies a separate visible window. Their product is explicit when both
are admitted. DC dimming changes amplitude continuously instead of imposing an
on/off carrier; it is represented by a unity gate and a declared amplitude. This
does not imply that an actual “DC” display lacks refresh dips or other ripple.

[RTINGS' image-flicker method](https://www.rtings.com/monitor/tests/motion/image-flicker)
measures a white field at different brightness settings and keeps ordinary PWM
separate from optional strobing. [Its strobe method](https://www.rtings.com/monitor/tests/motion/black-frame-insertion)
checks pulse width, phase, amplitude and pursuit appearance. One frequency or
a panel's refresh specification does not determine duty, phase or modulation
depth; those missing waveform quantities remain **NR**.

A later strobe can conceal more of the LC transition, but its benefit depends on
settling and scanout. [Blur Busters' crosstalk analysis](https://blurbusters.com/faq/advanced-strobe-crosstalk-faq/)
distinguishes incomplete-transition contamination during a single flash from
multiple flashes of the same source frame. Real top/bottom crosstalk depends on
row update and backlight scan timing. A model that updates the whole panel
simultaneously can honestly show phase-dependent unsettled transmission and
residual images; it cannot claim a measured rolling crosstalk band. Scanout and
per-zone rolling strobe phase remain **NR** unless explicitly implemented and
declared as additional **P** assumptions.

OLED has no backlight to strobe. BFI here means gating emitted pixel light while
allowing the ungated drive/response state to evolve. It does not route “black”
through the same slow LCD transition. For **P** fixed pulse amplitude and a
settled patch, **D** mean emission is duty times continuous emission; **P 25%**
duty therefore costs **D 75%** mean brightness. Mean-preserving boosting needs a
separate current/headroom model and may conflict with OLED capacity. M13 retains
the sole capacity update on the ungated content demand; no second ABL feedback
loop is inferred from the reduced emission. Capacity recovery due to BFI and
thermal/current behavior remain **NR**. Ambient reflection is added outside the
emission gate and must not flash off with the backlight.

The following original measurements illustrate why settings/specimens must stay
separate from generic priors:

| Original evidence | Number and grade | Conditions and transfer limit |
|---|---|---|
| [RTINGS Samsung QN90C review](https://www.rtings.com/tv/reviews/samsung/qn90c-qn90cd-qled), flicker section | **M 120 Hz** at high Movie-mode backlight; **M 960 Hz** below the stated threshold | Review specimen and picture/brightness settings only. Exact numeric menu thresholds are deliberately not imported. Duty/absolute phase and matched LC waveform are **NR** here. |
| Same QN90C review, optional BFI | **M 60 Hz and 120 Hz** operation; observed duplicated image | Original reviewer observation under its BFI setup. It does not identify the simulator's tau or an electrical OD LUT. |
| [TFTCentral LG CX OLED review](https://tftcentral.co.uk/reviews/lg_cx_oled), BFI section | **M 216 / 148 / 119 cd/m²** in low / medium / high BFI at **P source test setting 120 Hz** | Tested CX55, OLED Light at **P source test setting 100**, maximum-brightness comparison. ABL can also change luminance; do not invert these means into exact duty. Full pulse integrals are **NR** here. |
| Same CX review, pursuit comparison | At **P source test setting 60 Hz**, low/medium have **M two flashes per refresh** and duplicated motion; high synchronizes | Shows that multiple flashes and LC crosstalk are distinct mechanisms. A generic OLED BFI mode cannot inherit this waveform. |
| [RTINGS LG C4 OLED review](https://www.rtings.com/tv/reviews/lg/c4-oled/), flicker and BFI sections | **M 60 Hz** optional BFI; observed refresh-related brightness dip without ordinary PWM dimming | Current public prose supports this specimen observation. Numeric response-time tables were paywalled during research, so their values are **NR**, not reconstructed from older reviews. |

[RTINGS' response-time methodology](https://www.rtings.com/tv/tests/motion/motion-blur-and-response-time)
uses a photodiode transition grid, warm-up and a declared refresh condition.
Method versions have changed; old response summaries and newer pursuit/CAD
results are not interchangeable. This note deliberately supplies no generic
“LCD milliseconds” range from unmatched retail measurements.

## Metrics and standards boundaries

All simulated metric values are **D under P inputs**. A step matrix should save
both response state and emitted waveform, with black pre-roll or explicit
settled initialization. A dark PWM interval must not be mistaken for falling LC
response. Measure intrinsic GtG on the ungated response; measure flicker and
brightness on emitted luminance. Record endpoint levels, time origin, finite
observation duration and the crossing/settling convention.

| Metric | Proposed M18 definition (P), calculated value D |
|---|---|
| Response | First interpolated **P 10% and 90%** crossings relative to start/target amplitude. A missing crossing is null/unresolved, never zero. |
| Settling | First time after which every remaining sampled response is within a declared **P 2%** amplitude band. A finite hold cannot prove asymptotic settling; record the observation limit. |
| Overshoot / inverse-ghost amplitude | Maximum excursion beyond target in transition direction, divided by absolute step amplitude; also retain nits. Report undershoot/reverse transition analogously and expose moving-pattern residuals separately. A no-change step has no normalized GtG. |
| Pursuit blur | Rising/falling **P 10–90%** edge widths in pixels and the explicitly defined effective blur time above; retain full images so secondary peaks are visible. |
| Brightness cost | `1 - integrated_emission_gated / integrated_emission_reference` for the same content, state/peak constraints and exposure. Reference arms must be declared; transient phase can make the ratio differ from nominal duty. |
| Percent flicker | **D** `100*(Lmax-Lmin)/(Lmax+Lmin)`. An all-black trace needs an explicit zero-light policy. |
| Flicker index | **D** positive area above mean divided by total emitted area over a declared complete cycle, or explicitly labeled finite observation window. |
| Dominant frequency | Strongest non-DC spectral bin of the declared uniformly sampled trace; retain sample rate, window, duration and bin resolution. This is not guaranteed to be the fundamental or PWM carrier when content flashes, gates beat or harmonics dominate. |

[IEEE Std 1789-2015](https://www.lisungroup.com/wp-content/uploads/2020/02/IEEE-2015-STANDARDS-1789-Standard-Free-Download.pdf)
was read through a public rehost of the IEEE document, especially its definitions
and recommended-practice sections; the official IEEE page could not be fetched.
It defines percent modulation and flicker index and considers frequency,
waveform and duty. Its simple low-risk boundaries include **P normative**
`Mod% < 0.025*f` below **P normative 90 Hz** and `Mod% < 0.08*f` between **P
normative 90 and 1250 Hz**. These recommendations concern modulated lighting;
M18 does not turn them into a display, medical or personal-safety pass/fail.
A dominant FFT frequency paired with aggregate percent modulation is insufficient
for a multi-frequency signal. Neither percent flicker nor flicker index alone
includes frequency weighting. [DOE/PNNL's explanation](https://www.energy.gov/eere/ssl/articles/flicker-understanding-new-ieee-recommended-practice)
also distinguishes the metrics' limited information. The M18 report should use
waveform descriptors and retain the spectrum/context; no PstLM, SVM, perceptual
flicker threshold or health conclusion is established (**NR**).

[VESA's ClearMR introduction](https://vesa.org/featured-articles/vesa-brings-clarity-to-motion-blur-in-digital-displays-with-new-compliance-test-specification-and-logo-program/)
explains why time-only MPRT can overlook overshoot/undershoot and describes a
high-speed-camera method with luminance verification and controlled conditions.
Its original public description disables strobing for certification comparisons.
[The later VESA-hosted method article](https://vesa.org/wp-content/uploads/2024/05/ID-Mag_2024_May_ClearMR_Article_Reprint.pdf)
explains statistical improvements while retaining the clear-to-blurry-pixel
ratio. These public explanations are not the complete compliance test suite.
M18's edge widths and synthetic pursuit pictures are not ClearMR scores, a VESA
MPRT implementation or certified results. Compliance and named-device comparison
remain **NR**.

## Numerical and state handoff

A display tick has a rational start `t_k`, rational duration `T_k`, and **P**
integer sub-step count `N`. Save **D** boundaries
`t_k + j*T_k/N`, durations `T_k/N`, and sample positions separately. A midpoint
sample is at **D** `t_k + (j+1/2)*T_k/N`; do not label it as a boundary. An
absolute rational clock preserves an asynchronous PWM carrier across ticks and
checkpoints. Converting an accumulated float clock back to a rational does not
recover that identity.

A sampled on/off gate can miss a short pulse or invent the wrong duty. Choose
and document a **P** quadrature: exact gate occupancy per bin, aligned gate edges,
or sufficiently resolved midpoint samples with explicit admission/convergence
limits. Rational PTS makes the clock exact, not the quadrature or physical fit.
Repeat at finer resolution and report changes in pulse energy, response and
pursuit width; temporal aliasing can corrupt dominant frequency even when the
mean looks plausible. Analytic response evolution must split at OD command
changes. **P** simultaneous whole-panel updates and rectangular light gates are
an honest initial scope; row scanout, LED rise/fall, phosphor-like tails,
temperature and nonlinear voltage dynamics remain **NR**.

The LCD owner stores unblurred LC state and any previous command needed for OD;
the OLED owner stores ungated emitter response. M17 zone state and M13 capacity
retain their independent update rules. Preserve exact array bytes, dtype,
geometry, rational clock, original initialization, config/profile/model identity
and the full existing load/zone/capacity histories in a versioned checkpoint.
Validate before mutation and commit a complete successful tick atomically.
Restore must reproduce subsequent emitted samples and pursuit/metric inputs
exactly. Cold/settled starts are new histories, not continuation substitutes.

The admitted composition must be explicit:

- Legacy response/OD/BFI/pursuit cannot run alongside M18 as another owner;
  reject nonneutral legacy settings or require an explicit override policy.
- Off/repeat/analytic/MCI sequences feed one content command per rational output
  tick; M18 samples light inside that tick without extra reconstruction,
  source lookahead, zone or capacity updates.
- LCD PWM/strobe composes with M17 actual illumination, then LC transmission;
  OLED BFI composes with M13's existing capacity once. M17 plus M13 remains an
  invalid panel/controller combination.
- M9 schema-1 fits lack the sub-frame state/history contract and must reject.
- M10 angular leakage/transmission and M15 signed panel-domain colorimetry need
  an unambiguous LC/emitter mapping. Either implement and test that mapping or
  reject active composition; treating final signed RGB as nonnegative optical
  transmission is not an acceptable silent approximation.
- Ambient reflection stays outside emission gates. Automatic peak boosting,
  alternate power/ABL feedback and legacy tracking smoothers require explicit
  ownership; unsupported combinations reject before advancing histories.

The versioned runtime/protocol sidecar contains **P-only** input choices and
strictly checked support. Output metrics/PTS are **D**; matched photodiode/LUT/
strobe calibration remains **NR**. Synthetic moving edges/bars at several speeds,
a gray-step matrix and a flashing patch should expose blur, response, inverse
ghosts, modulation and brightness cost. Keep shared exposure across comparison
arms and visually inspect the pursuit/contact sheets. Full linear arrays remain
ignored; compact inspectable traces retain declared downsampling and summaries.

Acceptance requires disabled byte parity, monotonic/no-overshoot native steps,
explicit OD overshoot with eventual settling, correct phase/duty/energy behavior,
ideal hold-versus-pulse blur checks, sampled-frequency limitations, complete
checkpoint byte continuation and atomic rejection of ambiguous combinations.
The implementation report records the admitted model and exact verification;
this research establishes its evidence boundary, not a calibrated TV.
