# Color, transfer functions and HDR

Research date: 2026-10-15. Normative equations are distinguished from proposed simulator approximations. Use floating-point linear light and absolute cd/m² internally. A gamut container is not proof that a TV can reproduce its boundary.

## Primaries and decoding

| Encoding/gamut | R xy | G xy | B xy | White xy |
|---|---|---|---|---|
| BT.709 | .640,.330 | .300,.600 | .150,.060 | D65 .3127,.3290 |
| P3-D65 | .680,.320 | .265,.690 | .150,.060 | D65 .3127,.3290 |
| BT.2020 / BT.2100 | .708,.292 | .170,.797 | .131,.046 | D65 .3127,.3290 |

Sources: [BT.709-6](https://www.itu.int/rec/R-REC-BT.709/en), [BT.2020-2](https://www.itu.int/rec/R-REC-BT.2020/en), and [SMPTE ST 432-1](https://doi.org/10.5594/SMPTE.ST432-1.2010). P3-D65 differs from cinema DCI-P3 white and presentation transfer characteristics. Record whether gamut coverage uses CIE xy, u′v′, or a perceptual volume; percentages are not interchangeable.

For primary (x,y), use vector `(x/y,1,(1−x−y)/y)` as a column of P. Solve `s=P⁻¹W`, where W is the white XYZ with Y=1. Then `M=P diag(s)` and `XYZ=M RGB_linear`. Convert source to panel space using the matrices before gamut mapping; do not apply a primary matrix to PQ/gamma encoded channels. Actual panel primaries and spectra must replace ideal standards in calibrated profiles.

Decode range/chroma before transfer functions. Example 10-bit nominal limited-range luma: `(code−64)/876`; chroma center 512 and nominal excursion ±448. Preserve footroom/headroom until an explicit policy clamps it. Matrix coefficients, chroma siting, full/limited range and 4:2:0 reconstruction must come from metadata. BT.709's camera OETF is not its display EOTF.

## SDR EOTF

A simple exploratory display is `L=L_b+(L_w−L_b)V^γ`, with γ=2.2–2.4 as a **mode prior**, V normalized encoded signal. For reference SDR implement [BT.1886](https://www.itu.int/rec/R-REC-BT.1886-0-201103-I/en):

`L=a[max(V+b,0)]^2.4`
`a=(L_w^(1/2.4)−L_b^(1/2.4))^2.4`
`b=L_b^(1/2.4)/(L_w^(1/2.4)−L_b^(1/2.4))`.

This tends to `L_w V^2.4` for zero black. A 100-nit white is a useful controlled comparison target, not an intrinsic TV maximum. BT.1886 black-aware decoding expresses a desired display response; ensure the panel leakage stage does not add the same black pedestal twice. sRGB assets require the sRGB piecewise transfer, not an unconditional gamma 2.2.

## PQ and HLG

[BT.2100-2, Tables 4–5](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-S%21%21PDF-E.pdf) defines the following transfer families (this pinned edition is used for reproducibility, not a claim that it is the latest).

PQ/ST 2084 EOTF, N in [0,1]:

`p=N^(1/m2)`
`L=10000 [max(p−c1,0)/(c2−c3 p)]^(1/m1)`

`m1=2610/16384`, `m2=2523/32`, `c1=3424/4096`, `c2=2413/128`, `c3=2392/128`.

PQ is absolute and its 10,000-nit endpoint is not the display's peak. Approximate neutral checks: N=.508078→100 nits; N=.751827→1,000; N=1→10,000. Decode RGB components; luminance is then obtained in linear light.

HLG inverse OETF (scene-linear E):

`E=V²/3` for V≤.5; otherwise `E=[exp((V−c)/a)+b]/12`,
`a=.17883277`, `b=1−4a`, `c=.5−a ln(4a)`.

For ideal black and nominal surround, apply the system OOTF:
`RGB_display=L_w · RGB_scene · Y_scene^(γ_sys−1)`,
`Y_scene=.2627 R+.6780 G+.0593 B`,
`γ_sys=1.2+.42 log10(L_w/1000)`.

Handle zero Y explicitly. A useful initial peak sweep is 400–2,000 nits; black/surround compensation should follow the standard when needed. HLG is relative and requires the OOTF: inverse OETF alone is not final displayed light. PQ/HLG RGB and luminance must not be confused.

## Tone and gamut mapping

Reference background and display-adaptation guidance: [ITU BT.2390-8 (2020)](https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-BT.2390-8-2020-PDF-E.pdf). Implement its specified EETF as an optional standards-based baseline; test equations against that edition. The following simpler shoulder is **our proposed approximation**, not BT.2390 or a reverse-engineered vendor curve:

For desired Y, capacity P and knee K<P:
`f(Y)=Y` for Y≤K;
`f(Y)=K+(P−K)[1−exp(−(Y−K)/(P−K))]` otherwise.

Scale linear RGB by `f(Y)/Y` (black remains black), then gamut-compress. This is continuous with unit slope at K and asymptotes to P; it does not map mastering peak exactly to P. Explore K/P=.5–.8. A production curve may map a declared input endpoint exactly; document that distinction. HDR metadata (mastering display, MaxCLL/MaxFALL) informs mapping but can be missing/inaccurate. Dynamic mapping estimates frame/scene statistics and needs temporal smoothing and scene-cut reset to prevent pumping.

A scalar luminance shoulder cannot guarantee RGB stays inside panel capacities. Prefer hue-aware chroma compression in a specified perceptual space (e.g. ICtCp with correct transfer conventions), or begin with a documented RGB desaturation-to-white projection. Channel clipping is a diagnostic baseline that can shift hue. Local tone mapping is an image-processing effect and can create spatial halos independently of backlight optics.

## ABL, load and color volume

Use a neutral window measurement table versus lit fraction, commanded luminance, duration and temperature; bilinear/log interpolation is a **fit choice**. APL should mean a declared average of linear luminance, not mean PQ code. A power proxy can also depend on channel drive:

`P_req=mean_i Σ_c k_c e_ic`, `g=min(1,P_budget/max(P_req,δ))`, `e_out=g e_req`.

This proposed global limiter explains load coupling but is not a measured controller. Use fast limit plus thermal state `T_next=T+(1−exp(−dt/τ_th))(T_equilibrium(P_req)−T)` if data supports it. Explore load response 10–1,000 ms, thermal τ 1–100 s; these are priors. Static-logo dimming/ASBL over seconds or minutes is a separate optional controller. LCD backlights and plasma can have power limiting too.

WRGB model: approximate `RGB_target≈RGB_filtered + w(1,1,1)` in normalized white coordinates; choose w by constrained allocation with independently measured RGB and W maxima/power. High white peak alone cannot predict saturated-color peak. Do not model W as arbitrary added brightness without checking the reconstructed XYZ. QD-OLED omits W allocation but still has RGB/current/thermal limits.

For spectra, `XYZ_c=k∫S_c(λ)(x̄,ȳ,z̄)(λ)dλ`. QD conversion can narrow red/green emission relative to broad phosphor/filter systems; spectra, not a saturation slider, determine primaries. [Samsung Display's spectral explanation](https://global.samsungdisplay.com/31114) supports that mechanism; its performance claims require independent calibration. Proposed spectral sweeps: blue 445–470 nm, green 525–545, red 620–650; QD FWHM 20–40 nm versus broad phosphor surrogate 50–120 nm. These are illustrative fitting ranges, not all-material constants; multi-peak phosphors need measured spectra. CRT/plasma phosphor persistence is covered in [temporal notes](04-temporal.md).

Validate color volume with saturated RGB/CMY and intermediate hues at several luminances/APLs, reporting attainable XYZ or a declared ΔE metric. A 2D P3-coverage figure cannot describe the loss of saturated highlight luminance.

Open questions: reference tone-map policy, trustworthy mastering metadata, per-channel peak curves, WRGB allocation, spectral measurements and dynamic-power history.
