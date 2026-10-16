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

All parameters are **placeholders**, not calibrated TVs. HDR is scaled into a
shared SDR preview; amplified shadow rows reveal leakage. Motion rows distinguish
full hold from synthetic LCD overdrive and fixed-peak BFI probes. Macro RGB,
RGBW and staggered triangular QD-OLED apertures illustrate geometry at equal
logical pitch; their dimensions, white allocation and concentrated aperture
peaks are synthetic. See [the gallery report](docs/REPORT.md#visual-gallery-m6)
for interpretation and [fidelity research](research/m5-fidelity.md) for limits.
