# M5 fidelity: measured anchors, quantitative models and exposed parameters

Research checked **2026-10-16**. Scope: the four existing profiles, `generic_va_fald_miniled`, `generic_ips_edge`, `generic_woled`, and `generic_qdoled`. This is a research and implementation specification; it does not recalibrate their placeholder YAML values. Read alongside [STATUS](../reports/STATUS.md), [REPORT](../reports/REPORT.md), [M4 references](m4-reference-ranges.md), and the [M1 architecture](06-sim-architecture.md). CRT/plasma and GPU implementation are outside this note.

**Evidence labels:** **M** = published measurement on the named sample; **D** = calculation from stated inputs; **P** = proposed simulator model or fitting choice; **NR** = no verified numerical reference, missing conditions, or an unidentified parameter. NR is not zero. A mechanism that does not apply is explicitly marked *not applicable*. An approximate number retains its publisher's rounding; these sources generally do not supply uncertainty budgets. A TV sample, a supporting monitor measurement, and a technology-wide distribution are different kinds of evidence.

Every fit needs model, diagonal, region/panel variant, firmware, picture/input mode, local dimming, refresh/VRR, white point, source encoding and requested luminance, pattern geometry/position, warm-up, dwell, ambient and viewing geometry. Unknown conditions remain NR. The equations labeled P below are implementable approximations, not disclosed vendor algorithms.

## 1. Load-dependent brightness: window curves are conditional measurements

Define window fraction `f = lit area / screen area`. Define **absolute requested APL** as `A_req = mean(Y_req)` in nits, in linear light before limiting; a normalized load is `a_req = A_req / Y_ref`, with `Y_ref` recorded. For a neutral window on black, `A_req = f * Y_window,req`. Thus 10% area equals 10% normalized APL only for the declared reference level. Mean PQ code, measured output APL, and window area cannot be exchanged.

The following are original published tables or exact table-image transcriptions. They improve on several NR cells in M4. They are separate device/mode datasets, not one combined curve. All entries are nits; **peak does not establish a timed sustained value**.

| Sample / conditions | 1% | 2% | 5% | 10% | 25% | 50% | 75% | 100% | Timing / provenance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| WOLED: LG **42C2**, HDR Standard, dynamic tone mapping off | 717 | 717 | 717 | 717 | 396 | 243 | 192 | 152 | **M**, [TFTCentral review](https://tftcentral.co.uk/reviews/lg-oled-42c2), [original table image](https://tftcentral.co.uk/wp-content/uploads/2022/04/HDR_standard_3.png). Peak-window test; dwell NR. |
| QD-OLED: Samsung **65-inch S95B**, HDR10 Filmmaker | 1,000 | NR* | NR* | 1,000 | 600 | 300 | NR | 200 | **M**, [Sound & Vision test bench](https://www.soundandvision.com/content/samsung-65-s95b-quantum-dot-oled-4k-tv-review-test-bench): rounded 1–10% plateau; dwell NR. |
| VA mini-LED: TCL **98X955**, Theatre HDR | NR | 1,675 | 3,000 | 3,200 | 3,200 | 1,800 | 1,100 | 896 | **M**, [L&B original measurements](https://www.lbtechreviews.com/test/tcl-x955). Dwell NR; not transferable to a smaller X955. |
| IPS edge-lit: LG **55UH770V** | NR | NR | NR | NR | NR | NR | NR | NR | [HDTVTest](https://www.hdtvtest.co.uk/news/55uh770v-201610064369) reports a 455-nit peak without sufficient window/dwell conditions to fill these cells. |

*The S95B source states 1,000 nits over 1–10% windows; independent 2% and 5% readings are not tabulated. NR preserves that distinction rather than manufacturing extra samples. Its separate 1,004-nit HDR peak also appears in the review and should not be treated as a different window point.

For a historical **APL-labeled** comparison, DisplayMate measured LG **65EG9600** factory Cinema at **25/50/100% APL = 242/157/91 nits**; Vivid was **428/232/141**. This SDR-era dataset is distinct from the C2 HDR curve. [Original 2015 test](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm). The different curves emphasize picture-mode dependence. Time-qualified 0.1/1/10/60-second full-field traces for the selected C2, S95B, X955 and IPS samples remain **NR**.

### Concrete load models

1. **P: measured-window replay.** Store `(f, requested_level, RGB/white stimulus, time, temperature, mode, L_center)` nodes. Use piecewise-linear interpolation within a matched sweep, with no claim that interpolated values were measured. Separate peak and sustained tables; expose endpoint policy and fitted support. For WOLED/QD-OLED these measured neutral sweeps can use monotone interpolation. For mini-LED preserve the measured low-area suppression: the 98X955 is dimmer at 2% than at 10–25%. A forced monotone ABL curve would erase controller behavior.
2. **P: content proxy, explicitly optional.** `f_eff = mean(Y_req)/max(Y_req)` (zero for black) can index a neutral window table at the same maximum request. It measures spatial occupancy, not absolute electrical load: a 100-nit and 1,000-nit full field both give 1. Expose this as an approximate window proxy, never the default definition of APL. A full content model needs sweeps over requested amplitude and color as well as area.
3. **P: OLED power allocation.** Define `e_ic` as normalized **light-linear emitted amplitude** of channel c, with a calibrated XYZ basis and channel maximum. Use `P_req = P_idle + mean_i(sum_c k_c * e_ic^eta_c)`, `c=RGBW` for WOLED and `RGB` for QD-OLED. Solve for a common gain `g in [0,1]` such that `P(g*e) <= P_budget`, respecting individual channel maxima; bisection handles nonlinear positive exponents with nonnegative coefficients and a budget at least as large as idle power. Allocate RGBW to match target XYZ before applying current limits. The extra W aperture changes white-versus-saturated-color capacity. Channel watt coefficients, dimensionless exponents, idle draw, RGBW allocation LUTs and budgets for these TVs are **NR**; the measured white curves alone do not identify them.
4. **P: LCD backlight power.** `P_BL = P_idle + sum_j p_j * d_j^eta_j`, with zone drives `d_j in [0,1]`. Limit drives, reconstruct the backlight, then recompute LCD compensation. Emitted APL alone cannot predict this load: dark LCD pixels can sit over energized zones. The IPS edge case uses long strip influences (or one global drive), not per-pixel emissive power. Published watts-to-zone-drive coefficients are **NR** for both LCD profiles.
5. **P: separate state timescales.** Fast current limit, temperature-dependent capacity, and static-image dimming need separate states. One possible thermal surrogate is `T_next = T_eq(P) + (T_prev-T_eq(P))*exp(-dt/tau_th)`. Fit attack/release and thermal behavior from traces; their values are **NR** here. Do not turn source-history/static-logo dimming into pixel response lag.

The present implementation instead evaluates a synthetic ceiling after the panel stage: `F + (P0-F)*(1-clip(mean(Y_panel)/P0,0,1))^gamma` ([tonemap.py](../../src/tv_sim/stages/tonemap.py)). Its `abl_gamma` is not a measured power exponent, and `abl_power_budget_nits` is weighted nits, not watts. A table should constrain actual center output; using a measured output as an asymptotic shoulder ceiling can undershoot it. Solve the drive/tone-map/load relationship rather than applying the same restriction twice.

## 2. Viewing angle: leakage, white gain and gamma need separate fits

### Published angular anchors

[DisplayMate's 2017 direct TV comparison](https://www.displaymate.com/TV_Picture_Quality_with_Viewing_Position_1.htm) measured these sample-specific endpoints:

| Sample / mode | Gamma at 0° | Gamma at 45° | 45° luminance / 0° luminance (**D**) | Reported picture-contrast decrease |
|---|---:|---:|---:|---:|
| IPS LG **65SJ9500**, Cinema | 2.26 | 2.24 | 0.32 (68% decrease) | 5% |
| VA Samsung **65Q8**, Movie | 2.36 | 1.93 | 0.35 (65% decrease) | 63% |

The last column describes the grayscale intensity range over **10–100% signal**, not black-to-white extinction/native contrast. Numerical angular black levels in this comparison are **NR**. A stable gamma does not establish stable black. These are older LCD designs; wide-angle compensation films and newer panel variants need their own measurements.

On-axis IPS extinction anchors remain useful: LG **55UH770V** dimming-off ANSI black **0.093 nit at 120-nit white** gives **D: 1,290:1** ([HDTVTest](https://www.hdtvtest.co.uk/news/55uh770v-201610064369)); **49UB850V** gives **0.157 nit at 120**, or **D: 764:1** ([original test](https://www.hdtvtest.co.uk/news/49ub850v-201406033786)). These sample ratios do not specify angular leakage.

For leakage specifically, [DisplayMate's 2015 Samsung UN65JS9500 PVA FALD test](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm) reports dimming-off Movie white/black **207/0.066 nits** (about **3,136:1**). Its angular results give white **52% lower** and black **419% higher** at 45°. Therefore **D** `F_white=.48`, `F_black=5.19`, `C45/C0=.48/5.19=.0925`. A 419% increase means 5.19 times the original. The angular mode should not be inferred from the separate Movie result. This conventional FALD sample supports the mechanism, not a mini-LED profile fit.

### Concrete angular model

For either LCD, use **P**:

```text
L_i(theta,phi) = B_i * Fw(theta,phi)
                * [epsilon(theta,phi) + (1-epsilon(theta,phi))*g(q_i;theta,phi)]
epsilon(theta,phi) = 1 / C_native(theta,phi)
g(0)=0; g(1)=1
```

`B` is the normal-incidence fully open white backlight field. `Fw` is relative white luminance; `epsilon` is leakage relative to the fully open state **at the same angle**. Given separately measured white/black angular factors, `epsilon(theta)=epsilon(0)*F_black(theta)/Fw(theta)`. Consequently `L_black(theta)=B*epsilon(0)*F_black(theta)`. Fitting black and then also multiplying it by the same black-rise factor would double-count leakage.

Prefer signed horizontal/vertical/azimuth × gray × RGB LUTs. A reproducible sparse-endpoint demonstration on **0–45° only** can use:

```text
s = sin(theta)^2 / sin(45 degrees)^2
gamma(theta) = gamma0 + (gamma45-gamma0)*s
Fw(theta) = exp(log(Fw45)*s)
g(q;theta) = q^(gamma(theta)/gamma0)  # q is linearized at normal incidence
```

Interpolation is **P**, not additional angle measurements. Applying the full encoded gamma exponent again to already-linear q would be wrong. Near-black VA shoulders/domain mixtures need a LUT; one fitted gamma cannot describe every level. Do not infer an IPS angular leakage coefficient from its gamma endpoints. Complete angular extinction fits for both current profiles remain **NR**.

Compute each pixel's angle from screen dimensions, surface normal and eye position; use both eyes or a declared cyclopean eye. A single center-angle slider misses center-to-edge changes and IPS corner glow. Do not impose an extra cosine on a measured luminance curve.

For **WOLED and QD-OLED**, LCD transmission/extinction is *not applicable*. Use `XYZ_out=sum_c M_c(theta,phi,drive)*e_c`: angular primary spectra/gains and any gray dependence require emitter/film measurements. Full numerical angular RGB/gray LUTs for the selected OLED samples are **NR** here; the existing chroma-loss constants do not supply them.

## 3. Zone transport, PSF shape and measured halos

### Transport model and shape choices

For VA FALD and IPS edge LCDs, **P** `B_i=sum_j H_ij*d_j`, `0<=d_j<=1`; `H_ij` is the influence of zone/strip j at pixel i, in fully open-white nits per unit drive. Calibrate the all-on field once. Preserve edge losses or explicitly fit compensation; normalizing each clipped edge PSF independently invents light.

For LCD target T and leakage epsilon, use `q=clip((T/B-epsilon)/(1-epsilon),0,1)`, `L=B*(epsilon+(1-epsilon)*q)` for positive B; explicitly return zero emission for B=0. At angle, use the angular model above. Thus the black target near a highlight approaches `B/C_native`. As a **D synthetic example**, `B=1,000 nits` gives `0.25-nit` leakage for `C=4,000` and `1 nit` for `C=1,000`. These are calculations, not measured halo values.

Useful implementable shape families are:

| Influence family | Formula / representation (**P** unless sourced) | Appropriate use and limits |
|---|---|---|
| Anisotropic Gaussian | `G=exp[-.5*((x/sx)^2+(y/sy)^2)]/(2*pi*sx*sy)` | Smooth core; store sigma in mm or explicitly identified zone pitches, not unexplained preview pixels. |
| Core + scatter tail | `K=(1-a)*G_core+a*G_tail`, convolved with a measured/declared source footprint | Existing M3 family; tail energy a and sigmas remain synthetic until fitted. A wide low-energy tail can dominate dark-field halos. |
| Compact spline / measured map | Nonnegative spline basis or sampled per-zone `H_ij` | Allows non-Gaussian lobes, asymmetry and location-dependent optics; prefer measured maps for device emulation. |
| Edge light-guide influence | Per-strip/edge 2-D fields, including long propagation direction | IPS edge profile: full-height strips are a coarse stand-in. A radial FALD Gaussian is not evidence for its light-guide spread. |

A primary optical-design example, [Tan et al. 2018](https://doi.org/10.1364/OE.26.016572), uses a Gaussian diffuser component with **sigma 0.4 mm**, **1-mm LED pitch** and **6×6 LEDs per zone** in a **6.4-inch 2880×1440 IPS prototype**. Sigma is **0.4 LED pitches**, not 0.4 zone pitches; propagation and source geometry also contribute. These are prototype optical-model inputs, not a measured retail TV PSF. [Accessible paper](https://pdfs.semanticscholar.org/c17a/6ee3eb4a77d3fd87c64d90443e0bc2e5c7fc.pdf).

### Published halo measurements, separated from bare optical PSFs

[He et al. 2025, Optics Express](https://doi.org/10.1364/OE.557308) ([full text](https://www.researchgate.net/publication/389338778_Measurement_and_characterization_of_the_halo_effect_for_mini-LED_backlit_LCDs)) measured **27-inch IPS Lenovo Creator Extreme**, **1,152 zones**, native CR about **1,100**, and **27-inch VA KTC M27T20**, **576 zones**, CR about **3,000**. The box is **5% of each screen dimension** (**D: 0.25% area**), meter distance **1 m**, detection floor **0.001 nit**; masks separate camera flare from screen leakage. Lenovo's isolated halo maximum was **within 0.25 nits**; white/maximum halo about **1,000:1**, instrument-glare/halo about **30:1**. Both examples admitted Gaussian effective halo profiles. Their model `L_halo(x)=L_white*T*exp[-.5*(x/Wsigma)^2]` uses pixel width and `T≈1/CR`. This measures the controlled display's effective halo, not an isolated `H_ij`.

The [IDW 2023 precursor, LCT4-4](https://confit.atlas.jp/guide/event-img/idw2023/LCT4-04/public/pdf_archive?type=in) gives a concrete one-dimensional fit:

```text
L_halo(x) = 0.247 * exp[-0.5*((45-x)/129)^2] nits
```

The fit's sampling-to-physical/zone-pitch conversion is **NR**; **129 is not a transferable TV optical sigma**. This precursor and the later paper are related evidence, not independent population samples. The later paper explicitly uses pixels for its width variable. Neither source identifies our TV profiles' PSFs.

For comparison, **P** a centered Gaussian with amplitude A and width sigma crosses threshold h at `r=sigma*sqrt(2*ln(A/h))` when `A>h`; its full-line FWHM is `2.355*sigma`. A truncated outside-edge halo is not a full Gaussian spot. Width also changes when the threshold changes; always store h and coordinate units. The paper's 0.001-nit boundary is its measurement convention, not a universal visibility threshold.

| Current profile | Physical mechanism / available evidence | Missing quantitative identification |
|---|---|---|
| VA FALD mini-LED | Backlight spread × finite extinction; VA monitor halo evidence above | Matched TV zone map, calibrated `H`, sigma/tail and absolute halo profile **NR** |
| IPS edge LCD | Leakage over long strip/light-guide fields; IPS mini-LED monitor evidence does not identify an edge guide | Edge-strip `H`, angular halo width/luminance **NR** |
| WOLED | No LCD-zone leakage; emission may scatter in panel/cover optics | Measured emitted optical PSF **NR** |
| QD-OLED | No LCD-zone leakage; conversion/cover optics and observer flare are distinct effects | Measured emitted optical PSF **NR** |

Measure horizontal/vertical halo profiles, near-ring mean/max, far black, threshold width, outside-window energy and highlight retention. Save both all-black-run and same-frame-far-black baselines. Repeat window sizes/locations/zone phases, angles and dimming modes. Store distances in screen pixels, mm, zone pitches and visual degrees; the current 1–3-preview-pixel ring changes meaning with resolution. Calibrated camera flare subtraction is essential before fitting a weak tail. The simulator's emissive branch currently ignores its computed backlight/PSF map ([panel.py](../../src/tv_sim/stages/panel.py)); zero OLED halo in M4 does not validate optical scatter.

## 4. Aperture geometry and physical pixel pitch

### Layout evidence

The [LG Display construction description](https://www.lgdisplay.com/eng/attachment/download?originFileName=2018+Annual+Report_Form+20-F.pdf&s3FileName=2021-10-18%2FatAE9yAGG3l42LyLJEovkidNVoLNEla5.pdf) describes white OLED with color filters and an additional white subpixel. Original macro photographs show why a generic four-stripe mask is insufficient:

| Class | Published layout / concrete model requirement | Numerical aperture data |
|---|---|---|
| WOLED | Conventional older **RWBG** repeat; LG G5 example **BWRG**. Identify model/generation and RGBW allocation. [Original macros](https://www.rtings.com/tv/learn/qd-oled-vs-woled) | Per-channel polygons, widths, offsets and fill factors **NR**; do not assume four equal areas. |
| QD-OLED TVs in cited examples | Staggered/triangular RGB; green above red/blue in the illustrated repeat. [Original macro and construction analysis](https://www.rtings.com/tv/learn/what-is-qd-oled/) | Exact aperture dimensions/offsets **NR**; topology is observed, not metrically calibrated. |
| VA mini-LED LCD | RGB/BGR stripe and domain geometry must be identified from that panel | Current `rgb_stripe` is a placeholder; calibrated aperture **NR**. |
| IPS edge LCD | RGB/BGR aperture and electrode/domain pattern must be identified per panel | Current `rgb_stripe` is a placeholder; calibrated aperture **NR**. |

QD-OLED topology is not universal across products: [Samsung Display's 2026 monitor V-stripe announcement](https://news.samsungdisplay.com/34417?type=main) describes a different RGB arrangement. Do not use that monitor announcement to infer a TV layout. Four white-inclusive subpixels also do not mean a TV has four times its logical horizontal resolution.

### Pixel pitch for common 4K sizes

For a square-pixel 16:9 **3840×2160 active raster**, **D**:

```text
pitch_mm = 25.4*active_diagonal_inches / sqrt(3840^2+2160^2)
PPI = sqrt(3840^2+2160^2) / active_diagonal_inches
```

The following uses **nominal size classes**, not measured active diagonals. The [LG C2 manufacturer listing](https://www.lg.com/cac/tv-y-barras-de-sonido/lg-oled48c2psa?bvstate=pg%3A2%2Fct%3Ar) covers 42/48/55/65/77/83; the [Samsung 2023 manufacturer catalog](https://images.samsung.com/is/content/samsung/assets/th/microsite/ce/catalog/2023/q4/CE-Q4-part-AV-P1-27.pdf) lists 55/65/77 S95C. These examples establish size availability for those lineups, not the limits of later OLED generations.

| Nominal diagonal | Derived pitch (mm) | Derived PPI | WOLED example | QD-OLED example in cited catalog |
|---|---:|---:|---|---|
| 42 in | 0.242 | 104.9 | C2 | NR |
| 48 in | 0.277 | 91.8 | C2 | NR |
| 55 in | 0.317 | 80.1 | C2 | S95C |
| 65 in | 0.375 | 67.8 | C2 | S95C |
| 77 in | 0.444 | 57.2 | C2 | S95C |
| 83 in | 0.479 | 53.1 | C2 | NR |

Same active size and logical resolution give the same logical pitch across all four technologies. Subpixel center spacing is **not generally pitch/3 or pitch/4**. For actual-size corrections, the [S95B manufacturer sheet](https://image-us.samsung.com/SamsungUS/samsung/us/tvs/S95BD_TV_Spec_Sheet_7.11.22.pdf) specifies **54.6/64.5-inch** active diagonals for the 55/65 classes: derived pitches about **0.315/0.372 mm**. Use active dimensions rather than cabinet width; rounded calculations are not metrology of the active raster.

### Concrete aperture renderer

**P**, for physical position r, logical-pixel index (m,n), channel c and mask A:

```text
L_c(r) = sum_mn e_c[m,n] * A_c(r - [m*p_x,n*p_y] - delta_c)
L_optical = K_panel * sum_c L_c
```

Normalize each aperture using the calibration convention (unit integral or physical radiance/area), and include its channel spectrum/XYZ transform. Preserve RGBW allocation separately from geometry. A triangular set of apertures can repeat on a rectangular logical-pixel lattice. Apply optical filtering and integrate over output sample areas before downsampling; supersample until edge/color-fringe metrics converge. The present equal-cell mosaics box-average back to the original pixels and cannot predict subpixel fringing or physical pitch. Its QD placeholder even places R/G on the same row, unlike the cited green-above-red/blue macro.

## 5. Response, overdrive, emission timing and MPRT

### Published response and emission anchors

GtG is a transition metric; MPRT describes tracked motion/persistence under a declared measurement convention. Frequencies are not pulse widths. Supporting monitor results below demonstrate mechanisms and cannot calibrate a TV with the same panel label.

| Current class | Named published measurement | Protocol / NR boundary |
|---|---|---|
| VA mini-LED | **TV:** 65-inch US Samsung QN90B BFI **60/120 Hz**; Movie PWM **120 Hz at brightness 46–50**, **960 Hz below 46**. [RTINGS original test](https://www.rtings.com/tv/reviews/samsung/qn90b-qled) | Size/region/mode dependent; measured GtG grid, BFI duty and MPRT **NR** here. PWM and intentional BFI are separate controls. |
| VA supporting monitor | GP2711, firmware **V1.05**, 165 Hz: mean reported GtG **11.8 ms Off / 9.9 Normal / 6.8 Ultrafast**, with overshoot at Ultrafast. Strobe **120/144/165 Hz**; brightness **306→139 nits**; unavailable with local dimming/VRR. [TFTCentral](https://tftcentral.co.uk/reviews/cooler-master-tempest-gp2711) | Gamma-corrected publisher metric, not a TV tau; numerical voltage/overdrive LUT **NR**. |
| IPS edge TV | LG NANO85 2021 BFI **60/120 Hz**, with duplication/crosstalk; PWM **480 Hz** in specified cinema/expert SDR modes, **120 Hz** in other SDR modes/HDR. [RTINGS](https://www.rtings.com/tv/reviews/lg/nano85-2021) | Numeric TV transition grid, overshoot, BFI duty and MPRT **NR** here. |
| IPS supporting monitor | LG 38GL950G Fast OD mean GtG **3.7 ms at 160 Hz / 5.1 ms at 60 Hz**; Faster at 175 Hz **2.7-ms mean**, **1.1-ms best**, with **136% overshoot on 0→150 at 175 Hz**. [TFTCentral](https://tftcentral.co.uk/reviews/lg_38gl950g) | The review's overshoot definition and transition matter; not a technology bound. IPS need not be slower than VA. |
| WOLED TV | LG **42C2** reported **0.6-ms mean / 0.3-ms best GtG** at 120 Hz, similar at 60 Hz; BFI **60 Hz only**. [TFTCentral](https://tftcentral.co.uk/reviews/lg-oled-42c2) | BFI duty and measured MPRT **NR**. Best/mean is not a transition range or settling-time pair. |
| WOLED TV, separate sample | LG **C4**, worked 0→159 example: initial target crossing **0.4 ms**, overshoot to **RGB172**, total within **±3 RGB at 8.3 ms**. [RTINGS 2026 method](https://www.rtings.com/tv/tests/motion/motion-blur-and-response-time) | Fast first crossing does not establish complete settling; don't combine this trace and C2 GtG into one fitted device. |
| QD-OLED TV | Samsung **S95B**, BFI **60 Hz only**, even on 120-Hz input. [RTINGS](https://www.rtings.com/tv/reviews/samsung/s95b-oled) | Numeric TV GtG/overshoot, duty and measured MPRT **NR** here. |
| QD-OLED supporting monitor | AW3423DW **0.88-ms mean initial GtG**, OSRTT **fixed 5-RGB tolerance**; testing at **60–175 Hz** includes black-origin turn-on overshoot. [KitGuru original test](https://www.kitguru.net/peripherals/dominic-moass/dell-alienware-aw3423dw-review-qd-oled-175hz-ultrawide/all/1/) | Not luminance 10–90%, complete settling, or S95B behavior. |

RTINGS' 2026 methodology uses first crossing and final settling within ±3 RGB, and explicitly distinguishes older 80%/100% figures. [TFTCentral's method](https://tftcentral.co.uk/articles/response_time_testing) also distinguishes gamma-corrected GtG and total response. Preserve code/luminance domain, thresholds, transition endpoints and test version with every value.

### Concrete response and overdrive models

Prefer a measured start/target-gray × time step-response LUT, conditioned on refresh, temperature, mode and previous history. A simpler **P** model is:

```text
q(t+dt) = u + (q(t)-u)*exp(-dt/tau[g0,g1,refresh,temperature])
u_OD = clip(u + k[g0,g1,refresh]*(u-q_start), u_min,u_max)
```

Apply u_OD for `t_OD`, then return to u. Separate dark transitions and rise/fall; fit drive headroom and an extra pole or use a direct trace when one exponential cannot reproduce overshoot. For a monotonic exponential **in the same measurement domain**, `t10–90=ln(9)*tau`; `tau=t10–90/2.197`. A code-domain or first-target-crossing GtG number cannot be divided by 2.197 to obtain a linear-luminance tau. Voltage LUTs, pulse gains/durations and complete transition matrices for all four generic profiles remain **NR**. OLED has no need for a user-facing LCD OD knob, but its measured traces still need possible near-black overshoot/settling.

Run LCD response on transmission state and OLED response on emitter state before panel optics; keep zone-controller rise/fall and frame latency separate. The current implementation filters emitted RGB, uses a fully settled first frame, and has a synthetic pulse prefix ([temporal.py](../../src/tv_sim/stages/temporal.py)). Photodiode tests need explicit pre-roll and subframe samples.

### Emission gate and motion-width conventions

**P** `L_emit(x,y,t)=L_panel(x,y,t)*m(y,t)`, with scanout phase and measured pulse waveform. Expose pulse frequency, count, width, phase and peak; PWM can create several pulses per source frame. A single rectangular pulse of duty d at refresh f has `T_visible=1000*d/f` ms. At fixed peak, average luminance falls by d; mean-preserving pulse boost requires a separate current limit. Repeating the same source image at a higher refresh does not create new motion positions.

For pursuit velocity v, integrate time-resolved emission in retinal coordinates: `I(x)=integral(w(t)*L_emit(x+v*t,t)dt)/integral(w(t)dt)`, with time in seconds and v in px/s. With an ideal instantaneous pixel and rectangular emission aperture, full blur support is `|v|*T_visible/1000` pixels when T_visible is in ms; the **10–90% edge width** is 0.8 times that support. Define `BET_10–90=1000*edge_width/|v|` ms; extended BET `=1.25*BET` recovers ideal hold time. [Primary display-processing thesis, chapter 5](https://pure.tue.nl/ws/portalfiles/portal/1861238/200612229.pdf). These conventions explain why the number depends on its definition.

| Refresh / duty / unique source rate | Ideal visible time (ms) | Ideal 10–90 BET (ms) | Full support at 960 px/s | Evidence |
|---|---:|---:|---:|---|
| 60 Hz / 1 / 60 fps | 16.667 | 13.333 | 16 px | **D**, ideal rectangular hold |
| 120 Hz / 1 / 120 fps | 8.333 | 6.667 | 8 px | **D**, ideal rectangular hold |
| 60 Hz / .5 / 60 fps | 8.333 | 6.667 | 8 px | **D**, assumed single pulse |
| 120 Hz / .25 / 120 fps | 2.083 | 1.667 | 2 px | **D**, assumed single pulse |

These are **not measured device MPRTs**. All matched measured TV MPRT cells remain **NR**. Save full pursuit edge profiles to retain long response tails and inverse ghosting; do not add GtG and hold times as an exact MPRT formula. M4's quadrature subtraction of still-edge width is a diagnostic, not physical deconvolution. A shutterless/instantaneous OLED can still have visible hold blur, while BFI can trade brightness/flicker for shorter persistence.

## 6. Perception: comparing televisions changes the viewing stimulus

**Simultaneous contrast.** An equal-luminance patch can look different against different surrounds. Spehar, DeBonet and Zaidi measured brightness induction with a **1-degree** test disk, **9.5-degree** surround and **0.5-Hz** modulation. Their model uses spatial weighting `W(s)=kappa*exp(-alpha*s)` in degrees, local luminance gain controls, and a gain depending on test/surround differences. In schematic form, `I = -integral(W * G_surround * G_difference * L_surround)`, with perceived test response proportional to `G_test*L_test + I`. This supplies a quantitative model family, not a universal percentage brightness boost. Transferable observer coefficients for TV scenes are **NR**. [Original experiment and model, Eqs. 2–10](https://www.sciencedirect.com/science/article/pii/0042698995002553).

**Temporal luminance adaptation.** Zuena and Pytlarz tested **17 observers**, mean image luminances **0.1, 20, 100 and 338 nits**, and a **5-nit surround**. Brief exposure and longer adaptation produced different transition judgments. Their fitting signal uses PQ-scaled luminance, updated at **24 fps**:

```text
A_0 = PQ(mean_luminance_0)
v_t = PQ(mean_luminance_t)
tau = 25 if v_t >= A_previous, otherwise 850  # frame-based at 24 fps
A_t = (tau*A_previous + v_t) / (tau+1)
```

Those discrete poles correspond to **D: 1.062 s / 35.437 s** e-fold times (`-1/[24*ln(tau/(tau+1))]`). This is a published fitting model under that experiment, not a universal visual time constant or a panel parameter. Keep adaptation history separate from OLED ABL/thermal history. [2024 experiment, methodology and fitted model](https://library.imaging.org/jpi/articles/7/0/000401).

**Chromatic adaptation is another state.** Fairchild and Reniff's three-observer study found two exponential components rather than a single decay: observer-mean fast time constants about **0.9–1.5 s**, slow **38–53 s**; the abstract describes approximately 90% completion around 60 s. These are constant-luminance chromatic adaptation results, not dark-adaptation or HDR brightness thresholds. An optional two-state chromatic model needs weights and the relevant viewing condition; those weights for our comparisons are **NR**. [Original paper, Table 1 and abstract](https://opg.optica.org/josaa/abstract.cfm?uri=josaa-12-5-824).

**Reference geometry.** The pinned BT.2100-2 Table 3 specifies D65 neutral surround at **5 nits**, periphery **at most 5 nits**, avoidance of light on the screen, and **1.6–3.2 picture heights** for 3840×2160 critical viewing. These are reference evaluation conditions, not measured living-room averages. For formal subjective studies BT.500-15 normally calls for **at least 15 observers**, with exceptions identified as informal. [BT.2100-2](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-S%21%21PDF-E.pdf), [BT.500-15](https://www.itu.int/rec/R-REC-BT.500-15-202305-I/en).

P: the simulator should support both simultaneous and sequential comparison protocols:

- A side-by-side view has a shared room/surround and viewing history, with local adaptation around each screen. Apply an optional observer model to the **assembled visual field**, including borders and neighboring screens. Independently adapting or normalizing each TV would remove part of the comparison stimulus.
- A sequential A/B view needs recorded order, pre-adaptation, dwell, transition gap, scene content and gaze. Counterbalance order and screen position; repeat with a declared common adaptation state. A few-second switch and a minute-long dwell answer different perceptual questions.
- Use a matched-white SDR comparison (e.g. a project choice of 100 nits) to study black/gamma/angle, and a separately labeled maximum-capability HDR comparison. Match source, processing and angular image size. Preserve the brightness differences being evaluated with one shared preview exposure/tone map.
- Compare VA halo visibility both on-axis and from actual seat positions; compare IPS black/glow under the same room light. For both OLEDs include bright-field ABL and 24p/60p motion, and for QD-OLED explicitly measure ambient black/tint. None has a single context-free perceived contrast number.
- Keep radiometric output, panel optical halo, observer glare/induction and host-preview transformation as separate outputs. Add ambient reflection after emission gating: `L_view = L_emit + rho_diff*E/pi` is a Lambertian approximation. Report lux and reflectance separately. For example **D**, `rho=.01`, `E=100 lux` adds **0.318 nits** and can dominate an emissive black. Calibrated diffuse/BRDF and QD ambient-excitation coefficients remain **NR**.

Pixel pitch and halo width must become visual angle: `angle_rad = 2*atan(width_mm/(2*distance_mm))`. A nominal 65-inch 4K pixel is **D: 0.644 arcmin at 2 m**. This geometric calculation is not a claim that every observer resolves that pitch; acuity, contrast, focus and spectrum matter. Subpixel masks should appear in a filtered close view, not as a fixed grid imposed on every distant preview.

A useful ambient measurement anchor is the [RTINGS original WOLED/QD-OLED comparison](https://www.rtings.com/tv/learn/qd-oled-vs-woled): at **1,000 lux** in its setup, black measured **2.44 nits on Samsung S95F**, **0.35 on LG G5**, and **0.23 on LG C5**. These are different TV samples from the load table. One illuminance point does not identify diffuse reflectance, directional glare or QD excitation separately; those fitted coefficients stay **NR**.

## 7. Parameters the simulator should expose

These are proposed interfaces. **M §n** means that section contains a named-sample anchor, not a fitted value for the generic YAML. **NR** means the corresponding calibrated value or complete dataset is unavailable. Store each value with `{unit, status, source_url, conditions, uncertainty, fit_method}`; unknown uncertainty is NR, not a fabricated ± percentage. Keep measured nodes separate from interpolated nodes.

| Physical parameter / unit | VA FALD mini-LED | IPS edge | WOLED | QD-OLED |
|---|---|---|---|---|
| `device_id`, active size, region, firmware, picture/game/VRR mode | Mandatory metadata; missing fields NR | Same | Same | Same |
| `load_model`, `apl_domain`, `apl_reference_nits` | P: backlight power or window replay; source linear APL | P: strip/global power; source linear APL | P: RGBW power or window replay | P: RGB power or window replay |
| `window_luminance_lut(f,request,mode)` / nits | M §1; generic fit NR | NR | M §1; generic fit NR | M §1, partial area nodes; generic fit NR |
| `window_dwell`, `warmup`, `sustained_trace` / s, nits | NR for selected sweep | NR | NR for selected sweep | NR for selected sweep |
| Channel/color × amplitude × area capacity / XYZ or nits | NR | NR | NR, including W allocation | NR |
| `power_coefficients`, idle/budget / W; exponents / dimensionless; amplitude/drive domain | Zone-drive fit NR | Strip-drive fit NR | Light-linear RGBW amplitude fit NR | Light-linear RGB amplitude fit NR |
| Limiter attack/release / ms; thermal state/tau / °C, s | NR | NR | NR | NR |
| Static-image dimming detection/delay / s | NR | NR | NR | NR |
| `native_contrast_0`, black detection floor / ratio, nits | Older FALD M §2; current fit NR | M §2; current fit NR | LCD contrast not applicable; meter floor NR | LCD contrast not applicable; meter floor NR |
| `white_gain_lut(theta,phi)` / relative luminance | Sparse LCD M §2; current full LUT NR | Sparse LCD M §2; current full LUT NR | NR | NR |
| `black_leakage_lut(theta,phi)` / epsilon or ratio | Older FALD M §2; current full LUT NR | NR | LCD extinction not applicable | LCD extinction not applicable |
| `gray_rgb_angle_lut`, optional gamma endpoint fit / degrees, relative drive | Sparse M §2; full LUT NR | Sparse M §2; full LUT NR | NR | NR |
| Zone/strip count, bounds, centers, drive maxima / count, mm, nits | Current topology NR | Current topology NR | No backlight zones | No backlight zones |
| `zone_influence_H`, boundary/all-on calibration / nits per drive | NR for matched TV | NR for edge guide | Not applicable | Not applicable |
| PSF family; source footprint; core/tail sigma; tail energy / mm or identified pitches | P shapes §3; fitted coefficients NR | P shapes §3; fitted coefficients NR | Emitted-optics coefficients NR | Emitted-optics coefficients NR |
| Controller percentile/highlight protection; zone rise/fall/delay / fraction, ms, frames | Calibrated policy NR | Calibrated policy NR | Zone policy not applicable | Zone policy not applicable |
| `subpixel_generation`, channel order / enum + mask ID | RGB/BGR model-specific; NR | RGB/BGR model-specific; NR | M topology §4; generation required | M topology §4; generation required |
| `aperture_masks`, offsets, fill factors / mm or logical-pixel fractions | NR | NR | NR; unequal RGBW areas allowed | NR; staggered offsets allowed |
| `active_diagonal`, `resolution`, `pixel_pitch` / in, px, mm | Use active dimensions; D equation §4 | Same | Manufacturer examples + D §4 | Manufacturer examples + D §4 |
| Channel spectra/angular primaries, RGBW allocation / SPD, XYZ, mapping | NR | NR | NR | NR |
| Diffuse/specular reflectance, BRDF, ambient black/tint / fraction, sr^-1, XYZ | NR | NR | Ambient black point M §6; full fit NR | Ambient black point M §6; full fit NR, including QD excitation |

| Temporal parameter / unit | VA FALD mini-LED | IPS edge | WOLED | QD-OLED |
|---|---|---|---|---|
| Response start/target-gray LUT; domain and thresholds / ms, code or nits | Monitor anchors §5; full TV LUT NR | Monitor anchors §5; full TV LUT NR | TV examples §5; full LUT NR | Monitor anchor §5; full TV LUT NR |
| Rise/fall/dark tau vs refresh and temperature / ms, Hz, °C | NR | NR | NR | NR |
| OD gain/pulse/headroom/extra-pole LUT / ratio, ms, drive | NR | NR | User OD not assumed; trace model NR | User OD not assumed; trace model NR |
| First crossing, overshoot, settling tolerance/time / ms, code or nits | Full TV traces NR | Full TV traces NR | C4 worked trace §5; generic NR | Full TV traces NR |
| Refresh, unique input cadence, repeated frames / Hz, rational fps | Independent experiment/mode controls | Same | Same | Same |
| Scan duration/direction/row phase / ms | NR | NR | NR | NR |
| BFI support matrix by input/refresh/VRR / supported modes, Hz | M frequencies §5; complete matrix NR | M frequencies §5; complete matrix NR | M frequency §5; complete matrix NR | M frequency §5; complete matrix NR |
| BFI waveform, width/duty, count, phase and peak / ms, fraction, pulses/frame, nits | NR | NR | NR | NR |
| Brightness modulation/PWM waveform / Hz, duty, phase | M mode-specific frequencies §5; full waveform NR | M mode-specific frequencies §5; full waveform NR | Full emitted waveform NR | Full emitted waveform NR |
| Measured pursuit edge profile and declared MPRT/BET / px, ms | NR for matched TV | NR for matched TV | NR | NR |

| Observer / reporting parameter | Exposed value and evidence status |
|---|---|
| Eye position, distance, panel orientation/curvature, angular size / m, degrees | Experiment controls for all four; per-pixel view direction, not a technology constant. |
| Room lux, surround/periphery luminance, chromaticity, borders / lux, nits, xy | Expose independently; reference setting §6, actual room measured or NR. |
| Comparison mode/order, pre-adaptation, dwell, gap, gaze / enum, s, degrees | Protocol metadata; mandatory for perceptual comparisons. |
| Induction gain/scale, local/global adaptation, chromatic state / dimensionless, degrees, s | Model family and experiment-specific numbers §6; TV-scene calibration NR. |
| Eye velocity, pursuit integration, pulse timing / px/s or deg/s, ms | Experiment controls; save complete curves and cadence. |
| Halo baselines/thresholds, ring geometry, FWHM, retained-highlight ratio / nits, mm, degrees, fraction | Explicit metric definitions; absolute matched-TV reference NR (§3). |
| Preview host peak/black/gamut/EOTF and shared exposure/tone map / nits, color metadata | Host calibration measured or NR; never independently auto-normalize TVs in a brightness comparison. |

NR should disable a calibrated-device claim, not prevent a clearly labeled synthetic experiment. If exploration sliders retain M3 prior ranges, show them as **P, unmeasured**; do not prefill them as published values. Inapplicable LCD-zone parameters should be absent from OLED profiles rather than represented by arbitrary large native contrast or zero-radius backlight zones.

## 8. Implementation and acquisition priorities

1. **Land provenance and measurement replay first.** Add measured-window tables, dwell and metric-domain metadata. Keep the C2, S95B and 98X955 records separate from generic presets. The source table images/public text above are sufficient for those nodes; they do not support interpolated samples being labeled M or long-term thermal claims.
2. **Replace mechanism proxies in the correct order.** Move source-load estimation ahead of limiting; couple backlight drive and LCD compensation; apply angular leakage/gamma inside transmission; apply emissive optical PSF to actual emission. Preserve the CPU radiometric path as the reference. These are proposed follow-ups, not changes made by this document.
3. **Acquire the least identifiable data.** Need fixed-backlight angular gray/black/white sweeps; isolated zone/strip influence maps with flare control; geometry-calibrated micrographs and active dimensions; RGBW/color-current data; response traces and BFI/PWM waveforms. Complete retail-TV halo PSFs and response LUTs cannot be recovered uniquely from uncalibrated review photos or scalar averages.
4. **Use matched holdouts.** Fit on some window sizes/positions and gray transitions; evaluate other positions, zone phases, mixed colors, angles, low-APL stars/subtitles and motion. Measure 0.1/1/10/60-second luminance traces, with temperature/history, before adding sustained/thermal claims. A second device of the same technology is a transfer test, not validation of the first device's fit.
5. **Report physical and perceptual quantities separately.** Save emitted-nit arrays, source APL, drives, pulse traces and complete edge/halo profiles, then an optional observer-model result with its parameters and a shared preview transform. A clipped or auto-scaled SDR preview cannot establish HDR/black fidelity.

This research-only change leaves simulator code, presets and M4 artifacts untouched.
