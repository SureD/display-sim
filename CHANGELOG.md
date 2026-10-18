# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). M0–M15 are historical
milestone labels reconstructed from git log, not published semantic-version
releases. Dates use the recorded commit dates; commit IDs identify the source
records. Runtime package version remains defined in `pyproject.toml`.

## [Unreleased]

### Added

- Default-off M18 sub-frame LC response and overdrive LUTs, rational analytical
  PWM/strobe/OLED BFI emission, exact complete-history checkpoints and explicit
  M13/M17 ownership with all MEMC sequence modes.
- Primary-source temporal research, strict P-only protocol/provenance checks and
  `tv-sim subframe` synthetic response, flicker and pursuit-blur experiments with
  compact traces, shared-exposure galleries and simulated pursuit images.
- Default-off M17 LCD zone backlight dynamics with explicit asymmetric e-fold
  times, per-tick slew limits, scene-cut policy, initialization and exact full
  display-history continuation.
- P-only zone protocol/provenance validation and a separate `zone-temporal`
  synthetic clip experiment with rational PTS, zone traces, trail/settling/
  pumping metrics and shared-exposure off/on galleries.
- M16 formal project documentation, contribution/license files, decisions,
  chronological research index, development checks, CI, and review templates.
- Installable `tv_sim` src package with `tv-sim` and `python -m tv_sim` entry points;
  packaged profiles/protocols and a deprecated `python -m sim` CLI shim.

### Changed

- M19 pins the development NumPy/stub and image toolchain across Python 3.11/3.12,
  fixes portable NumPy scalar/array annotations including M18 metrics, and
  compares historical floating renders against authenticated decoded references
  while preserving exact same-machine default-path and checkpoint parity.
- Organize historical plan/status/report material under `docs/reports/` and
  research notes under `docs/research/`; retain generated example artifacts in
  `reports/`.
- Apply consistent formatting, lint rules and public API annotations, preserving
  simulation behavior and profile/data evidence bytes.

## [M15] - 2026-10-18

### Added

- Opt-in explicit source/panel primaries and white, RGB↔XYZ conversion, gamut
  clipping/compression, and a WOLED color envelope sharing the existing HDR/M13
  capacity owner.
- Versioned P-only colorimetry sidecars, source research, shared-exposure
  color-volume gallery, signed linear color-space export and viewer conversion.
- Matrix, mapping, composition, checkpoint, strict-schema and default-off parity
  coverage; milestone suite reached 1,137 tests.

Source: `b3bc463`; integration `3cb3a5e`.

## [M14] - 2026-10-17

### Added

- Default-off block-MCI proxy with bounded reduced-resolution matching,
  confidence/visibility, cut handling and recorded source-hold fallback reasons.
- Streaming adjacent-pair reconstruction, P-only motion config and seven-fixture
  synthetic truth validation with artifact gallery; suite reached 933 tests.

Source: `6d9ebf2`; integration `fb5dcca`.

## [M13] - 2026-10-17

### Added

- Opt-in OLED global capacity attack/release using explicit e-fold times and one
  update per display tick, with initialization policies and exact full-history
  checkpoint continuation.
- Separate `oled-dynamics` runner, P-only protocol and traces, conflict rejection
  and extensive off-path/history parity; suite reached 804 tests.

Source: `2430e5f`; integration `978c839`.

## [M12] - 2026-10-17

### Added

- M12a static browser comparison and `export-web`: linear-nit binary16 transport,
  shared mapping, reference-white calibration, extended WebGPU presentation,
  WebGL2/Canvas2D SDR fallbacks, macro views and motion playback.
- M12b offline eight-chapter technical explainer with three interactive Anatomy
  instruments, vendored license notices and numerical/browser verification.
- Chrome/macOS HDR research; physical host light output remained unverified.

Sources: M12a `54b43af` (integration `863ab00`); M12b `a2c50cc`
(integration `bbe995f`). The combined M11/M12 main suite reached 546 tests.

## [M11] - 2026-10-17

### Added

- Research/design for OLED capacity attack/release, explicit clock/history,
  initialization, checkpointing, one capacity owner and acceptance gates for the
  future M13 runtime. Measured controller constants remained NR.

Source: `6d19a43`; integration `47e17b9`.

## [M10] - 2026-10-17

### Added

- Opt-in signed horizontal/vertical center-ray viewing-angle model: independent
  LCD white/leakage/gray terms and OLED emission gains, with P-only angular
  sidecars and optional shared-exposure gallery row.
- Exact disabled/on-axis output and history parity; suite reached 534 tests.

Source: `d392f9e`; integration `19179e6`.

## [M9] - 2026-10-17

### Added

- Separate opt-in window replay/internal-drive fitting with strict support and
  amplitude/color/geometry/time matching, explicit exploratory assumptions,
  exclusive `.fit.json` datasets, baseline identity and no double limiting.
- Default pipeline, reports, gallery and motion-off parity checks.

Source: `202dbff`; integration `f89047a`.

## [M8] - 2026-10-17

### Added

- Versioned provenance snapshots for all effective generic profile values,
  named-sample measurement records, strict supported lookup and
  `provenance --check` validation. Runtime profile YAMLs were unchanged.

Source: `d0ca06f`; integration `94f248b`. M8 integrated before M7's runtime.

## [M7] - 2026-10-17

### Added

- MEMC/motion research, rational source/output PTS and repeat cadence, default-off
  analytic translation/known-layer reconstruction, safe holds/cuts, exact
  endpoint preservation and timing traces.
- A 24p repeat/interpolated gallery comparison and captured default-off parity.

Source: `1600d8a`; integration `c311510`. Research was committed during M6.

## [M6] - 2026-10-16

### Added

- Four-profile offline gallery with common row exposure, test patterns, pursuit
  motion/history and synthetic RGB/WRGB/triangular QD-OLED macro apertures.
- Profile-wiring research separating named measurement records from runtime
  placeholder assignments and proposing later provenance/replay/angle/dynamics
  handoffs.

Sources: `1923247`, `adf6bd4`, `ec2843e`, `1bb22ac`, `beceac8`, `5685b4b`;
integration `30f8e97`.

## [M5] - 2026-10-16

### Added

- Fidelity research covering load, angular mechanisms, PSF/LSF, apertures,
  response/emission and measurement gaps, plus Mac Metal/EDR research.
- Shaped PSFs, a tabulated LSF hook, and explicit optical boundary policies.

### Changed

- Support source-demand APL selection and spread OLED emission at the panel
  instead of blurring a dead backlight map.

Sources: `43a7360`, `b0f6082`, `335da56`, `1a533de`, `6116f8b`;
integration `1baa2e1`.

## [M4] - 2026-10-16

### Added

- Validation harness, published reference ranges, metrics/previews and a
  simulator-versus-published comparison with explicit unsupported cells.
- Temporal-only moving-edge width reporting and interpretation report.

### Changed

- Nudge placeholder HDR ceilings toward conditional published window anchors;
  this did not establish calibrated device profiles.

Sources: `311ec45`, `56e5fed`, `1562e32`, `f1c655a`, `e5f39eb`, `cc71643`;
integrations `091eb42`, `c7dbf01`.

## [M3] - 2026-10-16

### Added

- Zoned max/percentile backlight requests with two-Gaussian PSFs, float32 HDR
  shoulder and linear-APL ABL, optional overdrive/BFI, parameter notes and tests.

Sources: `f08e314`, `5577842`, `eeb0f22`, `976d377`; integration `477685d`.

## [M2] - 2026-10-15

### Added

- YAML profile schema and four generic placeholder families, linear-light NumPy
  stage pipeline, still-image CLI, synthetic patterns and initial pytest suite.

Sources: `226a38a`, `f4e9d70`, `acacec8`; integration `f0d7e05` on 2026-10-16.

## [M1] - 2026-10-16

### Added

- Foundation research on panel technologies, local dimming, HDR/color,
  temporal behavior, image processing, architecture and validation strategy.

Source: `37cc504`.

## [M0] - 2026-10-15

### Added

- Initial project goal, repository layout and PM milestone/workstream plan.

Source: `e1aa90b`.
