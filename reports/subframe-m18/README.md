# M18 synthetic sub-frame emission artifacts

All protocol, model and fixture parameters are **P** placeholders. Arrays,
waveforms, clocks and metrics are **D** under those choices. Matched device
response/OD/PWM/scanout calibration and certification remain **NR**. No shipped
profile is calibrated by this experiment. Read the
[research note](../../docs/research/m18-subframe-temporal.md) before interpreting
the output. The [gallery](index.html) works offline.

Reproduce into a fresh directory, preserving this evidence:

```sh
PYTHONUSERBASE=/tmp/m18-user python3 -m tv_sim subframe \
  --out reports/subframe-example
```

The packaged version-1 [P protocol](protocol.json) declares a 128×24 raster,
60 Hz display ticks and 32 exact rational bins per tick (1920 bins/s). Moving
edges and bars run for 12 ticks at 120, 360 and 720 px/s. Six directed transitions
cover the three-level 20/100/300-nit gray matrix; identical-level diagonal cells
have no response transition. Each step gets one separately settled preparation
tick and a 12-tick observed hold. A 5 Hz flashing patch and an independent
constant patch each run for one second.

The six arms use independent complete histories: LCD hold, LCD overdrive, LCD
strobe, LCD PWM, OLED hold and OLED BFI. The LCD backlight is a constant 1000 nits;
optical spread, ambient, legacy temporal response and static ABL are explicitly
disabled to isolate the new response/gating model. Both synthetic HDR ceilings
are 1000 nits with knee ratio 1, preserving all admitted gray targets through
1000 nits. The LCD native contrast is explicitly P 4000:1, deriving a D 0.25-nit extinction
floor. GtG reference levels below that floor reject; dark motion/flash content
can still request black and its actual emitted plateau remains observable.
LCD rise/fall e-fold times
are 5/8 ms. The illustrative OD table commands
`clip(new + 2 × (new − old), 0, 1)` for the first quarter tick; this deliberately
aggressive P example exposes overshoot. Strobe and BFI duty are one quarter,
with phases 5/8 and 3/8 of a tick respectively. PWM is 240 Hz at half duty.
OLED zero tau isolates emission duty; it is not a measured OLED response.

Every CSV row retains exact rational left/right PTS and duration, emitted mean
and centre-probe Y, and the ungated centre-pixel panel endpoint expressed as
nit-equivalent gray. The GtG JSON also retains those endpoint traces and their
exact clock, so response metrics can be recomputed independently. Response
crossings use linear interpolation between endpoints; settling requires all
remaining observed samples to stay within 2% of step amplitude. A transition
already above 90% in the first sample is unresolved and reports a timing upper
bound, rather than inventing a resolved zero-tau response time.

Pursuit images integrate actual emitted bin means in tracking coordinates over
one tick, using each bin midpoint for spatial displacement and retaining the
full shutter duration, including dark bins. Fixed-camera and pursuit images
share one sRGB exposure: 500 nits equals white. Pulse images are visibly dimmer;
there is no automatic normalization. MPRT here is explicitly
`10–90 edge width / (0.8 × speed)`, which returns the full duration for an ideal
continuous rectangular hold. The finite raster and midpoint quadrature add a
resolution floor, especially at the lowest speed. This is not a VESA ClearMR
certification or a matched physical pursuit-camera measurement.

Selected D results under the saved P protocol:

| Quantity | Hold | OD or impulse arm |
|---|---:|---:|
| LCD 100→300-nit 10–90 response | 10.988 ms | OD: 1.615 ms |
| LCD 100→300-nit settling within 2% | 19.792 ms | OD: 30.208 ms |
| LCD 100→300-nit overshoot | 0% | OD: 69.621% (139.241 nits) |
| LCD normalized MPRT, 720 px/s | 28.024 ms | Strobe: 23.141 ms |
| OLED normalized MPRT, 720 px/s | 16.659 ms | BFI: 4.496 ms |
| Constant-patch emitted mean | 300 nits | Strobe/BFI: 75 nits; PWM: 150 nits |
| Constant-patch flicker percent/index | 0% / 0 | Strobe/BFI: 100% / 0.75; PWM: 100% / 0.5 |
| Dominant constant-patch frequency | None | Strobe/BFI: 60 Hz; PWM: 240 Hz |

The FFT uses uniform bin means, excludes DC and reports the strongest discrete
frequency bin. The one-second trace has 1 Hz bins and a 960 Hz Nyquist limit.
The protocol rejects PWM at or above that limit; integration preserves energy
but cannot recover unresolved higher-frequency shape. The flashing-patch trace
contains both requested content modulation and emission modulation; its separate
constant-patch trace isolates the latter. These metrics do not implement IEEE
1789 biological risk classification.

Visual review opened all six edge/bar contact sheets, the 100→300-nit
waveform and constant-patch modulation plot. The OLED BFI pursuit edge is
narrower and dimmer. LCD strobing retains a displaced secondary edge from
incomplete LC settling. The bar reveals a brighter OD contour; the GtG trace
shows its strong overshoot and longer final settling. The low-speed LCD strobe
width can exceed hold width because pulse phase and LC history matter. Static
PNG files do not reproduce perceived flicker or host display luminance.

`manifest.json` records exact configs/profile snapshots, each arm’s complete
display identity covering runtime dependencies, experiment implementation hashes,
array hashes, metric definitions and artifact paths. Full linear content/output
and pursuit `.npz` arrays are reproducible and gitignored. The largest committed
JSON trace is below 180 kB. The run renders 1620 display ticks across independent
arms; CSVs contain 39168 observed emission bins, with another 11520 constant-patch
bins retained in JSON and preparation bins excluded from response traces.
