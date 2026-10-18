# M12b source ledger / 数字与证据

This page explains the current CPU reference implementation and clearly labeled synthetic experiments. The four `generic_*` presets are **P placeholders**. They are not calibrated examples of a named television. `evidence.json` snapshots effective profile values including dataclass defaults, plus formulas and limitations used by the explainer.

## 1. Pipeline / 管线

Use the actual order in [src/tv_sim/pipeline.py](../src/tv_sim/pipeline.py), not the aspirational ordering in [docs/research/06-sim-architecture.md](../docs/research/06-sim-architecture.md#data-flow-and-units):

`encoded RGB → EOTF decode → resize/sharpen → backlight/zone spread → panel → HDR shoulder/ABL → ambient → temporal → optional preview encode`.

- Buffers are float32 linear RGB in nit-scaled units. `Pipeline.run_linear()` returns the physical-model output before preview encoding; `run()` returns an 8-bit preview. Neutral `(L,L,L)` has luminance `L`; a single colored RGB component is not patch luminance.
- Current linear luminance weights are BT.709: **0.2126 / 0.7152 / 0.0722**, from [src/tv_sim/color.py](../src/tv_sim/color.py). The `Frame` has no complete color-space metadata. Identity panel matrices do not implement full BT.2020-to-panel color management.
- Default sRGB input white is **100 nits**; PQ input is absolute; HLG uses **1,000-nit** target peak by default. Raising panel capacity does not turn sRGB input into an HDR stimulus.
- Opt-in sequence reconstruction occurs after per-source decoding/spatial processing and before the backlight/panel stages. Display/load history advances once per output tick. See [src/tv_sim/sequence.py](../src/tv_sim/sequence.py).
- Ambient precedes response/BFI in the compatibility pipeline. Zero lux is required when illustrating emitted-light/BFI behavior without that ordering artifact.

Research citation: [M6 §1](../docs/research/m6-profile-wiring.md#1-what-can-be-wired-today), [M5 Mac §1](../docs/research/m5-mac-display.md#1-preserve-the-simulators-physical-output). Runtime authority: [pipeline.py](../src/tv_sim/pipeline.py), [decode.py](../src/tv_sim/stages/decode.py), [encode.py](../src/tv_sim/stages/encode.py).

## 2. Panels and subpixels / 面板与子像素

- LCD uses a shared backlight plus finite transmission; OLED emits per pixel. Mini-LED describes the backlight, not a separate LCD material. LED count is not independently controlled zone count.
- RGB stripes are a generic LCD aperture illustration. Actual RGB/BGR order, electrode domains, aperture dimensions and fill factors remain **NR** for these presets.
- WRGB uses a white-emitting OLED stack with filtered R/G/B and an additional W aperture. Aperture order varies by model/generation. The macro renderer illustrates an **R/W/B/G** repeat, not a universal layout.
- The cited QD-OLED TV family uses blue OLED excitation, red/green QD conversion and retained blue, with green above red/blue in a staggered triangular pattern. This is not a statement that every QD-OLED generation uses that layout.
- [src/tv_sim/macro.py](../src/tv_sim/macro.py) gives every technology the same square logical pitch. Default fill factor **0.72** and WRGB white allocation **65% × min(R,G,B)** are **P synthetic** choices. Apertures are independently area-normalized so the cell mean recovers input RGB. Concentrated aperture peaks are visualization energy, not measured emitter peak luminance. This macro allocation differs from the coarse, recombined runtime mosaic.
- A nominal **65-inch, 3,840×2,160** square-pixel raster has **0.375-mm pitch / 67.8 PPI (D)**. Same active size and logical resolution imply the same logical pixel pitch; subpixel spacing is not automatically pitch/3 or pitch/4.
- CRT/plasma are researched but have no current runtime profile.

Research citation: [Panel constructions](../docs/research/01-panel-tech.md#definitions-and-defensible-comparisons), [M5 §4 layout and pitch](../docs/research/m5-fidelity.md#4-aperture-geometry-and-physical-pixel-pitch). Runtime authority: [macro.py](../src/tv_sim/macro.py), [panel.py](../src/tv_sim/stages/panel.py).

## 3. Local dimming / 分区调光

Current VA preset: **16 columns × 12 rows = 192 zones**, a coarse **P demonstration**, not a shipping-TV zone map. At 4K, nominal pitch is **240×180 image pixels (D)**. IPS uses **8×1 full-height strips (P)**.

The regular-grid approximation pools `max(R,G,B)` in nits (zone percentile **100 = maximum**), expands rectangular zone footprints, applies the unit-sum PSF and clips backlight capacity. `B_i = Σ_j H_ij d_j` is the general transport model; no dense measured `H` is loaded by these presets.

VA spread is `K = 0.92 G_core + 0.08 G_tail`, with core sigma **0.75 / 0.75 zone pitches**, tail sigma **2 / 2 pitches**, and **reflect** boundary treatment. Each axis scales by its own zone pitch. These numbers are **P placeholders**, not measured optical constants.

For positive backlight `B`, the LCD output constraint is `L=clip(T,B/C,B)`. Thus a black target is bounded by `B/C`. **B=1,000 nits and C=4,000 give 0.25-nit leakage (D from synthetic inputs)**; **C=1,000 gives 1 nit**. Backlight spread and finite extinction together create LCD blooming. A blur applied to the final picture is a different mechanism.

Limits: no measured TV influence matrix, edge-light guide, zone-controller lag, iterative LCD/backlight allocation or per-zone watt model. The numerical `1e−8` safe floor in the legacy LCD function is not a physical black pedestal.

Research citation: [Transport and compensation](../docs/research/02-backlight-local-dimming.md#layout-and-light-transport), [M3 current grid/optics](../docs/research/m3-local-dimming-params.md#grid-and-optics), [M5 halo evidence](../docs/research/m5-fidelity.md#3-zone-transport-psf-shape-and-measured-halos). Runtime authority: [VA YAML](../src/tv_sim/profiles/generic_va_fald_miniled.yaml), [backlight.py](../src/tv_sim/stages/backlight.py), [panel.py](../src/tv_sim/stages/panel.py).

## 4. HDR and ABL / 绝对亮度与负载

PQ/ST 2084 is an absolute transfer definition, independent of display peak:

`p=N^(1/m2)`; `L=10000[max(p−c1,0)/(c2−c3p)]^(1/m1)`.

Constants: `m1=2610/16384`, `m2=2523/32`, `c1=3424/4096`, `c2=2413/128`, `c3=2392/128`. Checks: **N≈0.508078 → 100 nits; N≈0.751827 → 1,000 nits; N=1 → 10,000 nits (D)**.

The runtime shoulder is **P**, not BT.2390 or a disclosed vendor curve. For `K=kP`, it preserves `Y≤K`, otherwise `f(Y)=K+(P−K)[1−exp(−(Y−K)/(P−K))]`. With **P=1,000 / k=0.7**, outputs are **700 → 700**, **1,000 → 889.64**, **4,000 → 999.995 nits (D)**. It approaches the peak asymptotically, not at a finite mastering endpoint. RGB scales by `f(Y)/Y`, then excessive channels project toward equal-channel white.

ABL ceiling model: `a=clip(APL/P0,0,1)`; `P(a)=F+(P0−F)(1−a)^g`. A neutral window on black has `APL_request = area_fraction × requested_nits`. Area equals normalized APL only when request amplitude equals the stated reference `P0`.

| Current P preset | P0 / F (nits) | g | Knee | ABL |
|---|---:|---:|---:|---|
| VA FALD | 2,000 / 620 | 1 | 0.70 | on |
| IPS edge | 400 / 350 | 2 | 0.85 | off |
| WOLED | 850 / 170 | 2.4 | 0.85 | on |
| QD-OLED | 1,100 / 199 | 1 | 0.85 | on |

**Current-default caveat:** all shipped presets inherit `abl_source=emitted`, so their ceiling reads panel-stage output after panel clipping. `abl_source=demand` is a supported opt-in mode that reads requested linear luminance upstream. A dial using the research request-APL contract must label that experiment explicitly. `abl_response_ms=0` and `abl_backlight_tracking=0` retain instantaneous legacy behavior. `abl_power_budget_nits=0` disables the optional weighted-nit proxy, which is not an electrical watt budget. No timed thermal/static-logo behavior is modeled.

Research citation: [PQ and HLG](../docs/research/03-color-hdr.md#pq-and-hlg), [M3 ABL contract](../docs/research/m3-hdr-abl-params.md#abl-versus-load), [M6 current knobs](../docs/research/m6-profile-wiring.md#5-oled-abl-attack-and-release). Runtime authority: [color.py](../src/tv_sim/color.py), [tonemap.py](../src/tv_sim/stages/tonemap.py), [load.py](../src/tv_sim/load.py), [profile defaults](../src/tv_sim/profile.py).

## 5. Time and motion / 响应、保持与运动

The response surrogate is `q_next=u+(q_prev−u)exp(−dt/τ)` on emitted RGB. The first frame is fully settled; subsequent calls retain state before BFI/pursuit blur. **τ is not a quoted GtG average**. Only a monotonic one-pole response in the same measurement domain gives `t10–90=ln(9)τ`.

| P preset | τ (ms) | Derived t10–90 (ms) |
|---|---:|---:|
| VA | 8 | 17.58 |
| IPS | 12 | 26.37 |
| WOLED | 0.2 | 0.439 |
| QD-OLED | 0.1 | 0.220 |

OD uses a synthetic boosted command `u+k(u−q_start)` for a short prefix, then returns to target. All profiles have gain **0**; the LCD prefix setting is **2 ms**, OLED **0**. No measured transition/voltage LUT identifies these values.

Sample-and-hold is distinct from response lag: a fast emitter held in place still smears during pursuit. For an ideal single rectangular emission aperture, `T_visible_ms=1000*d/f`, full support `b=|v|*T_visible_ms/1000`, and 10–90 edge width `0.8b`. At fixed peak, mean luminance falls by duty `d`.

| Ideal D calculation, v=960 px/s | Visible time | Full support | 10–90 edge width |
|---|---:|---:|---:|
| 60 Hz, d=1 | 16.667 ms | 16 px | 12.8 px |
| 120 Hz, d=1 | 8.333 ms | 8 px | 6.4 px |
| 60 Hz, d=0.5 | 8.333 ms | 8 px | 6.4 px |
| 120 Hz, d=0.25 | 2.083 ms | 2 px | 1.6 px |

These are **not measured device MPRT**. Default runtime uses endpoint response plus seven shifted pursuit samples; the gallery opts into sixteen analytic subframe samples with a synthetic centered rectangular BFI aperture. No measured PWM, scanout or BFI waveform is claimed.

24p repeated at **60 Hz** produces **3:2 holds / 50 and 33.333 ms**. At **120 Hz**, **5:5 / 41.667 ms** equalizes cadence but keeps 24 unique motion positions per second. Current MEMC modes are **off / repeat / analytic**, default off. Analytic reconstruction uses known translations or known layered masks/depths; no automatic motion estimation or scene-cut detection is included. Rational timing is **D**, synthetic reconstruction is **P**, vendor algorithms/latency are **NR**. At 480 px/s, source steps are **20 px at 24 fps**, and ideal output steps are **8 px at 60 fps / 4 px at 120 fps**.

Research citation: [M5 response and timing](../docs/research/m5-fidelity.md#5-response-overdrive-emission-timing-and-mprt), [M7 cadence](../docs/research/m7-memc-motion.md#4-cadence-conversion-stutter-and-the-soap-opera-effect). Current support authority: [README](../README.md), [sequence.py](../src/tv_sim/sequence.py), [temporal.py](../src/tv_sim/stages/temporal.py).

## 6. Viewing angle / 视角

M10 is opt in and separate from legacy profile values. Combined center-ray angle obeys `cosθ=cos(h)cos(v)`, with **0–45°** exploration support; outside is rejected. Signed symmetry and independence from azimuth are **P assumptions**, not measured support.

For `s=sin²θ/sin²45°`, gains interpolate with `exp(log(gain45)*s)` and gray exponents with `1+(exponent45−1)*s`. LCD independently varies white gain `Fw`, emitted-black gain `Fb`, and gray exponent; `epsilon=epsilon0*Fb/Fw`. OLED uses only RGB emission gains.

| Current P endpoint at 45° | White RGB gain | Emitted-black gain | Gray exponent / emission gain |
|---|---|---|---|
| VA LCD | (0.65, 0.65, 0.65) | (5, 5, 5) | exponent (0.80, 0.84, 0.90) |
| IPS LCD | (0.80, 0.80, 0.80) | (2, 2, 2) | exponent (0.98, 1, 1.02) |
| WOLED | — | not applicable | emission (0.88, 0.92, 0.96) |
| QD-OLED | — | not applicable | emission (0.95, 0.96, 0.94) |

At a fixed 100-nit LCD backlight without other processing, the VA synthetic endpoints give **100/0.025 nits at 0° → 65/0.125 nits at 45°; contrast 4,000:1 → 520:1 (D)**. IPS gives **100/0.0833 → 80/0.1667; 1,200:1 → 480:1 (D)**. These are independent model mechanisms, not a retail ranking or measured fit.

All shipped angular values are **P placeholders**. Full fits, IPS angular leakage calibration, and measured OLED gains/spectra remain **NR**. A center-angle model does not predict per-pixel seat geometry or IPS corner glow. Do not apply an extra cosine fade to a luminance curve.

Research citation: [M5 angular mechanisms](../docs/research/m5-fidelity.md#2-viewing-angle-leakage-white-gain-and-gamma-need-separate-fits), [M6 angular source boundaries](../docs/research/m6-profile-wiring.md#3-angular-leakage-separate-va-and-ips-fits). Current authority: [M10 provenance](../docs/profiles.md#angular-schema-version-1-m10), [viewing_angle.py](../src/tv_sim/viewing_angle.py).

## 7. Host brightness / 宿主显示器映射

The static browser explainer is an SDR visualization, not a calibrated physical HDR presentation path. Current 8-bit sRGB preview maps **100 simulated nits to code 1** and clips higher values. `run_linear()` retains the original modeled nits.

- **Shared scale:** `L_preview=sL_T` preserves ratios inside the unclipped common range and changes absolute brightness/adaptation. For a hypothetical measured 600-nit host and 3,000/1,000-nit TVs, common **s=0.2 → 600/200 nits (D/P)**. Per-TV normalization would erase the 3:1 ratio.
- **Hard clip:** `min(L_T,L_H)` preserves lower values and loses differences above `L_H`. A shared shoulder preserves more highlight detail while changing ratios; it must be labeled.
- **EDR:** proposed native float path uses `C_EDR=M*C_TV_nits/W`, where **W is measured EDR=1 SDR/UI white**, not an assumed universal nit value. With **W=100 nits and admissible H=10**, 100/400/1,000 nits request EDR **1/4/10 (D/P)**. Ideal neutral ceiling is `W*H`; headroom alone is not a nit meter. Potential, current, and reference maxima have different meanings.
- A dimmer host cannot emit a brighter TV's original light. Lowering SDR white may raise the relative EDR ratio without raising physical peak. Host black floor, dimming halos, gamut/color volume, window/duration limits, ambient/adaptation and response/BFI remain separate limits. No Mac renderer or host calibration was implemented by that research.

Research citation: [EDR relative white](../docs/research/m5-mac-display.md#2-edr-is-relative-to-sdr-white-not-an-absolute-nit-encoding), [Shared scale and clipping](../docs/research/m5-mac-display.md#6-a-dimmer-host-cannot-emit-the-brighter-tvs-light). Runtime authority for current SDR output: [encode.py](../src/tv_sim/stages/encode.py).

## 8. Provenance / 证据等级

| Grade | Meaning | Safe page example |
|---|---|---|
| M | Published measurement on the named specimen in recorded conditions | LG 42C2 HDR Standard, DTM off: 10% window **717 nits**, 100% **152 nits**; dwell NR |
| D | Calculation from stated inputs, method and source retained | **1,000/4,000=0.25 nit** from a declared synthetic backlight/contrast example |
| P | Proposed model, synthetic preset, fitting choice or interpolation | **16×12**, sigma **0.75**, or a value interpolated between M nodes |
| NR | No verified numerical reference, unidentified parameter or unknown condition | Timed sustained traces, exact optical PSF, source amplitude or dwell where unknown |

`NR` never means zero; use `not_applicable` for an absent mechanism. A measurement can be M while its dwell, requested amplitude or uncertainty is NR. Interpolation between measured nodes remains P. Numerical membership in a published envelope is not a calibration pass.

Named-sample source records retain independent conditions: [M6 window table](../docs/research/m6-profile-wiring.md#2-measured-window-and-apl-records), [versioned provenance sidecars](../docs/profiles.md#preserved-measurement-records). S95B's independent 2%/5%/75% values remain NR; X955 numerical support starts at 2%; IPS's 455-nit scalar has unknown window fraction and cannot form a window curve.

Convention authority: [docs/profiles.md](../docs/profiles.md#evidence-and-unknowns), [M5 fidelity](../docs/research/m5-fidelity.md).

## Historical-text cautions

Current code and versioned sidecars take precedence for runtime behavior. Earlier research still supplies measurement sources and model reasoning.

- The first M4 sections of [docs/reports/REPORT.md](../docs/reports/REPORT.md) are historical. Their “OLED PSF ignored”, “MEMC not implemented” and chroma-only-angle wording must not describe current code.
- [M6 §1](../docs/research/m6-profile-wiring.md#1-what-can-be-wired-today) already identifies M5's stale emitted-only APL / ignored-PSF descriptions. The current QD-OLED **0.45-pixel** PSF actually spreads emitted RGB. [M6 §6](../docs/research/m6-profile-wiring.md#6-defaults-and-the-limits-of-m4-parity) records the saved-M4 parity exception.
- M6 angular extensions and M7 sequence CLI examples were design proposals when written. M10 and current README/code now implement opt-in angular behavior and **off/repeat/analytic** sequences. Proposed automatic block estimation and `blend/mci` modes remain absent.
