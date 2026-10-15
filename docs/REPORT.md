# TV display simulator — M4 validation report draft

Draft date: 2026-10-16. **Awaiting the validation harness and PM comparison results.** This document reports scope and method; it does not claim an empirical validation pass.

## Purpose and interpretation

The simulator explores how backlight topology, LCD extinction, emissive load limits, tone mapping and temporal persistence affect a displayed picture. The four examples are `generic_va_fald_miniled`, `generic_ips_edge`, `generic_woled` and `generic_qdoled`.

**All profile numbers are placeholders, not measurements of specific TVs.** A technology label is a mechanism demonstration, not a calibrated product emulation. Published measurements in [M4 reference ranges](../research/m4-reference-ranges.md) provide limited plausibility anchors with explicit gaps. Earlier research priors must not be presented as published measurements.

M1 research, M2 skeleton and M3 local-dimming/HDR/temporal implementation are recorded complete in [STATUS](STATUS.md); its 36/36 test result is historical project status, not a new test run or proof of perceptual fidelity. The M4 harness is being implemented separately. Planned entry point: `python3 -m sim validate`; planned machine-readable output: `reports/metrics.json`. Exact schema, defaults and ROI definitions require review after merge. No harness results are populated here.

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

## Validation patterns and metric definitions

The following is the reporting contract to reconcile with the landed harness. Any differing implemented definition must be recorded explicitly before filling the comparison table; these are not claims about code that has not landed.

| Pattern / experiment | Metric and interpretation | Required controls / metadata |
|---|---|---|
| 4×4 ANSI checkerboard | `C_ANSI = mean(Y in white ROIs) / mean(Y in black ROIs)` from the same output frame. Save numerator/denominator and ROI masks/margins. | Declare SDR/HDR white and dimming state. Boundary-excluded patch centers differ from averaging all cells. Dimming-on result is not native contrast. |
| Separate full-white/full-black fields | Sequential/full-field contrast `C_seq = mean(Y_white) / mean(Y_black)` across separate settled runs. | Reset state between fields; specify dimming/ambient. LCD zones can turn off: very high sequential contrast does not establish ANSI performance. Tiny LCD numerical floors are not meter sensitivity. |
| Neutral windows at 1/2/5/10/25/50/100% | Peak `max(Y)` inside actual raster window; also retain mean/center luminance if available. Plot versus actual lit fraction. | Record requested nits/encoding, raster dimensions, rounded area, location and dwell. A maximum affected by sharpening is not a meter's average aperture reading. |
| Same windows on black | Halo excess outside window relative to an identically configured black baseline. Report outside maximum and mean; any near-ring metric needs exact ring geometry/units. | Keep bright-window retention too. Off-window sharpening artifacts and ambient are not uniquely backlight bloom. At 100% outside ROI is empty: N/A, not zero. Do not compare global outside mean to near-ring published data. |
| Gray / PQ ramps | Per-level residual `e_i = Y_out,i - Y_target,i`; report absolute-nit MAE/RMSE/max and level range, with signed trace where available. Relative error excludes zero and declares denominator floor. | Distinguish isolated transfer-function accuracy from end-to-end tracking. End-to-end errors include intended shoulder/ABL/leakage. Below-knee tracking and above-knee mapping need separate interpretation. No equivalence to RTINGS tracking deltas without their definition. |
| Moving neutral edge | Normalize edge between measured dark/bright plateaus; find interpolated 10% and 90% crossings. `w10–90 = abs(x90-x10)` in pixels. | Record speed in pixels/s and pixels/frame, refresh, direction, transitions, pre-roll, frame index, ROI, response and BFI settings. If multiple crossings occur, state policy/flag ambiguity. |
| Response / BFI controls | For isolated first-order response, `t10–90 = ln(9)*tau`; fixed-peak duty d lowers mean approximately by d and reduces visible hold duration to d/frame-rate. | These are analytic model checks, not measurements of a TV. Mean-preserving BFI requires headroom and can clip. Test settled stills separately from moving sequences. |

For a measured edge speed `v`, `1000*w10–90/abs(v)` gives an **edge-width-equivalent time in ms**, not automatically a standardized MPRT. Even ideal continuous rectangular hold has 10–90 edge width of approximately `0.8*abs(v)*T_visible`; its full smear support is `abs(v)*T_visible`. Neither is GtG, and the discrete seven-sample implementation may depart from the continuous result. Do not convert a single still with no moving-edge history into a measured temporal response claim.

Black denominators at zero/below floor require a documented flag or lower bound, with JSON-safe serialization; never silently replace them with a convenient finite ratio. Sustained luminance cannot be inferred from repeatedly rendering a static image without a thermal/load-history model.

## Empty comparison worksheet — PM to fill after harness merge

Blank cells are intentional. Copy/expand each row for all four profiles and each window size. Each reference entry must include source, sample, mode, protocol and uncertainty. A mismatch or missing source should be marked N/A with reason. An engineering check may pass while real-TV calibration remains unassessed.

| Profile / metric | Sim metric + run / JSON key | Reference range / citation + matched conditions | Pass/fail rule + tolerance rationale | Result / limitation |
|---|---|---|---|---|
| VA FALD mini-LED — ANSI contrast | | | | |
| IPS edge-lit — ANSI contrast | | | | |
| WOLED — ANSI contrast / black bound | | | | |
| QD-OLED — ANSI contrast / black bound | | | | |
| Each profile — sequential full-field contrast | | | | |
| Each profile — 1% peak nits / halo | | | | |
| Each profile — 2% peak nits / halo | | | | |
| Each profile — 5% peak nits / halo | | | | |
| Each profile — 10% peak nits / halo | | | | |
| Each profile — 25% peak nits / halo | | | | |
| Each profile — 50% peak nits / halo | | | | |
| Each profile — 100% peak nits; halo N/A | | | | |
| Each profile — full-field sustained nits / duration | | | | |
| Each profile — EOTF error below knee | | | | |
| Each profile — shoulder / ABL mapping | | | | |
| Each profile — moving-edge w10–90 / speed / refresh | | | | |
| Each profile — BFI brightness / blur diagnostic | | | | |

The PM should choose rules before tuning and preserve failures. Physical invariants and analytic correctness can use numerical tolerances justified by precision/sampling. Empirical fidelity needs matched measurements and uncertainty; membership in a broad technology envelope alone earns at most a plausibility assessment. The research notes' proposed tolerances are not certification requirements.

## Reproduction and remaining decisions

After the harness lands, record code revision, harness/schema version, command/arguments, profile hashes/overrides, pattern values/encoding, resolution, actual area and masks, ambient/angle, temporal reset/pre-roll, refresh/motion/BFI, and artifact paths. Record actual test output separately from the historical M3 result. Review `reports/metrics.json` plus any generated CSV/previews; attach the manifest and results to this report. Do not guess JSON keys in advance.

Open: obtain missing measured window/sustained/halo/MPRT data; choose matched device/mode targets or explicitly retain synthetic demonstrations; reconcile harness ROI/error/edge definitions with this contract; choose acceptance tolerances; assess temporal sampling convergence; decide whether post-panel ABL, OLED PSF and reflected-light ordering need future implementation work. M4 report support does not change those implementations.
