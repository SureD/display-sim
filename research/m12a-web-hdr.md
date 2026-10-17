# M12a: Chrome/macOS HDR web preview

Sources checked **2026-10-17**. Read [M5 display research](m5-mac-display.md) for native EDR and physical validation. This note distinguishes a browser's accepted configuration from measured light output. **No macOS HDR display or photometer was available for this implementation.** The local test browser reports Google Chrome **154.0.8037.97** on Linux; its headless rendering cannot validate macOS EDR, physical nits, gamut, or display precision.

## Supported routes and runtime checks

Chrome documented WebGPU extended-range presentation in **Chrome 129**. The explicit presentation request is `toneMapping: {mode: "extended"}` with an `rgba16float` canvas. Standard mode limits output to the display's SDR range; extended mode permits the display's HDR range where available. Successful configuration is not an optical measurement. [Chrome 129 announcement](https://developer.chrome.com/blog/new-in-webgpu-129#hdr_support_with_canvas_tone_mapping_mode), [shipping entry](https://chromestatus.com/feature/6196313866895360).

The newest checked Chrome announcement, dated **2026-10-15**, adds `srgb-linear` and `display-p3-linear` canvas color spaces in **Chrome 155–156**. Probe a linear color space and retry with the older transfer-encoded space when it is rejected; do not assume the installed browser is already new enough. Keep the extended tone-mapping request in either case. [Chrome 155–156 announcement](https://developer.chrome.com/blog/new-in-webgpu-155-156#srgb-linear_and_display-p3-linear_color_spaces).

```js
const config = {
  device, format: "rgba16float", alphaMode: "opaque",
  toneMapping: {mode: "extended"}, colorSpace: "display-p3-linear",
};
try {
  context.configure(config);
} catch {
  config.colorSpace = "display-p3";
  context.configure(config);
  // Final shader must now apply the extended sRGB encoding transfer.
}
// Inspect getConfiguration() when available, including toneMapping.mode.
```

**Color encoding matters:** `display-p3` uses the sRGB transfer function, whereas `display-p3-linear` is linear. Neither the `rgba16float` format nor extended tone mapping implicitly changes that interpretation. For the older P3 route, first convert the simulator's declared linear RGB primaries to linear P3, divide by the calibrated white luminance, then apply the extended sRGB encoding transfer per component. Do not clamp the encoded HDR result to one. Directly writing linear amplitudes into a transfer-encoded P3 canvas gives the wrong light ratios. The standard defines the canvas spaces and requires conversion to the output device. [WHATWG canvas color spaces](https://html.spec.whatwg.org/multipage/canvas.html#color-spaces-and-color-space-conversion), [WebGPU color spaces and encoding](https://gpuweb.github.io/gpuweb/#color-spaces-and-encoding).

Canvas 2D floating-point backing storage and `rgba-float16` `ImageData` shipped separately, with a Chrome 137 shipping milestone. Request `getContext("2d", {colorSpace: "display-p3", colorType: "float16"})` and inspect `getContextAttributes()`; test the `ImageData` constructor too. **Precision support alone does not opt into extended presentation.** Current Chromium source still marks `CanvasHDR` and `CanvasToneMapping` experimental. A detected `configureHighDynamicRange({mode: "extended"})` may provide an experimental route, but it is not a dependable requirement for ordinary Chrome installations. Prefer the shipped WebGPU presentation route. [Chromium shipping intent](https://groups.google.com/a/chromium.org/g/blink-dev/c/w_3cqYiwFhU/m/EKFm06RNCgAJ), [Chromium runtime feature definitions](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/third_party/blink/renderer/platform/runtime_enabled_features.json5).

If WebGPU is unavailable, configuration is rejected, or the device is lost, use a fresh canvas for **WebGL2 SDR**; context types cannot be changed on an existing canvas. Keep the float16 nit assets upstream, apply the shared preview transform in the shader, encode sRGB, and label the result SDR. A final 2D SDR fallback keeps the page usable if WebGL2 is unavailable. Neither fallback creates HDR through extra numerical range in an intermediate texture.

## Capability and headroom are different

Use `matchMedia("(dynamic-range: high)")` and `matchMedia("(color-gamut: p3)")`, with change listeners. The dynamic-range query indicates capability, **not whether HDR is currently active**, and returns no nit ceiling. Gamut detection is approximate and separate from brightness. [Media Queries Level 5](https://www.w3.org/TR/mediaqueries-5/#dynamic-range).

There is no generally available numeric headroom API to assume. The July 2026 CSS HDR draft explicitly describes direct headroom exposure as restricted. Display **“not exposed by this browser”** when no supported property is available; do not invent a MacBook ratio or turn `high` into a number. [CSS Color HDR draft](https://www.w3.org/TR/2026/WD-css-color-hdr-1-20260728/#headroom).

For an optional user-initiated diagnostic, `getScreenDetails()` requires a secure context and Window Management permission. Handle denial and missing properties without blocking preview. Observe current-screen changes if permission is granted. [Window Management specification](https://www.w3.org/TR/window-management/#api-window-getScreenDetails).

Chromium's experimental `ScreenDetailed` properties have **different units**: `hdrHeadroom` is log2 stops (`ratio = 2 ** hdrHeadroom`), while obsolete `highDynamicRangeHeadroom` is already a linear ratio. Zero stops means ratio one. Show the property/source and units, and do not present the value as a photometer measurement. Feature presence and runtime status vary. [Chromium interface](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/modules/screen_details/screen_detailed.idl), [Chromium getters](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/modules/screen_details/screen_detailed.cc).

## Calibration and honest preview modes

The following is a **project mapping model**, conditional on a measured approximately linear response. Let `W` be the measured luminance of the renderer's neutral linear `(1,1,1)` patch and `H` the selected linear component ceiling. Then `C_request = M * C_nits * scale / W`. Unit white is a relative browser reference, not a universal 100- or 203-nit constant. Measure the patch through the same renderer as the scenes; keep its area/surround and display settings fixed. A single white measurement calibrates a scale, not the whole EOTF, black level, gamut, ABL, or time response. Validate additional known-nit neutral patches and a step wedge; annotate targets as requested/predicted until measured.

Use **scaled** for one common multiplier across both TVs and the whole sequence. This preserves ratios before clipping while changing absolute luminance. Use **clipped** for unit scale with an explicit selected component ceiling; it destroys over-ceiling distinctions. An assumed/user-entered ceiling must be labeled as such. If headroom is unknown, a conservative ceiling of one is an assumption, even on an HDR-capable screen. Never normalize each TV/frame independently. The TV simulation and its upstream tone map/ABL remain unchanged.

Chrome, macOS, the chosen display preset, user brightness, ambient adaptation, power/thermal behavior, and display hardware determine the emitted light. JavaScript cannot set the system brightness or native reference preset, bypass the compositor's mapping, read Apple's `NSScreen` EDR values, or certify absolute luminance. Recalibrate after changing display, preset, brightness, or relevant viewing conditions. A screenshot verifies software/layout only. The native measurement protocol and limits remain in [M5 display research](m5-mac-display.md).
