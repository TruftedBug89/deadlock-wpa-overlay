"""Fast normalised cross-correlation template matching (numpy only).

Used to locate Statlocker's "WPA ITEMS" heading inside a captured window
frame.  FFT based so a full 2560x1440 window scan is a few dozen milliseconds
instead of a Python double loop, which keeps the polling thread cheap and the
game free of stutter.
"""

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

_EPS = 1e-6


@dataclass(frozen=True)
class TemplateHit:
    """A located template occurrence in original image pixel coordinates."""

    x: int
    y: int
    score: float
    scale: float
    width: int
    height: int


def _integral_window_sum(values: np.ndarray, height: int, width: int) -> np.ndarray:
    """Sum of every ``height x width`` window, shape (H-h+1, W-w+1).

    The accumulation is float64 on purpose.  A 1936x1048 frame pushes a float32
    integral past 2e9, where one ulp is 256; subtracting neighbouring integral
    values then destroys the local variance and makes every window score 1.0.
    """
    padded = np.pad(values, ((1, 0), (1, 0)), mode="constant")
    integral = padded.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)
    return (
        integral[height:, width:]
        - integral[:-height, width:]
        - integral[height:, :-width]
        + integral[:-height, :-width]
    )


def ncc_map(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation map of ``template`` over ``image``.

    Both inputs are 2-D float arrays.  The result is shaped
    ``(H - h + 1, W - w + 1)`` with values in ``[-1, 1]``.
    """
    img = np.asarray(image, dtype=np.float64)
    tmpl = np.asarray(template, dtype=np.float64)
    if img.ndim != 2 or tmpl.ndim != 2:
        raise ValueError("ncc_map expects 2-D arrays")
    th, tw = tmpl.shape
    ih, iw = img.shape
    if th > ih or tw > iw or th < 2 or tw < 2:
        raise ValueError("template larger than image or degenerate")

    centred = tmpl - float(tmpl.mean())
    tmpl_norm = float(np.sqrt(np.sum(centred * centred)))
    if tmpl_norm < _EPS:
        raise ValueError("template has no contrast")

    # Circular correlation with zero padding large enough to avoid wrap-around.
    fh, fw = ih + th, iw + tw
    spectrum_img = np.fft.rfft2(img, s=(fh, fw))
    spectrum_tmpl = np.fft.rfft2(centred, s=(fh, fw))
    correlation = np.fft.irfft2(spectrum_img * np.conj(spectrum_tmpl), s=(fh, fw))
    # Zero-padded circular correlation: index (dy, dx) already refers to the
    # window whose top-left corner is (dx, dy), which is exactly the alignment
    # used by ``_integral_window_sum`` below.  Slicing away (tw-1, th-1) would
    # shift the numerator by almost a whole template relative to the
    # denominator and produce confident scores at the wrong position.
    correlation = correlation[: ih - th + 1, : iw - tw + 1]

    window = th * tw
    local_sum = _integral_window_sum(img, th, tw)
    local_sq = _integral_window_sum(img * img, th, tw)
    variance = local_sq - (local_sum * local_sum) / window
    # Flat windows have no contrast to correlate with; clamp to zero and let
    # the denominator guard below turn them into a zero score instead of noise.
    np.maximum(variance, 0.0, out=variance)
    denominator = np.sqrt(variance) * tmpl_norm
    safe = denominator > _EPS
    result = np.zeros_like(correlation, dtype=np.float32)
    np.divide(correlation, denominator, out=result, where=safe)
    np.clip(result, -1.0, 1.0, out=result)
    return result


def _resize_gray(array: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(array.astype(np.uint8), mode="L")
    return np.asarray(image.resize(size, Image.Resampling.BILINEAR), dtype=np.float32)


def find_template(
    image: np.ndarray,
    template: np.ndarray,
    *,
    scales: Sequence[float] = (1.0,),
    min_score: float = 0.70,
    max_scan_dim: int = 1400,
) -> Optional[TemplateHit]:
    """Locate the best template match across several scales.

    ``image`` and ``template`` are grayscale arrays.  Large windows are
    downscaled before scanning; returned coordinates are always in the
    original image's pixel space.
    """
    img = np.asarray(image, dtype=np.float32)
    tmpl = np.asarray(template, dtype=np.float32)
    if img.ndim != 2 or tmpl.ndim != 2 or img.size == 0 or tmpl.size == 0:
        return None

    ih, iw = img.shape
    th, tw = tmpl.shape
    if th >= ih or tw >= iw:
        return None

    factor = 1.0
    longest = max(ih, iw)
    if longest > max_scan_dim:
        factor = max_scan_dim / float(longest)

    scan = img
    if factor < 1.0:
        scan = _resize_gray(img, (max(2, int(round(iw * factor))), max(2, int(round(ih * factor)))))

    best: Optional[TemplateHit] = None
    for scale in _unique_scales(scales):
        eff = factor * scale
        sw = int(round(tw * eff))
        sh = int(round(th * eff))
        if sw < 4 or sh < 3 or sw >= scan.shape[1] or sh >= scan.shape[0]:
            continue
        scaled_tmpl = _resize_gray(tmpl, (sw, sh))
        try:
            correlation = ncc_map(scan, scaled_tmpl)
        except ValueError:
            continue
        if correlation.size == 0:
            continue
        index = int(np.argmax(correlation))
        dy, dx = divmod(index, correlation.shape[1])
        score = float(correlation[dy, dx])
        if score < min_score:
            continue
        if best is None or score > best.score:
            best = TemplateHit(
                x=int(round(dx / factor)),
                y=int(round(dy / factor)),
                score=score,
                scale=scale,
                width=int(round(tw * scale)),
                height=int(round(th * scale)),
            )
    return best


def _unique_scales(scales: Iterable[float]) -> list:
    ordered = []
    for value in scales:
        try:
            numeric = round(float(value), 3)
        except (TypeError, ValueError):
            continue
        if numeric > 0.2 and numeric not in ordered:
            ordered.append(numeric)
    return ordered
