"""Unit tests for validation metrics. No pipeline and no profiles."""

import numpy as np
import pytest

from sim.metrics import (
    abl_ratios,
    ansi_contrast,
    blur_width_ms,
    contrast_ratio,
    eotf_tracking,
    motion_blur_px,
    moving_edge_blur_px,
    rectangle_chebyshev_distance,
    window_bloom,
    window_peak_nits,
)


def test_contrast_ratio_is_undefined_at_the_black_floor():
    assert contrast_ratio(100.0, 0.0) is None
    assert contrast_ratio(100.0, 1e-4) is None
    assert contrast_ratio(100.0, 0.05) == pytest.approx(2000.0)


def test_ansi_contrast_on_a_perfect_checker():
    image = np.zeros((16, 16), dtype=np.float64)
    yy, xx = np.indices(image.shape)
    image[((yy // 4) + (xx // 4)) % 2 == 1] = 80.0
    result = ansi_contrast(image, cells=4, inset_fraction=0.25)
    assert result["white_nits"] == pytest.approx(80.0)
    assert result["black_nits"] == pytest.approx(0.0)
    assert result["contrast_ratio"] is None


def test_window_bloom_ring_and_full_frame():
    luminance = np.zeros((21, 21), dtype=np.float64)
    luminance[6:15, 6:15] = 100.0
    distance = rectangle_chebyshev_distance(21, 21, 6, 15, 6, 15)
    luminance[distance == 1] = 4.0
    black = np.full_like(luminance, 0.5)
    metrics = window_bloom(
        luminance, 6, 15, 6, 15, near_px=1, far_px=4, black_luminance=black
    )
    assert metrics["peak_nits"] == pytest.approx(100.0)
    assert metrics["halo_nits"] == pytest.approx(4.0)
    assert metrics["bloom_excess_nits"] == pytest.approx(3.5)
    assert metrics["far_black_nits"] == pytest.approx(0.0)
    covered = window_bloom(luminance, 0, 21, 0, 21, near_px=1, far_px=3)
    assert covered["halo_nits"] is None
    assert covered["bloom_excess_nits"] is None
    assert window_peak_nits(luminance, 6, 15, 6, 15) == pytest.approx(100.0)


def test_distance_is_zero_inside_and_one_on_the_neighbor():
    distance = rectangle_chebyshev_distance(5, 5, 1, 4, 1, 4)
    assert distance[2, 2] == 0
    assert distance[0, 2] == 1
    assert distance[0, 0] == 1


def test_abl_ratios_use_the_reference_window():
    assert abl_ratios([200.0, 100.0, 50.0]) == pytest.approx([1.0, 0.5, 0.25])
    assert abl_ratios([0.0, 10.0]) == [None, None]


def test_eotf_tracking_flags_a_clip_and_ignores_a_straight_ramp():
    codes = np.linspace(0.0, 1.0, 101)
    ideal = codes * 1000.0
    clipped = np.minimum(ideal, 100.0)
    result = eotf_tracking(clipped, ideal, codes)
    assert result["clipping_code"] == pytest.approx(0.10, abs=0.02)
    assert result["clipping_nits"] == pytest.approx(100.0, abs=1.0)
    assert result["mean_abs_rel_error"] > 0.5
    straight = eotf_tracking(ideal, ideal, codes)
    assert straight["mean_abs_rel_error"] == pytest.approx(0.0, abs=1e-6)
    assert straight["clipping_code"] is None
    near = eotf_tracking(np.array([0.2, 2.0]), np.array([0.0, 2.0]), np.array([0.0, 0.5]))
    assert near["mean_abs_error_nits_near_black"] == pytest.approx(0.2)


def test_moving_edge_blur_is_eight_pixels_on_a_ten_pixel_ramp():
    position = np.arange(40, dtype=np.float64)
    profile = np.clip((position - 10.0) / 10.0, 0.0, 1.0) * 100.0
    width = moving_edge_blur_px(profile)
    assert width == pytest.approx(8.0, abs=1e-6)
    assert blur_width_ms(width, motion_px_per_frame=8.0, frame_time_ms=16.0) == pytest.approx(16.0)
    assert moving_edge_blur_px(np.zeros(16)) is None
    assert blur_width_ms(None, 8.0, 16.0) is None
    assert motion_blur_px(10.0, 6.0) == pytest.approx(8.0)
    assert motion_blur_px(5.0, 6.0) == pytest.approx(0.0)
    assert motion_blur_px(None, 6.0) is None
