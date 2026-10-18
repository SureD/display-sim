# CLI usage

Install the package from a checkout with `python -m pip install -e '.[dev]'`.
Every command below also works as `python -m tv_sim …`. Run a subcommand with
`--help` for all options. `python -m sim` is a deprecated compatibility entry
point; Python imports use `tv_sim`.

## Still images and Python API

```sh
tv-sim --profile generic_woled --input input.png --output output.png
tv-sim --profile generic_va_fald_miniled --input input.png --output angle.png \
  --input-eotf srgb --ambient-lux 20 \
  --viewing-angle-horizontal 45 --viewing-angle-vertical 0
```

The available profiles are `generic_ips_edge`, `generic_va_fald_miniled`,
`generic_woled`, and `generic_qdoled`. Input EOTF defaults to the profile setting;
`srgb`, `pq`, and `hlg` are supported. PNG output is a preview at the profile's
reference exposure and can clip HDR. Angles opt into a synthetic model over a
combined center-ray angle of 0–45°; zero/omitted angles retain the baseline.

```python
import numpy as np

from tv_sim import Pipeline, load_profile

pipeline = Pipeline(load_profile("generic_woled"))
encoded_rgb = np.full((72, 128, 3), 0.5, dtype=np.float32)
linear_nits = pipeline.run_linear(encoded_rgb).rgb
```

Reuse the pipeline for a continuing display history; construct a fresh instance
for an independent trial. `run()` returns an encoded uint8 preview. Optional
`ColorimetryConfig`, `ViewingAngleConfig`, `ABLDynamicsConfig`, and `MotionConfig`
are separate runtime controls. The [architecture](architecture.md) explains the
state and units.

## Validation, provenance, and gallery

```sh
tv-sim provenance --check
tv-sim validate --out reports
tv-sim gallery --out reports/gallery
```

Validation writes metrics JSON/CSV, `comparison.md`, and PNGs. The comparison is a
plausibility check against conditional published anchors, not calibration. The
preserved [M4 comparison](reports/comparison.md) and
[gallery interpretation](reports/REPORT.md#visual-gallery-m6) explain the limits.
Generated outputs remain under `reports/`; historical prose lives in
`docs/reports/`. Use a separate output directory when comparing regenerated
results with the saved artifacts.

The gallery writes an offline HTML page, shared-exposure contact sheets, profile
hashes, settings, output statistics, and a motion trace. Optional rows use
`gallery --viewing-angle` or `gallery --colorimetry`; ordinary gallery output
keeps its existing comparison protocol.

## Colorimetry and color volume (opt-in)

```sh
tv-sim --profile generic_woled --input input.png --output color.png \
  --colorimetry --source-primaries display_p3 --gamut-mapping compress
tv-sim colorimetry --out reports/colorimetry-example
tv-sim export-web --out web/data --colorimetry \
  --source-primaries bt2020 --colorimetry-output bt2020
```

Primaries are declared independently of the EOTF; PQ/HLG do not imply BT.2020.
Source white defaults to D65; `--source-white x y` preserves absolute XYZ without
chromatic adaptation. M15 supports clip or straight white-centered CIE u′v′
hue-ray compression, which does not promise constant perceived hue. The WOLED
color envelope and global ABL/M13 capacity share one limiter. Panel coordinates
and envelope constants are P placeholders; spectra and measured color-volume
fits remain NR. See [the full contract](profiles.md#colorimetry-schema-version-1-m15).

## Motion sequences (opt-in)

```sh
tv-sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc repeat --out reports/motion-repeat
tv-sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc analytic --translation-px 20 0 \
  --out reports/motion-analytic
tv-sim motion --profile generic_woled --input-frames 'clip/frame_*.png' \
  --source-fps 24 --output-fps 60 --memc mci --motion-debug \
  --preview-reference-nits 1000 --out reports/motion-mci
tv-sim motion validate --seed 7 --gallery --out reports/motion-tests
```

Quote the input glob; files use lexical order, so pad frame numbers. `off` is the
default and makes one original call per source; omit `--output-fps` in that mode.
`repeat` schedules half-open holds, `analytic` requires known translation/layers,
and `mci` is the P-only reduced-resolution block proxy. Declare cuts with
`--cut-before INDEX ...`. Unsafe/ambiguous reconstruction uses source-hold
fallback and records reasons. Traces retain independent rational source/output
PTS, original endpoints, source lookahead assumptions, and hashes. Browser
playback and static sheets do not measure perceived smoothness or TV latency.

## OLED capacity dynamics (opt-in)

```sh
tv-sim oled-dynamics --profile generic_woled \
  --abl-dynamics capacity_attack_release_v1 \
  --abl-attack-ms 100 --abl-release-ms 1000 --abl-initial cold \
  --trials one_full_one --output-fps 60 --gallery \
  --out reports/oled-dynamics/example
```

The bundled protocol loads from package data automatically. Both e-fold times
are explicit P experiment inputs. A new output directory contains demand/emitted
trials, rational PTS, capacity/luminance traces, linear arrays, and history
checkpoints. `--abl-source demand` or `emitted` selects one load source.
`--state-in`/`--state-out` require one trial and one load source; continuation
requires `--abl-initial resume`. See [the protocol contract](profiles.md#oled-dynamics-protocol-schema-version-1-m13)
for initialization and incompatible legacy controls.

## Window drive fitting (opt-in)

```sh
tv-sim fit-windows --profile generic_woled \
  --source-dataset c2_42_hdr_standard_peak --dataset-id c2_exploratory_drive_v1 \
  --level-nits 1000 --settle-ms 100 --hold-ms 100 --exploratory \
  --out reports/window-fits/c2_exploratory_drive_v1.fit.json
```

Shipped named-sample records have unknown requested amplitude/timing, so this
example explicitly records exploratory P assumptions. Known mismatches and
out-of-support lookups always fail. Fits use new exclusive `.fit.json` files
outside the package profile tree; ordinary rendering never discovers or enables
them. A small residual does not establish a calibrated TV. See [M9 matching and
no-double-limiting rules](profiles.md#m9-window-replay-and-drive-fitting).

## Web preview and explainer

```sh
tv-sim export-web
python -m http.server 8000
# http://localhost:8000/web/
```

The viewer consumes linear-nit binary16 assets from `web/data/`, with extended
WebGPU presentation and SDR fallbacks. The browser and host own final light
output. Read the [calibration and HDR protocol](../web/README.md); use the
[offline explainer](../web-explainer/index.html) for the model's mechanisms.
