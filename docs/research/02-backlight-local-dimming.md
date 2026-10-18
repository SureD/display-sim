# Backlight, local dimming and LCD leakage

Research date: 2026-10-15. Equations below are a proposed reference implementation unless attributed to a paper. Values labeled **prior** need per-panel fitting. Mini-LED does not imply per-pixel control; see [panel definitions](01-panel-tech.md).

## Layout and light transport

Represent zone j by a footprint/center, maximum drive, and nonnegative influence image `H_ij`: luminance at LCD pixel i with zone j at full drive and the LCD fully open. Then

`B_i(t)=Σ_j H_ij d_j(t)`, `0≤d_j≤1`.

H has units nits, d is dimensionless. Calibrate `Σ_j H_ij=B_max,i` for all zones at 1. Do **not** separately normalize each clipped edge PSF to unit energy: that silently invents edge brightness. Measure edge/corner zones or explicitly fit boundary compensation. RGB backlights require `H_ijc`; start with a fixed-spectrum scalar backlight.

| Layout | Proposed simulation sweep | Important distinction |
|---|---|---|
| Global direct/edge-lit | 1 drive | Optical nonuniformity can exist without local dimming |
| Edge local dimming | 8–32 long strips as a prior | Light-guide influence is elongated, not a small radial Gaussian |
| Conventional FALD | e.g. 8×4 to 32×18 zones as a prior | Several LEDs may share a driver |
| Mini-LED FALD | e.g. 32×18 to 96×54 zones as a prior | Exact grid must be measured; size/region variants differ |

Published anchors: [RTINGS QN90B lab review](https://www.rtings.com/tv/reviews/samsung/qn90b-qled%20) describes over 900 zones on larger sizes; this is not evidence for a particular row/column grid. A [2024 prototype paper](https://www.sciencedirect.com/science/article/abs/pii/S0143816624003889) reports a 55-inch 4K prototype with 2,304 partitions and LSF reconstruction. Neither implies all mini-LED TVs share those counts.

For a synthetic direct-lit profile, convolve the rectangular zone footprint with a two-component Gaussian scatter kernel:

`h(r)=(1−a)G(r;σ_core)+aG(r;σ_tail)`.

**Prior sweep:** core sigma 0.2–0.8 zone pitches, tail sigma 1–3 pitches, tail energy a=0–0.15. These are dimensionless modeling choices, not extracted optical constants. Store x/y sigma independently in pitch units. Integrate over pixel area; preserve tails. The [Optica PSF study (2013)](https://opg.optica.org/ao/abstract.cfm?uri=ao-52-34-8239) investigates shaped PSFs including quadratic B-splines: Gaussian optics are convenient, not established universal physics. [SSC local-dimming paper (2010)](https://globals.ieice.org/en_transactions/electronics/10.1587/transele.E93.C.1556/_p) formulates LED interaction through an LSF. [SID engineering account](https://sid.onlinelibrary.wiley.com/doi/full/10.1002/j.2637-496X.2018.tb01099.x) explains why panel-specific optical crosstalk matters.

## Leakage and pixel compensation

For neutral desired emitted luminance T_i and native leakage ε:

`L_i=B_i[ε+(1−ε)q_i]`,
`q_i=clip((T_i/max(B_i,δ)−ε)/(1−ε),0,1)`.

δ is a numerical floor, e.g. 1e−6 nits, **not** a physical black pedestal. If B=0, output is 0 and drive may be set to 0. For color, solve compensation against the backlight spectrum/channel capacities and preserve RGB ratios until gamut compression is needed.

A dark pixel beside a bright highlight cannot fall below `εB_i`. Example: B=1,000 nits, C=4,000, ε=0.00025 implies 0.25-nit dark leakage; C=1,000 implies 1 nit. This halo is produced by PSF overlap **and** finite LCD extinction. Blurring the final image is not an equivalent model: bright-pixel detail can remain sharp while dark neighbors rise. If T>B, highlights clip; suppressing B to hide a halo can crush or dim small stars/subtitles. Viewing angle changes ε and hence halo visibility.

## Algorithms worth implementing

1. Baseline: zone max RGB-normalized luminance demand. Convert it to a drive using B_max; clamp. Reconstruct B with H and compensate LCD. A zone maximum alone does not account for overlapping neighbors.
2. Robust heuristic: zone percentile (95–100%, **tuning range**) plus a controlled small-highlight protection term. Fit spatial smoothing radius 0–1 zone pitches. Percentiles can discard tiny bright objects; measure retained highlight energy.
3. Optimization: minimize `Σ_i w_i(L_i−T_i)² + λP Σ_j d_j + λS ||D d||² + λT ||d−d_prev||²`, subject to physical drive/power bounds. D is zone-grid gradient. Normalize luminance errors by chosen reference nits before comparing λ values. Alternating q/d optimization is a proposed method; do not claim it reproduces a vendor algorithm. A simpler LP minimizes drive with `H d≥T` (fully open feasibility) but does not penalize leakage in dark pixels.
4. Temporal control: `d_t=d_prev+(1−exp(−Δt/τ))(d_target−d_prev)`, with separate rise/fall τ. Explore rise 0–30 ms and fall 0–150 ms. Add delay in frames separately; τ=0 means immediate. Include scene-cut reset and optional future-frame lookahead with corresponding input latency.

Power cap `Σ_j p_j d_j≤P_budget` can alter both zone output and pixel compensation. Model backlight PWM separately from slower zone decision changes. Global thermal regulation, zone pumping and slow static-image dimming are distinct states.

## Fit and validation

Measure a moving white dot, vertical/horizontal bars, starfield, black letterbox plus subtitles, and 1/2/10/25/50/100% white windows. Repeat at different positions, HDR levels, angles and picture/game modes. [RTINGS zone precision/transitions procedure](https://www.rtings.com/tv/tests/picture-quality/lighting-zones) provides practical moving-pattern evidence, but its photographs are not radiometrically calibrated PSFs.

Fit H with isolated driven zones if service access permits; otherwise infer an **effective** H from many sparse patterns, noting LCD compensation makes the inverse problem nonunique. Separate optical spread from camera lens flare using a calibrated camera and a black occluder test. Report halo profiles in nits, highlight error, dark-region leakage, zone lag and power. Do not tune PSF sigma to a JPEG screenshot without exposure/flare controls.

Open questions: physical PSF versus effective controller spread; edge treatment; exact zone topology; game/VRR policy; whether available measurements can identify ε and H independently.
