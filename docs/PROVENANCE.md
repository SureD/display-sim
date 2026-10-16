# Profile provenance (M8)

Each runtime profile has a separate `sim/profiles/<name>.provenance.yaml`
record with `schema_version: 1`. These records document the current generic
presets and preserve published measurements from the existing research.
They do not calibrate a generic preset to a named television.

```sh
python3 -m sim provenance --check
python3 -m sim provenance --check --profiles generic_woled generic_qdoled
```

The check reports invalid or missing records and exits unsuccessfully when
validation fails. The default check also rejects orphan sidecars with no
corresponding runtime profile. Runtime loading and the rendering pipeline do not read the
sidecars. Profile discovery excludes `*.provenance.yaml`, so adding a record
does not create another selectable TV profile. The four original runtime
YAML files remain unchanged.

## Evidence and unknowns

The labels follow [M5 fidelity](../research/m5-fidelity.md) and
[M6 profile wiring](../research/m6-profile-wiring.md):

| Label | Meaning |
|---|---|
| `M` | A published measurement on the named specimen under the recorded conditions. |
| `D` | A calculation from stated inputs, with its method and source retained. |
| `P` | A proposed model, synthetic preset, fitting choice, or interpolation. |
| `NR` | No verified numerical reference, an unidentified parameter, or an unknown condition. |

`NR` never means zero. Use `not_applicable` where a mechanism or field does
not apply, rather than where its value is merely unknown. A measured
luminance can have `M` evidence while its dwell, uncertainty, firmware, or
requested stimulus amplitude remains `NR`. Those gaps prevent a claim of
matched experimental conditions.

The shipped generic settings are documented as synthetic choices or values
without a matched measurement. A nearby published peak, contrast ratio, or
response result does not make a profile parameter measured. In particular,
panel response time constants are not published GtG averages, optical
spreading knobs are not measured TV kernels, and weighted-nit power knobs
are not electrical watt measurements.

## Schema version 1

| Top-level field | Meaning |
|---|---|
| `schema_version` | Integer `1`; unsupported versions fail validation. |
| `profile` | The corresponding runtime profile name. |
| `entries` | Provenance for every supported effective profile leaf. |
| `datasets` | Separate named measurement records, keyed by dataset ID. |

The `entries` mapping uses dotted profile paths. Each entry records an exact
`value` snapshot, evidence, source location, conditions, interpolation, and
support. Paths cover every leaf of the loaded profile, including defaults
from [the profile dataclasses](../sim/profile.py), not only keys explicitly
written in the runtime YAML. Lists are atomic: for example,
`panel.color_matrix` and `hdr.abl_channel_weights` each have one entry.
An absent optional table is recorded at `backlight.psf_profile` with a null
value; a supplied table uses its supported nested fields instead.

The validator compares entry paths against supported dataclass fields and
compares each stored value against the loaded value. Missing entries,
unsupported paths, and stale snapshots fail validation. This makes a later
default or runtime-profile change require an explicit provenance update.

| Entry field | Contents |
|---|---|
| `value` | The exact loaded scalar, null, or atomic list. |
| `evidence` | `M`, `D`, `P`, or `NR`. |
| `source` | A `locator` and `sample`; published sources also retain their URL. |
| `conditions` | Explicit experimental context, with unknowns retained as `NR`. |
| `interpolation` | `method` and `evidence`. |
| `support` | `range`, `unit`, and `outside: reject`. |
| `notes` | Interpretation, assumptions, or reasons a setting is synthetic. |

Each source retains a locator and sample identity. Local synthetic values
point to the runtime YAML or dataclass default and the relevant research;
published records retain the original review URL and table, asset, or
paragraph locator. Conditions preserve unknown values explicitly, including
mode, source encoding and requested amplitude, stimulus geometry, refresh
and VRR, white point, viewing geometry, instrument, warm-up, dwell, pattern
history, ambient light, temperature, and uncertainty where relevant.

`interpolation` records the method and evidence. An unchanged scalar uses
`method: none` with interpolation evidence `not_applicable`. A numerical
support interval records its unit and an `outside: reject` policy.
`range: NR` means that the measurement support is unknown; `range: not_applicable`
is reserved for values without a meaningful measurement axis. Neither is a
permission to extrapolate. Synthetic settings do not acquire measured
support merely because the simulator accepts a wider parameter range.

The separate `datasets` mapping stores named measurement records. Each
record has `kind` (`window_curve` or `unlocated_peak`), `specimen`, `source`,
`conditions`, `axis`, `metric`, `nodes`, `interpolation`, and `support`.
Each window node records `fraction`, `luminance_nits`, and `evidence`.
An unlocated scalar uses an `unlocated_peak` block rather than a fabricated
numeric node. `calibrated_profile_fit` and `timed_sustained_trace` remain
`NR` in these records. They are candidate evidence for future work; they
are not assignments to `hdr` parameters or active output curves.

## Preserved measurement records

The sidecars transcribe the values already documented in M5/M6; M8 performs
no new measurement or source acquisition.

| Sidecar | Named record | Preserved limits |
|---|---|---|
| `generic_woled` | LG 42C2 HDR Standard, dynamic tone mapping off; 1–100% peak-window table. | C2 values inherit the M5 table-image transcription; M6 records its unsuccessful refetch. Dwell and sustained traces remain `NR`. |
| `generic_qdoled` | Samsung 65-inch S95B HDR10 Filmmaker peak windows. | Independent 2%, 5%, and 75% readings remain `NR`; the publisher's rounded 1–10% plateau does not create extra measurements. |
| `generic_va_fald_miniled` | TCL 98X955 Theatre HDR peak-window table. | Numeric support begins at 2%; the 1% point is `NR`. The low-window suppression is retained and no monotonic OLED fit is imposed. |
| `generic_ips_edge` | LG 55UH770V 455-nit peak, window unlocated. | Window fraction and dwell remain `NR`; this scalar cannot supply a window curve or a supported fraction lookup. |

The original sources and per-node evidence remain in each record. These
samples are not interchangeable technology curves. A 100% peak entry does
not establish 10-second or 60-second sustained output, and another screen
size or picture mode is a different experiment.

## Measurement lookup

`sim.provenance.lookup_measurement(data, dataset_id, fraction)` is an
explicit research lookup. It returns the fraction, luminance in nits,
evidence, and whether the result was interpolated. It does not modify a
profile or run a rendering stage.

A lookup at a known numeric node retains that node's evidence. Between
known nodes, the declared piecewise-linear method returns `P`, including
when both endpoints are `M`. An `NR` node is preserved in the record and
does not become a measured value; any interpolation across its position is
still a proposed result. No lookup may leave the declared numeric support,
and an unknown support range fails explicitly. For example, an X955 lookup
below 0.02 fails, and the IPS unlocated peak cannot be looked up at any
window fraction.

Interpolation here is exploratory. It does not fill missing requested
amplitudes or timing, certify condition-matched replay, or activate the
future runtime replay proposed in M6. M8 implements the sidecars
and validation from §8 item 1; runtime fitting and replay remain separate
work.
