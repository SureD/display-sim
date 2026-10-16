# PM Plan
Workstreams
1. Research (Codex): physical models per panel tech, subpixel layouts, backlight/local dimming/blooming, HDR tone mapping, color gamut/EOTF, response time/motion blur/BFI, viewing angle, reflectance/ambient light, TV image-processing (upscale, sharpen, MEMC).
2. Architecture (Cursor): modular pipeline, TV profile spec (YAML), CLI + preview.
3. Implementation: Python/NumPy first (reference), GPU (PyTorch/WebGL) later; RTX 3070 box (dscs2pc) available for GPU experiments.
4. Validation: test patterns (ramps, checkerboard, ANSI contrast, window patterns for blooming), unit tests, sanity vs published measurements; visual gallery contact sheets.
Milestones: M1 research docs; M2 pipeline skeleton + 3 TV profiles; M3 local dimming + HDR + temporal; M4 validation + report; M5 mechanism fidelity (source-demand ABL, emissive PSF, shaped zone PSF/LSF) + macOS EDR research; M6 visual gallery (subpixel macro + multi-TV contact sheets) in progress; post-M6 GPU path (PyTorch on dscs2pc) pending user OK.
PM checks: each cycle review commits, test results, and whether work matches the plan.
