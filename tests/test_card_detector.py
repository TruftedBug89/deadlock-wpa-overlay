"""Card segmentation tests with synthetic Statlocker-style rows.

The real widget shows 1..5 centred cards; these tests build exactly that shape
and assert the detector finds every card and no phantom ones.
"""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from card_detector import detect_card_boxes, detect_statlocker_cards

STRIP_W = 800
STRIP_H = 260
BG = 18
PANEL = 30
CARD_W = 140
CARD_H = 210
GAP = 8


def make_strip(count: int, width: int = STRIP_W, height: int = STRIP_H) -> np.ndarray:
    image = Image.new("L", (width, height), BG)
    draw = ImageDraw.Draw(image)
    total = count * CARD_W + (count - 1) * GAP
    start = (width - total) // 2
    for index in range(count):
        x = start + index * (CARD_W + GAP)
        top = 24
        draw.rectangle([x, top, x + CARD_W - 1, top + CARD_H], fill=PANEL, outline=44)
        draw.rectangle([x + 46, top + 16, x + 94, top + 64], fill=190)  # icon
        draw.rectangle([x + 10, top + 110, x + 130, top + 124], fill=220)  # name line
        draw.rectangle([x + 10, top + 140, x + 92, top + 152], fill=150)  # wpa line
        draw.rectangle([x + 10, top + 170, x + 110, top + 182], fill=120)  # timing line
    return np.array(image, dtype=np.float32)


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_detects_every_centred_card(count):
    boxes = detect_card_boxes(make_strip(count))
    assert len(boxes) == count, f"expected {count} cards, got {len(boxes)}"
    widths = [box.w for box in boxes]
    assert all(abs(width - CARD_W) <= 6 for width in widths), widths
    # Left-to-right ordering with no overlaps.
    for left, right in zip(boxes, boxes[1:]):
        assert right.x > left.x


def test_single_card_is_centred():
    strip = make_strip(1)
    boxes = detect_card_boxes(strip)
    assert len(boxes) == 1
    centre = boxes[0].x + boxes[0].w / 2
    assert abs(centre - STRIP_W / 2) < 12


def test_no_cards_on_blank_strip():
    blank = np.full((STRIP_H, STRIP_W), BG, dtype=np.float32)
    assert detect_card_boxes(blank) == []


def test_never_returns_more_than_five():
    boxes = detect_card_boxes(make_strip(5), max_cards=3)
    assert len(boxes) <= 3


def test_vertical_trim_excludes_empty_margins():
    strip = make_strip(2)
    boxes = detect_card_boxes(strip)
    assert boxes
    for box in boxes:
        assert box.y >= 10
        assert box.bottom <= STRIP_H - 5
        assert box.h < STRIP_H


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_detect_statlocker_cards_variable_counts(count):
    # Create an RGB strip with `count` distinct card regions
    width = 740
    height = 185
    rgb = np.full((height, width, 3), 26, dtype=np.uint8)
    stride = width // count
    card_w = stride - 6
    for i in range(count):
        x = i * stride + 4
        # Add high intensity icon/text patch (> 50)
        rgb[30:150, x + 10 : x + min(card_w - 10, 100)] = 120
    boxes = detect_statlocker_cards(rgb, scale=1.0, max_cards=5)
    assert len(boxes) == count, f"expected {count} cards, got {len(boxes)}"
