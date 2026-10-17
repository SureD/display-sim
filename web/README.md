# Static TV preview · M12a

**All four TV profiles contain placeholder parameters. This is a synthetic comparison tool, not a calibrated reproduction of named TVs.** The browser preview is a separate presentation transform over the simulator's linear-nit output. The existing simulator outputs and defaults are unchanged.

## Run

From the repository root, with the project's Python dependencies installed:

```sh
python3 -m sim export-web
python3 -m http.server 8000
```

Open **http://localhost:8000/web/** in Chrome. No bundler, npm install, or build step is required. Use localhost for the secure-context requirements of WebGPU; an arbitrary plain-HTTP LAN URL may disable it. Loading `index.html` with `file://` is not supported because the page fetches its manifest and binary assets.

The default export writes `web/data/manifest.json`, frames, and profile snapshots at 256 × 144 logical resolution. To regenerate with different settings:

```sh
python3 -m sim export-web --width 320 --height 180 --motion-frames 24
python3 -m sim export-web --help
```

The minimum export resolution is 160 × 96. `--out` changes the output directory; the page expects its manifest at `data/manifest.json`, so use `--out web/data` for this viewer. Frame files are generated assets and can be regenerated from the Python source.

M15 colorimetry is a separate **default-off** choice:

```sh
python3 -m sim export-web --colorimetry --source-primaries bt2020 \
  --colorimetry-output bt2020 --out web/data
```

`--source-primaries` declares the RGB container, independently of PQ. The M15
output basis can be `bt2020`, `display_p3`, `xyz` or `bt709`; the default is
linear BT.2020. Its manifest carries source/panel xy and white, derived matrices,
P mapper/volume settings, NR measurement fields and exact sidecar snapshots.
BT.2020/D65 sources also include synthetic primary/secondary windows, saturated
ramps, illustrative skin/foliage colors and a hue sweep. All four panels remain
P placeholders. This path changes the simulated color behavior only when opted in.

The viewer converts the declared linear coordinates to signed linear BT.709
using `format.to_linear_srgb`, then the WebGPU renderer converts to Display P3.
Negative wide-gamut coordinates survive both conversions until the final host
gamut/component clip; SDR fallbacks clip their BT.709 presentation. Linear XYZ
uses X/Y/Z channels and Y in cd/m². Signed RGB components are coordinates, not
negative emitted light. Exposure, calibration and host HDR limits remain
separate from the TV model. Default exports retain their original asset bytes
and linear BT.709 interpretation.

## Use the viewer

Choose a TV independently for A and B, then select one shared gallery scene: stars, subtitles, narrow/wide bright windows, ramps, logical subpixels, synthetic aperture macro, or the pan sequence. Drag either image to pan both views, scroll or use Zoom to inspect pixels, and use Reset view to restore the framing. Subpixel macro opens the existing area-normalized aperture model. Its geometry and concentrated peaks are illustrative, not measured physical emitter dimensions or luminance.

For the motion scene, Play advances the exported CPU frames; the timeline allows frame inspection. The default export holds 12 pre-roll frames, then saves 24 frames using one persistent response/load pipeline per profile, with an 8-pixel/frame pan and synthetic pursuit integration. The manifest records the frame duration and effective settings. Playback wraps to the saved first frame and therefore resets the saved history at that boundary. Browser scheduling and the host panel add their own temporal behavior; this is not a photometric motion-response experiment or live simulation.

## HDR capability and renderer selection

Sources were checked **2026-10-17**; see [the detailed Chrome research](../research/m12a-web-hdr.md). Chrome's shipped WebGPU HDR route uses `rgba16float` and `toneMapping: {mode: "extended"}`. The viewer tries that route first, requests `display-p3-linear`, and retries with `display-p3` when the linear space is unavailable. In the latter case the final shader applies the extended sRGB encoding transfer to linear P3 values, preserving values above one. P3 primaries are not a substitute for this transfer-function conversion. [Chrome 129 HDR support](https://developer.chrome.com/blog/new-in-webgpu-129#hdr_support_with_canvas_tone_mapping_mode), [Chrome 155–156 linear canvas spaces](https://developer.chrome.com/blog/new-in-webgpu-155-156#srgb-linear_and_display-p3-linear_color_spaces).

If WebGPU is unavailable or fails, the viewer uses **WebGL2 SDR**. A **Canvas2D SDR** emergency fallback keeps the controls and images usable if WebGL2 also fails. SDR output clamps its presentation components to one. Canvas2D `colorType: "float16"` and `rgba-float16` ImageData support alone do not enable HDR presentation; Chromium's separate 2D HDR presentation APIs remain experimental, so this page does not depend on flags. The active renderer is shown on screen. [Chrome float canvas shipping intent](https://groups.google.com/a/chromium.org/g/blink-dev/c/w_3cqYiwFhU/m/EKFm06RNCgAJ), [Chromium runtime feature definitions](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/third_party/blink/renderer/platform/runtime_enabled_features.json5).

The panel reports `matchMedia("(dynamic-range: high)")` and `matchMedia("(color-gamut: p3)")`. These are capability signals: `high` does not establish an active HDR mode, current numeric headroom, or a nit ceiling. The page does not request Window Management permission to inspect screens. Where numeric headroom is unavailable, it says **“Not exposed by browser.”** [Media Queries specification](https://www.w3.org/TR/mediaqueries-5/#dynamic-range), [CSS HDR headroom limitations](https://www.w3.org/TR/2026/WD-css-color-hdr-1-20260728/#headroom).

**Requested component ceiling** is a manual preview setting, separate from reported headroom. Its initial assumption is 4× only when both WebGPU extended presentation and the HDR media query succeed. Otherwise the effective ceiling is fixed to 1×, including an extended-capable surface on a currently SDR-reported display. Four is not a detected Mac/display limit. Set a conservative value verified with the wedge; extra requested range cannot make an SDR host emit HDR. A successful extended canvas configuration does not prove any particular emitted brightness.

## Brightness mapping and meter calibration

Both TVs use the same settings, including every frame in a motion sequence. For neutral simulated luminance `N`, define `C` as the requested component ceiling, `P` as Shared scene ceiling in nits, `W` as White at component 1 in nits, and `E = 2 ** EV`:

| Mode | Requested linear component | Interpretation |
| --- | --- | --- |
| **Scaled · relative brightness comparison** | `e = min(C, N * E * C / P)` | A shared linear scale maps the selected scene ceiling to `C`; relative differences survive until clipping. Absolute source nits change. |
| **Clipped · calibrated-white request** | `e = min(C, N * E / W)` | Requests a white-calibrated scale and discards distinctions above `C`. At 0 EV it predicts source-nit matching only within a separately validated host response. |

The shared scene ceiling starts at **2000 nits** and stays fixed when changing scenes or TV selections. A lower-peak scene such as motion may therefore appear dim; explicitly lower this control, for example to 100 nits, when a brighter relative preview is useful. That changes the common scale and is not an automatic normalization.

RGB uses the corresponding source-to-canvas color conversion; gamut/component limits can further change saturated colors. The exported arrays retain their original linear nits. There is no independent per-TV or per-frame normalization, live upstream ABL adjustment, or extra TV tone map in these controls. Exposure is a common preview change.

`W` starts at an **unmeasured assumption of 100 nits**. To calibrate:

1. Keep the window wholly on the target display, fix its brightness/preset and viewing conditions, and position a luminance meter so its measurement area fits inside the reference patch.
2. Measure **the fixed component-1.0 patch**, which bypasses the scene mapping and exposure. Enter measured cd/m² in the adjacent field and choose Use reading. This supplies `W`; it changes the clipped-mode nit-to-component mapping.
3. Check several neutral steps in the wedge: **0, 10, 50, 100, 200, 400, 1000, 2000** simulated nits. The wedge uses the same current transform as A/B. Its labels are inputs, not measured screen luminance; in scaled mode compare the meter against `W * e`, not the original label.

A one-point reading fits one multiplicative scale under a linear-response assumption. It does not calibrate black, the complete EOTF, gamut, area-dependent dimming, thermal response, or HDR headroom. The selected ceiling is still a separate setting; merging upper steps can indicate clipping or further host mapping. A white reading does not make all requested nits physically reproducible.

Calibration is kept only for the browser tab session, not as a permanent display profile. Use Clear reading and remeasure after moving the window, changing display/preset/brightness, or changing browser/display configuration. The web platform cannot reliably identify every condition change or automatically keep a reading valid.

**Chrome and macOS own the final brightness mapping.** The page cannot set the system brightness slider, select a native reference preset, bypass ColorSync/compositing, query Apple's native `NSScreen` EDR values, or force a requested nit value to be emitted. Host peak limits, black leakage, gamut, local dimming, power, temperature, ambient adaptation, and viewing geometry still apply. The host also adds its own optics and temporal response on top of the simulation. The [native display research and measurement protocol](../research/m5-mac-display.md) describe the additional validation needed for physical accuracy.

## Data and provenance

`python3 -m sim export-web` uses `Pipeline.run_linear()` through the existing gallery protocol. Every `.f16` is headerless **IEEE 754 binary16, little-endian**, with **frame-major HWC RGB** layout, top-to-bottom rows, three channels, and no alpha. An asset of `F × H × W` pixels has `F * H * W * 3 * 2` bytes. Frame `i` starts at `i * frame_stride_bytes`; RGB channels are interleaved.

Default values are absolute linear-nit channel intensities under an explicit **linear sRGB / BT.709 primaries, D65** preview interpretation. Neutral `(N,N,N)` represents `N` cd/m² in the model; one colored channel value is not itself the patch's luminance. The default profiles have synthetic matrices and no calibrated spectral/gamut model. PQ is used to feed the existing pipeline, without implying BT.2020 primaries for these procedural scenes. M15 instead supplies the declared basis and matrices described above. No output OETF or SDR normalization is baked into either transport.

The schema-version-1 manifest includes:

- Transport interpretation, dimensions, frame counts/strides, byte lengths, SHA-256 hashes, and statistics from decoded float16 values, including quantization error.
- All four profile settings plus copied profile, provenance, and angular YAML snapshots with hashes; the effective gallery overrides are recorded separately.
- Scene source hashes, implementation-file hashes, motion pre-roll/timestamps, and the saved-loop boundary qualification.

The profile/provenance panel and linked manifest make the source assumptions inspectable. Preserve the original float32 pipeline output when doing numerical fidelity work: binary16 export introduces quantization, especially in very dim values.

## Verify

From the repository root:

```sh
python3 -m pytest -q
python3 -m sim export-web
python3 -m http.server 8000
```

With the server running, in another terminal:

```sh
node web/tests/smoke.cjs
```

The browser smoke test launches `/usr/bin/google-chrome` headlessly without npm dependencies. It checks real canvas pixels, selectors, mapping modes, calibration, macro pan/zoom, playback/seeking, errors, and mobile overflow, and writes screenshots plus results under `/tmp/tv-web-smoke`. See [test options](tests/README.md). Read the screenshots when assessing layout; a headless screenshot cannot measure physical nits or validate Chrome/macOS HDR behavior. A real HDR Mac and meter are required for that final check.

The implementation was checked in Chrome 154 on Linux: all 25 smoke checks pass
in default WebGL2, forced WebGL2 and Canvas2D SDR runs. An explicitly forced
SwiftShader WebGPU run accepts extended P3 configuration, but its software backend
cannot allocate the `RGBA_F16` swapchain SharedImage and loses the device. Runtime
SDR recovery passes the same checks. Successful HDR light output was not verified
on this host.
