# M17 — LCD zone backlight temporal dynamics

Research date: 2026-10-18. This note precedes the runtime implementation and
defines a synthetic, default-off experiment. It follows the repository's
[evidence convention](../profiles.md): **M** is an identified measurement,
**D** a calculation or declared mathematical definition, **P** a proposed model
or placeholder, and **NR** an unavailable or insufficiently identified value.
Every quantitative setting below has an evidence grade. Document identifiers,
dates, software types, version names and section/equation numbers are identifiers,
not measured display quantities. Mathematical constants and bounds in the
equations are **D under the stated P model**. No named television is calibrated.

## Evidence and what it establishes

| Source and access | Mechanism evidence | Numeric transfer to this simulator |
|---|---|---|
| Dolby, [EP2245615A1, Temporal filtering of video signals](https://patents.google.com/patent/EP2245615A1/en), description around the scene-change flow and luminance-map construction; full text inspected. | Independently limits rising and falling backlight commands, permits filtering bypass at scene changes, and computes LCD compensation using the limited backlight. It also relates spatial aliasing and temporal filtering to the backlight PSF. | Patent examples are proposed embodiments (**P**), not measured retail-TV response constants. Actual vendor thresholds/rates are **NR**. |
| Nadernejad, Mantel, Burini and Forchhammer, [Flicker Reduction in LED-LCDs with Local Backlight](https://backend.orbit.dtu.dk/ws/files/55474458/MMSP95.pdf), IEEE MMSP, DOI [10.1109/MMSP.2013.6659307](https://doi.org/10.1109/MMSP.2013.6659307); author manuscript at DTU inspected. | Local-feature-dependent IIR filtering reduces rapid zone changes, while smoothing can delay the backlight at scene changes. The work uses spatial and temporal zone information. | This is algorithm research with simulated backlights, not a measured mini-LED controller fit. Published algorithm coefficients are **P** for those experiments and are not copied into generic profiles. |
| [US10802333B2, Local dimming system and method adaptable to a backlight of a display](https://patents.google.com/patent/US10802333B2/en), description of temporal filtering, light-shape imitation and pixel compensation; full text inspected. | Scene-change-aware temporal filtering precedes illumination reconstruction from overlapping LED influence profiles and subsequent pixel compensation. | It supports the stage boundary, not a physical time constant. A matched optical/controller calibration is **NR**. |
| RTINGS, [Lighting Zone Precision and Transitions methodology](https://www.rtings.com/tv/tests/picture-quality/lighting-zones), current protocol text inspected. | Moving shapes expose flickering, dark leading edges from slow zone activation, and trailing halos from slow deactivation. The protocol also includes subtitles and separate game-mode assessment. | Transition and precision scores are explicitly subjective. Videos/scores do not supply a calibrated zone e-fold time; stimulus luminance, camera temporal response and device controller constants needed for such a fit remain **NR** here. |
| RTINGS, [TCL QM5K review](https://www.rtings.com/tv/reviews/tcl/qm5k), accessible black-level/transition discussion inspected. | The reviewed sample shows dark leading edges, trailing halos and subtitle/star-field haloing. This is an original reviewer observation supporting a failure mode. | It is qualitative specimen evidence, not an **M** tau or halo-energy measurement. Locked numeric fields were not recovered or inferred. No sample result becomes a generic-profile parameter. |
| RTINGS, [Hisense U8H review](https://www.rtings.com/tv/reviews/hisense/u8-u8h), accessible transition discussion inspected. | The reviewer describes much less conspicuous moving-zone transitions on this sample. Mechanism severity varies across implementations. | This qualitative counterexample cannot establish a technology-wide time constant or rank different measurement protocols. Numeric zone dynamics are **NR**. |

The SID paper Kerofsky and Zhou, *Temporal Filtering in LCD Backlight
Modulation*, DOI [10.1889/1.3069821](https://doi.org/10.1889/1.3069821), was
located, but the publisher full text could not be retrieved in this session.
It is a relevant follow-up locator, not an independently verified source for
equations or numbers here. The openly accessible IEEE manuscript and patents
provide the implementation evidence. A patent establishes a disclosed design,
not that a commercial product uses it, and a reviewer video is not a photodiode
trace. No externally measured numerical zone-transition parameter is imported.

## Proposed mechanism and its honest limits

The existing [backlight stage](../../src/tv_sim/stages/backlight.py) pools each
frame independently. Keep that exact path when the new configuration is absent
or off. On the active **P** path, each zone has a desired command `u_j` and a
persistent actual command `z_j`, both in nit-scaled backlight drive. Choose a
physically bounded zone target from the current processed picture; record its
pooling statistic, lower bound, peak bound and rasterized zone edges. Retain the
state in `float64` as a **P engineering choice**; cast only the command passed
to existing float32 optical transport. This is an effective controller command,
not LED junction temperature or instantaneous PWM duty.

For one display tick of duration `dt` seconds, the **P model** is

```text
tau_j = attack_s if u_j > z_j else release_s
alpha_j = -expm1(-dt / tau_j)
candidate_j = z_j + alpha_j * (u_j - z_j)
```

An explicitly supplied `tau_j = 0` means `candidate_j = u_j`. Equal target and
state stay equal. Both taus must be explicit, finite and nonnegative when the
feature is active. Attack means increasing zone light; release means decreasing
zone light. These names do not inherit OLED capacity semantics, where increased
load can lower the controlled quantity. For a held target without a slew cap,
the **D** error is multiplied by `exp(-dt/tau)` each tick. After **D** elapsed
time `tau`, remaining error is **D** `exp(-1)`, about **D 36.8%**; a frame-based
constant blend would change that physical interpretation with refresh rate.

An optional **P** `slew_nits_per_tick` clips `candidate_j-z_j` to a declared
maximum change in nits/tick, then updates `z_j`. A per-tick bound is
deliberately refresh-dependent; it must never be presented as a per-second
limit or silently rescaled. Disable it for refresh-rate invariance tests.
Applying a later `min(z_j,u_j)` would destroy slow release and is invalid.

For an unchanged target this first-order, bounded update is **D** monotone and
cannot overshoot its target. An overshoot metric should therefore be zero in
that isolated experiment. Output excursions can still arise from changing
targets, changing clipping, optical overlap and the independent pixel response.
The model must not manufacture ringing to make an overshoot chart interesting.
An explicit input delay, predictive lookahead, adaptive higher-order filter,
thermal limiter, hysteresis, PWM waveform and vendor compensation/overdrive
remain **NR**, unless separately introduced as declared **P** mechanisms.

### Optics, compensation and pixel response

Expand the filtered zone commands and apply the existing declared PSF/LSF and
boundary policy once. Then compensate LCD transmission against this actual
backlight map. A slow increase can leave insufficient illumination even with
the shutter fully open; a slow decrease leaves residual light that the finite
LCD extinction cannot fully block. Those two constraints produce leading-edge
dimming and a halo trail without blurring the bright object's geometry.

This stage choice follows the light-shape/compensation ordering in
[US10802333B2](https://patents.google.com/patent/US10802333B2/en). It also makes
the spatial-temporal interaction explicit: a wider PSF distributes a lingering
command over more dark pixels. An anisotropic edge-lit LSF can produce a long
strip of leakage instead of a compact halo. Zone count alone cannot determine
trail visibility. Off-axis leakage, ambient, exposure, contrast and motion
velocity also matter.

The active bounded target may clip *before* optical spread. Legacy rendering
spreads unbounded pooled demand and clips afterward. **D:** those operations
do not commute for over-peak sparse content. An active zero-tau experiment may
therefore differ from legacy at such inputs; label that active-model boundary
and test zero-tau equality with a matched instantaneous active controller.
Disabled rendering must retain the original arithmetic exactly.

The repository's pixel temporal stage operates on emitted RGB after panel,
HDR/ABL and ambient. Keeping it preserves existing response/hold/overdrive
behavior, but it is a **P cascade approximation**. It does not solve physical
time-dependent LC transmittance multiplied by a separately sampled LED waveform.
Do not interpret compounded pixel and zone lag as a measured LC GtG time.
Use a zero-pixel-lag diagnostic to isolate backlight dynamics, and retain the
ordinary pixel response in a separately identified full-pipeline comparison.

## Clock, cuts, history and composition contract

The following are **P engineering policies**, not measured TV behaviors.
Keep runtime configuration outside `TVProfile`, following M10/M13/M15, so
baseline profile leaves, M8 evidence and M9 fingerprints stay unchanged.
Only LCD profiles with a declared zoned backlight are eligible; OLED and
`per_pixel` emission reject. Reject conflicting ownership before mutating any
history or writing any experiment output.

The selected **P interface** is a separate `ZoneTemporalConfig` with active
model `zone_attack_release_v1`, explicit `attack_s`/`release_s`, optional
`slew_nits_per_tick`, `reset_on_scene_cut`, and optional
`cut_detection_threshold`. The detector's **P** score is the mean absolute
difference between previous and current bounded, unsmoothed zone targets,
divided by the declared backlight peak. Its comparison/bounds and threshold
are declared in the runtime/protocol schema; absent detection means no implicit
cut inference. Comparing the low-resolution target grid is inexpensive, but a
similar grid can hide a shot change and a flash/APL step can trigger a false
reset. This is a transparent heuristic rather than a vendor scene classifier.

| Concern | Required policy |
|---|---|
| Clock owner | A single Pipeline updates its zone state once per displayed tick using output `dt`. Decode, preparation, MEMC pair estimation, reconstruction samples and pursuit integration do not advance it. Save rational PTS/durations independently of floating-point arithmetic. |
| Initialization | `cold` starts from the declared minimum command; `settled_first_tick` installs the first target without an invented warm-up history; `explicit` requires a complete immutable rectangular tuple-of-tuples grid in nits matching the effective rasterized zone grid. These initialize zones only and do not claim resumed pixel history. |
| Continuation | Resume requires a full checkpoint with exact state bytes, dtype/shape, profile/config/optical identity, clocks, pixel/load histories and previous detector input. State-only initialization cannot claim exact continuation. Reject a second initializer, stale identity, malformed/nonfinite arrays, unknown time gaps or external mutation atomically. |
| Scene cuts | A declared cut is authoritative. When `reset_on_scene_cut` is selected, reset the zone command to its current target on the first displayed tick of the new shot, bypassing IIR/slew for that event. A selected detector can request the same reset. Preserve independent LCD/load histories; do not clear the whole display state. |
| Detector ownership | Store its previous bounded zone-target grid with zone history. Detection compares current targets with prior targets, not filtered output. An APL step/flash can falsely resemble a cut, and a similar-looking shot can be missed. Record declared/detected reasons separately. |
| MEMC | Off/repeat/analytic/MCI content first reaches the single display tail. A right-hand source endpoint marked as a new shot must not reset zones during an earlier old-shot interpolation/hold. Propagate declared source cuts when that source is actually displayed, including skipped indices. MCI's estimated cuts retain their reconstruction/confidence role; M17's own detector owns detected zone resets. |
| M13 capacity | M13 currently admits OLED profiles; M17 admits LCD only, so simultaneous active M13/M17 rejects. Do not create an extra capacity scalar inside the zone controller. |
| Legacy load mechanisms | Reject ambiguous combinations with legacy APL smoothing, backlight tracking, power-proxy derating or M9 schema-1 fits unless an explicit future composition identifies units, ordering and the sole owner. Existing off-path behavior remains exact. |
| M10 angles | Apply its LCD transmission/leakage terms after the actual filtered illumination. Angle affects rendered halo visibility, not zone targets or time constants. Include angle identity in checkpoints. |
| M15 colorimetry | Derive zone demand from the existing panel-domain processed target; preserve M15 gamut and joint capacity ownership. Never smooth RGB primaries, duplicate the tone mapper or reinterpret a zone command as output luminance. Checkpoint the colorimetry identity. |

Per-zone optical commands, global capacity and pixel response are different
states with different units. None should silently replace another or borrow
its checkpoint. A scene-cut backlight reset is an algorithm choice; it is not
an assertion that a panel's physical LC state instantaneously settles.

## Synthetic experiment and metrics

Use independent off/on pipelines for each complete clip, identical profiles,
initial conditions, decoded content and display clocks, and a shared fixed
exposure. All chosen stimulus levels, dimensions, durations, motion velocity,
taus, slew/cut thresholds and metric thresholds are **P** and must be saved in
a versioned sidecar. PTS, target/state/output arrays and metrics computed from
those inputs are **D under P assumptions**. Actual TV values remain **NR**.
The sidecar must retain these distinctions and pass `tv-sim provenance --check`;
an experiment must not promote its own outputs to **M**.

| Clip | What to retain and compare |
|---|---|
| Bright object moving across black | Exact object masks/trajectory; leading-edge highlight retention; leakage behind the moving object; selected zone histories as the object enters/leaves them. |
| APL step up and down | Stable baseline and hold intervals; target versus actual mean/probe commands; output mean/probe luminance; separate rise/fall settling times and late-interval slope. |
| Flashing small highlight | Full flash timeline; command/output peak-to-peak range and total variation; retained highlight energy. Reduced modulation can mean dimmed highlights, so report both. |
| Subtitle over a dark scene | Fixed dark-scene probe outside text; subtitle geometry and onset/offset; leakage/pumping at that probe and highlight retention inside the text mask. |

Recommended explicit metric definitions, all **P protocol choices** with **D**
calculated results:

- **Trail length:** in the region behind the known moving object's rear edge,
  the furthest pixel distance exceeding a saved luminance threshold after
  subtracting a matched black background. Exclude the current object mask.
  Save both absolute halo and the positive on-minus-off residual so ordinary
  spatial bloom is distinguishable from extra temporal trail.
- **Trail energy:** sum positive excess linear Y over the declared trailing
  region, multiplied by tick duration. Units are nit-pixel-seconds, not joules.
  A normalized ratio requires a declared nonzero highlight-energy denominator.
- **Settling time:** first tick after a known transition whose command/output
  error enters a saved band and stays there through the declared remaining
  hold. Report not reached when the clip is too short; never substitute its
  duration or infer sub-tick accuracy. Zone and emitted-Y settling are distinct.
- **Overshoot:** largest signed excursion past the held final target, with
  direction, reference interval and units. **D** expected isolated controller
  overshoot is zero. Never call a slow-release above-target residual a rising
  step overshoot.
- **Pumping/stability:** peak-to-peak Y at a nominally unchanged dark-scene
  probe, plus zone-command total variation over the declared interval.
  Include matched off/on values; content changes and pixel response can also
  change output. This is not a perceptual flicker score or a PWM measurement.

Keep full per-zone targets, before/after state, branch/reset/slew indicators,
rational PTS and output probe traces. Save inspectable JSON/CSV/PNG/HTML plus
gitignored reproducible linear arrays. Select onset, moving, offset and late
frames for contact sheets with one exposure across both arms; inspect the
images and trace curves. A static contact sheet demonstrates spatial residuals
but cannot establish perceived temporal smoothness on the user's display.

## Acceptance and future measurement

Before accepting the model, verify closed-form attack/release, explicitly zero
taus, equality, bounds, extreme `dt/tau`, slew ordering, every initializer,
declared/detected cuts, refresh-rate agreement without slew, exact full-history
continuation, atomic rejection and one update per display tick in every sequence
mode. Confirm all previous arrays, assets, substantive traces and goldens remain
byte-identical with the feature omitted/off. Source/checkpoint identity hashes
can truthfully change with code; do not hide rendering drift in that exception.

Real calibration needs synchronized photodiode and luminance measurements of
matched moving/window/subtitle stimuli with documented specimen, firmware,
picture/game/VRR settings, amplitude/primaries, refresh, zone position, warm-up,
preceding content, ambient/viewing geometry, instrument bandwidth and integration.
Track a bright probe and adjacent dark probes to distinguish compensation
limits, LCD lag and zone leakage. Separately identify optics and static native
contrast before fitting temporal parameters. Hold out trajectories, speeds,
areas and transitions. The present evidence supports the mechanism experiment;
measured PSFs, matched controller taus, compensation timing and named-device
prediction remain **NR**.
