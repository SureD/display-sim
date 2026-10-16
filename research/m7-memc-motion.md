# M7 MEMC and motion: model, artifacts and implementation boundary

Research checked **2026-10-16** against [README](../README.md), [STATUS](../docs/STATUS.md), [temporal research](04-temporal.md), [image-processing research](05-image-processing.md), and the current [stages](../sim/stages/). This is a research and implementation handoff; it changes no simulator code, profiles, M4 artifacts or gallery work. Consumer-TV feature descriptions establish behavior, while the public algorithms below establish reproducible model families. Neither establishes an exact Sony, Samsung or LG implementation.

Use the [M5/M6 evidence convention](m6-profile-wiring.md): **M** = published measurement, **D** = deduction from declared inputs, **P** = proposed model or synthetic experiment, **NR** = no verified numerical reference, unidentified parameter or missing conditions. NR is not zero and is distinct from *not implemented*. Spell out **noise reduction** to avoid confusing that processing family with the evidence label. No measured TV interpolation coefficients or artifact distributions are claimed here.

## 1. What exists now

| Location | Implemented behavior | MEMC boundary |
|---|---|---|
| [process.py](../sim/stages/process.py), `process_image` | Nearest/bilinear scaling, then unsharp masking, on linear-nit RGB. | One picture at a time; no motion estimation, deinterlacing or temporal noise reduction. |
| [temporal.py](../sim/stages/temporal.py), `respond` | First-order lag; optional overdrive command for a prefix of `frame_time_ms`, followed by the target. | Panel-response proxy, not reconstruction of intermediate content. `response_time_ms` is the time constant used by the equation, not a measured 10–90% GtG value. |
| `TemporalState.previous` / `apply_temporal` | Stores the lagged linear-nit image **before** BFI and pursuit blur. First frame, absent history or shape mismatch starts fully settled. | No source-frame buffer, source timestamps, vectors, visibility or scene-cut state. |
| `apply_bfi` | Duty scales frame-mean light and pursuit displacement; optional mean preservation with ceiling clipping. | No measured pulse train, scanout or PWM. BFI does not add motion positions. |
| `sample_and_hold` / `shift_x` | Seven horizontal bilinear shifts averaged using manually supplied `motion_px_per_frame`; clamped border samples. | A local pursuit-image proxy; it neither moves objects between frames nor estimates flow. No full time-resolved eye integration. |
| [pipeline.py](../sim/pipeline.py), `Pipeline.run_linear` | Decode → spatial processing → backlight → panel → tone map/ABL → ambient → temporal. Persistent panel and load states; one input produces one output. | No source/output-rate distinction. `frame_time_ms` advances both response and ABL dynamics. |
| [frame.py](../sim/frame.py), [cli.py](../sim/cli.py) | `Frame` contains RGB nits and optional backlight map. Existing still CLI has `--motion-px`. | No PTS, clip loader, frame-rate converter or MEMC switch. `--motion-px` means eye displacement per simulated frame, not estimated source displacement. |

The moving-edge [validation harness](../sim/validate.py) supplies successive pictures itself. Its `_render` creates a new `Pipeline` each time, sharing `TemporalState` but **not** `LoadState`; preserve this historical behavior for M4 comparisons. Its `temporal_only_blur_px` isolates the existing temporal stage, not interpolation quality. The [temporal tests](../tests/test_temporal.py) already protect lag, settled stills, pursuit-history isolation, overdrive and BFI.

## 2. A consumer-TV MEMC model

**Motion estimation / motion compensation (MEMC)** estimates how image content moves, then synthesizes pictures at additional presentation times. For example, [Sony's Motionflow description](https://www.sony.com/electronics/support/televisions-projectors-lcd-tvs/xel-1/articles/00013987) explicitly describes calculating and inserting a new frame between original frames. A marketing motion-rate number need not equal the panel's native refresh rate or the count of unique source samples.

A useful abstract controller has five parts; these are model families, not a disclosed vendor processing graph:

1. **Recover source timing.** Read progressive frames and PTS. Distinguish genuine 24p from 24p carried in a repeated 60p stream. Interlaced telecine requires field matching/deinterlacing before interpolation. Mixed video, film and overlays can have different cadences.
2. **Estimate correspondence.** Match luma blocks or estimate dense optical flow between adjacent frames, often in both directions. Hierarchical search handles larger motion; regularization favors coherent vectors. Camera pan and independently moving objects need different vectors. Video-codec prediction vectors are not automatically correct optical flow.
3. **Estimate reliability and visibility.** Mark ambiguous texture, out-of-bounds trajectories, occlusions and newly revealed background. A pixel hidden in one endpoint may still be usable from the other. Bidirectional consistency alone cannot determine every object's depth order.
4. **Synthesize at the output time.** Move usable samples along their trajectories, combine visible contributions, resolve collisions/holes and preserve original samples at exact source timestamps. This creates new positions; a crossfade of unmoved endpoints creates double exposures.
5. **Control exceptions.** Detect cuts and unreliable motion, suppress or reduce interpolation locally/globally, and repeat a source picture where reconstruction is unsafe. Smooth confidence decisions within a shot to avoid visibly switching between smooth and stepped motion.

Public implementations make these choices inspectable. [FFmpeg `minterpolate`](https://ffmpeg.org/ffmpeg-filters.html#minterpolate) separates duplication, blending and motion-compensated modes; it documents bidirectional/bilateral estimation, overlapped block compensation, adaptive reliability weighting, and replacing interpolation with duplicates at scene changes. This is an algorithm reference, not evidence that a TV runs FFmpeg.

[Herbst, Seitz and Baker (2009)](https://www.microsoft.com/en-us/research/publication/occlusion-reasoning-for-temporal-interpolation-using-optical-flow/) explicitly use bidirectional flow, depth ordering and regularization for occlusion reasoning and hole reduction. [Jiang et al., Super SloMo (2018)](https://arxiv.org/abs/1712.00080) combines flow, intermediate warps and visibility-aware fusion in a learned model. These explain why endpoint warping needs visibility handling; their networks, quality and runtime are not consumer-TV calibrations.

## 3. Minimal mathematical contract for a NumPy proxy (P)

Keep source PTS `t_i`, output PTS `s_j`, and panel refresh separate. For `t_0 <= s < t_1`, let `alpha = (s-t_0)/(t_1-t_0)`. Flow `f01(p)` maps source pixel `p` in `I0` to `p+f01(p)` in `I1`; `f10(q)` is the reverse field, in **pixels per source interval**, not pixels/s. Use one vector field for RGB to avoid artificial channel separation.

A candidate block matcher minimizes, over a finite displacement search, normalized luma SAD plus a declared neighbor-vector penalty. Use a fixed luma normalization/reference across the clip; per-frame peak normalization can hide flashes and change match costs. A fixed log-luma matching domain is an optional HDR experiment, while reconstruction can remain in decoded linear RGB nits. Record domains and the current pipeline's BT.709 luma-weight assumption; this is not calibrated wide-gamut processing.

One confidence cue is the forward/backward residual:

```text
r_fb(p) = ||f01(p) + bilinear_sample(f10, p + f01(p))||
```

Combine it with match residual, best-versus-next distinct candidate cost, texture support and boundary validity. Thresholds are P; a low residual does not prove correctness on repeating patterns. Keep occlusion/visibility separate from generic low confidence: an occluded endpoint may fail consistency while the other endpoint remains useful.

A straightforward reconstruction is **forward splatting**, with bilinear weights into the output raster:

```text
I0(p) contributes at x = p + alpha * f01(p)
I1(q) contributes at x = q + (1-alpha) * f10(q)
I_alpha(x) = accumulated weighted RGB / accumulated valid weight
```

Weights include visibility, confidence, spatial splat weight and temporal factors `(1-alpha)` / `alpha`. A known foreground/background fixture can supply depth order to reject hidden contributions. For ordinary clips, collisions without reliable ordering must lower confidence or trigger fallback; normalized accumulation alone does not solve occlusion. Use explicit validity masks and never reflect image content into disocclusion holes. A gather implementation instead needs **intermediate-to-source** fields; simply scaling a spatially varying endpoint flow at the output coordinate is not generally an inverse mapping.

Special-case `alpha=0` and the next source endpoint to return exact original arrays. If both endpoints are identical, skip estimation/resampling. For known constant displacement `d`, verify `I_alpha(x)=I0(x-alpha*d)` on the valid interior. At unknown holes use the declared source-hold fallback, not division by epsilon interpreted as black. Negative/positive subpixel translation and borders need explicit tests.

This proxy assumes approximately linear trajectories and consistent appearance within a source interval. Acceleration, rotation, deformation, transparency, flashes and large shutter blur can violate those assumptions. Interpolation does not recover the true unseen exposure or remove camera motion blur merely by moving its samples.

## 4. Cadence conversion, stutter and the soap opera effect

[Netflix's primary engineering explanation](https://netflixtechblog.com/native-frame-rate-playback-6c87836a948) illustrates 24→60 replication with 3:2 pulldown and distinguishes integer-rate repetition from uneven conversion. Its subject is source-device/HDMI timing, which is useful evidence for separating cadence handling from a TV's motion synthesis.

The following times are **D**, for exact rates and a constant-speed pan, with no interpolation or BFI unless stated:

| Source → output | Repetition/synthesis | What changes |
|---|---|---|
| 24 → 60 | Alternating three/two output holds; 50 / 33.333 ms per source picture. | Adds uneven cadence judder to the source's coarse temporal sampling. |
| 24 → 120 | Five repeats; every source picture held 41.667 ms. | Removes uneven conversion cadence; retains 24 motion positions/s and low-rate stutter. |
| 25 → 50 or 30 → 60 | Two repeats of each source picture. | Equal holds, still no extra scene samples. |
| 24 → 60 MEMC | Evaluate source-time phases `0, .4, .8, .2, .6, ...` across consecutive source pairs. | Ideally 60 evenly spaced motion positions/s, with reconstruction errors possible. |
| 24 → 120 MEMC | Pair phases `0, .2, .4, .6, .8`. | Ideally 120 positions/s; the film's motion appearance changes even with perfect vectors. |

Retain rational rates: `24000/1001 → 60000/1001` has the same 3:2 repeat ratio, and `24000/1001 → 120000/1001` has 5:5. `24000/1001 → 120/1` does **not** have exactly five ticks per source interval. Schedule from rational PTS rather than accumulating rounded milliseconds. A proposed finite-clip convention is output times `s_j = t_start + j/output_fps` strictly below `t_end`, where `t_end` is the last source PTS plus its declared duration; source-hold intervals are half-open `[t_i, t_(i+1))`. This fixes output count and tail behavior without adding a duplicate end tick.

**Cadence judder** here means uneven presentation intervals; **stutter** means visible stepping from low source sampling even with equal holds. Consumer menus sometimes call both “judder.” Cadence recovery followed by equal repetition can remove conversion judder without synthesizing motion. Detecting a known 3:2 progressive repeat pattern is an achievable later proxy; robust mixed-cadence detection and interlaced inverse telecine are separate work.

**Soap opera effect** is the smoother motion appearance of interpolated film, not necessarily a reconstruction error. [Samsung's support page](https://www.samsung.com/us/support/answer/ANS10006969/) explicitly associates its motion smoothing with this effect on movies and exposes separate blur, judder and backlight controls. Do not translate vendor slider values into an optical-flow coefficient without measurement. Compare repeated-film, cadence-corrected and interpolated sequences at the same duration. A still cannot demonstrate the effect, and a numerical smoothness score is not a validated perceptual SOE scale.

## 5. Artifacts that matter for stills and short clips

[Sony's artifact guidance](https://www.sony.com/electronics/support/televisions-projectors/articles/00153243) confirms that inserted frames can produce noise around fast movement, scene transitions and moving screen edges. The mechanisms below are **P**, consistent with the public interpolation literature; that guidance does not supply halo radii or failure rates.

| Effect | Model cause / useful stimulus | Observable output |
|---|---|---|
| Motion-boundary halo, tear or doubled outline | Foreground and background need different vectors; wrong visibility mixes samples. Move an opaque square across detailed stripes, then uncover text. | Individual interpolated crops, boundary error band and a flickering/shimmering sequence. This halo is distinct from optical bloom and sharpening overshoot. |
| Warped text, bending lines, texture boiling | Wrong matches on thin/repeated patterns, aperture ambiguity or smoothing across motion boundaries. Pan a fence behind a stationary caption; move a fine diagonal. | Source/intermediate triplets and short playback. Global translation alone cannot reproduce these local errors. |
| Cadence judder / residual stutter | Noninteger repetition, incorrect film lock, frame drops, or deliberate fallback. Use constant-speed pans with known PTS. | Position-versus-time trace, repeat-run lengths and clip. A single edge-width score misses this. |
| Soap opera effect | More unique motion positions change film cadence even when reconstruction is accurate. | Matched playback of 24p repetition versus interpolation; no still-only claim. |
| Fallback pumping / micro-stutter | Confidence oscillates between synthesis and source holds; a small fast ball disappears into texture. | Fallback masks/reasons, unique-position trace, temporal switching rate and playback. |
| Cut morph / flash smearing | Estimator interprets a cut or exposure change as motion; stale vectors cross the boundary. | Intermediate-frame leakage test before the declared cut PTS, and cut recovery time. |
| Blend ghosting | Uncompensated endpoint blending or overbroad confidence feathering. | Double contours in one synthesized frame. Keep simple blend as a negative control. |

A single supplied still has neither temporal correspondence nor known cadence. Return ordinary still behavior and mark MEMC assessment *not observable from this input*, rather than inventing motion. A still can seed a **synthetic** pan or layered occlusion fixture, with imposed velocity, masks, border fill and exposure labeled P. Such a fixture demonstrates the model, not the original scene's actual movement. Two real endpoints can expose a synthetic-frame defect; several intervals are needed for fallback switching, film-lock behavior or cut recovery.

## 6. Fallback and latency contract (P unless sourced)

Prefer explicit categorical modes initially: `off`, `repeat`, `blend`, `mci`. Avoid a vaguely calibrated “low/medium/high” strength. A crossfade between a held source and a displaced intermediate image can itself create ghosts; any future strength control needs a defined timing/reconstruction rule and endpoints.

For an interval containing a hard cut at `t1`, keep `I0` until `t1` and show `I1` at/after it. Do not interpolate across the cut or use nearest-frame selection that reveals the new shot early. Flush correspondence/confidence history, while keeping physical panel response and ABL history continuous. A visible response trail after the cut must remain distinguishable from synthesized shot leakage.

For local low confidence, prefer one visible warped endpoint if justified; otherwise source-hold that region and record the reason. A whole-frame hold is safer when the unreliable area is large. Out-of-range motion, out-of-bounds samples and ambiguous repeats should trigger the same declared policy. Use conservative hysteresis within a shot to limit switching; never carry smoothing across a detected cut. Scene-difference thresholds alone confuse flashes/large pans with cuts, so provide a fixture/manifest cut override and report false detections. Thresholds, area limits and hysteresis durations remain P/NR pending measurement.

At the first output show the first source without extrapolation. At the last source, hold through the declared final source duration; never invent a future frame. A single-frame input follows that hold rule. Reject inconsistent dimensions/encoding within a clip; resizing or starting a new segment must be explicit, with fresh motion state. Separate clips receive fresh motion, panel and ABL states.

Bidirectional interpolation needs the next source picture. A proposed fixed one-source-interval buffer is **D/P**: 41.667 ms at 24 fps or 16.667 ms at 60 fps, before compute/queues. Actual waiting depends on phase, input arrival and design; these are not measured TV input-lag figures or a universal minimum for every algorithm. Keep content PTS, output PTS and buffer latency separate. [Samsung's 2022 game-mode documentation](https://www.samsung.com/nz/support/tv-audio-video/2022-how-to-use-game-on-your-samsung-smart-tv/) states that disabling Game Motion Plus reduces input lag and that it cannot operate with VRR/FreeSync on the covered models. This is model-specific evidence, not a universal VRR restriction. Vendor latency and mode-switch behavior remain NR.

## 7. What NumPy can approximate and what stays NR

| Mechanism / quantity | Reasonable CPU reference scope | Remaining boundary |
|---|---|---|
| Timestamp scheduler, repeat conversion, exact source endpoints | Rational-rate offline image sequences; explicit progressive repeat fixtures. | Automatic mixed cadence, dropped-frame detection and interlaced film recovery not implemented. Real-TV lock time NR. |
| Motion synthesis | First use known 2D translation/layer masks; then bidirectional coarse-to-fine block matching with bilinear splats or overlapped blocks. | A proxy is implementable; a particular TV's search, layers, filters, precision and ordering remain NR. |
| Confidence and fallback | SAD/consistency/validity masks, cut overrides, local/whole-frame holds and debug records. | Consumer thresholds, fallback fractions, halo dimensions and slider mappings remain NR. |
| Artifact fixtures | Controlled vector error, coarse blocks, incorrect visibility or delayed fallback. Seed and label each injected failure. | These are P stress cases, not measured probabilities. Never add a universal glow around moving objects. |
| Learned interpolation | Cite as an alternative; keep outside the initial NumPy dependency set. | Requires separate weights/licensing/domain/runtime validation; named-TV neural models remain NR. |
| Panel and observer interaction | Reuse existing lag/OD/BFI after each synthesized target, with output tick duration. | Calibrated response LUT, time-resolved scanout/PWM/BFI and full pursuit integration remain absent/NR. |
| Performance and latency | Report measured offline runtime separately from assumed buffer delay. | No real-time 4K claim, measured TV latency or GPU work in this milestone. |

For an initial **P** budget, use 320×180 estimation images, 8/16-pixel blocks and a small declared pyramid search; render short fixtures before full-resolution clips. Report estimation scale and convert vectors back to output pixels. A brute-force matcher costs roughly image area times candidate count; do not materialize every candidate patch for a 4K sequence at once. Stream adjacent pairs and cache decoded/processed source frames. These are engineering starting points, not measured accuracy or performance targets.

## 8. Integration and proposed CLI hooks

All commands/options below are **proposed, not supported by the current CLI or YAML loader**. Prefer a separate `motion` subcommand so the existing still and M4 paths retain their contracts. Initial input should be numbered RGB images plus fixed rational source fps, or a manifest with explicit PTS, last-frame duration, encoding and optional cuts. A video decoder/audio muxer is not required for this research handoff.

```bash
# Existing command: identical behavior after any future MEMC work.
python3 -m sim --profile generic_woled --input in.png --output out.png

# Proposed sequence baseline: scheduler enabled, source pictures repeated.
python3 -m sim motion --profile generic_woled \
  --input-frames 'clip/frame_*.png' --source-fps 24000/1001 \
  --output-fps 120000/1001 --memc repeat --out reports/motion-repeat/

# Proposed synthesis, with diagnostics and fixed preview exposure.
python3 -m sim motion --profile generic_woled \
  --input-frames 'clip/frame_*.png' --source-fps 24000/1001 \
  --output-fps 120000/1001 --memc mci --motion-debug \
  --preview-reference-nits 1000 --out reports/motion-mci/

# Proposed synthetic fixtures and isolated tests; keep M4 validate separate.
python3 -m sim motion validate --fixtures pan occlusion text cut \
  --source-fps 24/1 --output-fps 60/1 --seed 7 --out reports/motion-tests/
```

Define `off` as a **legacy bypass**: one input → one existing pipeline call, original profile timing, no motion buffer and no resampling. Omitted settings follow this branch. Reject `off` combined with a request to change output fps; use `repeat` for an explicit output-refresh experiment. Disabling synthesis inside an already active scheduler is `repeat`, and can change panel/ABL timing relative to legacy execution. This distinction prevents an “off” option from silently breaking parity.

The enabled graph should be `decode + existing spatial processing per source → source buffer/estimation + reconstruction → requested-content frame → existing display tail per output tick`. Add an internal linear-content entry point later if needed; feeding synthesized nits through `run_linear(encoded)` would decode and sharpen twice. Never interpolate already simulated backlight, optical spread, panel lag or room reflections. Exact vendor processing order is NR; this placement is P and compatible with current stage domains.

Keep a separate `MotionState`/sequence record for frames, PTS, cadence, vectors and confidence. Do not use `TemporalState.previous` as a source endpoint. On the enabled path advance one persistent panel/load state per **output** tick with `frame_time_ms = 1000/output_fps`; compute demand APL from each requested interpolated/repeated frame. Avoid extra hidden pipeline calls that advance physical state.

Use pixels/s for new synthetic-motion and eye-velocity inputs; leave existing `--motion-px` semantics unchanged. For 480 px/s (**D**), source displacements at 24 fps are 20 px, and output-tick displacements at 60/120 Hz are 8/4 px. Natural-playback frames should use zero pursuit blur so host eye motion is not baked into every frame. An optional diagnostic pursuit snapshot can use the existing kernel with displacement `v_eye * dt`, clearly labeled as a local approximation.

Do not infer effective persistence from output fps alone: 24p repeated at 120 Hz still holds each motion position for 41.667 ms. Per-tick blur does not reconstruct that full tracked-eye image. Full pursuit needs time-resolved integration across repeated/synthesized emissions; changing the existing seven-sample kernel is separate work. Likewise, a 120-fps file played at 60 Hz cannot validate 120-Hz cadence. Save PTS and position traces alongside previews; contact sheets explain synthesis defects, not perceived smoothness by themselves.

Diagnostics should include source indices/PTS, output PTS, alpha, frame kind (original/interpolated/repeated), flow/confidence/visibility maps, cut and fallback reasons/fractions, and assumed lookahead. Save linear-nit arrays and units before preview encoding. Use one exposure/reference across each clip; the current harness's per-image-peak-normalized PNGs can hide temporal brightness changes. Record profile/source hashes, estimator parameters, seed, domains, output timing and observer mode in a new motion sidecar, without extending M4 report schemas by default.

## 9. Suggested verification and M4 compatibility gates

These are future hooks, not tests added by this note. Use a separate motion suite and separate report directory.

| Gate / fixture | Required assertion |
|---|---|
| **Disabled parity, all four profiles** | Against a captured pre-MEMC current-tree baseline, require exact float32 `run_linear` RGB/backlight maps, uint8 previews and final panel/load states for stills and multi-frame inputs. Defaults and explicit `off` take the same path; no new normalization, profile overrides, buffering, state advances or report fields. |
| **Original M4 harness** | Preserve 384×216 defaults, six moving-edge frames, 8 px/frame, fresh settled static state and existing report fields. Compare JSON/CSV metrics and decoded preview arrays in a temporary output directory; preserve historical load-history behavior. |
| Static / endpoints / numerical safety | Identical input pairs are exact no-ops; constant RGB/DC and endpoints are preserved. Outputs have expected shape/dtype, finite values and no invalid-weight NaNs. Zero confidence takes declared fallback. |
| Signed 2D/subpixel translation | Known flow reaches expected alpha positions on valid interiors, with a declared bilinear error tolerance. Compare both directions, vertical motion, border validity and alpha near 0/1. |
| Rational cadence | Verify source-index runs 3/2 for 24→60 and 5/5 for 24→120 repetition, also fractional equivalents and 25→50. Verify exact phase/PTS traces for MCI, total duration and no drift; count unique positions only on a nonstatic known pan. |
| Occluding layers / thin text | Compare to an analytic intermediate render with two velocities and visibility. Measure errors separately in visible interior, boundary and disoccluded regions. Force faulty vectors/masks to make artifact and fallback behavior reviewable. |
| Cut / flash / large motion / repeating texture | No new-shot contribution before declared cut PTS at the reconstruction stage; no cross-cut flow reuse. Check false cuts, out-of-range fallback, reason codes and bounded recovery. Physical response tails are a separate downstream expectation. |
| Sequence lifecycle | Defined first/last holds and one-frame duration; reject nonmonotonic PTS or inconsistent geometry; fresh state for independent clips. Repeat runs with fixed seed/config match. |
| Panel/ABL and observer isolation | Every output tick advances physical histories once. Do not reset them at a cut or accumulate pursuit blur into source or response state. For isolated plain lag/ABL, doubling refresh while holding targets constant must preserve fitted time constants in elapsed seconds, within declared numerical tolerance. |

**Historical-M4 caveat:** [M6's parity analysis](m6-profile-wiring.md#6-defaults-and-the-limits-of-m4-parity) records an existing QD-OLED PSF behavior change after M4: emitted spread is now applied, whereas saved M4 OLED emission ignored it. An unchanged MEMC-off path must match the **pre-MEMC current tree** exactly; it cannot promise equality to every historical artifact already changed by M5. Compare historical results separately with that documented exception; do not silently disable current optics or retune profiles to hide it. The exact historical code revision is the reference for full saved-M4 reproduction.

For motion quality, report synthetic position/trajectory error in pixels, per-region linear-luma error in nits, fallback fraction/reason and temporal switching counts. Boundary error is a MEMC diagnostic, not the existing backlight `halo_nits` metric or a standardized MPRT. Compare against known intermediate synthetic truth or withheld real high-rate frames with declared exposure/timestamps; interpolating a two-frame pair provides no independent truth. Retail-TV numerical matches, SOE ratings and quality thresholds remain **NR** until a matching measurement protocol exists.

Recommended handoff order: capture disabled baselines → rational repeat scheduler and diagnostics → analytic translation/layer reconstruction → block-estimation proxy with cut/confidence fallback → short-clip artifact comparison. Keep actual TV calibration, learned/GPU paths, video/audio plumbing and full observer/emission integration as separate milestones.
