# 屏幕之内 / Inside the display

Open **[index.html](index.html)** directly in a browser. No server, network, package installation, or build is required to view the page. Chinese is primary; headings have English subtitles. The theme toggle remembers its setting. [index-light.html](index-light.html) opens in light mode; `?theme=dark` and `?theme=light` explicitly select either theme.

Eight chapters follow the current simulator pipeline and research. Three Anatomy Figure instruments explain local dimming, PQ/ABL, and pursuit blur. Native controls support keyboard/touch, animations stop offscreen, and reduced-motion preferences disable idle animation. The page presents SDR diagrams, not calibrated HDR emission.

All four generic profiles are **P placeholders**. Numerical sources and historical-document caveats are in [SOURCES.md](SOURCES.md); [evidence.json](evidence.json) retains the effective parameter snapshot. The local-dimming instrument isolates the backlight/LCD stages at 128×72; the HDR meter isolates a neutral soft shoulder with manually specified APL; the pursuit rig shows ideal rectangular hold support, not measured MPRT.

## Rebuild and verify

From the repository root, with Node 20.10+ and the project's Python dependencies:

```sh
node web-explainer/build.mjs
node web-explainer/build.mjs --audit
node web-explainer/check-models.mjs
```

The build uses the vendored MIT Anatomy isometric kit and inline-kit helper. No dependency download is necessary. `--audit` checks recorded physical geometry and painter order; it is slower than the normal build. The model check compares full light-table rasters and PQ/ABL outputs against the actual Python stages, including the right-edge probe case.

Chrome screenshots and verification notes are in [shots/](shots/) and [VERIFICATION.md](VERIFICATION.md). The requested `/usr/bin/google-chrome` was used. Simulator code, runtime profiles and research were left unchanged.

## Source files

- `page.mjs`, `styles.css`, `app.js`: article, responsive design, theme, and small interactive diagrams.
- `figures/`: three instruments, their pure numerical models, and audit hooks.
- `build.mjs`: produces both offline HTML files, inlining runtime geometry helpers and figure scripts.
- `vendor/`: selected Anatomy kit files and adapted inline-kit path resolution. See [NOTICE.md](vendor/NOTICE.md).
