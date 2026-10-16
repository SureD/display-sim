"""ABL load limiting against the research/m3-hdr-abl-params.md contract."""

import numpy as np
import pytest

from sim.load import (
    LoadState,
    abl_capacity,
    backlight_derate,
    demand_apl,
    load_fraction,
    smooth_apl,
)
from sim.profile import HdrParams
from sim.stages.tonemap import effective_peak


def _hdr(**kwargs) -> HdrParams:
    base = dict(abl_enabled=True, abl_source="demand", abl_gamma=2.0)
    base.update(kwargs)
    return HdrParams(**base)


def test_demand_apl_is_mean_linear_luminance():
    rgb = np.zeros((4, 4, 3), dtype=np.float32)
    rgb[0, 0] = 100.0
    # BT.709 luminance of equal-energy 100 nits is 100 nits, over 16 pixels.
    assert demand_apl(rgb) == pytest.approx(100.0 / 16.0, rel=1e-6)


@pytest.mark.parametrize(
    "fraction, peak, full, expected",
    [
        # Analytic table in research/m3-hdr-abl-params.md ("ABL versus load").
        (0.01, 800.0, 150.0, 787.065),
        (0.10, 800.0, 150.0, 676.5),
        (0.25, 800.0, 150.0, 515.625),
        (0.50, 800.0, 150.0, 312.5),
        (1.00, 800.0, 150.0, 150.0),
        (0.01, 1000.0, 200.0, 984.08),
        (0.10, 1000.0, 200.0, 848.0),
        (0.25, 1000.0, 200.0, 650.0),
        (0.50, 1000.0, 200.0, 400.0),
        (1.00, 1000.0, 200.0, 200.0),
    ],
)
def test_capacity_matches_research_table(fraction, peak, full, expected):
    params = _hdr(panel_peak_nits=peak, abl_full_field_nits=full)
    apl = fraction * peak
    assert abl_capacity(apl, params) == pytest.approx(expected, rel=1e-6)


def test_capacity_is_monotone_nonincreasing_in_load():
    params = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0)
    caps = [abl_capacity(apl, params) for apl in np.linspace(0.0, 1200.0, 25)]
    assert all(later <= earlier + 1e-6 for earlier, later in zip(caps, caps[1:]))
    assert caps[0] == pytest.approx(1000.0)
    assert caps[-1] == pytest.approx(200.0)


def test_load_fraction_clips_and_honors_reference():
    params = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0)
    assert load_fraction(-5.0, params) == 0.0
    assert load_fraction(5000.0, params) == 1.0
    assert load_fraction(250.0, params) == pytest.approx(0.25)
    scaled = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0, abl_reference_nits=500.0)
    assert load_fraction(250.0, scaled) == pytest.approx(0.5)


def test_abl_off_returns_panel_peak():
    params = HdrParams(panel_peak_nits=640.0, abl_enabled=False, abl_full_field_nits=1.0)
    assert abl_capacity(9999.0, params) == pytest.approx(640.0)
    assert backlight_derate(9999.0, params) == 1.0


def test_capacity_rejects_bad_parameters():
    with pytest.raises(ValueError):
        abl_capacity(10.0, _hdr(panel_peak_nits=1000.0, abl_full_field_nits=0.0))
    with pytest.raises(ValueError):
        abl_capacity(10.0, _hdr(panel_peak_nits=100.0, abl_full_field_nits=200.0))
    with pytest.raises(ValueError):
        abl_capacity(10.0, _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0, abl_gamma=0.0))


def test_smooth_apl_settles_first_frame_then_lags():
    params = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0, abl_response_ms=100.0)
    state = LoadState()
    first = smooth_apl(state, 500.0, params, 16.666)
    assert first == pytest.approx(500.0)
    second = smooth_apl(state, 0.0, params, 16.666)
    # One 16.7 ms step of a 100 ms limiter: part way back, not all the way.
    assert 0.0 < second < 500.0
    assert second == pytest.approx(500.0 * np.exp(-16.666 / 100.0), rel=1e-6)
    for _ in range(120):
        last = smooth_apl(state, 0.0, params, 16.666)
    assert last == pytest.approx(0.0, abs=1e-3)


def test_smooth_apl_without_response_is_instantaneous():
    params = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0)
    state = LoadState()
    smooth_apl(state, 500.0, params, 16.666)
    assert smooth_apl(state, 0.0, params, 16.666) == pytest.approx(0.0)


def test_backlight_derate_tracks_a_fraction_of_the_capacity_drop():
    params = _hdr(
        panel_peak_nits=1000.0,
        abl_full_field_nits=200.0,
        abl_backlight_tracking=0.5,
    )
    full_field = backlight_derate(1000.0, params)
    # Capacity falls to 0.2 of peak; half of that drop reaches the backlight.
    assert full_field == pytest.approx(1.0 - 0.5 * 0.8)
    assert backlight_derate(0.0, params) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        backlight_derate(0.0, _hdr(abl_backlight_tracking=1.5))


def test_demand_source_refuses_to_measure_its_own_output():
    params = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0)
    rgb = np.full((4, 4, 3), 500.0, dtype=np.float32)
    with pytest.raises(ValueError, match="demand_apl_nits"):
        effective_peak(rgb, params)
    assert effective_peak(rgb, params, demand_apl_nits=500.0) == pytest.approx(
        abl_capacity(500.0, params)
    )


def test_unknown_abl_source_is_rejected():
    params = _hdr(panel_peak_nits=1000.0, abl_full_field_nits=200.0, abl_source="guess")
    with pytest.raises(ValueError, match="abl_source"):
        effective_peak(np.zeros((2, 2, 3), dtype=np.float32), params)
