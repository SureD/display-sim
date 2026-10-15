# Temporal response, motion and emission timing

Research date: 2026-10-15. Response time, motion persistence, refresh cadence and input latency describe different effects. Quoted transition percentages must match the measurement method. [RTINGS response-time methodology](https://www.rtings.com/tv/tests/motion/motion-blur-and-response-time) explicitly warns that old 80%/100% results and newer methodology are not directly comparable.

## LCD/OLED state response

A first-order approximation for a commanded normalized transmission u:

`q(t+dt)=u+(q(t)−u)exp(−dt/τ(q_start,u,T,refresh))`.

Use separate transition-dependent rise/fall LUTs. For a monotonic first-order step, `t10–90=τ ln9≈2.197τ`; settling to within 1% takes `4.605τ`. A quoted “100%” response needs a finite tolerance; it is not the mathematical asymptote. Solve in transmission/drive space chosen by calibration, then apply optical luminance. Response changes with temperature, grayscale and refresh rate.

| Parameter | Initial **model prior**, not a measured technology guarantee |
|---|---|
| Conventional LCD t10–90 | 2–20 ms; slow VA dark transitions may require 20–50 ms |
| OLED t10–90 | 0.05–1 ms for main transitions; near-black behavior requires separate data |
| LCD overdrive gain | 0–1 in the command law below; clipping and transition-specific LUT required |
| Output refresh | 50/60/100/120 Hz typical simulation cases; add higher modes only per profile |
| Input cadence | 23.976/24/25/29.97/30/50/59.94/60/120 fps; keep rational timestamps |

A proposed overdrive command is `u_OD=clip(u+k(u−q_start),u_min,u_max)` for a short drive interval, followed by u. Fit drive interval (prior .5–8 ms) and gain using a photodiode transition grid. Physical electrical voltage can overshoot a normalized optical target even when displayed RGB is bounded; the simplified command needs calibrated headroom to reproduce overshoot near white. Store a second decay state or a measured impulse/step response if one pole cannot fit inverse ghosting. Do not add an arbitrary bright trail after rendering and call it overdrive.

## Sample-and-hold and tracked-eye integration

Even an instantaneous OLED held for a frame blurs during smooth pursuit. [Blur Busters' original explanation](https://static.blurbusters.com/faq/oled-motion-blur/) gives 60 Hz persistence 16.7 ms despite fast pixel response. A more general [motion-blur measurement paper](https://arxiv.org/abs/1602.07573) distinguishes display-type assumptions.

For constant screen velocity v pixels/s and rectangular visible hold T_v, the tracked-eye blur support is approximately `b=|v| T_v`. At 960 pixels/s: 60 Hz full hold gives 16 pixels, 120 Hz gives 8; a 2-ms pulse gives 1.92. This is a support-width illustration, not a universal 10–90 edge-width or MPRT definition.

Render time-resolved emitted radiance L(x,t), then pursuit image
`I_retina(x)=∫ w(t)L(x+v_eye t,t)dt / ∫w(t)dt`.

The sign here follows the chosen pursuit-coordinate convention; verify with an ideal translating pattern. Eye/camera integration belongs after emission. A static screenshot cannot show sample-and-hold blur, flicker or interpolation cadence. Frame repeats at 120 Hz do not create 120 unique motion positions from 60 fps material: continuously emitting identical frames can still persist for 16.7 ms.

## BFI, PWM and scanning

Emission gate `m(y,t)` multiplies radiance; model scanout phase `t_row=t_frame+yT_scan/H`. A single strobe duty d gives visible time `T_v=d/f`; at fixed peak drive mean luminance falls approximately by d. Raising pulse intensity to preserve mean is bounded by panel/backlight current and thermal limits. Sweep d=.1–1 as an experimental setting, not a supported feature claim.

Separate backlight PWM (frequency/duty), rolling scanout and deliberate BFI. Example PWM sweep 120–2,000 Hz is provisional and not a safe inference from refresh rate. Unsynchronized strobe/scanout can expose unsettled LCD transitions and produce top/bottom crosstalk. Multiple pulses per source frame can create multiple pursuit images. 60/120-Hz light modulation can visibly flicker; a refresh specification alone says nothing about the actual waveform.

## Cadence, MEMC and lag

24 fps on 60 Hz typically uses alternating 3/2 frame holds (50/33.3 ms), creating cadence judder. At 120 Hz, 5:5 repeats equalize hold intervals but leave low-frame-rate stutter. OLED's rapid response can make that stepping more conspicuous than a slower LCD; this is not slower OLED response.

A baseline interpolator estimates bidirectional optical flow, warps adjacent frames toward time α, and confidence-blends only mutually consistent, visible samples. Ideal translation example: `I_α(x)=I_0(x−αv)` for a constant flow v over one source interval. Include scene-cut fallback and occlusion masks. [Microsoft's occlusion-aware interpolation research](https://www.microsoft.com/en-us/research/publication/occlusion-reasoning-for-temporal-interpolation-using-optical-flow/) establishes why warping alone is insufficient. [Sony support](https://www.sony.com/electronics/support/televisions-projectors-lcd-tvs/xbr-55x900a/articles/00153243) confirms interpolation may create artifacts in fast motion and transitions.

MEMC changes motion positions and apparent cadence; it does not merely blur two frames. It can produce occlusion halos, doubled edges, warped text and film-like motion changes. Future-frame interpolation adds at least its required lookahead buffer (e.g. one 24-fps interval is 41.7 ms), but actual vendor latency must be measured. Keep processing delay, scanout delay and pixel transition delay as separate outputs. Game mode and VRR may change controller behavior.

## CRT and plasma

Proposed CRT emission: each raster beam visit deposits channel energy `a_c`; phosphor response `h_c(t)=Σ_k a_ck exp(−t/τ_ck)` for t≥0, normalized for desired integrated energy. Convolve beam spot spatially, include row/raster/interlace timing and optional drive-dependent spot size. Exploratory decay constants .1–5 ms with a weak 5–30 ms tail are **uncertain phosphor priors**, not a generic CRT specification. Measure each channel's decay and state whether decay is time-to-10%, 1/e, or something else. Slow phosphor components can leave colored trails.

Plasma uses multiple address/sustain subfields per input frame, not one CRT-like impulse. Represent `L_c(t)=Σ_s E_cs h_c(t−t_s)` with per-cell subfield choices and phosphor h_c. A toy 8–12-subfield schedule per frame is a simulation assumption; real ordering, reset pulses and dithering are proprietary/generation dependent. Binary weights are an educational baseline, not a reverse-engineered schedule. Eye motion across different subfield decisions can produce false contours; differing decay creates color trails. [DisplayMate's plasma analysis](https://www.displaymate.com/ShootOut_Part_4.htm) is a historical primary test source; exact subfield waveforms still need acquisition. Advertised “600 Hz” subfield rates are not 600 independent source frames.

Validate with gray-to-gray photodiode traces, pursuit-camera moving edges at declared speed, 24p pans, scrolling text, occlusion sequences and RGB pulse decay. Use adaptive integration with dt at most one tenth the shortest fitted time constant/pulse duration, and demonstrate convergence; ordinary 1-ms timesteps cannot resolve a .05-ms OLED transition.

Open questions: response LUTs versus temperature/VRR, true BFI timing, phosphor decay spectra, plasma subfield schedule and reference pursuit integration.
