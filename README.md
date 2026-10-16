# TV Display Simulator
Goal: a simulator that reproduces how different TVs/monitors (LCD VA/IPS, mini-LED FALD, OLED, QD-OLED, CRT, plasma) look, covering panel materials/subpixel structure, optics, backlight/local dimming, tone mapping/HDR, image-processing enhancements (upscaling, motion, sharpening), and temporal behavior.
Layout: docs/ (PM plan, status), research/ (research notes by workers), sim/ (code), tests/.

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
unsafe motion and unknown borders use source-hold fallback. No automatic motion
estimation or cut detection is included. Original source times preserve the
original content exactly; the last picture holds for its source duration.
The sidecar records independent source/output PTS, phase, fallback flags,
assumed lookahead and hashes, alongside linear-nit `.npy` and fixed-exposure PNG
outputs. Python callers can use `Pipeline.run_sequence` with the separate
runtime `MotionConfig` and known `LayerScene` masks/depths; TV YAMLs are unchanged.

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
