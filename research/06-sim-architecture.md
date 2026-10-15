# Recommended simulator architecture and validation

Research date: 2026-10-15. This is a research proposal for the NumPy-first implementation in [PLAN](../docs/PLAN.md), not implemented software. M1 delivers these notes; M2 can implement the interfaces/schema, M3 the physical/stateful modules, M4 the measurement comparison. Sources and equations are in [panel](01-panel-tech.md), [backlight](02-backlight-local-dimming.md), [HDR](03-color-hdr.md), [temporal](04-temporal.md) and [processing](05-image-processing.md).

## Data flow and units

```text
source pixels + metadata + timestamps
  → unpack range / chroma / deinterlace
  → source-domain NR, scaling, detail processing (each domain explicit)
  → cadence conversion / optional MEMC → presentation timestamps
  → transfer decoding → linear XYZ desired light [cd/m²]
  → scene analysis / tone map / gamut map → panel-linear RGB demand
  → coupled drive allocation: ABL/power ↔ backlight zones ↔ LCD compensation
  → time-resolved panel response + scanout + emission gate
  → aperture reconstruction / panel optics / angular response
  → emitted XYZ field [cd/m²] + ambient reflection
  ├→ radiometric measurement engine / numeric artifacts
  └→ eye or camera integration → separate preview-display encoding
```

Not every image-processing operation is linear-light. Tagged buffers prevent accidentally applying optical convolution or luminance measurements to PQ code. MEMC may use a signal-domain guide while warping linear-light content; document that choice. Decode SDR into a black-free desired-light representation or explicitly account for BT.1886's target pedestal once. The physical panel adds its own leakage; do not double-count black.

Suggested buffers: `Frame(signal_rgb, encoding, primaries, range, pts_s)`; `LightFrame(xyz_nits, pts_s)`; `DriveFrame(panel_channels, zones, pts_s)`; `EmissionSample(xyz_nits, time_s)`; `Measurement(value, units, pattern, conditions)`. Arrays use H×W×C float32; float64 is useful for reference transfer/matrix calculations. Metadata must state physical screen dimensions and pixel geometry. Stateful modules expose reset, step(dt), serialize_state and deterministic seed. Independent runs reset history or specify a pre-roll sequence.

Power/local-dimming coupling: estimate channel and zone load → enforce power limits → reconstruct B → compensate LCD → recompute actual emitted RGB and power. Iterate to a declared tolerance or use a deterministic bounded solve, then report residuals. Do not apply ABL after optical output while leaving LCD compensation and power estimates inconsistent. Spatially varying backlights can require local gamut constraints. OLED allocation branches into RGB versus RGBW; CRT/plasma branch into raster/subfield excitation.

Keep angular response inside the appropriate emission/transmission model; fitting both a transmission LUT and a final angular fade to the same data double-counts it. Aperture rendering and subpixel optics may operate at higher resolution, but default distant-view simulation should use analytic filtering/downsampling.

Reference performance: one 3840×2160×3 float32 buffer is about 99.5 MB (94.9 MiB). A dense 4K×2,304-zone H matrix would be about 76.4 GB; use convolution for regular synthetic grids or sparse/truncated influence operators with documented tail error. Stream temporal samples; do not retain full 4K emission at kHz for an entire clip. NumPy CPU reference can use tiles and reduced-resolution zone fields; GPU parity should compare numeric outputs before visual tuning.

## Proposed YAML schema v1

YAML is data only: safe loader, reject unknown keys, validate finite values, disallow object constructors. The example below is **three synthetic TVs**, not measured named retail products. It is executable configuration design for M2, not a calibration claim. All overridden values are illustrative priors. Their optical mechanisms are grounded in the linked notes; exact numbers need the validation process below.

| Field | Contract / validation |
|---|---|
| `schema_version` | Exactly 1; explicit migration for future changes |
| `defaults`, `tvs` | Deep-merge defaults with each TV, replacing arrays in full; validate the merged profile |
| `id`, `provenance` | Unique ID; measured/estimated/synthetic status, sources and conditions; every real fit needs size, firmware, mode and date |
| `panel` | type: lcd/oled/crt/plasma; subtype: ips/ads/va/wrgb/qd_oled/etc.; positive pixel dimensions, diagonal inches, refresh Hz, aperture ID |
| `color` | Primary xy triplet and white xy; valid nondegenerate matrix; white inside gamut; nominal reference white >0 |
| `luminance` | Nonnegative ideal emissive black, positive full-open capacity; window fraction/luminance points ordered on [0,1] |
| `backlight` | type none/global/fald/edge; rows/columns >0 only when applicable; contrast >1 for LCD; PSF and time constants nonnegative |
| `power` | model off/window_curve/channel_budget; documented window-curve scaling convention; τ≥0 |
| `allocation` | Emissive RGB/RGBW solver and positive channel maxima; required for OLED; RGBW also needs W chromaticity/capacity |
| `response` | First-order t10–90 or LUT path; t>0; optional overdrive bounded and unit-tagged |
| `emission` | Scanout duration ≤frame interval; duty in (0,1]; pulse frequency when enabled |
| `view` | LUT path or named synthetic model; horizontal and vertical angle data for real calibration; reflectance in [0,1] |
| `processing` | Scaling kernel/domain, NR and sharpening parameters, MEMC boolean, tone-map ID and settings |
| `observer` | Positive viewing distance, lux≥0, optional eye/camera integration definition |

Conditional rules: OLED requires backlight none and matching RGB/RGBW allocation; LCD requires native contrast and a backlight; CRT/plasma require raster/subfield waveform configuration instead of a hold-only assumption. Reject contradictory fields rather than silently ignoring them. For real profiles, support per-parameter metadata `{value, unit, status, source, conditions, uncertainty}` or an equivalent sidecar; illustrative compact scalars below inherit `synthetic` status.

`window_curve_nits` is a measured/fitted neutral-white capacity versus rectangular bright-window area on black at a declared duration. In the initial `window_curve` proxy, compute normalized linear requested APL `a=mean(Y_request)/max(Y_request)` (a=0 for black); interpolate P(a) and scale **all** panel/zone demands by `min(1,P(a)/max(Y_request))` before physical allocation. This proxy reproduces neutral windows but is uncertain for mixed colors and arbitrary content; real models should use channel power. `capacity_nits` is the pre-limiter full-open/neutral capacity, not an extra gain applied to already absolute nits. Time constants smooth limiter state, not the image itself.

```yaml
schema_version: 1
defaults:
  provenance:
    status: synthetic
    conditions: "D65, normal incidence, dark room; not a retail calibration"
    sources:
      - "https://www.itu.int/rec/R-REC-BT.2100/en"
  panel:
    resolution_px: [3840, 2160]
    diagonal_in: 55
    refresh_hz: 120
  color:
    white_xy: [0.3127, 0.3290]
    reference_white_nits: 100
  processing:
    scale: {kernel: lanczos3, domain: linear_light}
    nr: {spatial_sigma_px: 0, temporal_beta: 0}
    sharpen: {gain: 0, sigma_px: 1}
    memc: false
    tone_map: {model: exponential_shoulder, knee_fraction: 0.7}
  emission:
    model: sample_hold
    scanout_ms: 8.0
    duty: 1.0
    pwm_hz: null
  view:
    model: synthetic_lut
    angle_deg: [0, 30, 60]
    white_gain: [1.0, 0.95, 0.75]
    diffuse_reflectance: 0.015
  observer: {distance_m: 2.5, ambient_lux: 0}
tvs:
  - id: synthetic_ips_sdr_tv
    panel: {type: lcd, subtype: ips, aperture: rgb_stripe, refresh_hz: 60}
    color:
      primaries_xy: [[0.640, 0.330], [0.300, 0.600], [0.150, 0.060]]
    luminance:
      capacity_nits: 350
      window_curve_nits: [[0.01, 350], [0.1, 350], [1.0, 350]]
    backlight:
      type: global
      native_contrast: 1000
      grid_rc: [1, 1]
      psf: {model: uniform}
      rise_ms: 0
      fall_ms: 0
    power: {model: window_curve, attack_ms: 0, release_ms: 0}
    response: {model: first_order, rise_t10_90_ms: 10, fall_t10_90_ms: 14, overdrive_gain: 0}
    emission: {scanout_ms: 16.0}
    view:
      leakage_multiplier: [1.0, 1.5, 4.0]
      gamma_delta: [0.0, 0.05, 0.15]
  - id: synthetic_va_mini_led_tv
    panel: {type: lcd, subtype: va, aperture: bgr_stripe}
    color:
      primaries_xy: [[0.680, 0.320], [0.265, 0.690], [0.150, 0.060]]
    luminance:
      capacity_nits: 1500
      window_curve_nits: [[0.01, 1500], [0.1, 1500], [0.5, 1000], [1.0, 650]]
    backlight:
      type: fald
      native_contrast: 4000
      grid_rc: [32, 48]
      psf:
        model: footprint_gaussian_mixture
        core_sigma_pitch_xy: [0.4, 0.4]
        tail_sigma_pitch_xy: [1.5, 1.5]
        tail_energy: 0.05
      algorithm: zone_max_compensated
      rise_ms: 8
      fall_ms: 40
    power: {model: window_curve, attack_ms: 20, release_ms: 100}
    response: {model: first_order, rise_t10_90_ms: 7, fall_t10_90_ms: 12, overdrive_gain: 0}
    view:
      leakage_multiplier: [1.0, 4.0, 12.0]
      gamma_delta: [0.0, -0.2, -0.5]
  - id: synthetic_qd_oled_tv
    panel: {type: oled, subtype: qd_oled, aperture: triangular_rgb}
    color:
      primaries_xy: [[0.700, 0.300], [0.210, 0.760], [0.140, 0.050]]
    luminance:
      capacity_nits: 1200
      ideal_black_nits: 0
      window_curve_nits: [[0.01, 1200], [0.1, 1000], [0.25, 600], [1.0, 220]]
    backlight: {type: none}
    power: {model: window_curve, attack_ms: 20, release_ms: 200}
    allocation: {model: rgb, channel_max_relative: [1.0, 1.0, 1.0]}
    response: {model: first_order, rise_t10_90_ms: 0.3, fall_t10_90_ms: 0.3, overdrive_gain: 0}
    view:
      white_gain: [1.0, 0.98, 0.85]
      gamma_delta: [0.0, 0.0, 0.0]
```

Additional schema conventions: `grid_rc` is rows,columns; `sigma_pitch_xy` uses horizontal/vertical zone pitches, not pixels. Angular arrays are symmetric, azimuth-independent **synthetic** curves with piecewise-linear interpolation over absolute angle and endpoint clamp; measured profiles should replace them with 2D signed-angle LUTs. `gamma_delta` acts on normalized panel drive; `white_gain` acts once on emitted luminance. For LCD, `leakage_multiplier` multiplies 1/native_contrast. No unspecified gamma offset or ambient tint is inferred. `rgb_stripe`, `bgr_stripe`, `triangular_rgb` are abstract mask IDs; actual aperture dimensions need assets. `channel_max_relative` multiplies the neutral-normalized panel primary maxima. PSF kernels integrate to unit energy before footprint convolution; full-grid H is calibrated as described in note 02.

Input encoding belongs to a separate run manifest, not the TV: input path/hash, RGB/YCbCr matrix, transfer, primaries, range, bit depth/chroma siting, rational fps, metadata, seed, profile hash, pre-roll, output metric/preview format. Record code revision and any fitting-data hashes. This prevents a PQ-only TV profile from incorrectly decoding an SDR clip.

## Validation plan

Use generated numeric patterns with explicit linear/PQ/HLG encoding and hashes. Never validate only against display screenshots. Primary measurement references include [RTINGS zone tests](https://www.rtings.com/tv/tests/picture-quality/lighting-zones), [angle tests](https://www.rtings.com/tv/tests/picture-quality/viewing-angle), [response methodology](https://www.rtings.com/tv/tests/motion/motion-blur-and-response-time) and the ITU standards linked in note 03. Lab pages with locked tables are evidence of method, not accessible numeric targets.

| Pattern / experiment | Observables | Acceptance / diagnostic |
|---|---|---|
| Numeric PQ/HLG/SDR ramps and round trips | Absolute light, monotonicity, endpoints | Analytic tests: relative error <1e−5 away from zero, absolute <1e−5 nits near zero; float64 reference; declare transfer domain |
| Full black, PLUGE and near-black steps | Detection floor, crush, dither, black pedestal | LCD black equals B/C for fixed B; OLED ideal black zero; physical meter limits reported |
| Constant fields + impulse | DC gain, convolution energy, edge behavior | Unit gain within 1e−5 away from intentional clipping; nonnegative B; no artificial border boost |
| Fixed-backlight 4×4 checkerboard and sequential fields | Native vs ANSI/scene contrast | Compare each protocol separately; no division by synthetic zero for infinite contrast |
| White windows 1/2/10/25/50/100%, 0.1/1/10/60 s | Peak/sustained luminance, load and thermal curve | Initial empirical target ±10% or reported uncertainty, whichever larger; report mode and timing |
| Single star, cross, moving dot, subtitles/letterbox | Halo radial profile, highlight loss, zone timing | Fit on one subset, evaluate positions/sizes on held-out patterns; initial ±20% halo luminance above meter floor |
| Gray/RGB/CMY and hue sweeps over brightness/APL | XYZ, white balance, gamut/volume | Initial median ΔE_ITP≤3 if instrument uncertainty permits; report tails and exact metric/scaling |
| Neutral/color patches at 0/15/30/45/60° on both axes | White falloff, gamma and black rise | Initial ±10% relative Y or absolute meter uncertainty; chromaticity fit separately |
| Gray-to-gray grid, 24p pans, 960 px/s edges, strobe fields | Response curves, pursuit blur, cadence, overshoot | Same response definition; target timing within 1 ms or 10%, whichever larger; temporal integration convergence <1% |
| Zone plates, phase edges, noise/grain, occlusion and scene cuts | MTF, ringing, aliasing, NR detail loss, MEMC artifacts | Identity/bypass must preserve samples; enhanced modes report tradeoffs, not a single fidelity score |
| 0/50/200/500-lux black/gray and point light | Ambient contrast, tint, diffuse/specular reflection | Fit diffuse separately from specular; record geometry and lux at screen |

All empirical tolerances above are **proposed project targets**, not standards or claims that sufficient data already exists. Separate model error, parameter uncertainty and instrument uncertainty. Use dark-frame/exposure calibration, prevent camera clipping, and measure camera flare before fitting halos. Match TV size, panel variant, firmware, picture mode, game/VRR state, color temperature, dimming setting and warm-up time. Keep calibration and validation patterns separate. Do not fit all parameters at once: global backlight/contrast → PSF/controller → color/power → temporal → processing/observer.

Numeric artifacts should include emitted XYZ/luminance arrays, zone drive traces, parameter/source manifests and measurement CSV/JSON. The preview renderer maps this physical result to the user's display via its own color management and tone mapping. An SDR preview cannot physically reproduce a 1,500-nit highlight or a darker black than its host; label the preview transform and expose false-color nits/zoom plots. Do not mistake preview limitations for TV physics.

## Open decisions for M2

1. Select actual devices and obtain accessible per-mode measurements; decide whether synthetic profiles are acceptable until hardware access.
2. Set reference observer geometry and whether first output is static radiometry, time traces, or pursuit-rendered clips.
3. Choose a deterministic baseline tone mapper and gamut compressor; scope optional proprietary-processing proxies.
4. Acquire PSF/zone topology, RGBW/channel-capacity data, response LUTs and legacy phosphor waveforms; these are the largest fidelity gaps.
5. Agree on measurement uncertainty and empirical acceptance targets before tuning.
