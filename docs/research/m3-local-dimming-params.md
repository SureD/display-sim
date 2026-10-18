# M3 local dimming parameters and validation contract

2026-10-16. All example parameters below are **synthetic priors**, not measured
retail specifications. Mechanism and fitting background: [M1 note 02](02-backlight-local-dimming.md)
and [panel note 01](01-panel-tech.md). Units are emitted cd/m² unless stated.

## Grid and optics

Use `zones_x=columns`, `zones_y=rows`; pitches `px=W/columns`, `py=H/rows`.

| Example | Columns × rows | Count | Pitch at 3840×2160 (x,y pixels) |
|---|---:|---:|---:|
| Current FALD fixture (coarse demonstration) | 16×12 | 192 | 240,180 |
| Conventional FALD sweep | 16×9 | 144 | 240,240 |
| Mini-LED sweep | 48×32 | 1536 | 80,67.5 |
| Dense mini-LED sweep | 96×54 | 5184 | 40,40 |
| Edge proxy | 8×1 | 8 strips | 480,2160 |

Noninteger pitches require actual `zone_edges` boundaries. LED count is not
zone count. Edge optics should use elongated measured influence fields; a
radial FALD blur is only a compatibility proxy there.

Proposed scatter PSF, convolved with each rectangular zone footprint:
`G(x,y;sx,sy)=exp(-0.5*((x/sx)^2+(y/sy)^2))/(2*pi*sx*sy)`;
`K=(1-a)*G_core+a*G_tail`. Sweep core sigma 0.2–0.8 pitches,
tail 1–3 pitches and tail energy a=0–0.15; start at (0.4,1.5,0.05).
Convert x/y sigmas independently using px/py. Sample each component on odd
support `nx=2*ceil(3*sx)+1`, `ny=2*ceil(3*sy)+1`, normalize its discrete sum,
then combine on a common zero-padded support. Three-sigma rectangular truncation
omits about 0.54% continuous 2D Gaussian mass before renormalization; compare
four-sigma support for convergence when measuring weak tails.

| Sampling example | Sigma x,y | Kernel nx×ny |
|---|---:|---:|
| One sample/pitch, core 0.4 | 0.4,0.4 | 5×5 |
| One sample/pitch, tail 1.5 | 1.5,1.5 | 11×11 |
| 8 pixels/pitch, core 0.4 | 3.2,3.2 | 21×21 |
| 8 pixels/pitch, tail 1.5 | 12,12 | 73×73 |
| Current 384×288, 16×12, sigma 0.75 | 18,18 | 109×109 |

Low-resolution kernels need area integration or supersampling to avoid aliasing.
The existing `_sigma_px` uses sigma times the **average** x/y pitch and a single
Gaussian. Keep it for compatibility or explicitly migrate to anisotropic optics.
Current reflect padding preserves DC but mirrors light at borders. For physical
H maps use measured edge zones or zero extension plus a fixed all-on calibration
map: `B_i=Bmax_i*(sum_j H_ij*d_j)/(sum_j H_ij)` where denominator is positive.
Do not renormalize each clipped zone PSF separately. Store tail/boundary policy.

The [Emmel/Whitehead PSF paper](https://doi.org/10.1364/AO.52.008239)
is a primary optical-design anchor, not a source for these Gaussian coefficients.

## Leakage and compensation

`epsilon=1/C`; `L=B*(epsilon+(1-epsilon)*q)`;
`q=clip((T/max(B,delta)-epsilon)/(1-epsilon),0,1)`.
For B=0 explicitly return zero; delta=1e-6 nits is numerical only.
This is equivalent to `clip(T,B/C,B)` in emitted light for positive B.
Current `lcd_transmit` implements that constraint with a tiny numerical floor.
VA C=2000–8000 (fixture 4000); IPS C=700–1500 (fixture 1200) are broad
priors. At B=1000, black is 0.125–0.5 nits for VA and 0.667–1.429
for IPS. Hold B fixed when testing inverse-contrast scaling. Backlight scatter
alone does not establish visible halo: measure after LCD transmission.

## Window size → halo metrics

Use 384×288 neutral windows on zero black at 1000 nits, 16×12 zones,
no sharpening, ambient, tone map or temporal blur. Construct side fractions
sqrt(area fraction) on both axes, record actual raster area. Repeat centered,
half-pitch shifted and near an edge. Use the same requested level at each size.
Define outside-window distance `d=max(dx/px,dy/py)` with dx/dy distance to
nearest lit pixel along each axis. Near ring: `0<d<=1`; far: `d>=4`.
Measure near mean/max, far mean, halo width above 0.01 nits, outside energy
`sum(Y_outside)/sum(T_inside)`, and highlight retention `mean(Y_inside)/1000`.
Subtract an identically configured all-black run before halo metrics.

| Lit area | Expected diagnostic (synthetic, no empirical tolerance claim) |
|---|---|
| 1%, 2% | Near-ring leakage positive and above far background; zone alignment strongly affects retention and normalized halo energy |
| 10% | Positive near halo; interior recovers better than tiny objects under max-pool/blur control |
| 25%, 50% | Halo remains along perimeter; total outside energy need not decrease monotonically |
| 100% | Outside metrics undefined (report N/A); all-on B flat, black/leakage tested separately |

For black target pixels assert `Y≈B/C` (rtol 1e-4, atol 1e-6 nits),
finite nonnegative output, and capacity bounds. Do not assert that peak halo
increases monotonically with area: zone phase and controller policy interfere.
A zero-scatter OLED control has zero outside emission. Existing M3 tests cover
1/2/10% FALD leakage and the OLED control; they do not calibrate a real TV.
Open: measured topology, edge optics, PSF/controller separation, and moving-zone
rise/fall (suggested sweeps rise 0–30 ms, fall 0–150 ms from note 02).
