# PM Plan

> Historical milestone record through M15. See [current documentation](../index.md)
> and [M16 engineering report](M16-repo-engineering.md) for the repository migration.
Workstreams
1. Research (Codex): physical models per panel tech, subpixel layouts, backlight/local dimming/blooming, HDR tone mapping, color gamut/EOTF, response time/motion blur/BFI, viewing angle, reflectance/ambient light, TV image-processing (upscale, sharpen, MEMC).
2. Architecture (Cursor): modular pipeline, TV profile spec (YAML), CLI + preview.
3. Implementation: Python/NumPy first (reference), GPU (PyTorch/WebGL) later; RTX 3070 box (dscs2pc) available for GPU experiments.
4. Validation: test patterns (ramps, checkerboard, ANSI contrast, window patterns for blooming), unit tests, sanity vs published measurements; visual gallery contact sheets.
Milestones: M1 research docs; M2 pipeline skeleton + 3 TV profiles; M3 local dimming + HDR + temporal; M4 validation + report; M5 mechanism fidelity (source-demand ABL, emissive PSF, shaped zone PSF/LSF) + macOS EDR research; M6 visual gallery (subpixel macro + multi-TV contact sheets) + profile-wiring research DONE; M7 MEMC/motion research DONE, M7 MEMC implementation phase 1 (baselines, rational repeat scheduler, analytic translation reconstruction) DONE; M8 profile provenance sidecar + validation DONE; M9 opt-in window replay/drive fitting (M6 wiring handoff item 2) DONE; M10 opt-in viewing-angle model (M6 wiring handoff item 4) DONE; M11 OLED capacity attack/release design research (handoff item 5) DONE; M12a web HDR/EDR preview + M12b explainer page DONE; M13 OLED attack/release runtime implementation (opt-in, per M11 design) DONE; M14 MEMC phase 2 (block-estimation proxy + cut/confidence fallback + motion validate fixtures + short-clip artifact gallery) DONE; M15 opt-in colorimetry + gamut/color-volume model (source/panel primaries sidecars, gamut mapping, WOLED RGBW ceiling) in progress; Mac native Metal/EDR app next (needs a Mac); post-gallery GPU path (PyTorch on dscs2pc) pending user OK.
PM checks: each cycle review commits, test results, and whether work matches the plan.

M15 opt-in colorimetry/color-volume research and implementation are complete
in `codex/m15-colorimetry`, uncommitted for PM review. It adds declared source
and P panel colorimetry, derived XYZ conversion, gamut mapping, a joint RGBW/HDR
capacity model and signed linear export metadata for the web/native renderers.
Default-off output parity remains required. Measured color-volume/spectral
calibration and native Mac Metal/EDR validation remain future work.
