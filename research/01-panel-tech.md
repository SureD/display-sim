# Panel technologies and optical model

Research date: 2026-10-15. Scope: direct-view consumer TVs, including legacy CRT/plasma; not a ranking of current products. All luminances are cd/m² (nits). **Prior** means an engineering exploration range, not a population statistic or a measured specification. **Measured** values identify the device and conditions. Manufacturer descriptions establish construction, not independently verified performance. Related models: [backlight](02-backlight-local-dimming.md), [color](03-color-hdr.md), [time](04-temporal.md).

## Definitions and defensible comparisons

Native LCD contrast is simultaneous white/black with a fixed backlight and local dimming disabled: `C_native=L_white/L_black`. Sequential full-black contrast with zones turned off is a different quantity. At fixed backlight, a 1,000-nit white and C=4,000 imply 0.25-nit black; a 100-nit SDR calibration implies 0.025-nit black. Never combine peak HDR white measured on one pattern with black measured on another and call the ratio native contrast.

| Technology | Spatial construction | Initial contrast prior | Initial white-luminance prior | Angle behavior to model |
|---|---|---|---|---|
| VA LCD | Usually RGB/BGR stripes; multi-domain electrode apertures inside each subpixel | 2,000–8,000:1, potentially lower with wide-angle films | SDR operating white 100–500; HDR small window 400–2,000 | Black leakage and gamma shift often worsen before white falls strongly; horizontal/vertical curves differ |
| IPS / ADS LCD | In-plane/fringe-field switching families; commonly RGB/BGR, domain/slit details vary | 700–1,500:1 for conventional designs; newer enhanced-contrast variants require measurements | SDR 100–500; HDR 300–1,000 | Usually better color/gamma stability than conventional VA; oblique dark-state glow remains |
| Mini-LED FALD LCD | VA/IPS/ADS panel over many independently driven backlight zones; LED count is not zone count | Inherit panel's native contrast, **not** advertised dynamic contrast | HDR small-window prior 700–3,000; full-field is independently constrained | Inherit LCD and film behavior; halos can become stronger off-axis |
| WRGB OLED | White-emitting OLED stack with filtered R/G/B and an additional W aperture; actual order/areas vary | Off pixels approximately zero emission; report instrument black upper bound, not a finite invented ratio | Older-to-modern TV exploration: small-window 400–2,000, full-white 80–300 | Broad usable angles; wavelength-dependent microcavity/film shifts and luminance rolloff remain |
| QD-OLED | Blue OLED excites patterned R/G quantum-dot conversion; blue channel retained; early TV panels use staggered/triangular RGB apertures | Same off-pixel caveat as WRGB | Representative early-generation-to-modern prior: small-window 800–2,500, full-white 150–350 | Broad color stability; ambient black rise/coating behavior needs separate fit |
| CRT | Scanned electron beams excite RGB phosphor dots/slots or aperture-grille stripes; beam footprint is not a rigid LCD pixel | No single useful native ratio: black bias, scene-dependent flare and ambient dominate | Sustained working white prior 80–150; small-area 100–300 | Direct-view CRT broadly stable; faceplate reflections, curvature and geometry matter |
| Plasma | Addressed RGB phosphor discharge cells, temporally coded subfields | Legacy exploration 500–30,000:1, highly generation/pattern dependent | Full-white prior 50–150; small window 100–400 | Broadly stable emission; front filters can introduce directional behavior |

These broad priors are deliberately conservative implementation bounds, **not limits on newer panels**. Start with SDR 100 nits for fair comparisons. Fixed-backlight LCD black prior follows white/C; do not assign a technology-wide absolute black. OLED ideal dark-room black can be zero in the model, but measured results must state meter detection limits. CRT/plasma black priors 0.001–0.5 nits span very different generations and setups; do not independently sample black, white and contrast inconsistently.

## Source anchors and limitations

- [RTINGS viewing-angle measurements](https://www.rtings.com/tv/tests/picture-quality/viewing-angle): measured color, brightness, black and gamma versus angle, with VA/IPS/OLED examples. [Sony X950H lab review](https://www.rtings.com/tv/reviews/sony/x950h) documents the wide-angle-film/native-contrast tradeoff and size differences. Numeric tables now locked were **not** used to invent exact calibration values.
- [BOE LCD technology](https://www.boe.com/global/en/Products_LCD.html) and [BOE TV display](https://www.boe.com/en/Enterprise/TVDisplay) identify ADS and optical-compensation developments. ADS is not a guarantee of a particular contrast value; marketing viewing-angle specifications are not color-accuracy thresholds.
- [LG Display 2018 annual report](https://www.lgdisplay.com/eng/attachment/download?originFileName=2018+Annual+Report_Form+20-F.pdf&s3FileName=2021-10-18%2FatAE9yAGG3l42LyLJEovkidNVoLNEla5.pdf) describes white OLED plus color-filter WRGB construction. [Samsung Display QD explanation](https://global.samsungdisplay.com/28135/) describes blue excitation and conversion. Neither fixes aperture geometry for all panel generations: require a macro photograph for a real profile.
- [DisplayMate direct measurements, 2005](https://www.displaymate.com/ShootOut_Part_1.htm): Sony PVM-20L5 CRT black about 0.01 nits versus NEC 61XM2 plasma about 0.42 nits in that setup. These old units do not bound late plasma performance. [CRT evaluation guide](https://www.displaymate.com/crt_test.html) explains black adjustment. [Technology analysis](https://www.displaymate.com/ShootOut_Part_4.htm) cautions that bare plasma panel brightness can differ greatly from finished TV brightness.
- [DisplayMate 2015 OLED/LCD measurements](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm): the tested OLED's Cinema full-white was 91 nits versus 242 at 25% APL; this illustrates load dependence, not a universal OLED curve. [QD-OLED lab construction/photographs](https://www.rtings.com/tv/learn/what-is-qd-oled/) provide a generation-specific layout reference.

## Implementable optics

For LCD channel c, with normalized aperture transmission q and spatial backlight B (nits at fully open reference white):

`L_c(x,t,θ,φ)=B(x,t) · [ε_c(θ,φ)+(1−ε_c(θ,φ))q_c(x,t,θ,φ)]`.

Choose channel normalization so neutral full-open RGB has Y=B. At normal incidence, neutral leakage `ε≈1/C_native`. Fit channel-specific leakage/gamma to angular patches rather than applying a uniform image fade.

A cheap **proposed approximation** is `q_c=clip(u_c,0,1)^γ_c(θ,φ)`, `ε_c(θ)=clip(ε_c(0)[1+k_c sin²θ],0,1)`, and channel gain `g_c(θ)=max(cosθ,0)^p_c`. Fit over 0°, 15°, 30°, 45°, 60° and both axes. Exploration bounds k=0–50, p=0–2, gamma change ±0.8 are tuning bounds, not material constants. Use angular LUTs when fitting real sets. Do not apply an extra cosine falloff to a measured luminance curve: an ideal Lambertian surface has angle-independent radiance/luminance.

For emissive panels, `XYZ(x,t)=Σ_c M_c e_c(x,t)` with c=RGB or RGBW, subject to channel and total-power limits. Near-black quantization/dither and mura are separate optional maps; zero black does not mean perfect low-code tracking.

For CRT scene-dependent veiling glare, an optional proposed model is `L_out=(1−f)L_direct+f(K_flare*L_direct)+L_bias`, with a nonnegative unit-integral broad kernel K_flare and exploratory energy fraction f=0–0.03. This redistributes scene light; it is separate from beam-spot growth. For plasma, add a measured reset/priming pedestal `L_reset(APL, mode)` to subfield emission, then enforce the power limit. Do not set plasma black to OLED zero by default. Both models need per-device data.

A spatial aperture renderer uses measured per-channel masks A_c at subpixel resolution, then optical reconstruction and downsampling. Include fill factor (provisional 0.5–0.95) and CRT beam sigma (provisional 0.2–1 pixel-equivalent, increases with drive). Do not paint a visible pixel grid into ordinary distant-view previews: use screen size, viewer distance and output sampling.

Ambient diffuse approximation: `L_ambient=ρ_diff E/π`, E in lux and effective diffuse reflectance ρ in [0,1]. Proposed sweep ρ=0.005–0.05, E=0–500 lux; measured BRDF is needed for specular lamps/windows and directional coatings. Observed contrast becomes `(L_w+L_ambient)/(L_b+L_ambient)`. Any QD-OLED ambient excitation/tint needs measured RGB black-versus-illuminance data; a generic technology constant is uncertain.

Open measurements: aperture photographs, angular RGB/gray curves, reflectance/BRDF, low-light instrument floor, and matched-mode white/black/window measurements for each candidate TV.
