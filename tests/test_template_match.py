"""Template matching tests (FFT normalised cross-correlation)."""

import numpy as np
import pytest
from PIL import Image

from template_match import find_template, ncc_map


def _texture(height: int, width: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(5, 60, size=(height, width), dtype=np.uint8).astype(np.float32)


def test_ncc_map_peaks_at_template_position():
    template = np.array(
        [[0, 255, 0, 255, 0], [255, 0, 255, 0, 255], [0, 255, 0, 255, 0], [255, 0, 255, 0, 255]],
        dtype=np.float32,
    )
    image = np.zeros((40, 50), dtype=np.float32)
    image[12:16, 21:26] = template
    correlation = ncc_map(image, template)
    y, x = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
    assert (x, y) == (21, 12)
    assert correlation[y, x] > 0.99


def test_find_template_locates_exact_copy():
    image = _texture(320, 420)
    template = image[91:121, 137:207].copy()
    hit = find_template(image, template, scales=(1.0,), min_score=0.8)
    assert hit is not None
    assert abs(hit.x - 137) <= 1
    assert abs(hit.y - 91) <= 1
    assert hit.score > 0.9


def test_find_template_handles_scaled_ui():
    base = _texture(288, 384, seed=11)
    template = base[80:104, 120:184].copy()
    enlarged = np.asarray(
        Image.fromarray(base.astype(np.uint8)).resize((480, 360), Image.Resampling.BILINEAR),
        dtype=np.float32,
    )
    hit = find_template(enlarged, template, scales=(1.0, 1.25), min_score=0.5)
    assert hit is not None
    assert abs(hit.x - 150) <= 8
    assert abs(hit.y - 100) <= 8


def test_flat_template_rejected():
    with pytest.raises(ValueError):
        ncc_map(np.zeros((20, 20), dtype=np.float32), np.full((5, 5), 9.0, dtype=np.float32))


def test_missing_template_returns_none():
    image = _texture(120, 160)
    template = _texture(10, 10, seed=99)
    assert find_template(image, template, scales=(1.0,), min_score=0.99) is None


def test_large_frame_keeps_true_peak_at_full_resolution():
    """Regression: float32 integral images overflowed on real frame sizes.

    The local variance of a 1936x1048 frame was destroyed by cancellation, so
    every window scored 1.0 and blank areas were accepted as the "WPA ITEMS"
    heading.  float64 accumulation keeps the peak where the template really is.
    """
    image = _texture(1048, 1936, seed=17)
    template = image[570:597, 931:1035].copy()
    correlation = ncc_map(image, template)
    y, x = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
    assert (x, y) == (931, 570)
    assert correlation[y, x] > 0.99


def test_flat_frame_cannot_fake_a_confident_match():
    image = np.full((1048, 1936), 31.0, dtype=np.float32)
    template = _texture(27, 104, seed=5)
    correlation = ncc_map(image, template)
    assert float(np.abs(correlation).max()) < 1e-3
