"""Reads the live WPA recommendation row out of Statlocker with OCR.

Pipeline: capture window -> locate "WPA ITEMS" -> crop row -> detect 1..5 cards
-> OCR each card -> fuzzy-match against local catalog. Never fabricates guesses.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from card_detector import CardBox, detect_card_boxes, detect_statlocker_cards
from template_match import TemplateHit
from wpa_detector import CapturedFrame, capture_statlocker_frame, locate_wpa_header

# Re-export engine and matcher primitives so callers and tests retain full compatibility.
from ocr_engine import (
    _HAS_WINRT,
    _OCR_ENGINE,
    _OCR_INIT_LOCK,
    _OCR_LOCK,
    _get_ocr_engine,
    _ocr_image_async,
    _ocr_result_async,
    _run_ocr,
    get_ocr_engine,
    ocr_image_async,
    ocr_result_async,
    run_ocr,
)
from ocr_matcher import (
    _EMPTY_PHRASES,
    # Near-exact threshold used when the candidate pool is Statlocker's own
    # WPA list: a garbled card is dropped rather than mislabelled.
    _RESTRICTED_MIN_SCORE,
    _HEADER_EXACT_SCORE,
    _MAX_ITEM_NAME_CHARS,
    _MAX_ITEM_NAME_WORDS,
    _MIN_MATCH_SCORE,
    _STAT_MARKER_RE,
    _rank_catalog_matches,
    clean_card_text,
    looks_like_item_name,
    match_catalog_item,
    match_catalog_item_ex,
)


@dataclass
class CardRead:
    """OCR result for a single detected card."""
    index: int
    box: CardBox
    raw_text: str = ""
    cleaned_text: str = ""
    item: Optional[dict] = None
    score: float = 0.0
    ambiguous: bool = False

    @property
    def name(self) -> Optional[str]:
        return self.item.get("name") if self.item else None


@dataclass
class ScreenReadResult:
    """Outcome of one live screen scan."""
    status: str = "not_visible"  # ok | empty | unresolved | not_visible | error
    cards: List[CardRead] = field(default_factory=list)
    header: Optional[TemplateHit] = None
    frame_method: str = ""
    region: Optional[Tuple[int, int, int, int]] = None
    error: Optional[str] = None
    frame: Optional[object] = None  # CapturedFrame, diagnostics only

    @property
    def names(self) -> List[str]:
        return [card.name for card in self.cards if card.name]

    @property
    def detected(self) -> int:
        return len(self.cards)

    @property
    def resolved(self) -> int:
        return len(self.names)


_MIN_ROW_WIDTH_RATIO, _MIN_ROW_HEIGHT_RATIO = 2.2, 3.0
_MIN_CARD_ASPECT, _MAX_CARD_ASPECT = 0.55, 3.0
_MIN_CARD_WIDTH_RATIO, _MAX_CARD_WIDTH_RATIO = 0.5, 4.0
_MAX_CARD_HEIGHT_RATIO = 12.0


def _row_region(frame: CapturedFrame, header: TemplateHit) -> Tuple[int, int, int, int]:
    """Pixel rectangle of the card row, derived from the detected heading size."""
    x0 = max(0, header.x - int(header.width * 0.10))
    y0 = min(frame.rgb.shape[0] - 2, header.y + int(header.height * 2.2))
    width = min(frame.rgb.shape[1] - x0, int(header.width * 8.8))
    height = min(frame.rgb.shape[0] - y0, int(header.height * 7.0))
    return (x0, y0, max(16, width), max(16, height))


def row_region_is_clipped(region: Sequence[int], header: TemplateHit) -> bool:
    """True when the auto-detected row is cut off by the window edge."""
    _x, _y, width, height = region
    return width < int(header.width * _MIN_ROW_WIDTH_RATIO) or height < int(header.height * _MIN_ROW_HEIGHT_RATIO)


def filter_plausible_cards(boxes: Sequence[CardBox], header: TemplateHit) -> List[CardBox]:
    """Drop boxes whose shape cannot be a recommendation card."""
    min_w, max_w = max(8, int(header.width * _MIN_CARD_WIDTH_RATIO)), max(9, int(header.width * _MAX_CARD_WIDTH_RATIO))
    max_h = max(8, int(header.height * _MAX_CARD_HEIGHT_RATIO))
    return [b for b in boxes if min_w <= b.w <= max_w and 0 < b.h <= max_h and _MIN_CARD_ASPECT <= (b.w / float(b.h)) <= _MAX_CARD_ASPECT]


async def _ocr_many(images: Sequence[Image.Image], engine) -> List[str]:
    return [await _ocr_image_async(image, engine) for image in images]


def _ocr_text_sync(pil_img: Image.Image, engine, upscale: float = 1.0) -> str:
    """Synchronously get OCR text using _ocr_image_async under _OCR_LOCK."""
    if engine is None or pil_img.width < 2 or pil_img.height < 2:
        return ""
    with _OCR_LOCK:
        try:
            return asyncio.run(_ocr_image_async(pil_img, engine, upscale))
        except Exception:
            return ""


def header_is_genuine(frame_rgb: np.ndarray, header: TemplateHit, engine) -> bool:
    """Confirm that a heading match really reads as ``WPA ITEMS``."""
    if header.score >= _HEADER_EXACT_SCORE:
        return True
    x0, y0 = max(0, int(header.x)), max(0, int(header.y))
    x1, y1 = min(frame_rgb.shape[1], x0 + max(2, int(header.width))), min(frame_rgb.shape[0], y0 + max(2, int(header.height)))
    crop = frame_rgb[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    with _OCR_LOCK:
        try:
            text = asyncio.run(_ocr_many([Image.fromarray(crop, mode="RGB")], engine))[0].upper()
            return "WPA" in text and ("ITEM" in text or "ITM" in text)
        except Exception:
            return False


def _ocr_card_row(
    row_rgb: np.ndarray,
    boxes: Sequence[CardBox],
    engine,
    preferred_names: Optional[Iterable[str]],
    catalog_items: Sequence[dict],
    restrict_to: Optional[Iterable[str]] = None,
) -> List[CardRead]:
    """OCR every detected card and resolve it to a catalog item."""
    crops = [
        Image.fromarray(row_rgb[b.y : b.bottom, b.x : b.right], mode="RGB")
        if row_rgb[b.y : b.bottom, b.x : b.right].size > 0 else Image.new("RGB", (2, 2))
        for b in boxes
    ]
    with _OCR_LOCK:
        try:
            texts = asyncio.run(_ocr_many(crops, engine))
        except Exception:
            texts = ["" for _ in crops]

    reads: List[CardRead] = []
    for index, (box, text) in enumerate(zip(boxes, texts)):
        cleaned = clean_card_text(text)
        item, score, ambiguous = (None, 0.0, False)
        if looks_like_item_name(cleaned):
            item, score, ambiguous = match_catalog_item_ex(
                cleaned, catalog_items, preferred_names, restrict_to=restrict_to
            )
            required = _RESTRICTED_MIN_SCORE if restrict_to is not None else _MIN_MATCH_SCORE
            if score < required:
                item, score, ambiguous = None, score, False
        reads.append(CardRead(
            index=index, box=box, raw_text=text, cleaned_text=cleaned,
            item=item, score=score, ambiguous=ambiguous,
        ))
    return reads


def _locate_header_via_ocr(frame_rgb: np.ndarray, engine) -> Optional[TemplateHit]:
    if engine is None or frame_rgb is None or frame_rgb.size == 0:
        return None
    try:
        crop = frame_rgb[: int(frame_rgb.shape[0] * 0.75), :]
        res = _run_ocr(Image.fromarray(crop, mode="RGB"), engine)
        if not res or not res.lines:
            return None
        for line in res.lines:
            t = (line.text or "").upper()
            if "WPA" in t and ("ITEM" in t or "ITM" in t or len(t) < 16):
                for word in line.words:
                    if "WPA" in word.text.upper():
                        r = word.bounding_rect
                        return TemplateHit(
                            x=int(r.x),
                            y=int(r.y),
                            score=0.92,
                            scale=1.0,
                            width=max(104, int(r.width * 3.0)),
                            height=max(27, int(r.height)),
                        )
    except Exception:
        pass
    return None


def _detect_empty_state(image_or_frame: np.ndarray, header_or_engine, maybe_engine=None) -> Optional[str]:
    """Check informational empty-state messages directly below the header or in frame."""
    if image_or_frame is None or image_or_frame.size == 0:
        return None
    if maybe_engine is not None:
        header, engine = header_or_engine, maybe_engine
        y0, y1 = int(header.y + header.height), min(image_or_frame.shape[0], int(header.y + header.height * 7.5))
        x0, x1 = max(0, int(header.x - header.width * 0.50)), min(image_or_frame.shape[1], int(header.x + header.width * 8.5))
        if y1 <= y0 or x1 <= x0:
            return None
        strip = image_or_frame[y0:y1, x0:x1]
    else:
        engine, strip = header_or_engine, image_or_frame
    if engine is None or strip.size == 0:
        return None
    text = _ocr_text_sync(Image.fromarray(strip, mode="RGB"), engine, upscale=1.0).lower()
    if not text:
        return None
    for p in ("pick a build", "selected build", "build panel"):
        if p in text:
            return "empty_pick_build"
    for p in _EMPTY_PHRASES:
        if p in text:
            return "empty_no_items"
    return None


def _recover_cards_from_row_ocr(
    row_rgb: np.ndarray,
    engine,
    preferred_names: Optional[Iterable[str]],
    catalog_items: Sequence[dict],
    restrict_to: Optional[Iterable[str]] = None,
) -> List[CardRead]:
    """Recover items directly from whole-row OCR when box segmentation misses."""
    res = _run_ocr(Image.fromarray(row_rgb, mode="RGB"), engine)
    if not res or not res.lines:
        return []
    candidates = []
    for line in res.lines:
        cleaned = clean_card_text(line.text)
        if looks_like_item_name(cleaned):
            item, score, amb = match_catalog_item_ex(
                cleaned, catalog_items, preferred_names, restrict_to=restrict_to
            )
            required = _RESTRICTED_MIN_SCORE if restrict_to is not None else _MIN_MATCH_SCORE
            if item and score >= required:
                r = line.words[0].bounding_rect
                box = CardBox(x=int(r.x), y=int(r.y), w=int(r.width), h=int(r.height))
                candidates.append((r.x, CardRead(index=0, box=box, raw_text=line.text, cleaned_text=cleaned, item=item, score=score, ambiguous=amb)))
    candidates.sort(key=lambda p: p[0])
    cards: List[CardRead] = []
    last_x = -999
    seen_names = set()
    for x, card in candidates:
        name = card.item["name"]
        if name not in seen_names and (x - last_x) > 35:
            card.index = len(cards)
            cards.append(card)
            seen_names.add(name)
            last_x = x
    return cards


def _looks_empty(image_or_frame: np.ndarray, header_or_engine, maybe_engine=None) -> bool:
    """True when any recognized empty-state phrase is visible below the header."""
    return _detect_empty_state(image_or_frame, header_or_engine, maybe_engine) is not None


def _unique_cards(cards: Sequence[CardRead]) -> List[CardRead]:
    """Keep one card per item name, re-indexed left to right."""
    kept: List[CardRead] = []
    seen = set()
    for card in sorted(cards, key=lambda c: c.box.x):
        name = card.name
        if name and name.lower() in seen:
            continue
        if name:
            seen.add(name.lower())
        card.index = len(kept)
        kept.append(card)
    return kept


def read_live_wpa_screen(
    catalog_items: Sequence[dict],
    *,
    region_override: Optional[dict] = None,
    preferred_names: Optional[Iterable[str]] = None,
    restrict_to: Optional[Iterable[str]] = None,
) -> ScreenReadResult:
    """Capture Statlocker and read every visible WPA card.

    When ``restrict_to`` is given (Statlocker's current WPA list), a card is
    only accepted if it matches one of those names, and anything else is
    dropped instead of being guessed.
    """
    frame = capture_statlocker_frame()
    if frame is None:
        return ScreenReadResult(status="not_visible", error="Statlocker window not capturable")
    engine = _get_ocr_engine()
    if engine is None:
        return ScreenReadResult(status="error", error="Windows OCR engine unavailable")

    if region_override:
        header = TemplateHit(
            x=int(region_override.get("x", 0)), y=int(region_override.get("y", 0)),
            score=1.0, scale=1.0,
            width=int(region_override.get("w", 760)), height=int(region_override.get("h", 265)),
        )
        x0, y0 = max(0, min(header.x, frame.rgb.shape[1] - 16)), max(0, min(header.y, frame.rgb.shape[0] - 16))
        region = (x0, y0, max(16, min(frame.rgb.shape[1] - x0, header.width)), max(16, min(frame.rgb.shape[0] - y0, header.height)))
    else:
        header = locate_wpa_header(frame)
        if header is None:
            empty = _detect_empty_state(frame.rgb, engine)
            if empty:
                return ScreenReadResult(status=empty, frame_method=frame.method, frame=frame)
            header = _locate_header_via_ocr(frame.rgb, engine)
            if header is None:
                return ScreenReadResult(status="not_visible", frame_method=frame.method, error="WPA ITEMS heading not found")

        empty_reason = _detect_empty_state(frame.rgb, header, engine)
        if empty_reason:
            return ScreenReadResult(status=empty_reason, header=header, frame_method=frame.method, frame=frame)
        if not header_is_genuine(frame.rgb, header, engine):
            return ScreenReadResult(status="not_visible", header=header, frame_method=frame.method, error="WPA ITEMS heading is not legible at the matched position")
        region = _row_region(frame, header)
        if row_region_is_clipped(region, header):
            return ScreenReadResult(status="not_visible", header=header, frame_method=frame.method, region=region, error="WPA ITEMS row is clipped at the window edge")

    x0, y0, width, height = region
    row = frame.rgb[y0 : y0 + height, x0 : x0 + width]
    if row.size == 0:
        return ScreenReadResult(status="error", header=header, error="Empty capture region")

    empty_reason = _detect_empty_state(row, engine)
    if empty_reason:
        return ScreenReadResult(status=empty_reason, header=header, frame_method=frame.method, region=region, frame=frame)

    boxes = detect_statlocker_cards(row, header.scale if header else 1.0, max_cards=5)
    gray = row.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    if not boxes:
        boxes = filter_plausible_cards(detect_card_boxes(gray, max_cards=5), header)

    cards = _ocr_card_row(row, boxes, engine, preferred_names, catalog_items, restrict_to)
    if not any(card.name for card in cards):
        recovered = _recover_cards_from_row_ocr(row, engine, preferred_names, catalog_items, restrict_to)
        if any(c.name for c in recovered):
            cards = recovered
        else:
            alt = filter_plausible_cards(detect_card_boxes(gray, max_cards=5), header)
            if alt and alt != boxes:
                alt_cards = _ocr_card_row(row, alt, engine, preferred_names, catalog_items, restrict_to)
                if any(c.name for c in alt_cards):
                    cards = alt_cards

    if not any(card.name for card in cards):
        card_all = " ".join((c.raw_text or "") for c in cards).lower()
        for phrase in ("pick a build", "selected build", "build panel"):
            if phrase in card_all:
                return ScreenReadResult(status="empty_pick_build", cards=cards, header=header, frame_method=frame.method, region=region, frame=frame)
        for phrase in _EMPTY_PHRASES:
            if phrase in card_all:
                return ScreenReadResult(status="empty_no_items", cards=cards, header=header, frame_method=frame.method, region=region, frame=frame)

    cards = _unique_cards(cards)
    return ScreenReadResult(
        status="ok" if any(card.name for card in cards) else "unresolved",
        cards=cards, header=header, frame_method=frame.method, region=region, frame=frame,
    )


def read_live_wpa_items(catalog_items: Sequence[dict]) -> Tuple[bool, List[str]]:
    """Backwards-compatible wrapper: ``(is_empty_state, item_names)``."""
    result = read_live_wpa_screen(catalog_items)
    return (result.status == "empty", result.names)
