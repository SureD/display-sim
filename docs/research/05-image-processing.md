# Image processing and vendor enhancements

Research date: 2026-10-15. These are reproducible algorithm families and proposed proxies. Public vendor feature descriptions do not disclose coefficients, neural weights or exact processing order; do not advertise these proxies as exact Sony/Samsung/LG emulation.

## Decode and spatial reconstruction

Explicitly record input resolution, interlace/progressive flag, cadence, range, primaries, transfer function, chroma format and siting. Unpack limited range and reconstruct chroma with its correct sampling phase before RGB conversion. For interlaced sources use weave only on static/film-consistent regions; moving regions need motion-adaptive deinterlacing. A toy bob mode is a useful artifact baseline. Film-cadence detection and frame-rate conversion are separate stages.

A separable resampler uses `J(x,y)=Σ_mn I(m,n) k(x/s_x−m) k(y/s_y−n)`, normalized for each output sample including boundaries. State pixel-center convention: e.g. input coordinate `(x+.5)/s_x−.5`. Anti-alias before downsampling by widening/scaling the reconstruction kernel. Compare bilinear (triangular kernel), bicubic, and windowed sinc:

`k_L(x)=sinc(x)sinc(x/a)` for |x|<a, otherwise 0; `sinc(x)=sin(πx)/(πx)`.

Proposed defaults: Lanczos a=2 or 3; cubic Keys parameter −.5; antialias enabled for downscaling. [Keys, cubic convolution (1981)](https://doi.org/10.1109/TASSP.1981.1163711) is the primary interpolation reference. Preserve DC gain. Negative lobes cause ringing; clamp only at a declared stage. Test impulse/edge alignment at fractional phases, not just attractive photographs.

Use linear-light scaling as the physically interpretable reference, but permit an explicitly tagged signal-domain resampler to approximate legacy TV processing. The two give different edge brightness. Real TV scaling may combine edge-adaptive interpolation, learned reconstruction and content classification; “AI” does not specify a reproducible algorithm. Neural super-resolution can hallucinate texture. If used, pin model, weights hash, color/range conventions, tiling and temporal stabilization.

## Sharpening

Unsharp mask proxy: `J=I+k[I−G_σ*I]`. Proposed exploration k=0–1.5, σ=.5–2 output pixels; k=0 is bypass. Use thresholded detail `d·1(|d|>t)` (or soft threshold) to avoid amplifying low-level noise, t=0–.02 normalized luma as a prior. Edge-adaptive gain and overshoot limiter should be separate options.

Example overshoot metric for a 0→1 step: `max(J)−1` and `−min(J)`, plus halo width in pixels. A sharpening pass can boost MTF but cannot recover information removed by sampling. Signal-domain luma sharpening can approximate familiar TV halos; linear-light RGB sharpening has different color/brightness behavior. Record the working domain. Do not silently sharpen chroma or subpixel aperture masks.

## Spatial and temporal noise reduction

A reproducible edge-preserving baseline is bilateral filtering:

`J_p=(Σ_q w_pq I_q)/(Σ_q w_pq)`;
`w_pq=exp(−||p−q||²/(2σ_s²)) exp(−||I_p−I_q||²/(2σ_r²))`.

Use a joint color distance rather than independent-channel edges. [Tomasi and Manduchi's original paper](https://users.cs.duke.edu/~tomasi/papers/tomasi/tomasiIccv98.pdf) defines this family. Proposed sweep σ_s=.5–3 input pixels, σ_r=.005–.05 normalized signal, radius ceil(3σ_s). These are simulator knobs, not vendor settings. Distinguish random sensor noise from film grain, mosquito artifacts, banding and compression blocks: one blur filter does not faithfully model all four.

Motion-compensated temporal proxy: `J_t=(1−β)I_t+β W(J_(t−1),flow)`, β=0–.8 as a prior. Lower β on disocclusions, scene cuts and flow-inconsistent regions. Temporal NR can erase grain and create trailing ghosts. A static frame cannot characterize its temporal footprint. Deblocking can use block-boundary-aware edge thresholds; debanding needs smooth-region masks and dithering to avoid erasing actual low-contrast detail.

Quantization model: `Q(x)=round((2^b−1)x)/(2^b−1)`, b=8/10/12 as experimental signal precision. Add optional dither before quantization, seeded and with declared spatial/temporal statistics. Do not assume input bit depth equals panel native bit depth; FRC is temporal panel driving, not additional source detail.

## What vendor documentation actually establishes

| Public feature | Source evidence | Simulator representation / uncertainty |
|---|---|---|
| Sony XR Clear Image | [Sony BRAVIA 7 product documentation](https://pro.sony/en_GB/products/tuner-displays/fwd-65xr70) describes zone division/dynamic frame analysis for noise reduction | Content-adaptive spatial/temporal NR followed by reconstruction; **order and exact implementation unknown** |
| Sony Motionflow | [Sony artifact troubleshooting](https://www.sony.com/electronics/support/televisions-projectors-lcd-tvs/xbr-55x900a/articles/00153243) describes frame insertion and possible noise/artifacts | MEMC with occlusion and cut handling; model-specific BFI controls need separate evidence |
| Samsung Contrast Enhancer | [Samsung support explanation](https://www.samsung.com/my/support/tv-audio-video/2022-how-to-troubleshoot-when-the-screen-brightness-of-your-samsung-tv-changes-automatically/) describes automatic brightness/contrast adjustment | Tunable luminance remap driven by frame/region statistics; coefficients unknown |
| Learned upscaling / object or depth enhancement | Feature names alone do not identify code, training data or geometry | Optional experimental module only; no claim of vendor fidelity without controlled input/output measurements |

Recommended abstract order: decode/chroma/deinterlace → conservative NR → scale → detail enhancement → cadence/MEMC → scene analysis and tone/gamut mapping → panel drive. Actual ordering varies; make profiles choose the processing graph with explicit domains. Input/game modes can bypass NR/MEMC, change sharpening, and alter local dimming. Test each supported mode independently rather than inheriting movie-mode measurements.

A proposed contrast-enhancement proxy uses a monotonic luma LUT whose knee/contrast is driven by robust scene percentiles, with history smoothing. Bound slopes to prevent noise amplification, use hue-preserving reconstruction, and expose it as optional. Saturation/“vivid” controls can expand chroma before gamut compression, but cannot create physical color volume. Skin-tone/object-aware remaps remain uncertain without proprietary model evidence.

## Validation

Use slanted edges, impulses, zone plates, 1-pixel grids, diagonal lines, low-resolution text, chroma checkerboards and phase-shifted edges. Measure MTF/edge overshoot, alias energy, chroma alignment and DC preservation. Compare clean references with known noise/grain/compression degradations; measure residual noise **and** lost detail. For temporal filters include moving grain, occluding fine text and hard cuts; report trailing energy and cut recovery frames. Keep sharpening, NR and scaling tests separate before testing their interaction.

Open questions: which processing domains to prioritize; licensing/reference weights for optional learned models; per-mode bypass behavior; objective targets for “enhancement” when intentional preference differs from reference fidelity.
