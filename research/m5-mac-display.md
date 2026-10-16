# M5 macOS display research: absolute luminance, EDR and validation

Sources checked **2026-10-16**. Read alongside [README](../README.md), [STATUS](../docs/STATUS.md), [M5 fidelity](m5-fidelity.md) and [color/HDR research](03-color-hdr.md). This is a research and implementation specification; no Mac renderer, GPU backend or hardware calibration was performed for this note.

**Evidence:** **D** = documented API behavior or manufacturer specification, with its conditions; **C** = calculation from stated inputs; **P** = proposed project procedure/model; **NR** = not verified or not measured. Manufacturer specifications are not measurements of our host. All actual host luminance, gamut, black, precision and timing results remain **NR** until measured on the selected Mac.

The practical route is a native Metal preview fed from the simulator's linear-nit output, a documented reference preset, and instrument verification. EDR support alone does not establish physical accuracy. A brighter TV can be represented numerically on any Mac, but its light output can only be reproduced inside the host's measured color/luminance/spatial/temporal envelope.

## 1. Preserve the simulator's physical output

[Frame.rgb](../sim/frame.py) stores float32 display-referred linear RGB in nit-scaled units. [Pipeline.run_linear](../sim/pipeline.py) returns this before output encoding. [encode_frame](../sim/stages/encode.py) instead returns uint8, including for PQ; the sRGB branch clips above `reference_nits`. In addition, [validate._preview](../sim/validate.py) normalizes each image to its own maximum. These files are useful diagnostics, but neither path preserves absolute brightness comparisons for an EDR preview.

**P:** Feed `run_linear()` directly into a float rendering path. Preserve the original arrays and add explicit RGB primaries, white point and units to the transport metadata. `Frame` currently does not carry a color-space tag; the identity panel matrix and BT.709 luminance helper do not implement complete BT.2020-to-display gamut management. Do not label arbitrary existing RGB as P3. A neutral `(L,L,L)` has luminance L in the usual normalized RGB basis; an individual colored component is not itself the patch's luminance. Compute Y using the coefficients of the declared primaries.

Keep the TV's tone map, ABL, panel optics and ambient model upstream. The host preview transform is a separately recorded operation; it must not silently change the simulated TV's physical outputs or be fitted into its profile.

## 2. EDR is relative to SDR white, not an absolute-nit encoding

**D:** For a linear EDR surface, `1.0` represents the current SDR/UI white. Its luminance depends on display brightness and configuration. Apple gives the example of a 400-nit display: at 100-nit UI white, EDR 4 represents 400 nits; at 200-nit UI white, EDR 2 represents 400 nits. Thus neither EDR 1 nor a headroom value is a universal nit calibration. [Apple: performing your own tone mapping](https://developer.apple.com/documentation/metal/performing-your-own-tone-mapping).

**P/C:** For an established, approximately linear reference response, define:

```text
W = measured luminance of neutral EDR (1,1,1), in cd/m²
H = current admissible EDR component maximum
C_edr = M_tv_to_linear_P3 * C_tv_nits / W
L_neutral_ideal = W * e                       # neutral EDR component e
L_neutral_limit_ideal = W * H
```

`M` converts linear RGB colorimetry, not PQ/sRGB code values. This equation is the requested ideal response, **not** a guarantee against host black leakage, load limiting or color-volume limits. A nonzero measured black can prevent the response passing through the origin; fit the measured transfer rather than assuming black subtraction will correct content-dependent mini-LED leakage. First validate neutral patches and then colors. **C:** With measured W = 100 nits and H = 10, neutral 100/400/1000 nits request EDR 1/4/10. Changing W requires changing the conversion or abandoning the absolute-match claim. Dividing TV nits by the host peak would instead map that peak to EDR 1 and leave the host's EDR headroom unused.

### Three NSScreen quantities serve different purposes

Read the `NSScreen` associated with the preview window, rather than assuming `NSScreen.main` is the destination.

| API | Documented meaning | Project use |
|---|---|---|
| `maximumPotentialExtendedDynamicRangeColorComponentValue` | Potential EDR capability; >1 indicates EDR support. Actual available headroom may be lower. | Capability check, not the current ceiling or a nit meter. [Apple capability guide](https://developer.apple.com/documentation/metal/determining-support-for-edr-values). |
| `maximumExtendedDynamicRangeColorComponentValue` | Current maximum. Can be 1 when no onscreen content requests EDR. Changes post `didChangeScreenParametersNotification`. | Query after opting into EDR and as frames/configuration change. A value of 1 alone does not prove permanent lack of support. [Apple API](https://developer.apple.com/documentation/appkit/nsscreen/maximumextendeddynamicrangecolorcomponentvalue). |
| `maximumReferenceExtendedDynamicRangeColorComponentValue` | Zero if reference rendering is unsupported. A positive value bounds components that avoid additional hardware tone mapping; may be below the current maximum. | Use the smaller of current and positive reference maxima for a reference run, then verify with a meter. [Apple API](https://developer.apple.com/documentation/appkit/nsscreen/maximumreferenceextendeddynamicrangecolorcomponentvalue), [reference rendering](https://developer.apple.com/documentation/metal/implementing-tone-mapping-on-reference-displays). |

**P:** Observe screen-parameter and window-screen changes, reacquire the screen and capabilities after mode changes, and log all three values with time. Keep the calibration tied to display ID and preset. Pause or label an absolute-validation run invalid when that configuration changes. Opt into EDR before making a final availability decision; do not create a startup loop that disables EDR because the initial current maximum is 1.

## 3. Native Metal surface and color management

**D:** Apple's macOS example uses `CAMetalLayer`, EDR opt-in, `.rgba16Float`, and `CGColorSpace.extendedLinearDisplayP3`. The latter has P3 primaries, D65 white, a linear transfer function, and can represent values below zero and above one. It differs from ordinary `displayP3`, which uses the sRGB transfer function. [WWDC22 example](https://developer.apple.com/videos/play/wwdc2022/10114/), [extended linear Display P3](https://developer.apple.com/documentation/coregraphics/cgcolorspace/extendedlineardisplayp3), [Display P3](https://developer.apple.com/documentation/coregraphics/cgcolorspace/displayp3).

Proposed setup sketch, not a complete/tested application:

```swift
import AppKit
import MetalKit

// Configure an MTKView before obtaining its drawable.
view.colorPixelFormat = .rgba16Float
view.colorspace = CGColorSpace(name: CGColorSpace.extendedLinearDisplayP3)!
if let layer = view.layer as? CAMetalLayer {
    layer.wantsExtendedDynamicRangeContent = true
    layer.edrMetadata = nil
}

// Re-evaluate on the destination screen as rendering/configuration changes.
if let screen = view.window?.screen {
    let current = screen.maximumExtendedDynamicRangeColorComponentValue
    let reference = screen.maximumReferenceExtendedDynamicRangeColorComponentValue
    let admissible = reference > 0 ? min(current, reference) : current
    // Pass admissible and the measured W to the preview transform.
    // reference == 0 means no documented reference-rendering range.
}
```

**P:** Use an opaque patch/image region, matching FP16 render attachments, and output linear P3 EDR components from the final shader. Avoid a hidden `[0,1]` clamp, sRGB OETF, integer upload or normalized intermediate. Preserve negative components through color conversion where needed, then handle out-of-gamut colors explicitly before requesting physical output. Extended numerical coordinates do not enlarge the panel's physical gamut. Set drawable dimensions from the view's backing-pixel size; declare resampling and avoid interpolation for pixel/subpixel tests.

**D:** `CAMetalLayer.colorspace` describes the rendered content. When set, Core Animation performs necessary color-space transformations; `nil` means the content is not color-matched. ColorSync provides profile-based color management and ICC transforms. Therefore tag the **source working space** correctly and allow the display transform, or implement a separately validated complete custom pipeline. Applying a device-profile transform and then tagging the result as ordinary P3 risks a second conversion. [Layer colorspace](https://developer.apple.com/documentation/quartzcore/cametallayer/colorspace), [ColorSync](https://developer.apple.com/documentation/colorsync).

An ICC profile characterizes color response; assigning one does not measure current white luminance, force brightness, or certify HDR accuracy. On 2021-or-later 14/16-inch MacBook Pro and supported Apple displays, use the reference-mode controls; do not assume the ordinary custom-ICC selector is available. [Apple: changing display profiles](https://support.apple.com/guide/mac-help/change-your-displays-color-profile-mchlf3ddc60d/mac).

**D:** A nil `edrMetadata` means no layer-metadata tone mapping; over-range values may clip. Non-nil `CAEDRMetadata` enables system tone mapping based on content/display characteristics. Its `opticalOutputScale` describes the source scale, not a promise that all values will be emitted unchanged. **P:** Leave it nil for testing the simulator's own output transform, and stay within the validated reference range. Test any system-tone-mapped preview as a different mode, to avoid applying two HDR shoulders. This still does not bypass ColorSync or the physical display controller. [Layer EDR metadata](https://developer.apple.com/documentation/quartzcore/cametallayer/edrmetadata), [system video tone mapping](https://developer.apple.com/documentation/metal/using-system-tone-mapping-on-video-content).

### 10-bit output, FP16 and dithering are separate questions

**D:** FP16 preserves values above 1 and fine increments for composition; it does not imply a 16-bit panel. `rgb10a2Unorm` stores ten bits per RGB channel but normalized linear components still cover only 0–1. Apple also documents a valid **encoded PQ** route with `.bgr10a2Unorm` and `itur_2100_PQ`; that route interprets the codes through PQ rather than as linear EDR amplitudes. Do not mix the two encodings. [Pixel format](https://developer.apple.com/documentation/metal/mtlpixelformat/rgb10a2unorm), [10-bit PQ presentation](https://developer.apple.com/documentation/metal/using-color-spaces-to-display-hdr-content).

**NR:** MacBook Pro's advertised one billion colors does not establish native ten-bit LCD drive versus FRC/dithering for every generation. Pro Display XDR is separately specified as true ten-bit. No primary Apple source found here establishes a universal macOS temporal/spatial dithering algorithm, precision, or supported way to disable it across devices. Do not claim either that dithering is absent or that it guarantees ten-bit accuracy. [MacBook specifications](https://support.apple.com/en-us/111902), [Pro Display XDR white paper](https://www.apple.com/pro-display-xdr/pdf/Pro_Display_White_Paper_Feb_2020.pdf).

**P:** Measure smooth ramps and adjacent small code steps. If diagnosing temporal dithering, use suitable high-speed optical acquisition, with fixed refresh/exposure, separating PWM, panel response and camera aliasing. Optional application dithering should be a documented preview choice, added at the relevant quantization boundary; it can reduce banding but cannot recover gamut or luminance headroom.

## 4. Liquid Retina XDR capabilities and reference modes

| Display / evidence | Published capability | Qualification |
|---|---|---|
| 14-inch MacBook Pro, 2021 | HDR: **1000 nits sustained full-screen, 1600 nits peak**; SDR: **500 nits**; P3, one billion colors. | Apple specification; peak footnote requires ambient below 25°C. [Model-specific specification](https://support.apple.com/en-us/111902). |
| 16-inch MacBook Pro, 2024 | HDR: **1000 sustained / 1600 peak**; SDR: **up to 1000 nits outdoors**. | Peak footnote requires temperatures below 25°C. [Stable model-specific specification](https://support.apple.com/en-us/121554). |
| Current 14/16-inch Liquid Retina XDR MacBook Pro page, checked on the date above | Same **1000 sustained / 1600 peak HDR** figures; SDR **up to 1000 nits outdoors**. | Outdoor SDR is not a fixed calibrated slider setting. Archive the exact model's specification for a run. [Current specifications](https://www.apple.com/macbook-pro/specs/). |
| Pro Display XDR, separate external display | 1000 nits full-screen sustained; 1600-nit highlights up to **39%** of screen area, with the remaining area black or no brighter than 500 nits, at up to 25°C. | **Do not transfer the 39% condition to MacBook Pro.** [Apple white paper](https://www.apple.com/pro-display-xdr/pdf/Pro_Display_White_Paper_Feb_2020.pdf). |

**NR:** The cited MacBook specifications do not provide a complete 1600-nit window-size/dwell curve, saturated-color brightness envelope, or guarantee that our exact content will attain peak. Do not label 1600 nits sustained full-screen. Ordinary Retina/SDR Macs require their own specs and EDR queries; they do not inherit XDR limits.

**D:** In System Settings → Displays → select the display → Preset, MacBook Pro offers **Apple XDR Display (P3-1600 nits)** for general use. **HDR Video (P3-ST 2084)** targets P3/PQ production up to **1000 nits full-screen sustained** in controlled BT.2100 conditions. **HDTV Video (BT.709-BT.1886)** and **Internet and Web (sRGB)** address different SDR workflows. Modes set color space, white point, gamma and brightness; some disable brightness, True Tone, Night Shift and automatic-brightness controls. [Apple preset guide](https://support.apple.com/en-us/108321).

Apple's Pro Display XDR developer talk describes HDR Video with **100-nit SDR white / 1000-nit HDR maximum**, hence headroom 10; it also explains that general-use presets and reference presets have different reference-rendering behavior. **P:** Start MacBook absolute-output work in HDR Video, query its reference maximum and measure W; do not assume that every preset or later custom setting has this same mapping. A PQ-based display preset does not require PQ-encoding an already linear Metal EDR surface. [Apple developer talk](https://developer.apple.com/videos/play/tech-talks/10023/).

**D:** Custom reference modes expose gamut, white point, transfer function and luminance options. Apple's full-screen-capability limit restricts maximum luminance to 1000 nits at D65 under normal conditions. Available options depend on display/OS. **P:** Record/export the complete custom preset; do not identify a mode from headroom alone. [Custom modes](https://support.apple.com/guide/mac-help/create-custom-reference-modes-mchl50ecf3c4/mac).

**D:** Apple documents brightness limiting after extended bright content at high ambient temperature. Monitor the warning icon and repeated reference-patch readings. A published peak is not a per-frame stability guarantee. [Brightness limiting](https://support.apple.com/en-us/101865). Current support pages also discuss **Studio Display XDR** and 2000-nit presets; these are a different product, not an upgrade to MacBook's 1600-nit specification. [Preset guide](https://support.apple.com/en-us/108321).

## 5. Calibration and measurement setup

**P:** Use AC power, fixed display mode/refresh and stable room lighting. Turn **True Tone**, **Automatically adjust brightness / ambient light compensation**, and **Night Shift** off where available; ensure schedules cannot re-enable them. Disable any active display color filters, inversion, third-party brightness utilities and battery dimming for the run. These are repeatability controls, not TV-profile parameters. True Tone changes color/intensity with ambient light, auto-brightness changes brightness, and Night Shift warms colors. [True Tone](https://support.apple.com/en-us/102147), [brightness controls](https://support.apple.com/guide/mac-help/change-your-displays-brightness-mchlp2704/mac), [Night Shift](https://support.apple.com/en-us/102191).

Fix the brightness slider if the mode permits it. **P/inference:** Its position is not a calibrated nit reading or a universal linear scale. Measure W through the **actual renderer**, record the setting, and remeasure after any change. Raising SDR brightness can reduce the EDR ratio without increasing physical peak; lowering it does not create extra peak nits. Reference modes may lock these controls, so do not prescribe a universal slider percentage.

**D:** Apple recommends a dim/dark room, control of stray light, ambient at or below about 25°C, at least 30 minutes of display warm-up and thermal stability, perpendicular meter alignment, and appropriate exposure/integration settings. It supplies tagged QuickTime test patterns and `Reference Values.txt`; match patterns to the preset and compare luminance/EOTF and chromaticities. This provides an independent check before testing our renderer. [Apple measurement procedure](https://support.apple.com/en-us/105101); patterns: [AVFoundation → Related Resources → Color Test Patterns](https://developer.apple.com/av-foundation/).

**P:** A suitable colorimeter can measure luminance/xyY and monitor repeatability, but needs adequate luminance range, near-black sensitivity and a correction appropriate to the display spectrum. Prefer checking/profiling it against a calibrated spectroradiometer on the actual display. Spectral mismatch can bias even repeatable readings; do not treat an arbitrary consumer meter as an absolute reference. [Portrait Displays: meter profiling](https://www.portrait.com/resource-center/meter-profiling-in-calman/). Record meter model/serial, calibration date, spectral correction, aperture/spot size, distance, integration and uncertainty/detection floor. Below its reliable floor, report an upper bound or NR, not zero black or infinite contrast.

**D:** Apple's macOS 26 Full Calibration guide supports selected spectroradiometers **and colorimeters**, including Calibrite Display Plus HL and Colorimetry Research CR-100; CR-100 requires a manufacturer-software matrix profile. Compatibility is instrument/OS-specific. It requires power for a MacBook calibration. Do not generalize an older spectroradiometer-only workflow or promise arbitrary colorimeter compatibility. [Full Calibration](https://support.apple.com/guide/mac-help/full-calibration-pro-display-calibrator-mchl628f5edf/26/mac/26).

Fine-Tune Calibration adjusts measured/target white point and luminance; supported MacBook presets can be fine-tuned separately. **P:** A white-point adjustment does not validate grayscale, saturated colors or HDR tracking. Recheck holdout patches after changes and preserve before/after records. [Fine-Tune Calibration](https://support.apple.com/guide/mac-help/fine-tune-calibration-pro-display-calibrator-mchlee9c1884/26/mac/26).

**NR:** Meter accuracy on our host remains unmeasured. New Studio Display XDR calibration/CMF requirements must not be assumed for Liquid Retina XDR; use the calibration space documented for the actual device/preset. [Apple measurement compatibility](https://support.apple.com/en-us/105101).

## 6. A dimmer host cannot emit the brighter TV's light

The following are **P/C preview strategies**, not claims of perceptual equivalence. Let `L_T` be simulated luminance and `L_H` a conservative **measured** host limit for the required area, duration, colors and reference mode. Also require that each converted color component fits and the host black floor is adequate; a neutral peak alone is insufficient.

| Strategy | Mapping | What the viewer can conclude |
|---|---|---|
| Absolute match inside the host envelope | `L_preview = L_T` | Measured luminance matching only for validated colors, geometry, times and black levels. Flag unrenderable values. |
| One shared linear exposure | `L_preview = s * L_T`, `0 < s <= 1` | Preserves luminance ratios within the common unclipped range, while changing absolute luminance/adaptation. Apply the same s to every TV and every compared frame. |
| Shared highlight shoulder / tone map | `L_preview = T(L_T)` | Makes more detail visible but changes highlight ratios and possibly local contrast/color. Record T, its parameters and the common scale; label the view tone-mapped. |
| Hard clip | `L_preview = min(L_T,L_H)` | Preserves lower values but destroys distinctions above the limit. Mark clipped regions. |
| False-color/plots/raw data | Encode nits or errors diagnostically | Supports quantitative comparison beyond the physical preview's limits; does not reproduce appearance. |

**C:** If a measured host supports 600 nits in the test condition and compared TVs reach 3000 and 1000 nits, common `s = 600/3000 = 0.2` produces 600 and 200 nits. Independently scaling each TV to 600 would erase their 3:1 peak difference. Fix the common scale over a temporal sequence too, so auto-exposure does not conceal ABL or pumping. For a luminance tone map, `RGB' = RGB * T(Y)/Y` (zero at Y=0) preserves chromaticity before gamut limits; subsequent clipping/gamut mapping can change it.

Lowering host SDR white can expose more **relative EDR headroom** but cannot make a 600-nit panel emit 3000 nits. A host black floor cannot be corrected by negative emitted light. Ambient reflections, gamut, angular screen size and adaptation also differ. Increasing software bloom or contrast cannot prove equivalent brightness perception.

**P/inference:** A mini-LED Mac's own dimming/optical halo is applied after the simulated TV halo, and its sample-and-hold/response follows simulated temporal processing. Thus even in-range nit matching does not establish OLED-black, halo, subpixel, BFI or motion fidelity. Spatially dependent host errors cannot generally be removed with a one-dimensional calibration LUT. Treat absolute luminance, color, spatial structure and temporal accuracy as separate validation claims; use an appropriate external display when the host fails the needed envelope.

## 7. PyTorch MPS caveats for a later GPU path

The versioned PyTorch links below use the 2.14 documentation snapshot; the development dtype note is identified separately. MPS accelerates computation; it does not opt a window into EDR, assign P3, calibrate nits or present a tensor. **P:** Keep native presentation separate from the tensor backend. Zero-copy PyTorch-to-drawable interoperability and real-time performance are **NR** here; unified memory alone is not proof of either.

- **Version/device support is conditional.** Apple's currently checked PyTorch instructions name Apple silicon, macOS 14+ and Python 3.10+ for their documented installation. Requirements vary with the PyTorch release; record actual hardware, macOS, Python and wheel/build versions. Check `torch.backends.mps.is_built()` and `is_available()` on the target. Do not repeat an unconditional historical “macOS 12.3+” minimum. [Apple installation guide](https://developer.apple.com/metal/pytorch/), [PyTorch MPS notes](https://docs.pytorch.org/docs/2.14/notes/mps.html).
- **Float64 is a porting issue.** MPS does not support float64 tensors; CPU fallback does not solve allocation/transfer of an unsupported dtype. The explicit explanation is in PyTorch's **development** documentation, so verify the installed release as well. [MPS double-precision limitation](https://docs.pytorch.org/docs/main/notes/mps.html#double-precision-types). Our [color functions](../sim/color.py) and [filters](../sim/filters.py) use float64 intermediates despite float32 `Frame` storage. A float32 GPU implementation changes arithmetic; keep the CPU path as the numerical reference.
- **Operator support and math settings matter.** `PYTORCH_ENABLE_MPS_FALLBACK=1` permits CPU fallback for unsupported operations; fast math and preferred Metal matmul are separate switches. **P:** First validate with fallback disabled and fast math off, then explicitly assess any mixed CPU/GPU path. Record relevant environment variables. Transfer/synchronization costs are an engineering concern, not a measured slowdown here. Do not disable allocator safeguards to force a larger workload; PyTorch warns that a zero high-watermark ratio can cause system-wide OOM. [MPS environment variables](https://docs.pytorch.org/docs/2.14/mps_environment_variables.html).
- **No blanket bitwise-parity guarantee.** Floating-point operation/reduction order can differ across CPU/GPU and releases. This is not evidence that every MPS operator is nondeterministic. **P:** Compare stage outputs and several temporal frames for ramps, PQ/HLG, filters, percentile/zone reductions, ABL and all profiles. Use absolute nit errors near black and relative error above a declared floor; specify tolerances before accepting the port. [Numerical accuracy](https://docs.pytorch.org/docs/2.14/notes/numerical_accuracy.html), [reproducibility](https://docs.pytorch.org/docs/2.14/notes/randomness.html).
- **Benchmark completed work.** `torch.mps.synchronize()` waits for MPS kernels. **P:** Warm up, synchronize before/after timed computation, and separately time tensor transfer, render submission and presentation; avoid measuring only asynchronous submission. Track tensor and driver allocations with the appropriate MPS memory APIs. Actual end-to-end FPS/latency and precision remain NR until a Mac run. [torch.mps APIs](https://docs.pytorch.org/docs/2.14/mps.html).

## 8. Proposed accuracy validation on a Mac

This is **P**, a project protocol, not Apple certification. Validate the host renderer before judging the simulator's TV mechanisms.

1. **Create a run manifest.** Record Mac/display identifier and model, glass option, OS/build, firmware, connection and HDR setting for an external display, preset/custom export, ICC identity where applicable, refresh/backing resolution, power, brightness controls, ambient lux/temperature, viewing/meter geometry, instrument correction/uncertainty, app commit and GPU/backend settings. Log W and all NSScreen EDR values. Record which values are NR.
2. **Establish an independent baseline.** Prepare the display as in §5. Measure Apple's tagged patterns in the matching preset against their reference file. If this fails, investigate preset/meter/display setup before attributing errors to our shaders. That test validates that playback path; it does not automatically validate our Metal path.
3. **Measure direct renderer patches.** Bypass TV simulation and render known linear P3 neutral values through the intended transport/shader/layer. Measure black, EDR 1, and a sweep corresponding to, for example, 0.1/1/10/50/100/200/400/600/1000 nits where admissible. Add near-black steps only within meter capability. Test 1600 separately only if the selected mode/reference range permits it; flag requests outside the envelope. Verify the relation `L ≈ W*e`, clipping onset, and absence of an unintended OETF or second tone map.
4. **Test color separately.** Measure RGB, CMY, white and intermediate saturation/luminance patches within the declared host volume. Calculate expected XYZ/xyY from the known linear RGB basis, not a blanket BT.709 luma coefficient. Check P3-tagged and correctly converted BT.709 inputs representing the same XYZ. Save out-of-gamut cases as a separate gamut-mapping test, not failures of an impossible absolute target.
5. **Characterize area, position and history.** Repeat neutral levels with 1/2/5/10/25/50/100% area windows, fixed surrounds and several screen positions. Ensure the meter's entire measurement spot/field of view fits inside each patch, especially small windows on a laptop; surround contamination can mimic area-dependent dimming. Save luminance at defined times, e.g. 0.1/1/10/60 seconds when the instrument can resolve them; otherwise mark unavailable timings NR. Include checkerboards, black beside a highlight and subtitle/star patterns. Repeat start/end reference patches and hot/cool runs. Build a measured host envelope rather than using 1600 for every condition. This detects host dimming, blooming, drift and nonuniformity.
6. **Exercise configuration changes.** Move the window between displays; change brightness/preset, then restore the calibrated configuration. Confirm headroom notifications, display identification, W invalidation and remeasurement. Keep a measurement window wholly on one display. Verify capture artifacts only for software diagnostics: even an HDR screenshot cannot measure emitted light, thermal limiting or panel optics. Supported recent Macs can capture HDR HEIF, so “all screenshots are SDR” is also incorrect. [Apple screenshot formats](https://support.apple.com/en-us/102646).
7. **Validate the complete simulator path.** Present saved `run_linear()` outputs and compare meter readings to the **post-preview-transform** expected XYZ/Y. Preserve original simulated nit arrays. In scaled mode compare against `s*L_T`; in tone-mapped mode compare against T, never claim the screen emitted the original nits. Compare identical raw frames through CPU/MPS before display so numerical and presentation errors are distinguishable. Reuse the existing harness's window/ANSI/ramp concepts, but avoid its per-image-normalized PNGs for absolute testing. Use a photodiode/high-speed acquisition for response/BFI/PWM claims; an integrating colorimeter cannot resolve the waveform by its averaged reading.
8. **Report errors and the validated envelope.** Save per-patch expected/measured XYZ, xyY, absolute nit residual, relative Y error above a declared floor, repeats, uncertainty, window/surround/time and headroom trace. Declare acceptance tolerances before measurement, based on intended use and instrument capability; no universal ±1% or sub-nit guarantee is established by this research. As an example project gate, 2% luminance error above 1 nit may be chosen only with an adequate uncertainty budget; this is not an Apple specification. Report low-light absolute errors/detection limits separately. Publish worst cases as well as averages, and explicitly mark failed/out-of-envelope conditions.

Required deliverables from that future experiment are the run manifest, raw readings, reference arrays, error tables/plots, host window/time/color limits and a statement of which claims passed. Until then, “EDR enabled” means an output capability, and the project's placeholder TV profiles remain synthetic rather than calibrated emulations of named televisions.
