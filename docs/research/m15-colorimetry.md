# M15 — explicit colorimetry, gamut and color volume

This note precedes M15 runtime implementation. It uses the repository's
[M/D/P/NR convention](../profiles.md): **M** is a measurement of an
identified specimen under recorded conditions; **D** is a deterministic
calculation or an explicitly declared standard definition; **P** is a proposed
synthetic model/placeholder; **NR** is not reported or not researched sufficiently
to use. A standard's coordinates are **D**, but assigning those coordinates to a
generic panel is **P**. Standard/document names, editions, equation identifiers
and milestone identifiers are identifiers, not measured quantities. No named TV
is calibrated here.

## Signal container, mastering display and simulated panel

An RGB triplet needs primaries, reference white, transfer function, signal range
and luminance normalization. These are independent declarations. A BT.2020
container does not prove that the programme uses its entire gamut; a mastering
display gamut describes the monitor used to judge the content, rather than
changing the meaning of the container's RGB components. P3-limited material
carried in BT.2020 must first be decoded as BT.2020. Reinterpreting those same
numbers as P3 changes the colors. The mastering monitor and actual occupied
content gamut remain **NR** when the source does not declare them. SMPTE's
[ST 2086 mastering-display metadata standard](https://doi.org/10.5594/SMPTE.ST2086.2018)
identifies mastering-display primaries, white and luminance; it does not replace
the signal colorimetry declaration.

| Declared encoding/reference | Red xy | Green xy | Blue xy | Reference white xy | Evidence/source |
|---|---|---|---|---|---|
| BT.709 | (0.640, 0.330) **D** | (0.300, 0.600) **D** | (0.150, 0.060) **D** | D65 (0.3127, 0.3290) **D** | [BT.709-6, system colorimetry](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.709-6-201506-I!!PDF-E.pdf) |
| Display P3 | (0.680, 0.320) **D** | (0.265, 0.690) **D** | (0.150, 0.060) **D** | D65 (0.3127, 0.3290) **D** | [ICC primary documentation supplied by Apple](https://registry.color.org/rgb-registry/displayp3) |
| BT.2020 | (0.708, 0.292) **D** | (0.170, 0.797) **D** | (0.131, 0.046) **D** | D65 (0.3127, 0.3290) **D** | [BT.2020-2, Table 3](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2020-2-201510-I!!PDF-E.pdf) |

Display P3 uses the sRGB transfer function in its standard encoding. A
**linear Display P3** float export deliberately carries its primaries and white
with a **linear** transfer declaration; the receiver must not decode it as
already encoded CSS `display-p3`. Cinema DCI-P3 has a different reference white
and transfer convention, so the simulator should use the unambiguous name
`display_p3`. [ICC Display P3](https://registry.color.org/rgb-registry/displayp3)
and [CSS Color](https://www.w3.org/TR/css-color-4/#predefined) supply the primary
encoding definitions.

BT.2100 specifies BT.2020 primaries/D65 with PQ or HLG signals. PQ is an absolute
display-light encoding with a nominal upper bound of **D 10,000 cd/m²**; that
bound is not a TV peak measurement. HLG recovers scene light and applies a
display OOTF whose output depends on the display peak and viewing assumptions.
Selecting an EOTF cannot infer a file's source primaries. Existing simulator
paths therefore retain their explicit compatibility assumption, **P BT.709**,
including existing images whose source metadata is absent. New HDR experiments
must declare BT.2020 when that is the signal intent. See
[BT.2100-3, system colorimetry and PQ/HLG tables](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-3-202502-I!!PDF-E.pdf).

The disabled legacy HLG implementation retains its BT.2020-weighted OOTF for
exact historical parity, even when a caller interprets its RGB as BT.709.
M15's enabled decoder instead derives the OOTF luminance from the declared
source matrix. This compatibility discrepancy is not a claim of a standard
BT.709 HLG encoding; faithful color-managed HLG work should use the explicit
path and the intended source declaration.

## What the panel families justify

Technology supports a mechanism, not a universal numerical primary triangle or
color-volume percentage. Native gamut varies with emitter/converter spectra,
filters, drive, mode, generation, angle and temperature. A gamut-area or coverage
percentage does not uniquely identify primary xy, spectra or a luminance envelope.

| Generic family | Supported mechanism / typical tendency | Safe initial model | What remains NR |
|---|---|---|---|
| QD-OLED | Blue OLED excitation plus narrow-band QD conversion yields distinct RGB output; no additional white boost subpixel. Broad gamut and high saturated-color output are plausible. [Samsung Display's original explanation](https://global.samsungdisplay.com/31114) is manufacturer evidence, not independent calibration. | **P** broad illustrative triangle approaching BT.2020; common RGB capacity. | Matched specimen xy/SPDs, channel maxima, spectral drift, measured volume vs. window/time. Manufacturer coverage claims do not fill these fields. |
| WOLED with RGBW | Filtered white OLED plus efficient white subpixel. White helps neutral/desaturated output; saturated output needs the filtered color channels. The original [Murdoch/Miller RGB-to-RGBW work](https://doi.org/10.1889/1.3069788) discusses high current for bright saturated colors. | **P** P3-like triangle plus a saturation-dependent capacity envelope. | Filter/SPD and white-subpixel chromaticity, RGBW allocation, per-channel power/current, measured color ceilings vs. area/time. |
| VA FALD mini-LED, QD/KSF | LC shutter mode and local-dimming geometry do not determine gamut. Blue-pumped QDs, narrow red KSF/PFS phosphor, green phosphor and filters determine the spectral triangle. QD and KSF can compete or coexist. | **P** P3-like triangle. Keep local-dimming/contrast mechanisms independent of the primary declaration. | Which converter/filter stack this generic family uses, matched spectra/xy, controller-dependent saturated volume. |
| IPS edge-lit | IPS and edge lighting describe transmission and illumination geometry. They do not require a narrow gamut; an inexpensive broadband backlight can be BT.709-like, while narrow-band converters permit wider gamut. | **P** BT.709-like triangle for this specific generic illustration. | Actual phosphor/filter stack, xy/SPDs and color-dependent luminance envelope. |

[Luo, Chen and Wu's original QD LCD analysis](https://doi.org/10.1364/OE.21.026269)
models different LC modes using measured QD emission and shows a tradeoff between
efficiency and gamut. Those prototype results do not calibrate a retail VA or
IPS profile. [Murphy and Hendy's KSF study](https://doi.org/10.1002/msid.70057)
includes their own spectrometer observations of retail displays and identifies
KSF both alongside and in place of QD conversion. Their showroom spectra support
the distinction of mechanisms, but uncontrolled demonstration modes and ambient
conditions do not provide this simulator's matched color-volume measurement.

### External measured anchors; no transfer to generic profiles

These are original reviewers' own instrument results on identified samples,
not manufacturer coverage claims. The percentages retain the authors' metric
and selected picture mode. They illustrate plausible family behavior and the
importance of conditions; they are not a common-protocol ranking or a fit.

| Named sample / family | Reported colorimetry result | Source conditions and remaining NR |
|---|---|---|
| Samsung QE65S95B, QD-OLED | BT.2020 **M 76%** and P3 **M 99%**, the author's **xy gamut coverage**, not color volume. | [AVForums original measurements/HDR results](https://www.avforums.com/reviews/samsung-s95b-qd-oled-tv-review.19923/): retail sample, firmware `1211`, HDR Filmmaker, D65/PQ target; Calman, Murideo Seven generator, Klein K-10A. The review flags the gamut Auto setting; the gamut measurement's precise selector/CMS state, stimulus luminance, area, dwell and uncertainty are **NR**, so this is not an identified maximum native gamut. Firmware digits identify the source record. |
| LG OLED65C2, RGBW WOLED | BT.2020 **M 72%** and P3 **M 97%**, the author's **xy gamut coverage**, not color volume. | [AVForums original measurements/HDR results](https://www.avforums.com/reviews/lg-c2-oled65c2-oled-evo-tv-review.19852/): purchased retail sample; HDR Filmmaker, D65/PQ target, Dynamic Tone Mapping Pro off; Calman, Murideo Seven, Klein K-10A. Gamut-patch amplitude, area, dwell, uncertainty and numeric primary xy remain **NR**. These coverage figures cannot determine saturated-color luminance ceilings. |
| Samsung QE65QN95B, VA/QD FALD mini-LED | BT.2020 **M 67%** and P3 **M 89%**, the author's **xy gamut coverage**, not color volume. | [AVForums original measurements/HDR results](https://www.avforums.com/reviews/samsung-qn95b-qe65qn95b-4k-neo-qled-tv-review.19992/): HDR Filmmaker, D65/PQ target; Calman, Murideo Seven, Klein K-10A. The article identifies VA, QD and mini-LED local dimming. Gamut-patch amplitude, area, dwell, uncertainty, firmware and numeric primary xy remain **NR**. |
| LG 65SJ9500, IPS LCD comparator | For the **managed Full HD gamut**, on-axis **M 96%** of sRGB/BT.709; separately, for the **native wide gamut**, on-axis **M 108%** of DCI-P3. These are **CIE 1976 gamut-size ratios** for different gamut conditions, not the same primary triangle or coverage/volume. | [DisplayMate original Table 1 and method](https://www.displaymate.com/TV_Picture_Quality_with_Viewing_Position_1.htm): Cinema mode, laboratory spectroradiometer and proprietary patterns; Table 1 separates Full HD and native-wide gamut tests. Exact gamut-selector state, instrument model, patch amplitude/area/dwell and uncertainty are **NR** here. The larger native-gamut size shows why IPS need not be BT.709-limited. The article does not identify an edge-light-guide measurement, so transfer to the generic edge-lit model remains **NR**. |

In all rows, exact numerical primary/white measurements and a matched
hue × luminance × area × time color-volume envelope remain **NR** for model
fitting. An area ratio exceeding the reference area does not establish complete
coverage of that reference triangle. Source-selected gamut management can also
hide a panel's physical native gamut. The generic assignments below therefore
remain **P**; none of these measurements supplies the RGBW ratio or exponent.

The initial sidecar assignments below are **all P**, including their D65 choice;
the standard definitions above remain **D** only in the source/encoding ledger.
These are proposed demonstration coordinates, not extracted measurements:

| Profile | Red xy, **P** | Green xy, **P** | Blue xy, **P** | White xy, **P** |
|---|---|---|---|---|
| `generic_qdoled` | (0.680, 0.310) | (0.220, 0.750) | (0.140, 0.050) | (0.3127, 0.3290) |
| `generic_woled` | (0.680, 0.320) | (0.265, 0.690) | (0.150, 0.060) | (0.3127, 0.3290) |
| `generic_va_fald_miniled` | (0.680, 0.320) | (0.265, 0.690) | (0.150, 0.060) | (0.3127, 0.3290) |
| `generic_ips_edge` | (0.640, 0.330) | (0.300, 0.600) | (0.150, 0.060) | (0.3127, 0.3290) |

## Conversion and mapping contract

Derive the RGB↔XYZ **D** matrices from the declared xy; do not hand-fit a
matrix or use rounded video luma coefficients as the exact XYZ Y row. For each
primary form `p=(x/y, 1, (1-x-y)/y)` and arrange those vectors as columns of `P`.
For reference white `w=(xw/yw, 1, (1-xw-yw)/yw)`, solve `s=P⁻¹w` and set
`M=P diag(s)`. Then `XYZ=M RGB` and
`RGB_panel=M_panel⁻¹ M_source RGB_source` for a common white. These equation
constants, matrix dimensions and normalization are **D** mathematical definitions.
Different whites require an explicitly declared policy. M15 supports
`none_absolute_xyz`: preserve absolute XYZ without chromatic adaptation, so
a source white differing from panel white remains chromatically different.
This is not an automatic white-to-white adaptation.
[BT.2408-8 Annex 7](https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-BT.2408-8-2024-PDF-E.pdf)
is the pinned matrix-derivation reference. The
[ITU catalogue](https://www.itu.int/pub/R-REP-BT.2408) now lists a newer edition;
this note pins the inspected edition rather than claiming it is latest.

A source-to-panel matrix can produce negative channels: they are valid evidence
of an unrepresentable source chromaticity, not negative emitted light. Record
pre-map masks/fractions and the declared reference domain before changing them.
Hard clipping is a useful explicit baseline, but clipping channels independently
can change luminance, hue and relative color detail. A compression can move
colors toward the destination white, preserving a chosen hue coordinate while
reducing chroma. Neither rule reproduces every TV's proprietary mode.

**P proposed mapper:** at fixed exact panel XYZ Y, use the neutral-axis ray
`rgb(t)=Y·(1,1,1)+t·(rgb-Y·(1,1,1))`. Find the nonnegative-channel boundary and
compress only the radial chroma near/outside it, with a **P 0.8** normalized knee.
This preserves the straight ray from white in CIE **D 1976** u′v′, as can be
checked by converting its endpoints to XYZ. Its radial parameter is not linear
in u′v′ distance. “Hue-preserving” here means this declared geometric ray; it is
not a claim of constant perceived hue for all colors/observers. Brightness
capacity is handled jointly in the HDR stage, not as a second chroma projection.

ICtCp offers HDR-oriented intensity/chroma separation and hue behavior; see
[Dolby's original ICtCp white paper](https://professional.dolby.com/siteassets/pdfs/ictcp_dolbywhitepaper_v071.pdf).
[Jzazbz's original paper](https://doi.org/10.1364/OE.25.015131) targets uniformity
for HDR/wide-gamut signals. [Ottosson's original Oklab description](https://bottosson.github.io/posts/oklab/)
defines a practical lightness/chroma/hue space with D65, while
[CSS gamut mapping](https://www.w3.org/TR/css-color-4/#gamut-mapping) describes
constant-lightness/hue OkLCh chroma reduction. These are alternative modeling
choices, not interchangeable hue lines. Oklab's relative-light operations should
not be labeled an absolute HDR appearance model. M15's geometric method can be
validated exactly without claiming the perceptual fidelity of those methods.

Tone and gamut mapping interact: an intensity change can move a point inside a
color-volume boundary, while channel clipping can change the color on which the
tone curve acts. [BT.2390-11](https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-BT.2390-11-2023-PDF-E.pdf)
discusses display adjustment for limited luminance/gamut and ICtCp. BT.2408-8
separates display gamut management from its example EETF mappings. The
simulator's exponential shoulder remains **P**, not an implementation of an ITU
EETF or a named manufacturer's algorithm.

## WOLED volume and one capacity owner

An efficient white emitter cannot increase saturated-primary luminance without
adding a white component and moving chromaticity toward white. A white-window
peak must therefore not be reused as the attainable luminance of every saturated
color. This is an RGBW allocation constraint, not proof of any particular TV's
white-subpixel activation threshold. [Miller and Murdoch's original extended
article](https://archive.informationdisplay.org/Portals/InformationDisplay/IssuePDF/03_2009.pdf)
describes exploiting white-subpixel efficiency and limiting RGB demand; it does
not identify coefficients for today's generic profile.

A minimal **P** model uses nonnegative mapped panel RGB, neutral fraction
`n=min(R,G,B)/max(R,G,B)` and a synthetic channel ceiling
`C_color=P0·[r+(1-r)·n^p]`. Proposed WOLED coefficients are **P r=0.45** and
**P p=2**; their measured values are **NR**. Other families use **P r=1**, so
this extra saturation penalty is inactive. The scalar endpoint and exponent are
synthetic choices, not RGBW electrical equations. Black receives a defined safe
neutral fraction; it emits black regardless.

Combine this constraint with the existing static ABL or M13 updated global
capacity through `C=min(C_global,C_color)`. For nonblack pixels, the attainable
luminance along the chosen RGB ray is `Y_cap=C·Y/max(R,G,B)` (**D**, given this
**P** channel-cube model). Use that ceiling in the existing shoulder once and
apply its common gain to RGB. The capacity stage owns all these limits together;
do not run a second RGBW output clamp or the legacy post-shoulder desaturation.
Read ABL load from its declared demand/emitted domain before limiting, and keep
M13's single per-tick state update. M10's RGB emission/transmission changes act
before this capacity decision. Channel power, temperature, hue-dependent RGB
maxima, non-additive spectra and measured RGBW controllers remain **NR**.

## Evidence, exports and acceptance

Versioned colorimetry sidecars must retain panel xy/white, model identifiers,
all **P** coefficients, source URLs/locators and explicit **NR** spectral/volume
fields. Validate finite nondegenerate primaries, supported white policy and
coefficient domains. Matrix elements are **D from declared inputs**; this does
not promote their **P** panel inputs to measurements. Preserve the existing
profile identity matrices and all old numeric paths when the runtime option is
off, checked with exact array/asset equality against pre-change captures.

Export linear XYZ or explicitly named linear Display P3/BT.2020 with units,
white, matrices, mapper/volume configuration and diagnostics. A linear channel
coordinate in nit-scaled RGB is not individually CIE luminance; XYZ Y is the
luminance. Host/browser conversion and exposure are separate. Preserve the
[M12a preview calibration distinction](m12a-web-hdr.md) and
[Mac EDR color-management contract](m5-mac-display.md): a correctly tagged float
buffer does not establish measured light output, host spectra or headroom.

Use **P** synthetic saturated ramps, BT.2020 primaries/secondaries,
skin/foliage-like patches and a hue sweep, with their exact source RGB intent
saved. These illustrative skin/foliage patches are not measured reflectances or
a standardized color chart. Compare profiles and mapping modes under one
shared exposure. Report **D** CIE u′v′ distances and ray-angle errors against
the declared source intent; define dark/neutral exclusions and preserve their
masks. CIE u′v′ distance is chromaticity error, not ΔE or proof of perceptual
indistinguishability. Report luminance error separately, including the deliberate
**P** saturated WOLED capacity loss. Inspect the contact sheet after numerical
checks; SDR clipping can hide wide-gamut differences and a screen image cannot
validate the physical model.

Matched on-axis/off-axis spectral sweeps, per-hue luminance vs. area and time,
RGBW drive/current identification, meter uncertainty and real source mastering
metadata remain **NR**. New data should identify specimen, mode, stimulus,
geometry, transfer/colorimetry, dwell/history and instrument; then replace only
the supported **P** fields while retaining original evidence and fit residuals.
