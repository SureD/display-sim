# Development

## Setup

The runtime supports Python ≥3.11 (no declared upper bound); the required CI
matrix covers CPython 3.11 and 3.12 on Ubuntu and macOS. Python 3.13 is also
declared in the package classifiers. Use 3.11 or 3.12 to reproduce CI.
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

The dev extra pins NumPy 2.4.6 (including its bundled type stubs), Pillow 13.0.0,
PyYAML 6.0.3, pytest 8.4.2, Ruff 0.14.1, mypy 1.18.2,
types-PyYAML 6.0.12.20250915, pre-commit 4.3.0, build 1.3.0 and Matplotlib
3.11.2. The Ruff pre-commit revision matches the dev extra. CI and `make install`
both install this same extra; runtime-only installs retain their broader lower
bounds. NumPy 2.5.4 requires Python ≥3.12, so an unpinned install selected
different NumPy versions and typing overloads on the two CI Python versions.

Matplotlib supplies the historical trace-chart backend. Normal runtime installs
can use the Pillow chart fallback; run the full golden suite with the dev extra
installed. Matplotlib is not required for simulation or ordinary previews.

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
Historical rendered values use the tolerances documented in
[the test guide](../tests/README.md). Same-machine default-path off/on comparisons,
checkpoint continuation, discrete data and rational traces retain exact parity.
Do not regenerate golden expectations to conceal an unreviewed behavior change.

To run both Linux CI environments without reusing another worktree's install:

```sh
export UV_CACHE_DIR=/tmp/m19-uv-cache
export UV_PYTHON_INSTALL_DIR=/tmp/m19-python
uv python install 3.11 3.12
for version in 3.11 3.12; do
    env_dir="/tmp/m19-py${version//./}"
    uv venv --seed --python "$version" "$env_dir"
    "$env_dir/bin/python" -m pip install -e '.[dev]'
    make PYTHON="$env_dir/bin/python" lint typecheck docs-check
    "$env_dir/bin/python" -m pytest -q
    "$env_dir/bin/python" -m build --outdir "/tmp/m19-dist-${version}"
    uv venv --seed --python "$version" "/tmp/m19-wheel-${version}"
    "/tmp/m19-wheel-${version}/bin/python" -m pip install "/tmp/m19-dist-${version}"/*.whl
    (
        cd /tmp
        "/tmp/m19-wheel-${version}/bin/tv-sim" --help
        "/tmp/m19-wheel-${version}/bin/python" -m tv_sim provenance --check
        "/tmp/m19-wheel-${version}/bin/python" -m sim --help
    )
done
```

This loop uses Bash's version-string substitution. Run it from the checkout;
use fresh environment/output paths when repeating it. The wheel smoke check uses
a separate environment outside the checkout so it cannot import editable source.
The workflow's quality job builds and force-reinstalls the wheel; the separate
test matrix also checks the editable CLI and bundled evidence from a temporary
working directory. Linux reproduction does not replace the macOS Actions jobs.

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
