# M6 profile wiring: measured loads, angular leakage, optical tables and ABL

Research date: **2026-10-16**. This is a wiring specification for the four existing generic profiles, based on [README](../README.md), [STATUS](../docs/STATUS.md), [M5 fidelity](m5-fidelity.md), [M5 Mac display research](m5-mac-display.md), and the current [profile loader](../sim/profile.py). It changes no simulator code, profile YAML or saved M4 artifacts. Published measurements below describe named samples; assigning one to a generic technology does not make that preset a calibrated TV.

Evidence follows M5 fidelity: **M** = published measurement; **D** = calculation; **P** = proposed model, interpolation or synthetic example; **NR** = no verified numerical reference or missing conditions. NR is not zero. Use `not_applicable` for a mechanism that does not apply. Unknown uncertainty, timing and source conditions remain NR even when a measured luminance is available.

## 1. What can be wired today

| Mechanism | Current runtime YAML | M6 action |
|---|---|---|
| Window/output luminance tables | No table field in `HdrParams`; `abl_gamma` supplies a synthetic curve | Keep measured records in a research sidecar; proposed replay adapter below requires code. |
| Requested linear APL | `hdr.abl_source: demand`, `abl_reference_nits`, `abl_response_ms` | Already supported; opt in separately from legacy `emitted` behavior and refit. |
| Angular white/black/gamma | Only `panel.viewing_angle_deg` and `angle_loss_per_deg` | These only desaturate RGB toward luminance. The proposed LCD leakage/white/gamma model requires code. |
| Symmetric separable optical LSF | `backlight.psf_profile: {step_zones, x, y}` | Already supported for LCD backlight spread and OLED emitted RGB; metadata stays outside the runtime block. |
| Optical tails and edges | `backlight.psf_shape`, `psf_boundary`, existing sigma/tail fields | Already supported; Gaussian + reflect are compatibility defaults. |
| OLED limiter attack/release | One shared `hdr.abl_response_ms` | Symmetric APL smoothing works today; separate constants and capacity/gain smoothing require code. |
| Electrical power | `abl_power_budget_nits`, `abl_channel_weights` | Weighted-nit RGB proxy only; no measured watt solver or RGBW allocation. Keep budget 0 for parity. |

The loader constructs dataclasses directly from each known section. Unknown keys **inside** `hdr`, `panel`, `backlight`, or `psf_profile` raise an error; unknown root keys are ignored, not implemented. Every YAML block below is labeled either **supported runtime fragment** (merge into a complete profile for a future experiment) or **proposed research schema** (not loadable as simulator settings). `NR` strings belong only in research records, never in active numeric dataclass fields. `null` in a supported block means an intentionally absent override, not a missing measurement.

Two M5 implementation descriptions are now stale: [M5 fidelity §1](m5-fidelity.md#1-load-dependent-brightness-window-curves-are-conditional-measurements) describes emitted-only APL, and §3 says the OLED branch ignores the PSF. Current [load.py](../sim/load.py), [pipeline.py](../sim/pipeline.py), and [panel.py](../sim/stages/panel.py) support demand APL and emitted-light PSFs. Use M5 for measurement evidence and current code for field semantics.

## 2. Measured window and APL records

### Named-sample values to preserve

All window entries are peak luminance in **cd/m² (nits)**. Each numeric cell is M; dwell, uncertainty and timed sustained behavior are NR. These are separate datasets, not interchangeable nodes of one technology curve.

| Dataset / candidate profile family | 1% | 2% | 5% | 10% | 25% | 50% | 75% | 100% | Source and conditions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `c2_42_hdr_standard_peak` / WOLED | 717 | 717 | 717 | 717 | 396 | 243 | 192 | 152 | LG 42C2, HDR Standard, dynamic tone mapping off; [review](https://tftcentral.co.uk/reviews/lg-oled-42c2), [table image](https://tftcentral.co.uk/wp-content/uploads/2022/04/HDR_standard_3.png). |
| `s95b_65_hdr10_filmmaker_peak` / QD-OLED | 1000 | NR | NR | 1000 | 600 | 300 | NR | 200 | Samsung 65-inch S95B, HDR10 Filmmaker; [Sound & Vision original test bench](https://www.soundandvision.com/content/samsung-65-s95b-quantum-dot-oled-4k-tv-review-test-bench). |
| `x955_98_theatre_hdr_peak` / VA mini-LED | NR | 1675 | 3000 | 3200 | 3200 | 1800 | 1100 | 896 | TCL **98X955**, Theatre HDR; [L&B original measurements](https://www.lbtechreviews.com/test/tcl-x955). |
| `uh770v_55_hdr_peak_unlocated` / IPS edge | NR | NR | NR | NR | NR | NR | NR | NR | LG 55UH770V: [HDTVTest](https://www.hdtvtest.co.uk/news/55uh770v-201610064369) gives 455-nit peak with window/dwell NR. Store that scalar separately. |

S95B's source reports a rounded 1000-nit plateau from 1–10%; its independent 2% and 5% measurements remain NR. A fit may span those fractions, labeled P. The X955's 2% suppression must survive interpolation; forcing a nonincreasing OLED-style curve is inappropriate. Its 98-inch data do not identify another size's curve. The 100% peak cells do not establish 10-second or 60-second sustained output.

Keep the historical **publisher-labeled APL** axis separate:

| Dataset | Published APL 25% | 50% | 100% | Axis caveat |
|---|---:|---:|---:|---|
| `eg9600_65_cinema_apl_2015` | 242 | 157 | 91 | LG 65EG9600 factory Cinema, SDR-era; [DisplayMate original table](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm). Absolute requested APL/reference nits and dwell NR. |

Vivid is excluded from candidate wiring: M5 transcribes 428 nits at 25% APL, while the primary page's brightness table says 433 and its power section says 428. Whether conditions differ is NR; do not average them or splice them into Cinema.

### Provenance schema and concrete rows

**Proposed research schema**, not runtime YAML. A future sidecar could live under `research/measurements/`; this note creates no such files. Conditions and provenance inherit from a dataset into its nodes; a node override must be explicit. Every dataset needs its own specimen, conditions and source locator, including NR fields.

```yaml
schema_version: m6-research-1
kind: measurement_sidecar_proposal
dataset_id: c2_42_hdr_standard_peak
candidate_profile_family: generic_woled
calibrated_profile_fit: NR
specimen:
  manufacturer: LG
  model: 42C2
  diagonal_in: 42
  region_panel_variant: NR
  firmware: NR
conditions:
  picture_mode: HDR Standard
  dynamic_tone_mapping: disabled
  input_mode: NR
  local_dimming: not_applicable
  refresh_hz: NR
  vrr: NR
  white_xy: NR
  source_encoding: NR
  requested_window_nits: NR
  source_rgb_primaries: NR
  stimulus: neutral_white_window_on_black
  stimulus_rgb_code: NR
  pattern_aspect_ratio: NR
  position_xy_fraction: NR
  warmup_s: NR
  dwell_s: NR
  prior_pattern_and_duration: NR
  ambient_lux: NR
  temperature_C: NR
  viewing_angle_deg: NR
  meter_geometry_and_spot: NR
  instrument_and_correction: NR
provenance:
  evidence: M
  source_url: https://tftcentral.co.uk/reviews/lg-oled-42c2
  source_asset_url: https://tftcentral.co.uk/wp-content/uploads/2022/04/HDR_standard_3.png
  source_locator: HDR Standard peak-window table
  extraction: exact_table_image_transcription_in_m5_fidelity
  inherited_source_check_date: "2026-10-16"
  m6_fetch_status: unavailable_timeout_or_fetch_error
  uncertainty_nits: NR
  repeat_count: NR
  instrument_floor_nits: NR
axis:
  kind: window_fraction
  unit: screen_area_fraction
  requested_apl_reference_nits: NR
metric: peak_center_luminance_nits
nodes:
  - {fraction: 0.01, luminance_nits: 717, evidence: M}
  - {fraction: 0.02, luminance_nits: 717, evidence: M}
  - {fraction: 0.05, luminance_nits: 717, evidence: M}
  - {fraction: 0.10, luminance_nits: 717, evidence: M}
  - {fraction: 0.25, luminance_nits: 396, evidence: M}
  - {fraction: 0.50, luminance_nits: 243, evidence: M}
  - {fraction: 0.75, luminance_nits: 192, evidence: M}
  - {fraction: 1.00, luminance_nits: 152, evidence: M}
timed_sustained_trace: NR
interpolation:
  method: piecewise_linear
  evidence: P
  support_fraction: [0.01, 1.0]
  endpoint_policy: reject_outside_support
  permit_nr_condition_replay: false
```

The last flag deliberately prevents claiming condition-matched replay when requested amplitude or timing is NR. An explicitly labeled exploratory replay may waive that restriction and log the assumed conditions; it must keep the original record intact. C2 values are inherited from M5's image transcription because this pass could not fetch the TFTCentral page/image. The S95B and X955 public tables and DisplayMate tables were accessible on this pass; source checks do not fill missing experimental conditions.

**Proposed research schema**, compact additional rows. Apply the full record fields above independently to each dataset; this block supplies the differing axes, sources and values, not shared experimental conditions. A scalar NR is an unknown, not a numeric table node for interpolation.

```yaml
dataset_rows:
  s95b_65_hdr10_filmmaker_peak:
    specimen: {manufacturer: Samsung, model: S95B, diagonal_in: 65}
    picture_mode: HDR10 Filmmaker
    source_url: https://www.soundandvision.com/content/samsung-65-s95b-quantum-dot-oled-4k-tv-review-test-bench
    source_locator: HDR 100-percent-white varying-window paragraph
    extraction: published_rounded_values
    axis_kind: window_fraction
    fractions: [0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0]
    luminance_nits: [1000, NR, NR, 1000, 600, 300, NR, 200]
    evidence: [M, NR, NR, M, M, M, NR, M]
    published_plateau: {support_fraction: [0.01, 0.10], approximate_nits: 1000}
    sustained_trace: NR
  x955_98_theatre_hdr_peak:
    specimen: {manufacturer: TCL, model: 98X955, diagonal_in: 98}
    picture_mode: Theatre HDR
    source_url: https://www.lbtechreviews.com/test/tcl-x955
    source_locator: Measurements table, TCL 98X955 column, Brightness rows
    extraction: published_table_values
    axis_kind: window_fraction
    fractions: [0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0]
    luminance_nits: [NR, 1675, 3000, 3200, 3200, 1800, 1100, 896]
    evidence: [NR, M, M, M, M, M, M, M]
    fit_support_fraction: [0.02, 1.0]
    enforce_nonincreasing_curve: false
    sustained_trace: NR
  uh770v_55_hdr_peak_unlocated:
    specimen: {manufacturer: LG, model: 55UH770V, diagonal_in: 55}
    picture_mode: NR
    source_url: https://www.hdtvtest.co.uk/news/55uh770v-201610064369
    axis_kind: window_fraction
    fractions: [0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0]
    luminance_nits: [NR, NR, NR, NR, NR, NR, NR, NR]
    unlocated_peak: {luminance_nits: 455, evidence: M, fraction: NR, dwell_s: NR}
    fit_support_fraction: NR
    sustained_trace: NR
  eg9600_65_cinema_apl_2015:
    specimen: {manufacturer: LG, model: 65EG9600, diagonal_in: 65}
    picture_mode: factory Cinema
    source_url: https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm
    source_locator: Brightness and Contrast table, LG OLED Cinema
    axis_kind: published_apl_fraction
    requested_apl_reference_nits: NR
    fractions: [0.25, 0.50, 1.0]
    luminance_nits: [242, 157, 91]
    evidence: [M, M, M]
    sustained_trace: NR
```

The proposed future `hdr.window_curve` adapter needs `enabled: false` by default, a dataset ID, `axis_kind`, requested-amplitude/color/mode/time matching, interpolation method, support and endpoint policy, and an explicit `application: calibrated_output_replay`. Table existence alone must not activate it. Require increasing unique fractions in (0,1], finite nonnegative numeric luminances, equal array lengths, and no interpolation across incompatible sweeps. Skip NR rows; preserve their NR status in reports. Inside support, interpolated outputs are P. Below X955's 2% support, reject rather than invent 1% output. Return zero emission for a black request without treating it as a measured `f=0` node.

**Proposed research schema**, concrete profile-to-dataset binding; the IPS binding stays NR because no usable window sweep exists:

```yaml
candidate_dataset_ids:
  generic_woled: c2_42_hdr_standard_peak
  generic_qdoled: s95b_65_hdr10_filmmaker_peak
  generic_va_fald_miniled: x955_98_theatre_hdr_peak
  generic_ips_edge: NR
proposed_profile_extension:
  hdr:
    window_curve:
      enabled: false
      dataset_id: c2_42_hdr_standard_peak
      axis_kind: window_fraction
      application: calibrated_output_replay
      condition_policy: require_matched_or_explicit_synthetic_override
      interpolation: piecewise_linear
      outside_support: reject
      content_proxy: disabled
```

For demand APL use `A_req = mean(Y_request)` in linear nits before limiting and `a_req = A_req / Y_ref`. A neutral window on black has `A_req = f * Y_window,request`; measured output nits do not recover requested nits. The optional occupancy proxy `f_eff = mean(Y_request)/max(Y_request)` is P, is 0 for black, and needs a matched request amplitude; it is not absolute APL. With the current BT.709 luminance helper, RGB primaries must be declared and converted correctly before using colored stimuli.

Do not copy C2's 717/152 into `panel_peak_nits`/`abl_full_field_nits` and call the curve fitted. The current asymptotic soft shoulder can undershoot a measured center value, and the analytic ABL curve cannot reproduce every table node. A replay/drive solver should reproduce actual output once, accounting for panel drive, tone mapping and load together. Avoid applying both a fitted output curve and a second limiter fitted to that same drop. Peak/sustained tables, amplitude/color sweeps, thermal state and static-image dimming remain separate.

## 3. Angular leakage: separate VA and IPS fits

### Current knobs and proposed physical knobs

| Parameter | VA mini-LED | IPS edge | WOLED | QD-OLED |
|---|---:|---:|---:|---:|
| Current `panel.native_contrast` (synthetic) | 4000 | 1200 | 1000000, unused | 1000000, unused |
| Current `panel.viewing_angle_deg` | 0 | 0 | 0 | 0 |
| Current `panel.angle_loss_per_deg` (synthetic chroma only) | 0.08 | 0.015 | 0.005 | 0.004 |
| Proposed matched-device angular white gain | NR | NR | NR, emitter model | NR, emitter model |
| Proposed matched-device angular leakage ratio | NR | NR | not_applicable | not_applicable |
| Proposed matched-device gray/RGB angle LUT | NR | NR | NR | NR |

The current law is `RGB_out = Y + (RGB_in-Y)/(1+k*angle_deg)` for positive angle and k; it changes chroma, not neutral black/white luminance. The code does not turn signed negative angles into their absolute value. Raising VA's k therefore cannot simulate washed-out black, and IPS's smaller k cannot identify IPS glow.

For an optional future LCD model, use fully open on-axis white field B and normal-incidence linearized transmission q:

```text
epsilon0 = 1 / C_native_0
epsilon(theta,phi) = epsilon0 * F_black(theta,phi) / F_white(theta,phi)
L = B * F_white * [epsilon + (1-epsilon)*g(q;theta,phi)]
g(0)=0; g(1)=1; B=0 gives zero emission
```

`F_black` describes emitted black rise relative to on-axis black. A LUT of `epsilon/epsilon0` instead describes leakage relative to **same-angle white**; these are different quantities. Store one representation with its definition, derive the other, and never multiply by both. Require positive white gain and `0 <= epsilon <= 1` over fitted support. Use the existing LCD compensation to determine q; the angle law belongs inside transmission. Any mismatch between this law and the present LCD approximation needs implementation work and new baselines.

| Source dataset, separate specimen/mode | White gain at 45° | Black factor at 45° | Gamma 0° → 45° | What it identifies |
|---|---:|---:|---|---|
| Samsung UN65JS9500 PVA FALD, [DisplayMate 2015](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm); angular picture mode NR | 0.48 D | 5.19 D | NR | `epsilon45/epsilon0 = 10.8125` D; `C45/C0 ≈ 0.09249` D. Mechanism demonstration, not a current mini-LED fit. |
| Samsung 65Q8 Movie, [DisplayMate 2017](https://www.displaymate.com/TV_Picture_Quality_with_Viewing_Position_1.htm) | 0.35 D | NR | 2.36 → 1.93 M | White/gamma endpoints; no angular extinction fit. |
| LG 65SJ9500 IPS Cinema, [same direct comparison](https://www.displaymate.com/TV_Picture_Quality_with_Viewing_Position_1.htm) | 0.32 D | NR | 2.26 → 2.24 M | Stable gamma does not establish stable black. |

419% higher black means **5.19 times** the initial black. The separate JS9500 dimming-off Movie measurement, white/black 207/0.066 nits, gives about 3136:1 D, but its mode must not be silently assigned to the angular sweep. Similarly, the 2017 reported picture-contrast decreases (63% VA, 5% IPS) describe 10–100% grayscale, not native black-to-white contrast. Do not combine Q8 gamma, JS9500 leakage and a generic zone map into a measured device.

**Proposed research schema**, the future `panel.angular` extension and independent sparse source records:

```yaml
proposed_profile_extension:
  panel:
    angular:
      enabled: false
      model: lcd_transmission_lut
      dataset_id: NR
      coordinates: signed_horizontal_vertical_degrees
      white_gain_lut: NR
      leakage_representation: epsilon_over_epsilon0
      leakage_lut: NR
      gray_rgb_lut: NR
      outside_support: reject
      replace_legacy_chroma_loss: true
source_endpoint_records:
  js9500_2015:
    source_url: https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm
    picture_mode: NR
    angle_deg: [0, 45]
    white_gain: [1.0, 0.48]
    black_gain: [1.0, 5.19]
    epsilon_over_epsilon0: [1.0, 10.8125]
    evidence: D
    matched_on_axis_native_contrast: NR
  q8_2017_movie:
    source_url: https://www.displaymate.com/TV_Picture_Quality_with_Viewing_Position_1.htm
    angle_deg: [0, 45]
    white_gain: [1.0, 0.35]
    encoded_gamma: [2.36, 1.93]
    black_gain: NR
    leakage_lut: NR
  sj9500_2017_cinema:
    source_url: https://www.displaymate.com/TV_Picture_Quality_with_Viewing_Position_1.htm
    angle_deg: [0, 45]
    white_gain: [1.0, 0.32]
    encoded_gamma: [2.26, 2.24]
    black_gain: NR
    leakage_lut: NR
```

For a sparse **P demonstration limited to 0–45°**, set `s=sin²(theta)/sin²(45°)`, `Fw=exp(log(Fw45)*s)`, and, where a black endpoint exists, `Fb=exp(log(Fb45)*s)`. Interpolate gamma with s and use `g(q)=q^(gamma(theta)/gamma0)` because q is already linearized. These interpolation choices are not additional measurements; unsigned symmetry is an assumption to record. A simpler `epsilon=epsilon0*(1+k_epsilon*sin²(theta))` would give **D/P** `k_epsilon=19.625` for the JS9500 endpoint, whereas `Fb=1+k_black*sin²(theta)` gives `k_black=8.38`. Those k values describe different models, not VA/IPS material constants; matched generic-profile k values remain NR.

Acquire signed horizontal/vertical/azimuth × gray × RGB/black/white sweeps at fixed backlight and record compensation films, meter floor, mode and local dimming. Screen dimensions, surface normal and eye position should produce per-pixel angles; one center-angle scalar misses IPS corner glow. Do not add a cosine factor to a measured luminance LUT. OLED needs angular emitter/film primary transforms, not LCD extinction; numerical OLED transforms remain NR.

## 4. Existing LSF/PSF table hooks

The implementation is in [backlight.py](../sim/stages/backlight.py) (`table_kernel1d`, `psf_axis_kernels`, `apply_light_spread`) and [panel.py](../sim/stages/panel.py) (`emission_psf`, `spread_emission`).

| Runtime path | Allowed values / units | Wiring semantics |
|---|---|---|
| `backlight.psf_shape` | `gaussian` (default), `exponential_tail` | Core stays Gaussian. The second option changes the **tail**, not the whole kernel; tail scale is not Gaussian sigma. |
| `backlight.psf_sigma_zones`, `psf_sigma_y_zones` | Axis sigma in zone pitches for LCD; pixels for `per_pixel` OLED | Missing y copies x. LCD pixel sigma = axis sigma × that axis's zone pitch. |
| `backlight.psf_tail_sigma_zones`, `psf_tail_sigma_y_zones` | Same units as core | Missing tail y copies tail x; it does not copy core y. |
| `backlight.psf_tail_weight` | Proposed fit range [0,1], default 0 | Blend of two separable 2-D kernels. Existing VA value is 0.08. |
| `backlight.psf_profile.step_zones` | Positive sample interval; default 1 | Multiplied by x/y zone pitch on LCD; directly pixels on OLED despite the field name. One shared interval for both axes. |
| `backlight.psf_profile.x`, `.y` | Nonnegative relative half-LSF samples at 0, step, 2×step, … | Either axis can be omitted; omitted axis keeps its parametric kernels. No CSV/path loader. |
| `backlight.psf_boundary` | `reflect` (default), `zero`, `calibrated_zero` | Mirror edges; lose off-screen energy; or zero-pad then divide by the all-on response, respectively. |

**Supported runtime fragment; synthetic P samples, measured values NR.** This demonstrates the accepted nested keys for an LCD experiment; it is not a measured TV LSF.

```yaml
backlight:
  psf_shape: gaussian
  psf_boundary: reflect
  psf_tail_weight: 0.0
  psf_profile:
    step_zones: 0.25
    x: [1.0, 0.60, 0.20, 0.04, 0.0]
    y: [1.0, 0.45, 0.10, 0.01, 0.0]
```

Each supplied axis needs at least two samples, a positive center, and support spanning at least a one-pixel radius after conversion. The code mirrors the half-profile, linearly resamples onto integer pixel offsets, truncates support at `floor((N-1)*step_px)`, and normalizes the discrete kernel to unit sum. Supply finite values and sufficient tail support before loading; this is not a claim that every invalid value is checked by the loader. A final zero sample is useful for a deliberately tapered synthetic support; measured truncation needs its residual-energy uncertainty recorded.

A table replaces **both core and tail on the supplied axis**. With both x and y supplied, the two components become identical and tail weight has no effect. With only x supplied, y still has its parametric core/tail mixture. Use tail weight 0 for a fully specified measured separable table unless that hybrid is intentional. The result is a symmetric, shift-invariant separable approximation, not an asymmetric 2-D PSF or a location-dependent `H_ij` map. `psf_shape` is still validated when both axes are tabulated; there is no `table` shape enum.

On LCD, convolution follows expansion of each pooled zone into a rectangular raster footprint and precedes floor/peak clipping. An isolated-zone response that already includes this footprint cannot automatically be inserted as the extra convolution kernel; fit the composed model or separate the footprint first. On OLED, the kernel acts per emitted RGB channel after emitter clipping and before the matrix/mosaic/angle and tone-map stages. Unit-sum tables retain relative shape, not measured absolute amplitude. Keep optical kernel measurements separate from controller-dependent output halos.

For uniform LCD zones, `pitch_x_px = raster_width/zones_x`, `pitch_y_px = raster_height/zones_y` (the implementation uses the realized grid dimensions). With measured physical sampling `delta_mm`, choose `step_zones = delta_mm/pitch_mm` per axis. Because the hook has only one step, resample x/y into a common normalized interval when physical pitches differ. Preserve the original data and conversion in provenance. Edge mode's y pitch is the full panel height when `zones_y=1`; it is not horizontal strip spacing. For OLED, changing the working raster changes the physical meaning of pixel units unless physical pixel pitch/resampling is declared.

`zero` preserves simulated border losses. `calibrated_zero` divides the spread by the response to an all-one field at each output location; it is an explicit uniform all-on compensation assumption, not an independently measured edge calibration or per-zone renormalization. `reflect` keeps legacy numerics; the filter falls back to edge padding if its radius reaches the axis length. Parametric Gaussian support is truncated at `ceil(3*sigma)` and exponential support at `ceil(5*scale)`, then normalized. None of these modes loads a measured all-on `Bmax(x,y)` map.

**Proposed research schema**, metadata associated with a future measured LSF:

```yaml
optical_measurement:
  dataset_id: NR
  evidence: NR
  source_url: NR
  specimen_and_mode: NR
  measurement_kind: NR  # bare_optical_lsf | effective_display_halo
  coordinate_unit: mm
  coordinate_samples: NR
  raw_response_nits: NR
  source_footprint_and_zone_phase: NR
  all_on_white_field_nits: NR
  camera_flare_correction: NR
  black_baseline_and_instrument_floor_nits: NR
  normalization: discrete_unit_sum_after_resampling
  separability_and_symmetry_fit_error: NR
  edge_compensation_evidence: NR
  uncertainty_and_tail_truncation: NR
```

No retail-TV optical tables in M5 identify these four profiles. [Tan et al. 2018](https://doi.org/10.1364/OE.26.016572)'s 0.4-mm diffuser sigma at 1-mm LED pitch in an IPS prototype is not 0.4 zone pitches. [He et al. 2025](https://doi.org/10.1364/OE.557308) and the [IDW precursor](https://confit.atlas.jp/guide/event-img/idw2023/LCT4-04/public/pdf_archive?type=in) describe effective controlled-display halos, not isolated optical transport kernels; the precursor's width 129 has no verified transfer to our zone pitches. Keep these as external validation evidence. IPS mini-LED measurements do not calibrate an IPS edge light guide. OLED optical scatter is applicable, but its measured kernel is NR; LCD backlight leakage is not applicable.

## 5. OLED ABL attack and release

### Supported symmetric experiment

[smooth_apl](../sim/load.py) carries one demand-APL state per `Pipeline`. For frame interval dt and `hdr.abl_response_ms=tau`, it uses `A_next=A_target+(A_prev-A_target)*exp(-dt/tau)`. A missing/first state is already settled; tau 0 is instantaneous. `hdr.abl_source: demand` is necessary for that state to feed tone-map ABL. With legacy `emitted` and backlight tracking 0, changing `abl_response_ms` alone does not smooth OLED brightness.

**Supported runtime fragment for either OLED, synthetic experiment P; measured tau NR.** Keep the selected profile's existing peak/curve settings unless conducting a separate refit.

```yaml
hdr:
  abl_enabled: true
  abl_source: demand
  abl_reference_nits: 0.0  # fallback to this profile's panel_peak_nits
  abl_response_ms: 100.0   # synthetic symmetric e-fold time, not measured
  abl_backlight_tracking: 0.0
  abl_power_budget_nits: 0.0
```

This opt-in changes M4 behavior. A research sweep of 10/100/1000 ms is a **P prior**, not a C2/S95B timing measurement. An e-fold time is neither a 10–90% transition nor panel GtG. For a first-order state in the same domain, `t10–90=ln(9)*tau`; nonlinear capacity/tone mapping need not preserve that relation in measured output luminance. Keep `temporal.response_time_ms` at its existing panel-response value; it must not stand in for ABL.

### Proposed independent constants

**Proposed research schema**, fields for a later `hdr` extension; these do not exist in `HdrParams` today:

```yaml
oled_abl_candidate_records:
  generic_woled:
    measured_attack_ms: NR
    measured_release_ms: NR
    measured_thermal_tau_s: NR
    measured_static_dimming_delay_s: NR
  generic_qdoled:
    measured_attack_ms: NR
    measured_release_ms: NR
    measured_thermal_tau_s: NR
    measured_static_dimming_delay_s: NR
proposed_profile_extension:
  hdr:
    abl_dynamics_model: legacy_apl  # default; optional capacity_attack_release
    abl_attack_ms: 0.0              # compatibility default, not a measurement
    abl_release_ms: 0.0             # compatibility default, not a measurement
    abl_dynamics_initial_state: settled_first_frame
    abl_dynamics_fit_dataset_id: NR
```

Proposed semantics: derive the unsmoothed target capacity `C*` from instantaneous source demand or the matched replay model, then select attack when `C* < C_prev` (dimming after higher load), release when `C* > C_prev` (recovery). Update `C_next=C*+(C_prev-C*)*exp(-dt/tau_selected)`; tau 0 takes the target immediately. Smooth gain instead only under a separately named model; smoothing APL, capacity and gain are not equivalent. Do not run the existing `abl_response_ms` smoother as well as the proposed capacity smoother. Legacy mode remains the default; the new mode must reject conflicting nonzero legacy smoothing. Missing measured constants keep calibrated dynamics disabled, with a separately labeled synthetic experiment permitted.

| Profile | Present synthetic capacity settings | Measured dynamics | M4-compatible dynamics |
|---|---|---|---|
| WOLED | `panel_peak_nits=850`, `abl_full_field_nits=170`, `abl_gamma=2.4` | Attack/release, thermal and static dimming NR | `abl_source=emitted`, `abl_response_ms=0`, tracking 0; no new mode |
| QD-OLED | `panel_peak_nits=1100`, `abl_full_field_nits=199`, `abl_gamma=1` | Attack/release, thermal and static dimming NR | Same legacy defaults |

Measure dark/low-load → bright/full-field → dark/low-load sequences with fixed amplitude, timestamps, temperature, mode, pre-roll and repeated trials. Reuse one pipeline across frames. Start from a known settled frame or explicit initial state; fresh pipelines for every frame erase load history. Acquire subframe traces for fast limiting and 0.1/1/10/60-second samples for longer behavior where the instrument permits; otherwise timing is NR. Fit attack and release in the stated domain, and test withheld amplitudes/colors/areas. White-window curves alone cannot identify RGBW channel power, electrical watts, thermal time constants or static-logo logic.

## 6. Defaults and the limits of M4 parity

Leave the shipped YAMLs unchanged for this research. The following values retain the current legacy algorithm when no new mechanism is selected.

**Supported runtime fragment, common compatibility defaults already provided by the dataclasses:**

```yaml
backlight:
  psf_shape: gaussian
  psf_boundary: reflect
  psf_profile: null
hdr:
  abl_source: emitted
  abl_reference_nits: 0.0
  abl_response_ms: 0.0
  abl_backlight_tracking: 0.0
  abl_power_budget_nits: 0.0
  abl_channel_weights: [1.0, 1.0, 1.0]
```

| Existing value to preserve | VA FALD mini-LED | IPS edge | WOLED | QD-OLED |
|---|---|---|---|---|
| Mode / grid `(x,y)` | `fald`, (16,12) | `edge`, (8,1) | `per_pixel`, (1,1) | `per_pixel`, (1,1) |
| Core sigma x/y | 0.75 / 0.75 pitches | 1.5 / 0.15 pitches | 0 / omitted→0 pixels | 0.45 / omitted→0.45 pixels |
| Tail sigma x/y, weight | 2 / 2, 0.08 | 2.5 / omitted→2.5, 0 | default 2 / omitted→2, 0 | default 2 / omitted→2, 0 |
| Backlight peak/floor nits | 2000 / 0 | 400 / 0 | 850 / 0 | 1100 / 0 |
| Zone percentile | 100 | 100 | 100 | 100 |
| HDR peak / full-field / gamma | 2000 / 620 / 1 | 400 / 350 / 2 | 850 / 170 / 2.4 | 1100 / 199 / 1 |
| ABL enabled / knee | true / 0.70 | false / 0.85 | true / 0.85 | true / 0.85 |
| Response tau ms / frame ms | 8 / 16.666 | 12 / 16.666 | 0.2 / 16.666 | 0.1 / 16.666 |
| Sharpen amount / sigma | 0.25 / 0.8 | 0.2 / 0.8 | 0.15 / 0.7 | 0.15 / 0.7 |

Also retain identity color matrices; angle 0 and the existing chroma coefficients; ambient lux 0 and the existing reflectances; input sRGB/100-nit white/1000-nit HLG peak; processing scale 1/bilinear; sample-and-hold true; motion 0 in profiles; BFI duty 1 with mean preservation false; and OD gain 0 (LCD OD duration 2 ms, OLED 0). Preserve the whole original profiles and hashes rather than reconstructing them from a subset of this table. Future window and angular models must default disabled; future separate ABL dynamics must default to the legacy path.

**Strict saved-M4 parity has a QD-OLED exception.** At M4 (`c7dbf01`), the OLED path ignored its computed PSF map; M5 applies the existing QD-OLED 0.45-pixel sigma to emitted RGB. Gaussian+reflect and unchanged YAML therefore do not reproduce every saved M4 metric. A read-only probe at the saved 384×216 geometry gives QD-OLED 10% window center ≈979.695 nits in both cases, but current near-ring halo ≈25.739 nits versus saved M4 zero. With only emitted-optics sigma disabled, the probe's halo returns to zero. This is a mechanism change, not evidence that the old zero halo was physically validated.

**Supported runtime fragment, optional experiment to compare emitted output against M4; do not overwrite the shipped QD-OLED preset:**

```yaml
backlight:
  psf_sigma_zones: 0.0
  psf_sigma_y_zones: 0.0
  psf_tail_weight: 0.0
  psf_profile: null
  psf_shape: gaussian
  psf_boundary: reflect
```

WOLED already has zero core sigma and zero tail weight. The QD override recovers M4's lack of emitted optical spread, but also changes the debug backlight map, which M4 computed and ignored; it cannot restore both that old map and old emission through existing YAML. Treat complete historical artifact equality as requiring the historical code revision. The targeted probe verifies center/halo behavior only, not all motion/ramp pixels or all artifacts.

M4's [harness](../sim/validate.py) forces PQ code 1 (a **10,000-nit request**) for windows/ANSI, uses fresh settled state for static patterns, and runs seven nominal window areas at 384×216. Its moving-edge helper also creates a fresh pipeline per frame, carrying temporal state but not load state, so that sequence does not validate attack/release either. It does not supply measured dwell or thermal prehistory, and it does not test the 75% source node. Record actual rasterized area. With `abl_source: demand` and the WOLED fallback reference 850 nits, an approximately 10% 10,000-nit request already saturates normalized load; retaining the old gamma/ceilings will not retain the old window result. Keep demand-APL refits in a separate experiment with known stimulus amplitude.

For later implementation, compare unchanged-default results against both the pre-change current tree and the saved M4 manifest, explicitly accounting for the QD PSF difference. Use `python3 -m sim validate --out /tmp/tv-m6-parity` to avoid overwriting committed reports, preserve commit/profile hashes, and compare linear-nit metrics/arrays with declared tolerances. M4's defaults are six motion frames and 8 pixels/frame; changing frame count, history or geometry changes the comparison. Adding measured replay, angular leakage, edge compensation, demand APL or nonzero dynamics is an opt-in baseline change, not an M4 parity requirement.

## 7. Keep host preview calibration separate

Per [M5 Mac display research](m5-mac-display.md), profile measurements describe TV physical output. Preserve `Pipeline.run_linear()` arrays and explicit primaries/white/units before any preview transform. The uint8 encode path and harness's per-image-normalized PNGs cannot validate absolute HDR differences. A host manifest needs display/preset, measured SDR white W, current/reference EDR headroom, measured window/time/color/black envelope, instrument/geometry, and the shared preview transform. Actual host values remain NR until measured.

Use one fixed exposure or declared tone map across compared TVs **and temporal frames**; independent or per-frame normalization can hide brightness and ABL differences. Host optics and mini-LED leakage add their own halos after simulated optics, so a Mac preview cannot identify the TV kernel. Apple's 1600-nit MacBook peak specification does not fill a window/dwell table or certify sustained full-field output; the external Pro Display XDR's 39% condition is not a MacBook condition. Keep host calibration out of TV `hdr`, `panel` and PSF fits.

## 8. Implementation handoff and remaining NR data

1. Add a versioned provenance/measurement sidecar and validation before changing runtime profiles. Preserve measured/derived/interpolated status per value, raw source locators, unknown conditions and out-of-support failures. C2/S95B/X955 can supply named-sample peak records; IPS still cannot supply a window table.
2. Add opt-in window replay/drive fitting with explicit amplitude/color/time matching and a separate dataset ID; fit output luminance without double limiting. Keep defaults and original generic YAMLs for comparisons.
3. Use the existing half-LSF hook only for identified symmetric separable data. Full `H_ij`, location-dependent edge/light-guide maps, calibrated all-on fields and matched retail-TV optical LSFs remain NR and need additional code/data.
4. Add LCD angular transmission with independently identified white/leakage/gray terms. VA's older sparse endpoints are demonstrations; IPS leakage and both current profiles' full angular fits remain NR. OLED angular spectra/gains remain NR under an emitter model.
5. Add optional OLED capacity attack/release only after defining state domain, initialization and conflict handling. Measured constants, thermal/static-image controllers, RGBW allocation and watt coefficients remain NR. Run a history-aware experiment separate from the settled static M4 harness.

Review this note by checking YAML syntax, supported keys against the dataclasses, the source tables against M5/original URLs, and the parity exceptions against current stage ordering. This research does not establish new device calibration or update the saved M4 report.
