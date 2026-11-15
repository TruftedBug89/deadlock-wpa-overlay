"""Dynamic detection of Statlocker WPA cards.

Statlocker renders between one and five recommendation cards and centres them
inside its widget, so a fixed five-slice crop reads the wrong pixels as soon as
the count changes.  This module finds the *actual* cards in a captured strip:

1. estimate the strip background,
2. build a per-column "ink" profile,
3. group columns into runs, merging tiny gaps and splitting touching cards,
4. trim each run vertically to the rendered content.

The result is a list of boxes in the same pixel space as the input image, in
left-to-right order, ready for per-card OCR.  No OCR and no Win32 here, which
keeps it unit-testable with synthetic images.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class CardBox:
    """An axis-aligned card region inside the analysed strip."""

    x: int
    y: int
    w: int
    h: int
    activity: float = 0.0

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


def _box_blur_1d(values: np.ndarray, radius: int) -> np.ndarray:
    """Cheap moving average used to smooth column profiles."""
    if radius <= 0 or values.size == 0:
        return values
    kernel = np.ones(radius * 2 + 1, dtype=np.float32)
    kernel /= kernel.sum()
    padded = np.pad(values.astype(np.float32), radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _runs_from_profile(profile: np.ndarray, threshold: float, gap_tolerance: int) -> List[tuple]:
    """Return ``(start, end)`` inclusive column runs above ``threshold``."""
    above = profile > threshold
    runs: List[tuple] = []
    index = 0
    size = above.size
    while index < size:
        if not above[index]:
            index += 1
            continue
        start = index
        last_true = index
        while index < size:
            if above[index]:
                last_true = index
            elif index - last_true > gap_tolerance:
                break
            index += 1
        runs.append((start, last_true))
    return runs


def _split_wide_runs(runs: List[tuple], profile: np.ndarray, typical_width: float, gaps: int) -> List[tuple]:
    """Split runs that clearly contain more than one touching card."""
    if typical_width <= 4:
        return runs
    output: List[tuple] = []
    for start, end in runs:
        width = end - start + 1
        pieces = max(1, int(round(width / typical_width)))
        if pieces <= 1 or width < typical_width * 1.55:
            output.append((start, end))
            continue
        step = width / pieces
        boundaries = [start]
        for piece in range(1, pieces):
            guess = int(round(start + step * piece))
            search_radius = max(2, int(typical_width * 0.25))
            low = max(start + 2, guess - search_radius)
            high = min(end - 1, guess + search_radius)
            if low >= high:
                boundaries.append(guess)
                continue
            window = profile[low : high + 1]
            boundaries.append(low + int(np.argmin(window)))
        boundaries.append(end + 1)
        boundaries = sorted(set(boundaries))
        for left, right in zip(boundaries[:-1], boundaries[1:]):
            if right - left > gaps:
                output.append((left, right - 1))
    return output


def _merge_until(runs: List[tuple], limit: int) -> List[tuple]:
    """Merge the closest neighbouring runs until at most ``limit`` remain."""
    merged = list(runs)
    while len(merged) > limit > 0:
        gaps = [(merged[i + 1][0] - merged[i][1], i) for i in range(len(merged) - 1)]
        if not gaps:
            break
        _, index = min(gaps)
        merged[index] = (merged[index][0], merged[index + 1][1])
        del merged[index + 1]
    return merged


def _vertical_bounds(mask: np.ndarray, x0: int, x1: int) -> tuple:
    """Find the top/bottom of rendered content inside a column range."""
    rows = mask[:, x0 : x1 + 1].mean(axis=1)
    if rows.size == 0 or float(rows.max()) <= 0.0:
        return 0, mask.shape[0] - 1
    threshold = max(0.02, float(rows.max()) * 0.12)
    active = np.nonzero(rows > threshold)[0]
    if active.size == 0:
        return 0, mask.shape[0] - 1
    return int(active[0]), int(active[-1])


def detect_card_boxes(
    gray: np.ndarray,
    *,
    max_cards: int = 5,
    min_width: int = 24,
    min_activity: float = 0.012,
    gap_tolerance: int = 3,
    noise_tolerance: Optional[float] = None,
) -> List[CardBox]:
    """Detect card regions in a grayscale strip.

    Args:
        gray: 2-D array (float or uint8) of the card row.
        max_cards: Hard upper bound; Statlocker never shows more than five.
        min_width: Reject slivers narrower than this many pixels.
        min_activity: Minimum fraction of "non-background" pixels per column.
        gap_tolerance: Columns below threshold tolerated inside one card.
        noise_tolerance: Absolute gray delta treated as noise.

    Returns:
        Left-to-right :class:`CardBox` list (possibly empty).
    """
    img = np.asarray(gray, dtype=np.float32)
    if img.ndim != 2 or img.size == 0:
        return []
    height, width = img.shape
    if height < 8 or width < 16:
        return []

    tolerance = float(noise_tolerance) if noise_tolerance is not None else _estimate_noise(img)
    background = _estimate_background(img)
    mask = np.abs(img - background) > tolerance
    if mask.mean() < min_activity:
        return []

    profile = _box_blur_1d(mask.mean(axis=0), radius=2)
    peak = float(profile.max())
    if peak < min_activity:
        return []
    threshold = max(min_activity, peak * 0.16)

    runs = _runs_from_profile(profile, threshold, gap_tolerance)
    runs = [(a, b) for a, b in runs if (b - a + 1) >= min_width]
    if not runs:
        return []

    # Drop runs that are pure border lines: require some vertical substance.
    runs = [(a, b) for a, b in runs if float(mask[:, a : b + 1].mean()) > min_activity]

    # Merge tiny gaps (e.g. anti-aliased card borders) BEFORE splitting wide runs.
    runs = [(a, b) for a, b in _merge_runs_touching(runs) if (b - a + 1) >= min_width]
    if not runs:
        return []

    widths = [b - a + 1 for a, b in runs]
    typical = float(np.median(widths))
    runs = _split_wide_runs(runs, profile, typical, gap_tolerance)
    runs = _merge_until(runs, max_cards)
    runs = [(a, b) for a, b in runs if (b - a + 1) >= min_width]
    if not runs:
        return []

    boxes: List[CardBox] = []
    for start, end in runs[:max_cards]:
        top, bottom = _vertical_bounds(mask, start, end)
        pad = 2
        y0 = max(0, top - pad)
        y1 = min(height - 1, bottom + pad)
        boxes.append(
            CardBox(
                x=int(start),
                y=int(y0),
                w=int(end - start + 1),
                h=int(y1 - y0 + 1),
                activity=float(profile[start : end + 1].mean()),
            )
        )
    return boxes


def _merge_runs_touching(runs: Sequence[tuple]) -> List[tuple]:
    """Join runs separated by one or two pixels (anti-aliased card borders)."""
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= 2:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _estimate_noise(img: np.ndarray) -> float:
    """Robust noise estimate from a small corner patch, clamped to a sane range."""
    patch = img[: min(8, img.shape[0]), : min(8, img.shape[1])]
    spread = float(np.median(np.abs(patch - np.median(patch))))
    return float(np.clip(spread * 3.0 + 4.0, 6.0, 24.0))


def _estimate_background(img: np.ndarray) -> float:
    """Estimate the strip background from its margins.

    A global median fails when four or five cards cover most of the row: the
    card panel then outnumbers the background and becomes the "median", which
    makes every gap look like ink and merges all cards into one box.  The outer
    band of the crop is background by construction, so sample that instead.
    """
    height, width = img.shape
    band = max(1, min(4, height // 8, width // 8))
    border = np.concatenate(
        [
            img[:band, :].ravel(),
            img[-band:, :].ravel(),
            img[:, :band].ravel(),
            img[:, -band:].ravel(),
        ]
    )
    if border.size == 0:
        return float(np.median(img))
    # If the crop is so tight that the margin contains card pixels, fall back
    # to a low percentile: Statlocker's panel is brighter than its backdrop.
    if float(np.std(border)) > 16.0:
        return float(np.percentile(img, 10))
    return float(np.median(border))


def boxes_to_slices(boxes: Sequence[CardBox]) -> List[tuple]:
    """Convert boxes to ``(x0, y0, x1, y1)`` PIL crop tuples."""
    return [(b.x, b.y, b.right, b.bottom) for b in boxes]


def detect_statlocker_cards(
    row_rgb: np.ndarray,
    scale: float = 1.0,
    max_cards: int = 5,
) -> List[CardBox]:
    """Detect 1 to 5 dynamic recommendation cards in Statlocker's live WPA row.

    Statlocker dynamically renders 1, 2, 3, 4, or 5 cards and stretches them
    across its recommendation strip (~740px base width).
    """
    if row_rgb is None or row_rgb.size == 0 or row_rgb.ndim < 3:
        return []
    h, w = row_rgb.shape[:2]
    max_w = min(w, int(round(740.0 * scale)))
    card_h = min(h, int(round(185.0 * scale)))
    if max_w < 32 or card_h < 32:
        return []

    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    gray = row_rgb[:card_h, :max_w].astype(np.float32) @ weights

    y_min = int(round(15.0 * scale))
    y_max = int(round(165.0 * scale))
    bg_est = float(np.percentile(gray, 15)) if gray.size > 0 else 30.0
    thresh_val = max(28.0, min(50.0, bg_est + 14.0))
    active = (gray[y_min:y_max, :] > thresh_val).mean(axis=0)

    kernel_size = max(5, int(round(9.0 * scale)))
    if kernel_size % 2 == 0:
        kernel_size += 1
    smoothed = np.convolve(active, np.ones(kernel_size) / kernel_size, mode="same")

    thresh = 0.07
    in_span = False
    start = 0
    spans = []
    for x, val in enumerate(smoothed):
        if val > thresh and not in_span:
            in_span = True
            start = x
        elif val <= thresh and in_span:
            in_span = False
            spans.append((start, x - 1))
    if in_span:
        spans.append((start, len(smoothed) - 1))

    min_span_w = int(round(30.0 * scale))
    spans = [s for s in spans if (s[1] - s[0] + 1) >= min_span_w]
    if not spans:
        return []

    first_x = spans[0][0]
    last_x = spans[-1][1]
    tot_w = last_x - first_x + 1

    if tot_w < 300 * scale and len(spans) == 1:
        count = 1
    elif len(spans) == 2 and (spans[1][0] - spans[0][1]) > 80 * scale:
        count = 2
    elif len(spans) == 3 and all((s[1] - s[0] + 1) < 250 * scale for s in spans) and last_x < 685 * scale:
        count = 3
    elif len(spans) == 4 and all((s[1] - s[0] + 1) < 200 * scale for s in spans):
        count = 4
    elif any((s[1] - s[0] + 1) > 250 * scale for s in spans) or last_x > 680 * scale or len(spans) >= 5:
        count = 5
    else:
        count = min(max_cards, max(1, len(spans)))

    if count == 5:
        stride = int(round(146.0 * scale))
        card_w = int(round(142.0 * scale))
    elif count == 4:
        stride = int(round(175.0 * scale))
        card_w = int(round(170.0 * scale))
    elif count == 3:
        stride = int(round(230.0 * scale))
        card_w = int(round(225.0 * scale))
    elif count == 2:
        stride = int(round(350.0 * scale))
        card_w = int(round(340.0 * scale))
    else:
        stride = int(round(700.0 * scale))
        card_w = int(round(700.0 * scale))

    count = min(count, max_cards)
    boxes: List[CardBox] = []
    for i in range(count):
        bx = int(i * stride)
        bw = min(card_w, max_w - bx)
        if bw > 20:
            boxes.append(CardBox(x=bx, y=0, w=bw, h=card_h, activity=1.0))
    return boxes
