"""End-to-end stills through every bundled profile, plus the CLI."""

import numpy as np

from sim.patterns import white_window, window_bounds
from sim.pipeline import Pipeline
from sim.profile import available_profiles, load_profile
from sim.stages.encode import encode_frame


PROFILES = (
    "generic_va_fald_miniled",
    "generic_ips_edge",
    "generic_woled",
    "generic_qdoled",
)


def test_profiles_load():
    assert set(PROFILES) <= set(available_profiles())
    for name in PROFILES:
        profile = load_profile(name)
        assert profile.name == name
        assert "placeholder" in profile.description.lower()


def test_pipeline_on_white_window(tmp_path):
    encoded = white_window(96, 96, fraction=0.1)
    y0, y1, x0, x1 = window_bounds(96, 96, 0.1)
    # A pixel just outside the window, and the far corner.
    near = (y0 - 2, (x0 + x1) // 2)
    corner = (1, 1)
    linear = {}
    previews = {}
    for name in PROFILES:
        profile = load_profile(name)
        frame = Pipeline(profile).run_linear(encoded)
        preview = encode_frame(frame, profile.output)
        assert np.isfinite(frame.rgb).all()
        assert frame.rgb.min() >= -1e-5
        assert frame.backlight is not None
        assert preview.shape == encoded.shape
        assert preview.dtype == np.uint8
        linear[name] = frame
        previews[name] = preview

    va = linear["generic_va_fald_miniled"]
    assert va.backlight[near] > va.backlight[corner] + 1.0
    oled = linear["generic_woled"]
    assert oled.backlight[corner] < 1e-3
    assert oled.backlight[near] < 1.0
    # IPS leakage and the FALD halo are different pictures.
    assert not np.allclose(
        linear["generic_va_fald_miniled"].rgb,
        linear["generic_ips_edge"].rgb,
    )
    # QD-OLED crosstalk moves light; WOLED with sigma 0 does not.
    assert not np.allclose(
        linear["generic_woled"].backlight,
        linear["generic_qdoled"].backlight,
    )
    from sim.cli import main

    src = tmp_path / "in.png"
    dst = tmp_path / "out.png"
    from PIL import Image

    Image.fromarray(encoded, mode="RGB").save(src)
    main(
        [
            "--profile",
            "generic_va_fald_miniled",
            "--input",
            str(src),
            "--output",
            str(dst),
        ]
    )
    assert dst.is_file()
    saved = np.asarray(Image.open(dst))
    assert saved.shape == encoded.shape
    assert saved.dtype == np.uint8
