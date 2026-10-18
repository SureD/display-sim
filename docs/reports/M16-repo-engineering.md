# M16: repository engineering

Date: 2026-10-18. Branch: `codex/m16-repo-engineering`.

M16 turns the M0–M15 research implementation into an installable, documented
Python repository. Simulation arithmetic, defaults, runtime profile values and
versioned evidence bytes are preserved. No git metadata was written; all work
is left for PM review and commits. Files were moved through the filesystem as
required by this sandbox; git can detect renames when the PM stages them.

## Changes

- Installable `src/tv_sim` package, `tv-sim` console entry point and
  `python -m tv_sim`; a small installed `python -m sim` compatibility shim.
- Bundled profiles and synthetic protocols, with documented loading that works
  outside the checkout. Historical source locators in evidence records retain
  their original bytes; current documentation explains their path aliases.
- Documentation entry point, architecture, CLI guide, profile schema,
  development/release guide, five ADRs, archived reports and a chronological
  M1–M15 research index. README links to retained gallery PNGs and both web apps.
- MIT license (SureD), contribution guide, milestone changelog, editor settings,
  Make targets, pinned dev tools, pre-commit configuration, issue/PR templates,
  and Linux/macOS CI on Python 3.11/3.12.
- Ruff formatting and E/F/I/B/UP linting, public API annotations, practical mypy
  checks, module documentation, redundant import/dead-code cleanup, and a
  documented package API. Test layers and slow/golden/e2e markers are explicit;
  the default test run includes slow tests.
- Portable golden report comparisons authenticate captured fixtures and compare
  numeric fields within tight tolerances. Stable pixels/arrays remain exact;
  only renamed metadata labels are normalized. No simulation golden hashes are
  regenerated to accommodate changed behavior.
- Removed 32 regenerable FP16 web transport files (27,328,512 bytes). No tracked
  bytecode or NumPy arrays existed. Small reports, gallery PNGs, metadata and all
  test fixtures are retained. Run `tv-sim export-web --out web/data` to regenerate
  browser transports; see [development](../development.md) for other artifacts.

## Validation

The full post-migration suite passes, including every existing test and eight
new checks that protect the portable numeric metadata comparisons.

| Final command | Exact result |
|---|---|
| `python3 -m pytest -q --tb=short` | `1145 passed in 204.03s (0:03:24)` |
| `python3 -m ruff check .` | `All checks passed!` |
| `python3 -m ruff format --check .` | `92 files already formatted` |
| `python3 -m mypy` | `Success: no issues found in 49 source files` |
| `python3 scripts/check_docs.py` | `Documentation links: all local targets and anchors passed` |

The tool commands used `PYTHONUSERBASE=/tmp/m16-user` as explained below; the
full test run included all slow/golden/e2e tests, with no exclusions or skips.

Confirmed artifact and packaging checks:

- Original baseline: `1137 passed in 845.42s (0:14:05)`.
- Mypy: `Success: no issues found in 49 source files`.
- Ruff: `All checks passed!`; format check: `92 files already formatted`.
- Documentation: all local link targets and anchors pass
  `python3 scripts/check_docs.py` (the `make docs-check` command).
- `tv-sim validate`: all 15 output files checked against the pre-M16 capture;
  14 are byte-identical, and the Markdown comparison differs only in CLI/research
  path labels.
- `tv-sim gallery`: all 11 output files checked; eight PNGs, the manifest and
  motion trace are byte-identical. HTML differs only in CLI/documentation labels.
- `tv-sim export-web`: all 32 FP16 assets are byte-identical to the committed
  originals. The retained sample manifest now records current source paths and
  implementation hashes; the large binary files remain removed from the tree.
- Build and installed-wheel audit: 11/11 checks passed outside the checkout,
  including all four profiles, still rendering, console/module CLIs, deprecated
  shim, provenance, MIT metadata, 16 YAML resources, three JSON resources and
  `py.typed`. The source distribution includes every test module and all seven
  fixture files. All 19 bundled resources and all five original golden fixture
  files retain their original bytes.
- Browser code: nine mapping tests pass; explainer build/audit passes; its model
  check passes ten local-dimming rasters (maximum error `1.22e-4` nit), 48
  PQ/ABL/shoulder cases and four pursuit cases.

Pre-commit configuration validation passes. Hooks were not installed because
this task prohibits writing git metadata. This container has no `make` binary;
all verification used the equivalent Python commands from the Makefile directly.

The supplied environment runs Python 3.13.5, NumPy 2.5.4 and Pillow 13.0.0.
Pinned tools were installed using `pip install --user` with
`PYTHONUSERBASE=/tmp/m16-user`, a writable user base inside this sandbox. CI
provides the requested Python 3.11/3.12 and macOS coverage; those remote jobs
cannot be claimed as executed locally.

The first migrated full run had 1141 passing tests and four chart-only failures:
the temporary user base hid the original optional Matplotlib installation and
selected the existing Pillow fallback. All numeric traces, simulation arrays and
display previews in those tests matched. The dev extra now pins Matplotlib
3.11.2, the original chart renderer, so historical plot goldens remain exact and
CI installs the same backend. No plot golden was excluded or rewritten.

Formatting and relocation change implementation hashes in export manifests and
checkpoints. Generator labels and source paths also describe the new package.
These metadata changes are expected; rendered values and pixel assets are the
parity contract.

## Suggested PM commit split

1. Tooling/configuration: metadata, license, editor/ignore settings, Makefile and
   pinned development dependencies.
2. Ruff formatting: mechanical formatting/import ordering, isolated for review.
3. Lint fixes: redundant imports, unused names and safe simplifications.
4. Typing/public API: annotations and mypy fixes with arithmetic preserved.
5. Docs reorganization: README, guides, ADRs, contribution guide, changelog and
   archived reports.
6. Research move/index: historical research notes, chronological index and links.
7. Src layout migration: filesystem renames, import/entry-point/resource paths,
   compatibility shim and portable golden metadata normalization.
8. CI and hygiene: workflows, templates, pre-commit, test documentation/markers,
   portable numeric goldens and removal of generated web binaries.

Because the working tree contains the combined result, the PM may use selective
staging or construct intermediate commits when splitting mechanical formatting
from renames. Do not update scientific fixtures or runtime parameters merely
to make a staging split pass.
