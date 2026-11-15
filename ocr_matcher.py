"""Item name extraction and fuzzy catalog matching for OCR results."""

import difflib
import re
from typing import Iterable, List, Optional, Sequence, Tuple

_MIN_MATCH_SCORE = 0.72
# Restricted reads (Statlocker's own WPA list) demand near-exact card text.
_RESTRICTED_MIN_SCORE = 0.90
_HEADER_EXACT_SCORE = 0.90
_MAX_ITEM_NAME_CHARS = 34
_MAX_ITEM_NAME_WORDS = 5
_EMPTY_PHRASES = (
    "no item stands out",
    "stands out",
    "no item",
    "no recommendation",
    "not enough data",
    "check back",
    "pick a build",
    "selected build",
    "build panel",
)

_STAT_MARKER_RE = re.compile(
    r"(?:"
    r"\b(?:WPA|USUALLY|USUAL|WIN\s*RATE|WINRATE|WIN|RATE|BEHIND|AHEAD|ANEAD|LEAD|DEFICIT)\b"
    r"|[+%]"
    r"|\b~?\d{1,2}:\d{2}(?::\d{2})?\b"
    r"|\b~?\d{1,2}\s*(?:M|MIN|MINS)\b"
    r"|\b\d+(?:\.\d+)?%"
    r")",
    re.IGNORECASE,
)


def clean_card_text(text: str) -> str:
    """Extract item name from a card's OCR text, stripping stats and noise."""
    if not text:
        return ""
    upper = (
        text.upper()
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("…", "...")
    )
    upper = re.sub(r"\b0(?=[A-Z]{2,}\b)", "O", upper)
    upper = re.sub(r"\b1(?=[A-Z]{2,}\b)", "I", upper)
    upper = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", upper)
    upper = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", upper)

    match = _STAT_MARKER_RE.search(upper)
    if match:
        upper = upper[: match.start()]

    upper = re.sub(r"[|\[\]{}<>_~`\"#*^/\\:]+", " ", upper)
    upper = re.sub(r"\b(?:CAN\s*BUY|CANBUY)\b", " ", upper)
    upper = re.sub(r"^\s*CAN\b|\bCAN\s*$", " ", upper)
    upper = re.sub(r"\b\d+\b", " ", upper)
    upper = re.sub(r"^[^A-Z0-9]+|[^A-Z0-9]+$", "", upper)
    return re.sub(r"\s{2,}", " ", upper).strip()


def looks_like_item_name(text: str) -> bool:
    """Check if cleaned text resembles a plausible Deadlock item name."""
    name = (text or "").strip()
    if not 3 <= len(name) <= _MAX_ITEM_NAME_CHARS:
        return False
    words = name.split()
    if not words or len(words) > _MAX_ITEM_NAME_WORDS:
        return False
    letters = sum(1 for char in name if char.isalpha())
    visible = sum(1 for char in name if not char.isspace())
    digits = sum(1 for char in name if char.isdigit())
    return visible > 0 and letters >= max(3, int(visible * 0.7)) and digits <= 1


def _rank_catalog_matches(
    ocr_name: str,
    catalog_items: Sequence[dict],
    preferred_names: Optional[Iterable[str]] = None,
    restrict_to: Optional[Iterable[str]] = None,
) -> List[Tuple[dict, float]]:
    """Rank catalog items by similarity to an OCR'd card name.

    ``restrict_to`` hard-limits the candidates to the set Statlocker is
    currently recommending, so OCR noise can never invent a different item.
    """
    if not ocr_name or len(ocr_name) < 3:
        return []
    preferred = {name.lower() for name in (preferred_names or [])}
    allowed = {str(name).strip().lower() for name in (restrict_to or []) if str(name).strip()}
    scored: List[Tuple[dict, float]] = []
    norm_ocr = re.sub(r"[^A-Z0-9]+", "", ocr_name)

    for item in catalog_items:
        if item.get("type") and item.get("type") != "upgrade":
            continue
        item_name = (item.get("name") or "").upper()
        if not item_name:
            continue
        if allowed and item_name.lower() not in allowed:
            continue
        norm_item = re.sub(r"[^A-Z0-9]+", "", item_name)

        if item_name == ocr_name:
            ratio = 1.0
        elif item_name.startswith(ocr_name) or ocr_name.startswith(item_name) or norm_item == norm_ocr:
            ratio = 0.98
        elif norm_item.startswith(norm_ocr) or norm_ocr.startswith(norm_item):
            ratio = 0.96
        elif item_name in ocr_name or ocr_name in item_name or norm_ocr in norm_item or norm_item in norm_ocr:
            ratio = 0.90
        else:
            first_word = item_name.split()[0]
            ratio = max(
                difflib.SequenceMatcher(None, item_name, ocr_name).ratio(),
                difflib.SequenceMatcher(None, first_word, ocr_name).ratio(),
                difflib.SequenceMatcher(None, norm_item, norm_ocr).ratio(),
            )
            if len(ocr_name) <= _MAX_ITEM_NAME_CHARS and len(ocr_name.split()) <= _MAX_ITEM_NAME_WORDS:
                for token in (t for t in re.findall(r"[A-Z0-9']+", item_name) if len(t) >= 4):
                    if token in ocr_name or (len(token) >= 6 and token[1:] in ocr_name):
                        ratio = max(ratio, 0.85)

        if item_name.lower() in preferred:
            ratio = min(1.0, ratio + 0.02)
        if allowed and ratio < _RESTRICTED_MIN_SCORE:
            continue
        scored.append((item, ratio))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def match_catalog_item(
    ocr_name: str,
    catalog_items: Sequence[dict],
    preferred_names: Optional[Iterable[str]] = None,
    restrict_to: Optional[Iterable[str]] = None,
) -> Tuple[Optional[dict], float]:
    ranked = _rank_catalog_matches(ocr_name, catalog_items, preferred_names, restrict_to)
    return (ranked[0][0], ranked[0][1]) if ranked else (None, 0.0)


def match_catalog_item_ex(
    ocr_name: str,
    catalog_items: Sequence[dict],
    preferred_names: Optional[Iterable[str]] = None,
    restrict_to: Optional[Iterable[str]] = None,
) -> Tuple[Optional[dict], float, bool]:
    ranked = _rank_catalog_matches(ocr_name, catalog_items, preferred_names, restrict_to)
    if not ranked:
        return None, 0.0, False
    item, score = ranked[0]
    ambiguous = (
        len(ranked) > 1
        and abs(score - ranked[1][1]) <= 1e-6
        and item.get("name") != ranked[1][0].get("name")
        and score < 1.0
    )
    return item, score, ambiguous
