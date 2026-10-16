# TV display simulator — M4 validation report

Report date: 2026-10-16. **Values are pre-calibration, harness run on main c3abfbd.** Results below are transcribed from `reports/metrics.json`; this report does not claim real-TV calibration or an empirical fidelity pass. Another worker is re-tuning profiles and adding `reports/comparison.md`; the PM must refresh these tables after merging that work.

## Purpose and interpretation

The simulator explores how backlight topology, LCD extinction, emissive load limits, tone mapping and temporal persistence affect a displayed picture. The four examples are `generic_va_fald_miniled`, `generic_ips_edge`, `generic_woled` and `generic_qdoled`.

**All profile numbers are placeholders, not measurements of specific TVs.** A technology label is a mechanism demonstration, not a calibrated product emulation. Published measurements in [M4 reference ranges](../research/m4-reference-ranges.md) provide limited plausibility anchors with explicit gaps. Earlier research priors must not be presented as published measurements.

M1 research, M2 skeleton and M3 implementation are recorded complete in [STATUS](STATUS.md). The M4 harness is merged and produces [metrics.json](../reports/metrics.json), CSV and preview images. STATUS records 44/44 tests passing; that is historical project evidence, not a test run performed for this documentation update or proof of perceptual fidelity.

## Pipeline method as implemented

The CPU NumPy/Pillow pipeline stores float32 linear RGB in absolute nits. `Pipeline.run_linear` executes:

`decode → spatial processing → backlight/local dimming → panel → HDR shoulder/ABL → ambient → temporal`

`Pipeline.run` then encodes an 8-bit preview. Metrics must use linear output, not PNG code values. The current luminance helper uses BT.709 RGB weights. Neutral tests avoid interpreting that helper as a complete BT.2020/panel-color measurement system.

1. Decode sRGB to the selected SDR white, absolute PQ, or HLG with the selected display peak/OOTF. Default profiles use sRGB at 100-nit white: raising a panel peak does not make the source an HDR peak stimulus. HDR validation must explicitly construct PQ-encoded float patterns at declared requested nits.
2. Resize with nearest/bilinear sampling, then optional unsharp masking. These processing operations can affect pattern edges and peak readings; retain settings for profile demonstrations and disable them in isolated mechanism checks.
3. Pool maximum-channel nit demand by zone max or percentile. Expand regular zones, then apply a normalized two-Gaussian spread with separate x/y pitch scaling. FALD uses a grid; the edge proxy uses full-height strips. Clip backlight to its floor/peak. Boundary padding is an approximation.
4. For LCD, transmission is constrained by `1/native_contrast ≤ q ≤ 1`; emitted RGB is backlight times transmission. Thus dark-pixel spill approaches `B/C`, while insufficient backlight clips highlights. OLED emission instead clips target RGB directly to the emitter peak. Apply a color matrix, synthetic subpixel mosaic/recombination and an off-axis chroma-loss proxy.
5. Apply the synthetic exponential HDR shoulder, optional instantaneous APL ceiling and optional weighted-channel global limiter. Scale by luminance and project excessive RGB toward white. This is not a vendor curve or BT.2390 implementation. In the current order, APL is computed from **panel-stage output**, after panel clipping, rather than untouched source demand. The configured full-field ceiling is consequently not a guaranteed measured 100% output.
6. Add neutral diffuse reflection `reflectance * lux / pi`.
7. Apply first-order response lag with persistent frame state, optional short overdrive command, BFI duty/brightness gate, then pursuit blur as seven horizontally shifted samples. The first frame is fully settled; temporal tests need explicit history/pre-roll. The stored state precedes eye blur/BFI.

The order is a tractable reference implementation, not a coupled electro-optical/power solver. Ambient is added before temporal filtering, so the returned image can include response/BFI treatment of reflection. Use zero lux for emission/BFI comparisons; do not interpret that ordering as physical modulation of room reflections.

## Modeled mechanisms, placeholders and omissions

| Component | Implemented mechanism | Fidelity boundary |
|---|---|---|
| Transfer functions / units | sRGB, PQ and HLG conversion; float linear nits | Transfer correctness is separately testable. No complete metadata/range/chroma input pipeline or source-to-panel gamut management. |
| LCD / local dimming | Zone pooling, spread, finite extinction and capacity clipping | Profile contrast, grid, PSF and controller parameters are synthetic; no measured influence matrix/light guide, zone lag or coupled power solver. |
| OLED | Per-pixel emission and a load-dependent limiter | No fitted RGBW current allocation, QD spectra, thermal state or aging. The computed per-pixel backlight/PSF map is **not consumed by the self-emissive emission branch**, so current OLED PSF settings do not produce emitted optical halos. |
| HDR / ABL | Continuous soft shoulder; instantaneous load ceiling; optional channel proxy | Not measured window tables, watts, thermal regulation, static-logo dimming, dynamic metadata or a vendor tone mapper. |
| Subpixels / color / angle | Synthetic RGB/WRGB/triangular mosaic; matrix hook; chroma mixing | Recombination restores source pixels; no measured aperture/spectral/color-volume model. Angle proxy does not reproduce measured black/gamma/white angular curves. |
| Ambient | Uniform Lambertian neutral offset | Reflectance is unfitted; specular reflections, glare and QD ambient excitation/tint absent. |
| Temporal | First-order emitted-RGB lag, optional overdrive prefix, BFI gate and pursuit proxy | Tau is not quoted GtG. No measured transition LUT, electrical overshoot dynamics, scanout, PWM or measured BFI waveform; seven-sample blur needs convergence assessment. |
| Image processing | Resizing and unsharp masking | MEMC is stubbed/not implemented; no vendor scaler, noise reduction or deinterlacer reproduction. |
| Other paths | CPU reference and preview output | CRT/plasma, GPU path and calibrated observer/display rendering are absent. |

A preview on an ordinary screen cannot reproduce arbitrary simulated black levels or HDR peak luminance. sRGB preview values above its reference clip; output encoding/host display must not be mistaken for physical simulator output.

## Landed harness and metric definitions

Definitions were checked against [validate.py](../sim/validate.py) and [metrics.py](../sim/metrics.py). All scores use linear RGB output converted to luminance, not preview code values. The saved run is 384×216. Static patterns use fresh temporal state, whose first frame is settled; they do not simulate a dwell or warm-up. ANSI, on/off, windows and PQ ramp force PQ input; code 1 requests 10,000 nits, not the profile's nominal peak. Profile processing remains enabled. Gray ramps and moving edges use the profile input encoding (sRGB here).

| JSON field / experiment | Actual definition |
|---|---|
| `ansi.{white_nits,black_nits,contrast_ratio}` | 4×4 black/white checker; mean of each cell's central region after a 25% inset per side (integer rounding), then average white and black cells separately. Ratio is white/black. This is dimming-on HDR ANSI, not native contrast. |
| `on_off.*` | Whole-frame means from independent full-white and full-black renders. `contrast_ratio` is JSON `null` if black ≤ `1e-4` nits (or inputs nonfinite). This is a numerical reporting floor, not a simulated meter floor. |
| `windows[i].peak_nits` | **Mean of the central half of the window**, trimming one quarter per side when both dimensions permit; not a maximum pixel. Requested areas are 1/2/5/10/25/50/100%. |
| `windows[i].halo_nits` | Mean in a Chebyshev ring 1–3 pixels outside the rectangle for this resolution. `far_black_nits` is the mean at distance ≥12 pixels. |
| `bloom_excess_nits`; `bloom_above_far_nits` | Near-ring mean minus the same ring of an independent black render; near-ring mean minus this window frame's far mean, respectively. These are different baselines. All outside fields are `null` at 100%. |
| `abl_ratio_vs_smallest` | Window center mean divided by the 1% window center mean. It measures output area dependence, not watts or sustained brightness. |
| `grey_ramp.*`; `pq_ramp.*` | Column-mean luminance versus ideal decoded luminance: mean/max absolute relative error for ideal ≥1 nit; absolute-nit MAE for ideal <1 nit. Gray codes are quantized uint8 sRGB; PQ codes are float samples spanning 0–1. These are end-to-end spatial ramp errors, including mapping, optics and ABL. |
| `clipping_code`; `clipping_nits` | First sample reaching ≥95% of measured ramp peak, retained only if ideal subsequently grows >20% and measured output grows <5% of peak. Nits are measured output at that code; `null` means this heuristic did not detect clipping. It is not the shoulder knee. |
| `mprt.as_configured.{blur_px,blur_ms}` | Six moving-edge frames at 8 pixels/frame, frame time 16.666 ms (about 480 pixels/s, 60 Hz). First frame is settled; subsequent frames retain state, without separate black pre-roll. Final-frame middle-third rows are averaged; end 15% medians define plateaus, with first upward linearly interpolated 10%/90% crossings. Time = width × frame time / speed in pixels/frame. |
| `still_blur_px`; `motion_blur_px`; `motion_blur_ms` | Settled edge at final position with pursuit motion set to zero; then `sqrt(max(0, moving_width² − still_width²))`, converted by the same speed. Quadrature subtraction is an approximate diagnostic, not a physical deconvolution or standardized MPRT. |
| `mprt.bfi`; `mprt.overdrive` | All saved profiles have duty 1 and overdrive gain 0. BFI comparison uses duty 0.5 with mean preservation off; LCD overdrive probe uses gain 0.5 for a 2-ms prefix. OLED prefix duration is 0, so overdrive is unsupported. These probes are harness stimuli, not calibrated profile settings. No BFI brightness metric is saved. |

Actual raster area fractions, in requested-area order, are 0.0100791, 0.0201823, 0.0497685, 0.0991995, 0.25, 0.501736 and 1.0. Ring widths are image pixels, not the zone-pitch geometry proposed in M3 research. PNGs are independently scaled so each frame's maximum RGB nit maps to sRGB code 1; montage brightness cannot be compared radiometrically.

## Filled comparison worksheet

**Snapshot: pre-calibration, harness run on main c3abfbd. All profiles remain placeholders.** Abbreviations below map to `generic_va_fald_miniled` (VA), `generic_ips_edge` (IPS), `generic_woled` (WOLED), and `generic_qdoled` (QD-OLED). Keys are relative to `profiles.<profile>` in the saved JSON.

**In** means numerical membership in the explicitly cited sample envelope. **Out** means outside that envelope or different from an isolated anchor at its published precision. **No-reference** means no matching numerical protocol/quantity is available; qualitative agreement is stated separately. There is no invented tolerance, and none of these labels is a calibration pass/fail. Published modes, sizes, firmware, dwell and uncertainty are not matched by these generic profiles. Source IDs and their full citations/conditions are in [M4 reference ranges](../research/m4-reference-ranges.md); no earlier research prior is used as a measured range.

### Contrast and black level

| Profile / JSON metric | Saved simulator value | Published anchor | Assessment |
|---|---|---|---|
| VA `ansi` | White 1417.23; black 0.268475 nits; ratio 5278.8:1 | V1 QN95B ANSI black 0.048 nits, SDR/HDR; same-pattern white unavailable | Black **out** versus isolated anchor; TV ratio **no-reference**. V3 GP2711 monitor ~3598–3800:1 is supporting static evidence only, not a matching TV ANSI test. |
| IPS `ansi` | White 377.927; black 0.333333 nits; ratio 1133.78:1 | I1/I2 dimming-off ANSI at 120-nit white: black 0.093/0.157, derived ratios ~1290/~764 | Ratio **in** selected ~764–1290 envelope; absolute black **out** of 0.093–0.157, with different white and dimming conditions. No matched calibration conclusion. |
| WOLED `ansi` | White 312.499; black 0 nits; ratio null | W2 EG960V 0-nit meter reading on 4×4 ANSI | Qualitative black agreement; finite ratio **no-reference**. Exact synthetic zero does not establish a real meter detection limit. |
| QD-OLED `ansi` | White 399.999; black 0 nits; ratio null | Q2 sequential black 0.000; numeric ANSI NR | **No-reference** for ANSI; per-pixel dark-room black qualitatively agrees with Q3. |
| VA `on_off` | White 1417.23; black 2.5e-12 nits; ratio null | No matched sequential numeric range | **No-reference**; zones shut off, leaving a numerical floor. |
| IPS `on_off` | White 377.927; black 8.33333e-12 nits; ratio null | I1 full-black 0.066 nits at 120-nit white | **No-reference** for matched ratio; black differs under shutdown and unmatched white. Do not substitute this for ANSI black. |
| WOLED `on_off` | White 150; black 0 nits; ratio null | W2 full black 0-nit reading | Qualitative agreement; finite ratio **no-reference**. |
| QD-OLED `on_off` | White 200; black 0 nits; ratio null | Q2 S95B HDR10 Filmmaker black 0.000; contrast unmeasurable | Qualitative agreement with unmeasurable ratio; finite range **no-reference**. |

Sequential contrast is undefined under the harness floor for **all four** profiles. It must not be reported as a huge finite LCD ratio or measured infinity for OLED. In particular, backlight shutdown makes sequential LCD behavior a poor test of simultaneous contrast.

### HDR window center luminance

Values are `windows[i].peak_nits`, in nits. The final column applies to all four values unless otherwise stated.

| Requested area | VA | IPS | WOLED | QD-OLED | Published comparison / assessment |
|---|---:|---:|---:|---:|---|
| 1% | 1417.23 | 377.927 | 748.078 | 935.251 | **No-reference** for matched numeric 1% anchors; V2 reports only X95K <1000, so VA is out of that one-sided observation, not a class range. |
| 2% | 1417.23 | 377.927 | 739.877 | 925.171 | **No-reference**: independently tabulated 2% values unavailable. |
| 5% | 1417.23 | 377.927 | 713.932 | 893.315 | **No-reference** for 5% numerical values. |
| 10% | 1417.23 | 377.927 | 666.247 | 834.817 | VA **in** V1/V2 ~1300–1774; IPS **no-reference**; WOLED **out**, just below W1/W3 667–717 (and below W1 707–717); QD-OLED **out** versus Q1 977. |
| 25% | 1417.23 | 377.927 | 514.905 | 649.01 | **No-reference** for 25% numerical values. |
| 50% | 1417.23 | 377.927 | 311.373 | 398.613 | **No-reference** for 50% numerical values. |
| 100% | 1417.23 | 377.927 | 150.0 | 200.0 | VA **out** above V1/V2 591–almost 650; IPS/WOLED **no-reference** for HDR full-white; QD-OLED **out** versus Q1 199 (close numerically, no tolerance supplied). |

VA's 10% luminance matches the broad selected envelope but its flat 1–100% output does not reproduce the load dependence of either cited VA TV. LCD ABL is off in these placeholder profiles; the VA full-white result is therefore much too high versus those anchors. IPS is likewise flat; I1's 455-nit peak has no usable window size/dwell and cannot validate any row.

WOLED's 666.247-nit 10% result narrowly misses the broader 667–717 envelope; this small miss has no demonstrated significance given unmatched setups and absent uncertainty budgets. QD-OLED's 834.817-nit 10% result is below the 977-nit S95B anchor, while its 200-nit full-white result is close to 199. These are consequences of synthetic peak, shoulder and instantaneous load settings, not fits to retail sets. WOLED's 150-nit HDR full-white output must not be scored against EG960V's 149-nit unspecified-duration reading or C2's 170-nit maximum-brightness SDR result.

### Area dependence and halo worksheet

The following arrays follow 1/2/5/10/25/50/100% order. Halo/bloom/far values are nits; N/A is JSON null.

- **VA** `abl_ratio_vs_smallest`: 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0.
- **IPS** `abl_ratio_vs_smallest`: 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0.
- **WOLED** `abl_ratio_vs_smallest`: 1.0, 0.989037, 0.954355, 0.890612, 0.688304, 0.416231, 0.200514.
- **QD-OLED** `abl_ratio_vs_smallest`: 1.0, 0.989222, 0.95516, 0.892612, 0.693942, 0.426209, 0.213846.

| Profile | `halo_nits` / `bloom_excess_nits` | `far_black_nits` | `bloom_above_far_nits` | Reference assessment |
|---|---|---|---|---|
| VA | Both 0.375 at every non-full window; N/A at 100% | 0.0202, 0.03368, 0.0474551, 0.054065, 0.0708457, 0.281625, N/A | 0.3548, 0.34132, 0.327545, 0.320935, 0.304154, 0.0933754, N/A | **No-reference** numerically; positive spill qualitatively agrees with V1/V2 blooming. |
| IPS | Both 0.333333 at every non-full window; N/A at 100% | 0.333333 at each non-full window; N/A at 100% | 0 at each non-full window; N/A at 100% | **No-reference** numerically; uniform elevated black differs from a localized excess. I1 describes vertical strip blooming, not a nit threshold. |
| WOLED / QD-OLED | Both 0 at each non-full window; N/A at 100% | 0 at each non-full window; N/A at 100% | 0 at each non-full window; N/A at 100% | **No-reference** numerically; absence of LCD zone halos agrees qualitatively with W1/Q3. |

The decreasing VA near-minus-far excess does not mean absolute near-ring leakage decreases: its near mean stays constant while the far field rises. IPS has positive black-baseline excess but zero near-minus-far excess, illustrating why the two fields must not be conflated. OLED's computed PSF map is not consumed by the emissive branch; zero halo here establishes no measured optical PSF fidelity.

### Ramps, motion and remaining worksheet entries

All ramp comparisons are **no-reference**: the selected publications supply no matching end-to-end error statistic. Values below are relative-error fractions, not percent. A separate below-knee score is **not emitted** and cannot be inferred from these aggregate values.

| Profile | Gray mean / max relative error | Gray <1-nit MAE (nits) | Gray clipping code / output nits | PQ mean / max relative error | PQ <1-nit MAE (nits) | PQ clipping code / output nits |
|---|---|---:|---|---|---:|---|
| VA | 0.00116556 / 0.0351975 | 0.00164416 | N/A | 0.139351 / 0.858277 | 7.18778e-05 | 0.785901 / 1350.24 |
| IPS | 0.010599 / 0.180443 | 0.00151128 | 0.898039 / 78.331 | 0.294679 / 0.962207 | 0.000883838 | 0.642298 / 359.36 |
| WOLED | 0.000433093 / 0.00192484 | 0.000843696 | N/A | 0.288229 / 0.959832 | 3.2341e-05 | 0.655352 / 382.541 |
| QD-OLED | 0.000433092 / 0.00192484 | 0.000843695 | N/A | 0.253744 / 0.946652 | 3.23409e-05 | 0.686684 / 509.29 |

PQ error includes deliberate compression of the 0–10,000-nit source into a much lower output capacity. It is not evidence of incorrect PQ decoding. The spatial ramp also exercises local dimming and global APL limits; IPS gray clipping warrants an isolated transfer/processing check before interpretation as EOTF tracking. Near-black MAE is a separate absolute measure and must not be mixed with the relative statistic.

| Profile | Moving `blur_px` / `blur_ms` | `still_blur_px` | `motion_blur_px` / `motion_blur_ms` | Duty-0.5 BFI total width px / ms | Gain-0.5 overdrive total width px |
|---|---|---:|---|---|---|
| VA | 8.71294 / 18.1512 | 1.48553 | 8.58537 / 17.8855 | 8.0687 / 16.8091 | 8.71272 |
| IPS | 74.707 / 155.633 | 67.6726 | 31.6473 / 65.9293 | 74.7229 / 155.666 | 74.793 |
| WOLED | 7.59644 / 15.8253 | 0.774997 | 7.55681 / 15.7427 | 3.93248 / 8.19234 | N/A (unsupported) |
| QD-OLED | 7.59644 / 15.8253 | 0.774997 | 7.55681 / 15.7427 | 3.93248 / 8.19234 | N/A (unsupported) |

All motion/BFI/overdrive numerical comparisons are **no-reference**: the sources do not provide matched pursuit widths, MPRT, duty or transition probes. W1's WOLED GtG 0.3-ms best / 0.6-ms mean is a different measurement and cannot validate the ~15.8-ms pursuit result. Fast OLED transitions coexist with hold blur; BFI roughly halves its width here. VA response trailing limits the reduction. IPS's still width of 67.6726 pixels dominates the 74.707-pixel moving width: its 155.633-ms equivalent mostly reflects spatial backlight spread, not temporal response. Even the quadrature estimate is only a diagnostic; non-Gaussian spatial/temporal kernels and changing zone drive need separate controlled experiments. The slight IPS width increase under BFI/overdrive is not proof of measured worse motion performance.

BFI brightness is **not measured by the harness**. The fixed-peak, mean-preservation-off model implies reduced emission at lower duty, but no saved brightness value can be compared with W1's 25–127-nit adjustment range or I1's qualitative brightness reduction. Duty alone does not reproduce published scanning, frequency or image-duplication behavior.

Full-field sustained luminance/duration is **not modeled or measured** for every profile and has **no-reference** duration-qualified range in the selected sources. The 100% window/on-off white values are static outputs, not sustained ratings. Below-knee EOTF error, measured GtG, overshoot amplitude, thermal traces and absolute halo widths are likewise absent; no worksheet pass is inferred for them.

## Limitations and recommended next steps

1. **Calibrate against matched measurements.** Preserve this pre-calibration snapshot. After the parallel profile/comparison work merges, the PM should regenerate artifacts, refresh every table against `reports/comparison.md`, record the new revision and profile hashes, and retain out-of-range results. Choose target device/size/firmware/mode, geometry, requested nits, dimming, ambient, angle, warm-up and timing before selecting tolerances. These profiles remain placeholders even after a plausibility retune.
2. **Acquire measured LUTs and PSFs.** Fit window/load/temperature tables and channel-power behavior; obtain LCD transition/overdrive LUTs, scanning/BFI waveforms, optical influence maps and zone-controller timing. Separate measured panel extinction from dimming-on ANSI. Obtain missing 2/25/50% anchors, matched VA native contrast, QD-OLED ANSI, absolute halo profiles and 0.1/1/10/60-second full-field traces. Do not interpolate gaps into purported measurements.
3. **Isolate mechanisms and resolve model ordering.** Test transfer decoding separately from spatial ramp tracking, measure below-knee and shoulder regions separately, and isolate temporal response from static optics and changing backlight drive. Check temporal/spatial sampling convergence and longer histories. Revisit panel-stage rather than source-demand APL, coupled backlight/LCD power, emission-state filtering, reflected-light placement and the misleading unused OLED PSF fields. Current ABL has no thermal or load-history state.
4. **Extend fidelity where evidence supports it.** Measured gamut/color-volume and spectral/subpixel optics, angle curves, glare and QD ambient black rise remain absent or proxies. MEMC, CRT/plasma and vendor processing are unimplemented. Retain absolute-nit metrics; host-display previews cannot establish HDR or black-level fidelity.
5. **Build a GPU path against the CPU reference.** A future PyTorch/WebGL implementation can enable interactive sweeps and realtime preview, with the RTX 3070 host noted in PLAN as a candidate. Require numerical parity on the same patterns and convergence checks before treating speed as validation. No GPU performance result is claimed here.

## Reproduction and handoff

The source of all current values is [reports/metrics.json](../reports/metrics.json), labeled **pre-calibration, harness run on main c3abfbd**. This documentation update did not regenerate or overwrite reports. To make a separate fresh run without altering the saved artifacts:

```sh
python3 -m sim validate --out /tmp/m4out
```

Defaults are all available profiles, 384×216, motion 8 pixels/frame and six edge frames. Preserve the code revision, profile files/hashes and any overrides alongside outputs: JSON currently has no revision/hash manifest or explicit schema version, and static dwell is not recorded because it is not simulated. Keep run provenance distinct from a later calibration run. STATUS's unit-test count is not a substitute for matched empirical validation.

## Summary

M4 now has a concrete harness-based baseline and a filled comparison. IPS contrast and VA 10% brightness fall inside selected published envelopes; VA full-white and OLED 10% brightness miss the cited anchors. OLED black/halo and load-dependent behavior agree qualitatively. Missing references and mismatched protocols prevent a calibration claim: all profiles remain placeholders, and the PM must refresh this pre-calibration report after the parallel retune.
