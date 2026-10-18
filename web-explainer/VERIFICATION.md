# M12b verification

Verified using **`/usr/bin/google-chrome`**, opening the local HTML files directly. No web server or network is required.

## Numerical truth

`node web-explainer/check-models.mjs` passes:

- **10 complete local-dimming rasters** against `simulate_backlight()` and `lcd_transmit()` at five positions and two contrasts. Maximum absolute difference: **1.2207e-4 nit**, from floating-point intermediates. Probe remains outside the bright window at either screen edge.
- **48 PQ / ABL / neutral shoulder cases** against `pq_eotf()`, `abl_capacity()` and `soft_shoulder()` using all three instrument presets, four codes and four loads. Tolerance 0.001 nit; current outputs match exactly in the independent HDR comparison.
- **4 ideal pursuit calculations**, including 120 Hz / duty 0.25 / 960 px/s = 2.0833 ms / 2 pixels of full support. This is explicitly distinct from measured MPRT and the simulator's 10–90 metric.
- `python3 -m tv_sim provenance --check`: **4 baseline/angular profile records pass**. Original simulator files and settings were not edited.

Each visible calculation, moving part and live readout shares its figure's model. Research citations and P/NR caveats are in the page and [SOURCES.md](SOURCES.md).

## Anatomy geometry

`node web-explainer/build.mjs --audit` passes with **zero failing lines**:

| Figure | Physical solids | Checked poses |
|---|---:|---|
| Local-dimming light table | 51 | full left, center, intermediate, full right; same painter order |
| PQ/ABL meter | 57 | static supported assemblies, dynamic pointer paths |
| Pursuit camera | 67 | camera x = −70, 0, +70; same painter order |

Clearance, terminals, loose ends, folds, support, depth order, mid-flight intersections, self-overlap, wobble, seats, coverage and crowding all report **0**. There are no pipes, shaders or exploded assemblies; those extra workflows do not apply. The complete report is [anatomy-audit.txt](verification/anatomy-audit.txt).

## Browser interactions and line ends

The scripted checks in [browser-actions.json](browser-actions.json) pass on desktop dark (1440 px) and phone light (390 px), with reduced motion. They assert chapter order, exactly three instruments, no horizontal page overflow, full-right halo/contrast scaling, arrow-key motion, 45° angular values, scaled/clipped mapping, 5:5 cadence, full-load HDR, BFI/pursuit values, and synchronized theme tokens. Chrome console and uncaught exceptions are clean.

Both themes return:

| Figure | Floating line ends | Ends checked |
|---|---:|---:|
| Local dimming | 0 | 214 |
| PQ/ABL | 0 | 448 |
| Pursuit | 0 | 76 |

The separate default-pose checks also pass. The driven checks cover the right-edge window and changed HDR/pursuit settings. Logs: [desktop dark](verification/browser-dark.txt), [phone light](verification/browser-phone-light.txt).

Using the supplied skill scripts, the reproducible browser commands are:

```sh
CHROME_PATH=/usr/bin/google-chrome node /home/box/agent-data/workflows/anatomy/scripts/drive.mjs web-explainer/index.html --actions web-explainer/browser-actions.json --reduced --width 1440 --height 1100
CHROME_PATH=/usr/bin/google-chrome node /home/box/agent-data/workflows/anatomy/scripts/drive.mjs web-explainer/index-light.html --actions web-explainer/browser-actions.json --reduced --width 390 --height 1000
```

## Visual inspection

All retained PNGs in [shots/](shots/) were opened and read. They include desktop/phone openings, each instrument in desktop dark and phone light, local-dimming mechanism closeups at **4× in both themes**, a four-frame motion contact sheet, and pipeline/panel/angle/mapping/evidence layouts. HDR and pursuit 4× component closeups were also inspected during their individual construction checks. Long source text/readouts fit; the mobile parameter table scrolls within its own container. Offscreen/reduced-motion behavior and native keyboard controls were checked.

The page is an SDR technical visualization. The screenshots establish software layout and behavior; they do not measure host luminance, HDR capability, optical response or perceptual fidelity.
