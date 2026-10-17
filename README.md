# TV Display Simulator
Goal: a simulator that reproduces how different TVs/monitors (LCD VA/IPS, mini-LED FALD, OLED, QD-OLED, CRT, plasma) look, covering panel materials/subpixel structure, optics, backlight/local dimming, tone mapping/HDR, image-processing enhancements (upscaling, motion, sharpening), and temporal behavior.
Layout: docs/ (PM plan, status), research/ (research notes by workers), sim/ (code), tests/.

M12a adds a static browser comparison with a shared brightness transform,
meter-based reference-white calibration, subpixel macro views and motion playback:

```sh
python3 -m sim export-web
python3 -m http.server 8000
# Open http://localhost:8000/web/
```

There is no JavaScript build step. The viewer requests an extended Display-P3
float16 WebGPU surface, with WebGL2 SDR and Canvas2D SDR fallbacks. HDR capability
is separate from measured light output; Chrome/macOS own the final brightness
mapping. All profile parameters remain placeholders. See the
[web preview protocol](web/README.md) and [Chrome HDR research](research/m12a-web-hdr.md).
The exporter preserves linear-nit frames and provenance in `web/data/` without
changing ordinary simulator or gallery outputs.

Build the offline visual gallery and open `reports/gallery/index.html`:

```sh
python3 -m sim gallery
python3 -m pytest -q
```

The gallery compares all four generic profiles side by side on starfields,
subtitles, bright windows, gradients, a 36-frame pan with pre-roll, and a macro
subpixel crop. PNGs retain their exposure labels; `manifest.json` records profile
hashes, settings and linear-nit output statistics. Use `--out PATH` to write a
separate folder. The HTML and relative PNGs work offline.

M7 adds a 24p repeat-versus-interpolated pan comparison and exact PTS/position
traces (`memc_trace.json`). Timing from declared rational rates is **D**;
analytic translation/layer reconstruction is **P** (a synthetic model), with
vendor algorithms and calibration **NR**. Static sheets show positions, not
perceived smoothness.

MEMC defaults **off**. The still CLI, validation harness, and existing gallery
images retain their pre-M7 outputs, protected by captured golden hashes. For
numbered RGB images, opt into a separate motion experiment:

```sh
python3 -m sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc repeat --out reports/motion-repeat
# For synthetic inputs with a known 20-pixel horizontal source displacement:
python3 -m sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc analytic --translation-px 20 0 \
  --out reports/motion-analytic
```

`off` makes one original pipeline call per source; omit `--output-fps` in that
mode. `repeat` schedules half-open source holds (24→60 is 3:2; 24→120 is 5:5).
`analytic` reconstructs prepared linear-nit content before the display stages.
Declare cuts with `--cut-before INDEX ...`; cuts, missing/mismatched models,
unsafe motion and unknown borders use source-hold fallback. Original source times preserve the
original content exactly; the last picture holds for its source duration.
The sidecar records independent source/output PTS, phase, fallback flags,
assumed lookahead and hashes, alongside linear-nit `.npy` and fixed-exposure PNG
outputs. Python callers can use `Pipeline.run_sequence` with the separate
runtime `MotionConfig` and known `LayerScene` masks/depths; TV YAMLs are unchanged.

M14 adds the separate **opt-in `mci` block motion proxy**, with deterministic
NumPy matching on an estimation raster capped at 320×180, 8/16-pixel blocks,
and a declared coarse-to-fine search. Matching uses fixed-reference linear
BT.709 luma; vectors are saved in output pixels per source interval. Confidence,
forward/backward visibility, unresolved collisions, cuts and exposure changes
can trigger local or whole-picture source holds with recorded reasons.
Declared and detected cuts hold the old shot until the new source PTS.

```sh
python3 -m sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc mci --motion-debug \
  --preview-reference-nits 1000 --out reports/motion-mci
python3 -m sim motion validate --seed 7 --gallery --out reports/motion-tests
```

The isolated validation suite covers pan, two-layer occlusion, thin text, cuts,
repeating texture, large motion and flashes. It saves linear-nit sources,
analytic intermediate truth, repeat/analytic/MCI results, region masks,
PTS traces, trajectory/vector error, regional luma error and fallback switching.
The optional offline gallery compares short occlusion/text clips at one shared
exposure. These reports are separate from M4; browser playback and contact
sheets do not establish perceived smoothness or a panel refresh-rate result.

Every estimator threshold is a **P placeholder** in the versioned
[`motion_block_synthetic_v1.json`](research/measurements/motion_block_synthetic_v1.json),
checked by `provenance --check`. Use `--motion-config PATH` for a separately
labeled config or `--block-size 16` for the larger estimation blocks. The
simple cut detector can miss similar shots or misclassify large appearance
changes; thin detail and repeated texture can produce substantial fallback.
No named TV or vendor MEMC algorithm is calibrated.

The MCI CLI streams adjacent images and estimates each pair once. All motion
modes reconstruct requested content before backlight/optics/panel/ABL stages;
one persistent display history advances per output tick. To combine with M13,
add `--abl-dynamics capacity_attack_release_v1 --abl-attack-ms 100
--abl-release-ms 1000`; these taus are explicit P inputs. Both controls default
off. Existing repeat/analytic traces, default rendering and M13 experiments
retain exact captured output parity.

All parameters are **placeholders**, not calibrated TVs. HDR is scaled into a
shared SDR preview; amplified shadow rows reveal leakage. Motion rows distinguish
full hold from synthetic LCD overdrive and fixed-peak BFI probes. Macro RGB,
RGBW and staggered triangular QD-OLED apertures illustrate geometry at equal
logical pitch; their dimensions, white allocation and concentrated aperture
peaks are synthetic. See [the gallery report](docs/REPORT.md#visual-gallery-m6)
for interpretation and [fidelity research](research/m5-fidelity.md) for limits.

Check the versioned provenance sidecars without changing runtime settings:

```sh
python3 -m sim provenance --check
```

See [profile provenance](docs/PROVENANCE.md) for the evidence convention,
schema, named-sample measurement records, and strict lookup support rules.

M9 adds **opt-in window replay / drive fitting**. This example uses explicit
exploratory assumptions because the M8 C2 record has unknown requested
amplitude, primaries and timing:

```sh
python3 -m sim fit-windows --profile generic_woled \
  --source-dataset c2_42_hdr_standard_peak --dataset-id c2_exploratory_drive_v1 \
  --level-nits 1000 --settle-ms 100 --hold-ms 100 --exploratory \
  --out reports/window-fits/c2_exploratory_drive_v1.fit.json
```

Without `--exploratory`, amplitude/color/time and geometry must match known
source conditions. Known mismatches always fail. Sources outside numeric
window support, including the unlocated IPS peak, cannot be fitted.
`--fractions` selects supported windows; by default only numeric source nodes
are fitted. The source snapshot retains every `NR` node, and requested gap
interpolation remains `P`. Placeholder targets remain `P`.

The separate `.fit.json` dataset records source evidence, assumptions,
requested/rasterized areas and APL, timing, residuals, and independent `P`
internal-drive fits. Files are created exclusively, outside `sim/profiles`;
the original generic YAMLs remain the comparison baseline. Python callers
can explicitly use `sim.window_replay.load_fit` and `replay_fit` to reproduce
the saved experiments. No ordinary pipeline, validation, gallery or motion
call loads or activates these files.

Each forward trial applies the existing pipeline limits once, comparing its
final peak-center hold luminance with the target. The target never becomes
an extra ABL/output limiter. These fits identify a proposed per-window drive
normalization, not a calibrated TV or arbitrary-content response. See the
[M9 contract](docs/PROVENANCE.md#m9-window-replay-and-drive-fitting) for the
amplitude, color, time and no-double-limiting rules.

M10 adds an **opt-in viewing-angle model** with signed horizontal and vertical
runtime angles. For a still preview and an offline comparison:

```sh
python3 -m sim --profile generic_va_fald_miniled --input in.png --output out.png \
  --viewing-angle-horizontal 45 --viewing-angle-vertical 0
python3 -m sim gallery --viewing-angle --out reports/gallery-angle
```

`--viewing-angle` is an alias for the horizontal option. Supplying either
angle opts in; omitting both, or setting both to zero, preserves the original
pipeline exactly. Python callers use
`Pipeline(profile, viewing_angle=ViewingAngleConfig(enabled=True, horizontal_deg=45))`
with `ViewingAngleConfig` from `sim.viewing_angle`.

LCD transmission separates angular white gain, emitted-black leakage gain,
and RGB gray-response exponents, so contrast loss and gamma/color wash-out
can be varied independently. Emissive panels use RGB emission gains only.
Every shipped angular value is a **P placeholder**, with current-profile
full fits, IPS leakage fits, and OLED measured gains/spectra **NR**. The
separate versioned `*.angular.yaml` records are checked by the provenance
command; the original TV YAMLs retain all runtime values.

The synthetic model supports a combined angle of 0–45° and rejects
extrapolation. Its center ray uses `cos(theta) = cos(horizontal)*cos(vertical)`;
unsigned symmetry and azimuth independence are P assumptions. It does not
predict per-pixel angles or IPS corner glow. Angular terms precede the existing
HDR/ABL and temporal stages; emitted-load ABL can therefore interact with them.
The gallery isolates the mechanisms with a labeled fixed-backlight 100-nit
SDR experiment, shared exposure, and on-axis versus +45° pairs for all four
profiles. Its new sheet is included only with `--viewing-angle`; ordinary
gallery, validation, MEMC-off and M9 replay defaults retain their goldens.
See [angular provenance](docs/PROVENANCE.md#angular-schema-version-1-m10).

M13 adds **opt-in OLED capacity attack/release**, default **off**. The runtime
config stays outside the TV profiles; both e-fold times must be supplied
explicitly. For a synthetic black → 1% → full-field → 1% → black history:

```sh
python3 -m sim oled-dynamics --profile generic_woled \
  --abl-dynamics capacity_attack_release_v1 \
  --abl-attack-ms 100 --abl-release-ms 1000 --abl-initial cold \
  --protocol research/measurements/oled_dynamics_synthetic_v1.json \
  --trials one_full_one --output-fps 60 --gallery \
  --out reports/oled-dynamics/example
```

All numbers in this versioned protocol are **P placeholders**; measured
dynamics and calibration remain **NR**. The command runs independent demand
and emitted load trials with distinct IDs; `--abl-source demand` or `emitted`
selects one. It saves rational PTS, per-tick capacity/luminance traces,
onset/late/recovery linear-nit arrays and complete history checkpoints. The
optional offline gallery uses one fixed exposure across every frame.
Other protocol trials cover black gaps, 1/2/5/10/25/50/75/100% steps and
identical probes following different histories. Existing M4 reports are unchanged.

Python callers use `Pipeline(profile, abl_dynamics=ABLDynamicsConfig(...))`
with `ABLDynamicsConfig` from `sim.abl_dynamics`. Each `display_content` tick
updates one global nit-capacity state and uses it for the existing HDR shoulder.
`cold` starts at the profile peak; `settled_first_tick` erases the first
capacity transient; `explicit` requires `initial_capacity_nits`. Display black
pre-roll through the same pipeline to initialize pixel history and recover
capacity. `checkpoint()` saves full history; a fresh pipeline configured with
`initial="resume"` uses `restore_checkpoint(data)` for exact continuation.
CLI `--state-in/--state-out` require one trial and one load source, and resume
requires `--abl-initial resume`. New artifacts never overwrite existing files.

Active mode rejects nonzero legacy APL smoothing, backlight tracking and
weighted-nit power budgets, unsupported panels/tone mappers, and M9 v1 fit
composition. It holds updated capacity constant during each tick's temporal
exposure, an endpoint approximation. Thermal/static-image controllers and
electrical watts remain unmodeled; no named TV is calibrated. See the
[design](research/m11-oled-dynamics.md) and
[protocol provenance](docs/PROVENANCE.md#oled-dynamics-protocol-schema-version-1-m13).

Disabled rendering and histories retain exact pre-M13 goldens, including
M10 galleries and web-export frame/asset bytes. Export manifests retain truthful
source-code hashes, so their `implementation_sha256` metadata changes with code.
