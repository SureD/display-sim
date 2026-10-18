# M4 published reference ranges and evidence gaps

Research checked 2026-10-16. These are **published sample measurements**, not technology limits, population confidence intervals, or calibration of our profiles. All luminances are cd/m² (nits). The four `generic_*` profiles contain placeholders, not measurements of specific TVs. Earlier M1/M3 **priors** remain exploration bounds and must not be relabeled measured ranges.

## Reading the evidence

**M** = accessible numerical measurement; **D** = arithmetic derived from cited measurements; **Q** = qualitative observation; **NR** = no verified, accessible numerical source found for the stated protocol. An isolated number is an anchor, not a range. An envelope combines only the explicitly named samples/conditions; it does not imply every intermediate value was measured. Reviewers generally do not provide uncertainty budgets here: rounding, panel sample, size, mode, firmware, meter floor, timing and temperature remain unresolved. No fabricated error bars are attached.

Native contrast requires a fixed backlight with dimming disabled. ANSI contrast uses simultaneous black/white patches; dimming-on ANSI is scene-dependent. Sequential full-white/full-black contrast is neither. OLED “infinite” means black below detection in that setup, not a measured numerical infinity. Never divide a small-window HDR peak by an unrelated ANSI black reading.

Peak-window area is a fraction of screen area, not side length. A full-white peak is not automatically a sustained full-white result. For sustained data require a stated dwell/trace, mode and warm-up. Do not interpolate missing window sizes to manufacture published measurements.

## Contrast anchors

| Class | Published native / simultaneous contrast evidence | Uncertainty and comparison boundary |
|---|---|---|
| VA FALD mini-LED | **NR** for an accessible, complete TV native/ANSI ratio in the selected sources. QN95B measured ANSI black: **0.048 nits** in SDR and HDR [V1]. Same-pattern white is not given alongside it, so no ratio is derived. As a **monitor-only supporting anchor**, GP2711 static contrast is ~**3,598:1** by default and ~**3,800:1** in the review conclusion [V3]. | GP2711 is VA mini-LED but is not a TV calibration. Its ~3,598–3,800 envelope spans setup states, not a class range. Wide-angle films and dimming policy can substantially change TV results. |
| IPS edge-lit | UH770V: dimming-off ANSI black **0.093 nits** at **120-nit** white → **~1,290:1 (D)** [I1]. Older UB850V: **0.157 nits** at **120-nit** white → **~764:1 (D)** [I2]. Selected-sample ANSI envelope **~764–1,290:1**, not a universal IPS bound. | UH770V full-black raster **0.066 nits** at that setup [I1] must not replace its ANSI denominator. Automatic backlight shutdown also makes some sequential results misleading. |
| WOLED | EG960V returned a **0-nit meter reading** on full black and 4×4 ANSI [W2]. C2 reviews describe per-pixel black without local-dimming halos [W1, W3]. | No finite native/ANSI range established. Meter detection floor is not quantified by these anchors. Do not use the YAML `native_contrast` field as measured OLED contrast. |
| QD-OLED | S95B HDR10 Filmmaker: reported black **0.000 nits**, full-on/full-off contrast unmeasurable [Q2]. RTINGS reports essentially perfect dark-room blacks [Q3]. | Q2 is sequential, **not ANSI**. Numeric ANSI range **NR**. Ambient black rise is a separate condition, not dark-room emission leakage. |

Sources for this table: [V1: AVForums QN95B review](https://www.avforums.com/reviews/samsung-qn95b-qe65qn95b-4k-neo-qled-tv-review.19992/), [V3: TFTCentral GP2711 review](https://tftcentral.co.uk/reviews/cooler-master-tempest-gp2711), [I1: HDTVTest UH770V review](https://www.hdtvtest.co.uk/news/55uh770v-201610064369), [I2: HDTVTest UB850V review](https://www.hdtvtest.co.uk/news/49ub850v-201406033786), [W2: HDTVTest EG960V review](https://www.hdtvtest.co.uk/news/55eg960v-201504224046), [Q2: Sound & Vision S95B test bench](https://www.soundandvision.com/content/samsung-65-s95b-quantum-dot-oled-4k-tv-review-test-bench).

## HDR neutral-window brightness

The requested sizes are all listed, including gaps. **NR** means a source was not verified; it does not mean zero brightness. Values from plots without an exact tabulated/text value were not guessed. RTINGS lists the relevant window measurements but several numeric tables were locked on access.

| Class / measured sample and setting | 2% peak | 10% peak | 25% peak | 50% peak | 100% peak / full-white reading | Full-field sustained |
|---|---:|---:|---:|---:|---:|---|
| VA mini-LED: 65-inch Samsung QN95B, HDR Filmmaker [V1] | NR | **1,774 M** | NR | NR | **591 M** | NR: no timed full-field value verified |
| VA mini-LED: 65-inch Sony X95K, review HDR setup [V2] | NR | **~1,300 M** | NR | NR | **almost 650 M** | NR: no duration-qualified numeric trace verified |
| IPS edge-lit: LG 55UH770V [I1] | NR | NR | NR | NR | NR | NR |
| WOLED: LG 42C2, HDR Standard, DTM off [W1] | NR* | **~717 M** | NR | NR | NR | NR for a timed HDR full-field reading |
| QD-OLED: 65-inch Samsung S95B, HDR Filmmaker, firmware 1211 [Q1] | NR | **977 M** | NR | NR | **199 M** | NR: reviewer explicitly notes brightness is not maintained indefinitely |

*W1 says small windows through 10% reach ~717 nits, but does not independently tabulate 2%; that cell remains NR. The same review has a ~707-nit summary; retain approximately **707–717** as its reporting/rounding envelope, not sample variation. [W1: TFTCentral LG 42C2](https://tftcentral.co.uk/reviews/lg-oled-42c2).

The VA TV **10% envelope is ~1,300–1,774** and full-white envelope **591–almost 650**, across V1/V2; mode/controller differences prevent interpreting them as matched tests. V2 also measures a 1% window below 1,000 nits, illustrating that smaller windows need not be brighter on local-dimming LCDs. [V2: FlatpanelsHD Sony X95K](https://www.flatpanelshd.com/review.php?subaction=showfull&id=1655879889).

The IPS UH770V review reports **455-nit peak**, but does not specify a usable window size/dwell for this table. It cannot fill any of the five cells. [I1: HDTVTest UH770V](https://www.hdtvtest.co.uk/news/55uh770v-201610064369).

Another 42C2 test measures **667 nits at 10%**, giving a selected-review WOLED 10% envelope **667–717**, with differing setups. This is not a bound on larger/newer WOLED TVs. [W3: TechSpot LG C2 42-inch](https://www.techspot.com/review/2507-lg-c2-monitor/).

S95B also measures **1,004-nit HDR peak** in another Filmmaker test, but that excerpt does not identify the window area; it is excluded from the 10% envelope. The matched 10% anchor remains 977. [Q2: Sound & Vision S95B test bench](https://www.soundandvision.com/content/samsung-65-s95b-quantum-dot-oled-4k-tv-review-test-bench), [Q1: AVForums S95B review](https://www.avforums.com/reviews/samsung-s95b-qd-oled-tv-review.19923/).

### Full-field and load evidence outside the HDR table

WOLED C2 **SDR** at maximum OLED pixel brightness: approximately **262 nits at 1–75%**, falling to **170 nits at 100%**; at a calibrated **120 nits**, output remains 120 across 1–100%. The wording describes maintained levels but supplies no common timed thermal protocol; this is not a certified long-duration sustained HDR rating. EG960V's maximum full-white reading is **149 nits**, also not a duration-qualified HDR measurement. Keep SDR, HDR and calibration-level sweeps separate. [W1: TFTCentral C2](https://tftcentral.co.uk/reviews/lg-oled-42c2), [W2: HDTVTest EG960V](https://www.hdtvtest.co.uk/news/55eg960v-201504224046).

The sources above do not establish duration-qualified sustained full-field **ranges for any of the four classes**. Acquire 0.1/1/10/60-second traces before validating sustained behavior. No timed thermal or static-logo state exists in the current simulator.

## Blooming, response and BFI

| Class | Published observations / measurements | What remains unavailable |
|---|---|---|
| VA FALD mini-LED | QN95B suppresses small highlights to hide halos; subtitles can still expose blooming [V1]. X95K shows pronounced HDR blooming [V2]. QN90B pixel transitions are described as quick, with some dark-transition overshoot and persistence blur; BFI operates at **60/120 Hz**, with duplication from timing [V4]. | Numeric TV GtG/ANSI range, calibrated halo width/luminance and numeric MPRT **NR**. GP2711 monitor slow black smearing [V3] is a warning against treating VA as one response constant. |
| IPS edge-lit | UH770V has six full-height dimming strips and visible vertical blooming/backlight fluctuations. “Clear Plus” scanning reduces luminance [I1]. NANO85 2021 supports **60/120-Hz** BFI with image duplication [I3]. | Numeric GtG/MPRT and pulse duty **NR**. Motion-resolution lines from UH770V are not milliseconds or edge width. |
| WOLED | C2 measured GtG **0.3 ms best / 0.6 ms mean**, not a min–max transition range. Pursuit blur remains at 60 Hz. BFI works at **60 Hz**, not 120 Hz in the tested setup; BFI luminance adjustment ~**25–127 nits** [W1]. Dark-room local-dimming halos absent [W1]. | No verified numeric MPRT or BFI duty here. GtG is not hold persistence. No technology-wide BFI claim follows from one model. |
| QD-OLED | S95B has nearly instantaneous response but visible hold persistence; optional BFI exists [Q3]. Ambient light raises/tints blacks [Q1, Q3]. Per-pixel emission avoids LCD zone halos [Q3]. | Accessible numeric GtG, numeric MPRT, pulse duty and exact supported BFI frequencies **NR** in the evidence transcribed here. Do not infer 120-Hz BFI from 120-Hz input support. |

[V4: RTINGS QN90B](https://www.rtings.com/tv/reviews/samsung/qn90b-qled), [I3: RTINGS NANO85 2021](https://www.rtings.com/tv/reviews/lg/nano85-2021), [Q3: RTINGS S95B](https://www.rtings.com/tv/reviews/samsung/s95b-oled). LCD PWM brightness control is separate from deliberate BFI. OLED refresh-cycle brightness dips are not equivalent to LCD PWM.

## Applying these references to M4

1. Use a measured sample only after matching TV size/variant, firmware, picture mode, white point, dimming, input level, pattern geometry, timing, ambient and viewing angle. Our generic profiles cannot earn a real-TV calibration pass from these tables.
2. Missing or mismatched data means **N/A / insufficient evidence**, not pass or fail. Public review photographs establish visible blooming, not an absolute nit halo threshold or PSF fit.
3. Record raw white/black luminances with contrast. Zero/below-floor black should have a flag/bound; do not put a fabricated finite contrast in JSON.
4. Compare GtG only using the same transition endpoints/thresholds. The model parameter is tau: for a first-order step, `t10–90 = ln(9) * tau`. Pursuit edge width needs motion speed and an edge-width convention; it is not directly comparable with GtG.
5. The PM must choose empirical tolerances before tuning. M1's ±10% luminance / ±20% halo suggestions are **project proposals**, not publisher/specification acceptance rules. DisplayHDR certification thresholds, if added later, must retain their version and test protocol; they are not measured class ranges.

Open evidence requests: exact 2/25/50% HDR tables for each class; matched fixed-backlight TV native contrast for VA; QD-OLED ANSI; timed full-field traces; absolute halo profiles; GtG transition grids; pursuit MPRT and measured BFI waveforms. These gaps are explicit deliverable limitations, not implied simulator failures.
