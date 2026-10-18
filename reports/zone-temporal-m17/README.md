# Synthetic LCD zone temporal dynamics — M17

[Open the offline gallery](index.html). All constants and stimulus choices are
**P** placeholders; arrays, PTS and numerical results are **D under P assumptions**.
Matched measured controller constants and named-TV calibration remain **NR**.
The [research note](../../docs/research/m17-zone-temporal.md) explains the mechanism,
source limits and required calibration conditions.

Generate into a fresh directory with this worktree's installed package:

```sh
PYTHONUSERBASE=/tmp/m17-user python3 -m tv_sim zone-temporal \
  --attack-s 0.05 --release-s 0.15 --out reports/zone-temporal-m17-fresh
```

The saved run uses the same command with `--out reports/zone-temporal-m17`.
Existing output directories reject. The package's versioned
[protocol](../../src/tv_sim/data/measurements/zone_temporal_synthetic_v1.json)
is copied into [protocol.json](protocol.json); its demonstration taus do not
silently configure the runtime. The two time constants are explicit seconds.

This comparison uses the unmodified generic VA FALD optical grid, PSF, native
contrast and static HDR/ABL settings. Each clip has independent off/on histories,
128×72 pixels (**P**), 120 output ticks at 60 Hz (**P**), and a 2-second duration
(**P**). Input is prepared float32 BT.709 RGB in nits, so decoding and spatial
processing are bypassed. The copied experiment profile sets ambient lux,
pixel-response tau, overdrive and pursuit motion to zero, BFI duty to one and
integration samples to one (**P isolation policies**). The original profile is
unchanged. The off arm omits the new configuration entirely; the on arm starts
cold, with attack 0.05 seconds and release 0.15 seconds (**P**), no slew cap and
no automatic cut detection. No synthetic event is declared as a scene cut.
`--pixel-response profile` runs a separately identified LCD-response cascade.
The [manifest](manifest.json) retains the effective profile, original profile
hash, explicit overrides, controller identity and source fingerprints.

All primary sheets share one sRGB exposure: 1000 nits maps to white (**P**).
The separately labeled shadow sheets share a 1-nit reference (**P**) across
both arms and all fixtures; their highlights and the 2-nit scene clip to white.
Neither transform establishes physical output on the viewer's display.

| Clip / inspectable output | Off → on result (**D under P**) |
|---|---|
| [Moving object](moving_object/contact.png), [amplified shadows](moving_object/shadows.png), [trace](moving_object/trace.png) | Maximum above-threshold rear trail 10 → 22 pixels; integrated rear halo 8.357650 → 24.318071 nit-pixel-seconds. Positive on-minus-off temporal residual reaches 21 pixels and 16.067170 nit-pixel-seconds. Foreground light retention 0.557230 → 0.498400. |
| [APL up/down](apl_step/contact.png), [trace](apl_step/trace.png) | On-arm rise command/output settling 0.15 seconds; fall command settling 47/60 seconds, while compensated output settles at the first 1/60-second tick. Isolated command and output directional overshoot are zero. |
| [Flashing highlight](flashing_highlight/contact.png), [amplified shadows](flashing_highlight/shadows.png), [trace](flashing_highlight/trace.png) | Zone-command total variation 89600 → 25044.271384 nits. Foreground light retention 0.543213 → 0.414582: reduced command modulation costs highlight energy. |
| [Subtitle](subtitle/contact.png), [amplified shadows](subtitle/shadows.png), [trace](subtitle/trace.png) | Unchanged black-bar probe peak-to-peak excursion 0.122546 → 0.122555 nits; the smoothing changes onset/decay but does not reduce this whole-clip range. Foreground light retention 0.745155 → 0.713779. |

Trail lengths use a 0.05-nit threshold (**P**) in the known object's height band,
behind its current rear edge, excluding its foreground mask. Each arm subtracts
an independent matched black-only history with the same profile, initialization
and clocks. The temporal residual is the positive difference of those halo maps.
Energy sums positive excess Y times tick duration over the trailing region; it
is not joules and includes no perceptual visibility model. The reported maximum
is restricted to ticks with the object present; off-screen afterglow remains
visible in the saved late samples and arrays.

Settling means the first tick endpoint entering a 5%-of-target band (**P**) and
remaining there through the rest of the known hold. A short clip can report
“not reached”; it never substitutes clip duration or infers sub-tick accuracy.
Command and output targets are distinct. The output reference is the matched
off-arm final tick of that hold, with no general claim of equilibrium.
Overshoot measures excursion past a held target in the transition direction;
slow-release above-target residual is not mislabeled a falling-step overshoot.
The first-order controller has no ringing term. Total variation sums absolute
successive zone-command differences. Generic probe peak-to-peak values include
content changes; only the unchanged subtitle probe is labeled a pumping proxy.
These are not PWM or perceptual flicker measurements.

Each fixture directory retains full per-zone targets, before/after state,
branch/reset/slew decisions and rational PTS in `trace.json`, probe summaries in
`probes.csv`, metric definitions/results in `metrics.json`, and primary/shadow
contact sheets plus a standalone trace plot. The reproducible `linear.npz`
archives contain input/output RGB and foreground masks; moving-object archives
also retain both matched black histories. These large arrays stay gitignored.

The primary and amplified moving, APL, flashing and subtitle sheets and their
trace curves were visually inspected during generation. The chosen samples show
onset, active motion/hold, offset and late residuals: the moving shadow sheet
shows the elongated rear halo; flashing and subtitle sheets show light remaining
after content switches off; the APL sheet shows a dimmed leading rise. The main
exposure suppresses very low-level halos, as expected. Static sheets do not
establish perceived temporal smoothness on a host display.

A separately identified temporary moving-object comparison was also generated
with the same explicit taus and `--pixel-response profile --fixtures
moving_object --out /tmp/m17-pixel-response`. Its ordinary 8-ms profile tau
(**P**) was retained and its sheets inspected. Rear-trail length was 10 → 23
pixels and rear energy 1072.486298 → 1157.917249 nit-pixel-seconds (**D under P**),
including emitted-RGB pixel persistence. Those totals cannot be attributed to
backlight leakage alone or compared as a calibrated physical halo measurement.
The primary retained dataset isolates zone dynamics; the separate mode preserves
the ordinary pixel-response cascade and records it explicitly in its manifest.
