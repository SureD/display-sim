# M15 synthetic colorimetry comparison

[Open the inspected gallery](index.html). Reproduce from the repository root:

```sh
python3 -m tv_sim colorimetry --out reports/colorimetry-m15
```

All panel assignments, source stimuli and exposure choices are **P**. Matrices,
mask fractions and errors are **D calculations under those P inputs**. No named
TV is calibrated. Measured panel primaries, spectra, RGBW allocation/current,
per-hue luminance envelopes and host optical output remain **NR**. Primary-source
references and model definitions are in [the research note](../../docs/research/m15-colorimetry.md).

The **P** experiment uses a 320 × 180 raster, BT.2020/D65 linear RGB encoded as
float PQ, and one shared **P 2,000-nit** preview white across every tile, method
and profile. Sources include saturated RGB/CMY/white ramps, separated
primary/secondary windows at **P 25/100/400/1,000/2,000 channel nits**, illustrative
skin/foliage-like patches at **P 100/1,000** scale, and a **P 1,000-channel-nit** hue
and saturation sweep. Window cells have **P 0.7** fill along each axis to retain
a black surround and expose color capacity at moderate APL. The patches are
synthetic linear colors, not measured reflectances or a standard chart.

The complete pipeline retains each generic profile's spatial processing,
optics, panel transmission and static ABL. On-axis viewing and zero ambient
are declared **P** overrides; M13 dynamics are off for this static comparison.
Each still begins with fresh settled panel history. Preview conversion is
panel RGB → linear BT.709 → shared exposure → clip → sRGB transfer. This SDR
host clip is separate from the simulated TV; it can conceal wide-gamut errors.

The following are **D** errors for the separated BT.2020 primary/secondary
windows, measured numerically against their declared pre-display XYZ intent.
They describe the full P pipeline, including intentional brightness loss and
LCD/optical mixing, rather than the gamut mapper alone.

| Generic profile | Mapper | Mean u′v′ distance (D) | Maximum u′v′ distance (D) | Mean absolute Y error, nits (D) |
|---|---|---:|---:|---:|
| VA mini-LED | clip | 0.030514 | 0.062306 | 24.280 |
| VA mini-LED | compress | 0.043731 | 0.092528 | 19.420 |
| IPS edge | clip | 0.049657 | 0.116284 | 132.218 |
| IPS edge | compress | 0.071965 | 0.221904 | 129.394 |
| WOLED | clip | 0.029936 | 0.061570 | 128.340 |
| WOLED | compress | 0.043389 | 0.084394 | 126.485 |
| QD-OLED | clip | 0.017459 | 0.049305 | 71.542 |
| QD-OLED | compress | 0.028356 | 0.069990 | 69.201 |

CIE 1976 u′v′ distance is a chromaticity distance, **not ΔE**, and excludes
luminance. Chromaticity is excluded when either source or output XYZ Y is at
most **P 10⁻⁶ nit**, or the chromaticity denominator is at most **P 10⁻¹²**;
Y error still includes those pixels. Optical leakage into intended black can
therefore affect the Y error without inventing a black chromaticity. The
manifest records valid/excluded counts and every pattern's errors. Local float
arrays include the actual validity and OOG masks.

Compression retains the declared straight hue ray from white in u′v′ at the
mapping stage and preserves its Y before capacity mapping, subject to float32
rounding. It deliberately reduces more chroma near the boundary than clipping;
a larger distance from an impossible source intent is therefore expected, and
does not contradict hue-ray preservation. Subsequent LCD transmission, angular
terms, optics and spatial processing can alter the final hue. No universal
perceptual advantage or error threshold is claimed.

WOLED's **P** peak is 850 channel nits and its **P** saturated RGB ratio is 0.45,
giving a **D 382.5-channel-nit** color ceiling for a saturated panel RGB ray.
In the separated-window experiment its **D** global capacity is **503.705 nits**
with clipping and **521.149 nits** with compression. Saturated colors therefore
meet the smaller color ceiling while neutral white retains the global ceiling.
The minimum of these constraints feeds one HDR shoulder. Under heavier-load
ramps/sweeps, global ABL can become the tighter limit for both; no second RGBW
limiter follows the shoulder.

All four contact sheets were visually inspected. The separated windows show
WOLED's brighter neutral versus saturated patches, and the shared exposure
retains the generic profiles' brightness differences. Clip and compression
produce visible saturation changes in the ramps and hue sweep; compression
reduces abrupt clipping transitions but also softens color separation. The
illustrative skin/foliage rows broadly agree between methods because most
samples lie inside the panel triangles. Edges include sharpening, optical
spread and LCD leakage. These observations verify a synthetic demonstration,
not emitted luminance, a named device or perceptual fidelity.

`manifest.json` retains exact profiles, sidecar hashes, matrices, scalar
diagnostics and array hashes. The large, reproducible `.npy` intents, output XYZ,
capacity maps and masks are ignored locally by [`.gitignore`](.gitignore); rerun
the command to regenerate them. Default-off parity is tested independently
against captures made before M15 runtime edits. Implementation fingerprints
remain truthful and can change with source code while legacy asset bytes and
substantive traces stay equal.
