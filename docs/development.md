# Development

## Setup

Use Python 3.11 or 3.12 to match CI. The package also declares Python ≥3.11.
From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pre-commit install
```

`make install` installs the editable package with its pinned development tools
into the active environment. If a managed environment requires user installs,
use `python3 -m pip install --user -e '.[dev]'` and ensure the user scripts directory
is on `PATH`. NumPy, Pillow, and PyYAML are the runtime dependencies. The src
layout requires installing the package before invoking the CLI or Python API;
loading bundled profiles/protocols does not depend on the working directory.

The dev extra pins Matplotlib to the renderer used by historical trace-chart
goldens. Normal runtime installs can use the existing Pillow chart fallback;
run the full golden suite with the dev extra installed so its chart backend is
reproducible. Matplotlib is not required for simulation or ordinary previews.

## Checks and tests

```sh
make format
make lint
make typecheck
make test
make docs-check
pre-commit run --all-files
```

Ruff handles formatting and E/F/I/B/UP lint rules. Mypy checks the package at the
pragmatic strictness configured in `pyproject.toml`; public APIs carry annotations.
Pytest configuration and markers live in that same file. See [test layers](../tests/README.md)
for unit, parity/golden, end-to-end, and `slow` tests.

```sh
python -m pytest -q
python -m pytest -q -m 'not slow'
python -m pytest -q -m slow
```

The full suite, including slow tests, is required for a model or packaging change.
CI runs lint/type checks plus tests on Linux and macOS with Python 3.11/3.12.
Platform-sensitive numerical checks use the documented tolerance while exact
parity remains required for byte-stable outputs on the reference platform.
Do not regenerate golden expectations to conceal an unreviewed behavior change.

## Regenerate inspectable artifacts

Tracked PNG/HTML/JSON artifacts provide reviewable examples. Cache files,
virtual environments, full-precision generated `.npy`/`.npz` arrays, and bulk
web frame transport are ignored; versioned test fixtures remain in `tests/`.
Run from the checkout root:

```sh
tv-sim validate --out reports
make gallery
tv-sim colorimetry --out reports/colorimetry-m15
tv-sim subframe --out reports/subframe-example
tv-sim motion validate --seed 7 --gallery --out reports/motion-m14
tv-sim export-web --out web/data
```

For comparison runs, choose a new `--out` path to preserve saved evidence.
Experiment runners that create exclusive outputs require a fresh directory.
The [motion artifact notes](../reports/motion-m14/README.md) and
[colorimetry notes](../reports/colorimetry-m15/README.md) record their protocols
and numerical interpretation. Regenerated manifests include implementation
fingerprints, so source refactoring changes those identity fields even when
rendered arrays/assets and substantive traces match exactly.

The explainer has no browser build dependency installation. With Node 20.10+
and the editable Python package:

```sh
node web-explainer/build.mjs
node web-explainer/build.mjs --audit
node web-explainer/check-models.mjs
node --test web/tests/mapping.test.mjs
```

The optional [browser smoke test](../web/tests/README.md) needs Chrome. Native
Mac EDR emission requires a real HDR Mac and luminance meter; a headless browser
cannot establish emitted nits.

## Package and release

1. Update the version and supported-Python metadata in `pyproject.toml`; document
   user-visible changes under `Unreleased` in [CHANGELOG.md](../CHANGELOG.md).
2. Run all checks and compare default `validate`, `gallery`, and affected opt-in
   artifacts with the reviewed baseline. Validate profile/protocol provenance.
3. Build a source distribution and wheel with `python -m build`; inspect that
   `tv_sim/profiles/` and `tv_sim/data/measurements/` are included.
4. Install the wheel into a fresh environment outside the checkout. Smoke-test
   `tv-sim --help`, `python -m tv_sim --help`, `tv-sim provenance --check`, and
   representative validation/gallery commands there.
5. Prepare the release notes and artifact evidence for PM review. The PM owns
   final commit organization, tags, publishing, and integration authorization.

Historical `sim/` and `research/` locators embedded in unchanged provenance data
are preserved evidence. Their current locations are documented in
[profiles](profiles.md#historical-paths-and-packaged-data).
