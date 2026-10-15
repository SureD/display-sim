# M3 HDR and ABL parameters

2026-10-16. **Normative** means a transfer definition; **prior** means an
unfitted modeling range; **synthetic** means a reproducible example, with no
statistical confidence interval. See [M1 HDR](03-color-hdr.md) for full EOTFs.

## Shoulder implementation

Existing `soft_clip`: `K=k*P`, `f(Y)=Y` below K, otherwise
`K+(P-K)*(1-exp(-(Y-K)/(P-K)))`. Validate P>0 and 0<=k<1.
It is monotone, C1 at K, asymptotic to P. Apply RGB gain f(Y)/Y in linear
light, preserving zero. Prior k=0.5–0.8; current fixtures use synthetic 0.85,
a deliberately later knee. With P=1000, k=0.7: f(700)=700,
f(1000)=889.64, f(4000)=999.995 nits (analytic examples).

Optional finite-endpoint shoulder for declared source peak S>P:
let D=S-K, A=P-K, z=(Y-K)/D and m=D/A. For K<Y<S use
`f(Y)=K+A*(m*z/(1+(m-1)*z))`; retain identity below K and clamp P at/above S.
It has unit initial slope, maps S to P and is monotone, but derivative jumps
at the final clamp. This is our approximation, **not BT.2390**. A standards
baseline should implement the pinned [BT.2390-8](https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-BT.2390-8-2020-PDF-E.pdf)
EETF separately. Neither scalar shoulder enforces individual RGB capacity;
add a declared gamut-compression policy before claiming color-volume fidelity.

## ABL versus load

Keep the current contract explicit: `a=clip(mean(Y_request)/P0,0,1)`;
`P(a)=F+(P0-F)*(1-a)^g`. P0 is panel small-window capacity, F full-field
capacity, g a synthetic shape parameter (explore 1–3, fixture 2).
Validate 0<F<=P0, g>0. Compute load before mapping, never from PQ code or
post-limit output (which would create feedback). Black load gives P0, not light.

| a (linear average / P0) | WOLED P0=800,F=150,g=2 | QD-OLED P0=1000,F=200,g=2 |
|---:|---:|---:|
| 0.01 | 787.065 | 984.08 |
| 0.10 | 676.5 | 848 |
| 0.25 | 515.625 | 650 |
| 0.50 | 312.5 | 400 |
| 1.00 | 150 | 200 |

All entries are **synthetic ceilings**, not resulting mapped peaks or measured
window data. For a neutral window commanded at P0, a equals window area;
for a dimmer window a=area*command/P0. A full field at 100 nits is not a=1.
The M1 architecture's `mean(Y)/max(Y)` window-table proxy is a different
contract: do not interchange tables or silently migrate it into `effective_peak`.
A future measured area/load table needs its own model selector and duration.
Piecewise-linear interpolation, endpoint clamp, and monotone nonincreasing
capacities are a deterministic initial implementation.

Broad priors from M1: WOLED small-window 400–2000, full-field 80–300;
QD-OLED 800–2500 and 150–350 nits. These are uncertain exploration ranges,
not guarantees or endpoints to sample independently. The [DisplayMate 2015
experiment](https://www.displaymate.com/TV_OLED_LCD_ShootOut_1G.htm)
provides historical evidence of OLED load dependence; it does not calibrate
these profiles. Channel-power fitting is needed for colored scenes.
Load response prior 10–1000 ms; thermal state 1–100 s. Keep these distinct
from response lag and static-logo dimming; present skeleton ABL is instantaneous.

## PQ/HLG targets and uncertainty

| Quantity | Numeric convention / sweep | Status |
|---|---|---|
| PQ decode endpoint | code 1 → 10000 nits | Normative absolute EOTF, not TV peak |
| PQ neutral checks | code .508078 → about 100; .751827 → about 1000 | Rounded analytic checks; use full-precision equations for tolerances |
| Source highlight tests | 1000,4000,10000 nits | Synthetic source scenarios, not assumed metadata |
| SDR comparison white | 100 nits | Project convention |
| HLG target peak Lw | 400–2000 nits; start 1000 | Prior display sweep; current profiles set 1000 |
| HLG system gamma | 1.2+.42*log10(Lw/1000): 1.033–1.326 | Normative nominal-surround formula in pinned BT.2100-2 |
| LCD HDR capacity | 700–3000 mini-LED; 300–1000 IPS example sweep | Broad prior; mode/size/thermal uncertainty unresolved |

HLG inverse OETF produces scene light; apply the luminance-dependent OOTF
before display allocation. For neutral V=.75, scene E≈.265 and Lw=1000,
gamma=1.2 gives about 203 nits. Default srgb inputs never become PQ by changing
the panel peak. Metadata/encoding belongs to the run, display capacity to the TV.
Use pinned [BT.2100-2](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-S%21%21PDF-E.pdf)
for reproducibility; the [ITU index](https://www.itu.int/rec/R-REC-BT.2100/en)
now lists BT.2100-3 (2025) in force. A version upgrade needs equation review.

Validate neutral ramps for monotonicity/black preservation/bounded peaks, OLED
1→100% windows for decreasing ceiling AND emitted highlight, and ABL-off
invariance to area. Keep absolute tests separate from preview encoding.
Open: reference shoulder policy, RGBW allocation/channel power, metadata fallback,
limiter attack/release and measured window duration/temperature.
