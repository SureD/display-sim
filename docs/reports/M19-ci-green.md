# M19 — portable CI and historical golden checks

Verified 2026-10-19, Asia/Shanghai, on branch `codex/m19-ci-green`, based on
M18 main `d633a90`. Both Linux CI-equivalent runs pass all **1,700 tests**:
the original 1,680 tests plus 20 regression checks for historical comparisons.
Changes remain in the working tree for PM review; nothing was committed or
pushed. macOS Actions verification remains an integration check, not a local
verification claim.

## Evidence and root causes

The public GitHub API exposed runs
[#1](https://github.com/SureD/display-sim/actions/runs/39086749795),
[#2](https://github.com/SureD/display-sim/actions/runs/39097095822), and
[#3](https://github.com/SureD/display-sim/actions/runs/39107789890).
All Python 3.11 matrix jobs failed the quality step. Python 3.12 reached pytest;
the macOS jobs failed tests, while Linux passed runs #1/#3 and failed #2.
Downloading job logs returned HTTP 403, “Must have admin rights to Repository.”
The detailed diagnosis below therefore comes from isolated local reproduction;
the precise macOS/earlier-run artifact differences could not be inspected.

### NumPy's bundled typing differed between Python environments

Ruff 0.14.1 and mypy 1.18.2 were already pinned. Runtime NumPy was unbounded
above its `>=1.26` requirement. Original editable-dev installs resolved:

| Interpreter | NumPy | mypy 1.18.2 on original source |
| --- | --- | --- |
| CPython 3.11.17 | 2.4.6 | 9 errors in 3 files |
| CPython 3.12.15 | 2.5.4 | No errors |
| CPython 3.12.15, switched to NumPy 2.4.6 | 2.4.6 | The same 9 errors |

Installed package metadata declares NumPy 2.4.6 compatible with Python ≥3.11
and NumPy 2.5.4 with Python ≥3.12. Holding Python and mypy fixed isolates the
cause to NumPy's versioned bundled stubs, rather than a changed mypy release or
interpreter semantics. M18 added five errors in `subframe_metrics.py` to the
four reported earlier in `block_motion.py` and `zone_temporal_experiment.py`.

The fixes convert the ranked motion cost to a Python `float` and annotate
dimension-preserving float64 reductions with justified `NDArray[np.float64]`
casts. A generic `np.ndarray` cast would itself be redundant with newer stubs;
the precise casts pass both NumPy 2.4.6 and 2.5.4. No blanket ignores were added.
The configured final check covers 59 source/script files; the original-source
comparison above checked the 58 package source files.

The dev extra now pins NumPy 2.4.6, Pillow 13.0.0 and PyYAML 6.0.3, alongside
the existing tool pins. Runtime-only lower bounds remain unchanged. CI and
`make install` already install the same dev extra, and the Ruff hook revision
already agrees with that extra, so workflow/hook changes were unnecessary.
The package requires Python ≥3.11 without an upper bound; the required CI
matrix is Python 3.11/3.12 on Ubuntu/macOS, with 3.13 also declared in metadata.

### Whole-report hashes hid one-step numerical differences

The six reported M14 validation tests reproduced as six failures on Python
3.11, while the original Python 3.12 installation passed all six. Contrary to
the initial PNG-encoder hypothesis, every rendered artifact matched in this
reproduction: only canonical `motion-validation.json` differed.

With NumPy **held at 2.4.6**, Python 3.11 versus 3.12 differed in exactly eight
`summary.*.regions.*.linear_luma_mae_nits` fields. Each difference was one
float64 ULP. All other substantive report fields matched, including per-frame
inputs to the aggregation. Python 3.12's documented change to float `sum`
explains this result. See [Python's built-in `sum` documentation](https://docs.python.org/3.12/library/functions.html#sum).

One boundary region used these identical error sums on both interpreters:

```text
926.5717080539703, 1818.8903158205032, 483.1338692998886,
1244.2076047525404, 873.1081215684891, 1606.63159009037
pixels = 1761
3.11 sum: 0x1.b288b0fc88db9p+12 -> MAE 3.9480654228198535
3.12 sum: 0x1.b288b0fc88db8p+12 -> MAE 3.948065422819853
math.fsum on both: 0x1.b288b0fc88db8p+12
```

Disabling AVX512F/AVX2/FMA3 on the original Python 3.12 environment still
passed all six tests. No local evidence establishes BLAS, libm or PNG encoding
as the cause of those six failures. Such platform sensitivity remains a reason
to avoid historical hashes of rendered floats and compressed images, but is
not presented here as a proven diagnosis of inaccessible macOS logs.

### Additional historical environment coupling

The expanded audit also found four failures in enabled M13 experiment
comparisons: canonical checkpoints embedded `identity.numpy_version=2.5.4`,
while the pinned environment correctly emitted `2.4.6`. Experiment manifests
embed the same environment identity under `pipeline_identity`. All other
substantive state matched. Historical comparisons now verify the actual
identity equals `numpy.__version__`, while accepting that the captured version
describes another environment. Actual checkpoint checksums are verified before
canonical comparison; runtime checkpoint compatibility checks are unchanged.

## Golden audit and comparison rules

Audited SHA/digest and exact-array comparisons across the complete suite,
including M7/M9/M10, M13/M14/M15 and M17/M18. Historical comparisons changed in
the MEMC, OLED-dynamics, M14, colorimetry and viewing-angle gallery modules.
The nine M17/M18 zone/subframe modules contain no machine-captured float/PNG
hash baselines: their exact checks compare same-host runs, checkpoints,
independent calculations, explicit endpoints or rational clocks. Those checks
remain unchanged; their targeted suite passed 535 tests on each interpreter
before the complete runs.

Historical rendered references are decoded and compared as follows:

| Value | Declared tolerance |
| --- | --- |
| float32 arrays and motion maps | Relative `2e-6`, absolute `1e-7` |
| float64 arrays and motion maps | Relative/absolute `1e-12` |
| PNG / explicitly identified uint8 previews | One code value per channel |
| FP16 web transport | One adjacent finite FP16 code |
| Named derived M14 image/trajectory metrics | Relative/absolute `1e-12` |

Shapes, dtypes, NPZ member names, Boolean masks, integer reason codes, rational
traces, profile bytes and stable JSON metadata remain strict. Web transport
statistics use relative `1e-3` / absolute `1e-7` to reflect FP16 precision;
maximum quantisation-error statistics instead use absolute
`max(1e-7, peak_nits * 2e-6)`. Existing M16 numerical JSON/CSV and gallery
comparisons retain their previous tolerances.

Hashes embedded in reports/web manifests are linked only when they identify a
rendered payload. Each current hash first authenticates its actual file bytes;
the corresponding decoded values then compare with the historical reference.
Protocol/profile hashes, settings, evidence labels, schema, counts and rational
timing do not acquire numerical tolerance. Ordinary digest dictionary equality
is unchanged, preserving same-machine omitted/explicit-off identity checks.

The new fixture stores 1,074 authenticated references in 4,879,522 bytes.
The original baseline JSON files were not changed. Initial values were recovered
only when their raw-array or canonical file-payload hashes matched the existing
historical digests, using the Python 3.13/NumPy 2.5.4 capture environment and
preserved matching outputs. Missing NPZ/report/source references were recovered
from preserved outputs by the same hash check. At test time every reference
must authenticate again before decoding; a separate test checks archive
integrity and coverage of all historical rendered-file records.

Fixture SHA-256:
`eeba7a32cede96e8d250359831432139c75dd1b27842c3c598cbfad21b5a8fc5`.
The exact fixture path is exempted from the generated-NPZ ignore rule.

The helper module now has 28 tests, including 20 added checks for strict
metadata/discrete values, permitted roundoff, rejected material drift,
reference authentication, linked hashes and adjacent FP16 boundaries.
The first full verification exposed a reference-loader bug: identical bytes
can describe Boolean and uint8 arrays. The corrected loader authenticates the
bytes and interprets them using the historical record's exact shape/dtype;
a regression test protects this case. No simulation behavior was changed by
that correction.

## Final verification

Host: Linux x86_64, kernel `6.12.94+`, glibc 2.41. Interpreters installed under
`/tmp/m19-python`; editable environments `/tmp/m19-py311` and `/tmp/m19-py312`.
No earlier milestone environment was reused. This host lacked `make`; Debian
GNU Make 4.4.1 was extracted under `/tmp/m19-make` without a system install.
The Makefile and CI recipe themselves were unchanged.

Both dev environments used NumPy 2.4.6, Pillow 13.0.0, PyYAML 6.0.3,
pytest 8.4.2, Ruff 0.14.1, mypy 1.18.2, Matplotlib 3.11.2,
types-PyYAML 6.0.12.20250915, pre-commit 4.3.0 and build 1.3.0.

| Check | CPython 3.11.17 | CPython 3.12.15 |
| --- | --- | --- |
| `ruff check .` | All checks passed | All checks passed |
| `ruff format --check .` | 111 files already formatted | 111 files already formatted |
| `mypy` | No issues, 59 source files | No issues, 59 source files |
| `scripts/check_docs.py` | All local targets/anchors passed | All local targets/anchors passed |
| `tv_sim provenance --check` | 4 profiles; all listed v1 schemas OK | 4 profiles; all listed v1 schemas OK |
| Full `pytest -q` | **1700 passed in 373.13s** | **1700 passed in 368.07s** |
| `pip check` | No broken requirements | No broken requirements |
| Build sdist + wheel | Both built successfully | Both built successfully |
| Installed wheel, outside checkout | All four smoke commands passed | All four smoke commands passed |

Quality commands used `make PYTHON=/tmp/m19-py311/bin/python lint typecheck
docs-check` and the corresponding Python 3.12 executable. Full pytest included
all slow tests, with distinct `/tmp/m19-full-final-py311` and
`/tmp/m19-full-final-py312` temporary roots. See the
[development reproduction recipe](../development.md#checks-and-tests).

Wheels were force-installed into separate `/tmp/m19-wheel-3.11` and
`/tmp/m19-wheel-3.12` environments. From `/tmp`, each passed `tv-sim --help`,
`python -m tv_sim --help`, `python -m tv_sim provenance --check`, and
`python -m sim --help`. The compatibility shim emitted its expected deprecation
warning. Imports resolved under each wheel environment's `site-packages`, not
the checkout. Each wheel contains 16 profile files, five protocol files and
`py.typed`. Runtime-only wheel installs selected NumPy 2.4.6 on Python 3.11 and
2.5.4 on Python 3.12, exercising the broader runtime dependency declarations.

Exact logs are retained under `/tmp/m19-py311-*` and `/tmp/m19-py312-*`, including
`pytest-final.log`, `quality-final.log`, `provenance.log`, `build.log`, and
`wheel-*.log`. Original-source mypy comparisons and summation probes remain
under `/tmp/m19-mypy-before-*`, `/tmp/m19-motion-version-comparison.log` and
`/tmp/m19-sum-probe-py31*.log`.

## Suggested commit split

1. Portable NumPy source annotations and deterministic dev dependency pins.
2. Historical rendered-reference comparisons, authenticated fixture, ignore
   exception, helper regression tests and test-policy documentation.
3. Development reproduction guide, changelog, this report and report/status
   index updates.

PM review/commit and the four Ubuntu/macOS Actions jobs remain the integration
step. No main-branch CI success is claimed before those jobs run on the changes.

## M19b — historical JSON traces after Actions #7

Follow-up verified 2026-10-19, Asia/Shanghai. PM committed M19 as `79f9c61`,
`68b4899`, `f884944`, merged it as `1e6c62a`, and fast-forwarded this worktree
through status commit `570e8bf`. The earlier integration note above describes
the original M19 handoff; this section records the subsequent CI gap and fix.
M19b changes remain uncommitted and were not pushed.

### Remaining failure and reproduction

[Actions run #7](https://github.com/SureD/display-sim/actions/runs/39159243116)
passed the quality job, but all four Ubuntu/macOS × Python 3.11/3.12 test jobs
failed. PM supplied the summary `6 failed, 1694 passed`, all six in
`test_m14_validation_and_gallery_assets_match_pre_m15`, with the first mismatch
at `root.cut/pts-trace.json.bytes`: `49008` versus `49009`, or `49116` versus
`49117`. The public jobs API confirms those job conclusions; the log download
endpoint again returned HTTP 403, “Must have admin rights to Repository.”

The remaining comparator used a filename whitelist for decoded JSON:
`motion-validation.json`, checkpoint states, and M13 experiment manifests.
Other JSON, including `pts-trace.json`, M13 `trace.json`, and motion CLI
manifests, still became opaque byte-length/SHA records. A trace embeds computed
image metrics and capacity floats, so a tiny numerical change can alter its
decimal representation and consequently both its length and SHA. The first
length assertion hid the decoded numerical difference.

Controlled one-ULP changes to authenticated archived traces reproduce the exact
reported lengths and failure path with the **original committed helper**:

| Capture | Controlled field/value change | Canonical bytes |
| --- | --- | --- |
| M13 WOLED cut trace | `apl_nits`: `26.769044335683187` → `26.76904433568319` | 49009 → 49008 |
| M13 QD-OLED cut trace | `dt_ms`: `16.666666666666668` → `16.66666666666667` | 49117 → 49116 |

Both original comparisons fail at `root.cut/pts-trace.json.bytes`. Both fixed
historical comparisons pass, while ordinary digest equality still rejects the
different bytes. These probes verify the serialization mechanism and reproduce
the comparison failure; inaccessible CI logs prevent identifying the particular
scalar that changed on each runner. No specific CPU/libm cause is asserted.

### Fix and whole-suite audit

All JSON records encountered by the historical artifact comparator now decode
their authenticated saved payloads. Dictionaries retain exact keys; lists
retain exact lengths/order; integer, Boolean, string and null types/values
remain exact. Only finite floats accept `rtol=1e-12`, `atol=1e-12`; float/int
substitution, nonfinite numbers and material numerical changes fail. This
supersedes M19's narrow image/trajectory field whitelist, covering floating
trace and diagnostic fields regardless of their filename or nesting.

The saved payload's SHA and recorded byte length are still authenticated
exactly. Current JSON serialization length/SHA may differ; its decoded values
are the historical comparison target. No equality operator was changed, and
same-machine default-path, repeated-run and checkpoint comparisons stay exact.
The existing NumPy environment-identity exception remains explicitly checked.

PTS traces now link their rendered-array hashes through the complete experiment
root, passed by both historical artifact collectors. Trace paths such as
`cut/analytic_0000.npy` are relative to that root, rather than to the nested
`cut/pts-trace.json` directory. Current array SHA values must first match their
actual files before decoded array/reference comparison.

| Audited comparison | Result |
| --- | --- |
| M14 PTS traces across seven fixtures and three display variants | Decode JSON; tight finite-float comparison and linked array authentication |
| M13 trial traces and motion CLI manifests | Decode JSON instead of opaque historical hashes |
| Existing report/checkpoint JSON | Shared finite-float rule; strict strings/hex state and actual checkpoint checksum validation retained |
| Historical validation metrics JSON/CSV | Already decoded/typed; existing tolerances retained, with a new one-byte CSV regression check |
| Gallery `memc_trace.json` historical hashes | Retained exactly: floating fields are deterministic 0/1 fallback fractions and fixed rational-to-float durations; timing/positions use rational strings |
| Profile/protocol/source identity hashes and saved-reference hashes | Retained exactly; stable input/evidence identities or reference authentication |
| M17/M18 and other same-machine artifact/checkpoint byte comparisons | Retained exactly; these compare outputs produced on the same host |

The complete raw JSON/CSV hash/size audit found no additional historical CSV
gap. The 1,074-entry rendered-reference archive already contains every needed
JSON payload; no baseline or reference fixture was regenerated or changed.
Its SHA remains
`eeba7a32cede96e8d250359831432139c75dd1b27842c3c598cbfad21b5a8fc5`.

Seventeen regression cases were added, bringing the helper module to 45 tests.
They cover one-byte JSON float serialization changes under three filenames,
strict structure/rational/integer/Boolean/string/type checks, rejected
nonfinite floats, exact saved-reference lengths, nested trace array paths and
checksum validation, and typed CSV float tolerance with exact integer cells.
Reference coverage now includes every historical JSON artifact record, so a
future filename cannot silently fall back to an unaudited opaque comparison.

### Exact verification

Reused the worktree's `/tmp/m19-py311` and `/tmp/m19-py312` editable environments
with CPython 3.11.17/3.12.15, NumPy 2.4.6, pytest 8.4.2, Ruff 0.14.1 and
mypy 1.18.2. Imports resolve to this checkout. No runtime source or dependency
versions changed during M19b.

| Check | CPython 3.11.17 | CPython 3.12.15 |
| --- | --- | --- |
| Full `pytest -q`, including slow tests | **1717 passed in 386.71s** | **1717 passed in 381.62s** |
| `ruff check .` | All checks passed | All checks passed |
| `ruff format --check .` | 111 files already formatted | 111 files already formatted |
| `mypy` | No issues in 59 source files | No issues in 59 source files |
| `scripts/check_docs.py` | All local targets/anchors passed | All local targets/anchors passed |

Full runs used separate `/tmp/m19b-full-py311` and `/tmp/m19b-full-py312`
temporary roots. Quality checks used the unchanged Makefile's
`lint typecheck docs-check` targets with the corresponding interpreter. The
system `python3 scripts/check_docs.py` and `git diff --check` also pass.
Supplemental Python 3.11 execution with AVX512F/AVX2/FMA3 disabled passes all
six affected validation tests in 12.94s. The one-ULP probes also pass against
the new comparator while reproducing the original helper's exact failure.

Logs: `/tmp/m19b-py311-pytest.log`, `/tmp/m19b-py312-pytest.log`,
`/tmp/m19b-py311-quality.log`, `/tmp/m19b-py312-quality.log`,
`/tmp/m19b-original-helper-reproduction.log`, `/tmp/m19b-one-byte-reproduction.log`,
`/tmp/m19b-helper.log`, and `/tmp/m19b-no-simd.log`.

Suggested commit: `M19b: compare historical JSON traces by decoded values`.
Actual Ubuntu/macOS Actions verification follows PM integration; local Linux
results and controlled roundoff tests do not claim that those jobs have run
on this unpushed follow-up.
