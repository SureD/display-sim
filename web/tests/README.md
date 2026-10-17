# Browser smoke check

From the repository root, generate preview assets with `python3 -m sim export-web`,
then start `python3 -m http.server 8000`. In another terminal, run:

```sh
node web/tests/smoke.cjs
node --test web/tests/mapping.test.mjs
```

The script uses `/usr/bin/google-chrome` in headless mode, software WebGL via
SwiftShader, and Chrome's debugging pipe. No npm packages or build step are needed.
Node 18 or later runs the smoke script; the numeric ES-module tests use Node 20.19 or later. An optional URL argument replaces the default
`http://127.0.0.1:8000/web/`; `CHROME_BIN` replaces the Chrome executable and
`TV_SMOKE_OUTPUT` replaces the default `/tmp/tv-web-smoke` output directory.

Checks cover real canvas pixels, profile and scene changes, brightness modes,
measurement calibration, macro zoom and pan, playback and seeking, browser errors,
and mobile overflow. PNG screenshots plus `results.json` are written to the output
directory. Screenshot checks verify rendering and interaction; a headless SDR
display cannot validate a physical HDR output luminance or macOS EDR behavior.

To request Chrome's software WebGPU adapter explicitly, set `TV_SMOKE_WEBGPU=1`.
This adds test-only `--enable-unsafe-webgpu --use-webgpu-adapter=swiftshader` flags.
The preview still probes the real canvas configuration and uses an SDR fallback
when the adapter or extended canvas is unavailable. Force individual fallback
paths with URL arguments ending in `?renderer=gl2` or `?renderer=2d`.
For driver investigations, `TV_SMOKE_CHROME_FLAGS` accepts a JSON array of
additional flags; these affect only the test browser.
