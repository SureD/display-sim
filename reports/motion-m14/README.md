# M14 synthetic motion artifact comparison (P)

Open [index.html](index.html) for repeat / analytic / block-MCI contact sheets and PTS-based playback. This experiment uses seed 7, 128×72 linear RGB, six 24-fps sources per fixture and fifteen 60-fps output ticks (0.25 seconds). Every preview uses the same 1000-nit reference. Browser playback is illustrative; it does not validate panel cadence or perceived smoothness.

All settings are P placeholders. Timing and errors are D calculations under that experiment. Named-TV calibration, vendor algorithms, perceptual soap-opera scores and measured artifact distributions remain NR.

| Fixture | Repeat trajectory MAE (px) | MCI trajectory MAE (px) | MCI fallback | Boundary Y MAE (nits) | Disoccluded Y MAE (nits) | Decision-changing ticks |
|---|---:|---:|---:|---:|---:|---:|
| pan | 1.668 | 0.664 | 29.0% | 4.640 | 7.517 | 9 |
| occlusion | 2.076 | 1.868 | 21.2% | 3.636 | 41.063 | 9 |
| text | 1.655 | 1.610 | 55.9% | 5.652 | 19.054 | 9 |
| cut | 0.835 | 0.584 | 67.0% | 5.213 | 11.831 | 6 |
| repeating_texture | 1.655 | 1.655 | 100.0% | 10.109 | 1.443 | 0 |
| large_motion | 25.627 | 25.627 | 60.0% | 35.171 | 17.117 | 1 |
| flash | 0.407 | 0.259 | 45.4% | 3.623 | 15.087 | 3 |

Scores use intermediate ticks with a right endpoint, excluding the final hold. Trajectory error is the weighted centroid of the actual rendered colored marker versus analytic truth; counts of missing/spurious visible markers and valid trajectory samples are saved separately. Large motion has only four visible-marker samples. Vector endpoint error is a separate diagnostic. Region masks backproject the current material point to test left-source visibility; boundary and disoccluded metrics partition the remaining interior. Switching counts track changes in fallback decisions at intermediate ticks within a shot, rather than changes caused by exact originals, tail holds or cuts.

The final sheets were visually inspected: MCI leaves a small foreground edge chip and isolated red fragments in the occlusion clip, plus residual stepping around thin text. The pan improves over repeat, but this proxy retains substantial error on newly revealed backgrounds. Repeating texture uses full source holds. Large motion exceeds the search range and invokes conservative confidence holds; the proxy cannot reliably determine the true magnitude of unmatchable motion. No false cuts were recorded in these fixtures; that is not a general cut-detection guarantee.

The artifact-generation interval from first source write through the final sidecar write was **68.86 s**, excluding process startup. This is measured offline compute/output time on this run, separate from the assumed **1/24 s (41.667 ms)** adjacent-source lookahead recorded per tick. Measured TV latency remains NR; no real-time throughput is claimed.

Reproduce into a new directory:

```sh
python3 -m sim motion validate --width 128 --height 72 --source-count 6 \
  --seed 7 --gallery --out reports/motion-m14-rerun
```

[motion-validation.json](motion-validation.json) embeds the protocol, estimator settings, source/runtime hashes, all metrics and artifact paths. Each fixture folder contains source, analytic truth, repeat/analytic/MCI float32 nit arrays, fixed-exposure PNGs, region masks, pair vector/confidence/visibility/reason maps, per-tick fallback masks/reasons and a rational PTS trace. These are requested-content diagnostics before display stages and do not extend M4 reports. The optional Python `profile` argument saves an additional display sequence with one persistent pipeline per comparison mode and one physical update per output tick.
