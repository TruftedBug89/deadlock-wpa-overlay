"""Screen-reader helpers that do not need a live Statlocker window.

The OCR tests skip themselves when Windows' WinRT OCR is unavailable, so the
suite stays green on a machine without the optional ``winrt`` wheels installed.
"""

import numpy as np
import pytest
import os

import live_screen_reader

from live_screen_reader import (
    _HAS_WINRT,
    _get_ocr_engine,
    _looks_empty,
    clean_card_text,
    filter_plausible_cards,
    header_is_genuine,
    looks_like_item_name,
    match_catalog_item,
    row_region_is_clipped,
)
from card_detector import CardBox
from template_match import TemplateHit

CATALOG = [
    {"name": "Silencer"},
    {"name": "Siphon Bullets"},
    {"name": "Diviner's Kevlar"},
    {"name": "Inhibitor"},
    {"name": "Mercurial Magnum"},
]


def test_clean_card_text_strips_stat_markers():
    assert clean_card_text("SILENCER WPA +2.3% USUALLY 34:31") == "SILENCER"
    assert clean_card_text("SIPHON BULLE... WPA +2.2% USUALLY 34:04") == "SIPHON BULLE"
    assert clean_card_text(")IVINER'S KEV... WPA +2.2% USUALLY 26:54") == "IVINER'S KEV"


def test_clean_card_text_edge_cases():
    # Leading punctuation & noise
    assert clean_card_text(")DIVINER'S KEVLAR") == "DIVINER'S KEVLAR"
    assert clean_card_text(") INHIBITOR") == "INHIBITOR"
    assert clean_card_text('"SILENCER"') == "SILENCER"
    assert clean_card_text("'SILENCER'") == "SILENCER"
    assert clean_card_text("“SILENCER”") == "SILENCER"
    assert clean_card_text("‘DIVINER'S KEVLAR’") == "DIVINER'S KEVLAR"
    assert clean_card_text("(INHIBITOR)") == "INHIBITOR"
    assert clean_card_text("[INHIBITOR]") == "INHIBITOR"
    assert clean_card_text(":SILENCER:") == "SILENCER"
    assert clean_card_text("- SILENCER -") == "SILENCER"

    # Trailing dots & ellipsis
    assert clean_card_text("SILENCER.") == "SILENCER"
    assert clean_card_text("SILENCER...") == "SILENCER"
    assert clean_card_text("SILENCER…") == "SILENCER"

    # Timestamps without "USUALLY"
    assert clean_card_text("SILENCER 34:31") == "SILENCER"
    assert clean_card_text("SILENCER ~34:31") == "SILENCER"
    assert clean_card_text("DIVINER'S KEVLAR 26:54") == "DIVINER'S KEVLAR"
    assert clean_card_text("SILENCER 34M") == "SILENCER"

    # Preserves words containing WIN and RATE
    assert clean_card_text("SLOWING BULLETS WPA +2.3% USUALLY 34:31") == "SLOWING BULLETS"
    assert clean_card_text("SERRATED KNIVES WPA +1.9% USUALLY 20:10") == "SERRATED KNIVES"
    assert clean_card_text("SLOWING HEX WPA +3.0%") == "SLOWING HEX"
    assert clean_card_text("SERAPHIM WINGS WPA +2.5%") == "SERAPHIM WINGS"

    # Curly apostrophe & digit confusion
    assert clean_card_text("DIVINER’S KEVLAR") == "DIVINER'S KEVLAR"
    assert clean_card_text("S1LENCER WPA +2.3%") == "SILENCER"
    assert clean_card_text("1NHIBITOR WPA +1.8%") == "INHIBITOR"

    # CAN BUY badge & stat markers
    assert clean_card_text("CAN BUY SPIRIT SHREDDER AHEAD +0.9%") == "SPIRIT SHREDDER"
    assert clean_card_text("CANBUY FLEETFOOT ANEAD +0.5%") == "FLEETFOOT"
    assert clean_card_text("CAN BUY MELEE CHARGE AHEAD +0.5%") == "MELEE CHARGE"
    assert clean_card_text("CAN BUY OUNDLESS S... WPA +3.0%") == "OUNDLESS S"


def test_clean_card_text_tolerates_empty_input():
    assert clean_card_text("") == ""
    assert clean_card_text("WPA +1.0%") == ""


def test_match_exact_and_truncated_names():
    item, score = match_catalog_item("SILENCER", CATALOG)
    assert item["name"] == "Silencer"
    assert score >= 0.9

    item, score = match_catalog_item("SIPHON BULLE", CATALOG)
    assert item["name"] == "Siphon Bullets"
    assert score >= 0.9

    item, score = match_catalog_item("DIVINER'S KEV", CATALOG)
    assert item["name"] == "Diviner's Kevlar"
    assert score >= 0.9


def test_match_single_character_ocr_noise():
    item, score = match_catalog_item("NHIBITOR", CATALOG)
    assert item["name"] == "Inhibitor"
    assert score >= 0.8

    # Missing leading D and missing apostrophe
    item, score = match_catalog_item("IVINERS KEV", CATALOG)
    assert item["name"] == "Diviner's Kevlar"
    assert score >= 0.85

    # Truncated without apostrophe
    item, score = match_catalog_item("DIVINERS KEV", CATALOG)
    assert item["name"] == "Diviner's Kevlar"
    assert score >= 0.95


def test_match_all_five_statlocker_cards():
    raw_cards = [
        "SILENCER WPA +2.3% USUALLY 34:31",
        "SIPHON BULLE... WPA +2.2% USUALLY 34:04",
        ")IVINER'S KEV... WPA +2.2% USUALLY 26:54",
        "NHIBITOR WPA +1.8% 24:15",
        "MERCURIAL MAG... +3.1%",
    ]
    expected = [
        "Silencer",
        "Siphon Bullets",
        "Diviner's Kevlar",
        "Inhibitor",
        "Mercurial Magnum",
    ]
    for raw, exp_name in zip(raw_cards, expected):
        cleaned = clean_card_text(raw)
        assert looks_like_item_name(cleaned), f"Failed looks_like_item_name: {cleaned!r}"
        item, score = match_catalog_item(cleaned, CATALOG)
        assert item is not None, f"Failed to match {cleaned!r}"
        assert item["name"] == exp_name, f"Expected {exp_name}, got {item['name']}"
        assert score >= 0.72, f"Score {score} below minimum threshold for {exp_name}"


def test_ocr_lock_is_reentrant_and_thread_safe():
    import threading
    from live_screen_reader import _OCR_LOCK

    # RLock must allow re-entrant acquisition on the same thread
    with _OCR_LOCK:
        with _OCR_LOCK:
            pass

    # Thread safety check
    order = []

    def worker(num):
        with _OCR_LOCK:
            order.append(num)

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(order) == 2


def test_match_returns_none_for_short_text():
    assert match_catalog_item("", CATALOG) == (None, 0.0)
    assert match_catalog_item("XX", CATALOG) == (None, 0.0)


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="Native Windows OCR needs an interactive desktop; parser logic is tested with mocks")
def test_engine_availability_is_reported_honestly():
    if not _HAS_WINRT:
        assert _get_ocr_engine() is None
    else:
        engine = _get_ocr_engine()
        # None is possible when no OCR language pack is installed.
        assert engine is None or hasattr(engine, "recognize_async")


@pytest.mark.skipif(not _HAS_WINRT, reason="winrt OCR not installed")
@pytest.mark.skipif(bool(os.environ.get("CI")), reason="Native Windows OCR needs an interactive desktop; parser logic is tested with mocks")
def test_engine_initialises_when_winrt_exists():
    engine = _get_ocr_engine()
    if engine is None:
        pytest.skip("no Windows OCR language pack")
    assert hasattr(engine, "recognize_async")


def _header(width: int = 104, height: int = 27) -> TemplateHit:
    return TemplateHit(x=100, y=50, score=1.0, scale=1.0, width=width, height=height)


def test_projected_row_is_not_clipped():
    assert not row_region_is_clipped((90, 110, 915, 351), _header())


def test_narrow_row_is_rejected_as_clipped():
    # Real-world false positive: a 183 px crop under a 104 px heading inside a
    # browser advertisement thumbnail.
    assert row_region_is_clipped((1753, 315, 183, 351), _header())


def test_short_row_is_rejected_as_clipped():
    assert row_region_is_clipped((90, 110, 915, 60), _header())


def test_single_tall_sliver_is_not_a_card():
    sliver = CardBox(x=0, y=0, w=122, h=351, activity=0.5)
    assert filter_plausible_cards([sliver], _header()) == []


def test_plausible_cards_survive_filtering():
    boxes = [
        CardBox(x=0, y=0, w=150, h=200, activity=0.4),
        CardBox(x=160, y=0, w=150, h=200, activity=0.4),
    ]
    assert filter_plausible_cards(boxes, _header()) == boxes


def test_slivers_narrower_than_the_heading_are_dropped():
    narrow = CardBox(x=0, y=0, w=40, h=60, activity=0.3)
    assert filter_plausible_cards([narrow], _header()) == []


def test_oversized_table_blob_is_not_a_card():
    # Real-world false positive: the whole post-match scoreboard was segmented
    # as a single 823x351 box.
    table = CardBox(x=0, y=0, w=823, h=351, activity=0.6)
    assert filter_plausible_cards([table], _header()) == []


def test_item_name_gate_accepts_real_names():
    for name in ("SILENCER", "DIVINER'S KEV", "SIPHON BULLE", "MYSTIC REGENERATION"):
        assert looks_like_item_name(name), name


def test_item_name_gate_rejects_scoreboard_text():
    scoreboard = (
        "MVP SOULS 111K 118K 86K K 26 10 14 14 12 D 11 13 13 7 20 A 20 39 34 23 23 "
        "DMG 108K 103K 120K 56K 103K OBJ 9.4K 14K LLK 12K HEAL 13K 37K 52K 36K ITEMS"
    )
    assert not looks_like_item_name(scoreboard)


def test_item_name_gate_rejects_digits_and_fragments():
    assert not looks_like_item_name("34:31")
    assert not looks_like_item_name("WPA +2.3%")
    assert not looks_like_item_name("")
    assert not looks_like_item_name("AB")


def test_exact_header_match_is_trusted_without_ocr():
    frame = np.zeros((80, 220, 3), dtype=np.uint8)
    header = TemplateHit(x=10, y=10, score=0.95, scale=1.0, width=104, height=27)
    assert header_is_genuine(frame, header, object())


def test_weak_header_match_requires_legible_text(monkeypatch):
    frame = np.zeros((80, 220, 3), dtype=np.uint8)
    header = TemplateHit(x=10, y=10, score=0.73, scale=1.0, width=104, height=27)

    async def comparison_text(_images, _engine):
        return ["MVP COMPARISON"]

    monkeypatch.setattr(live_screen_reader, "_ocr_many", comparison_text)
    assert not header_is_genuine(frame, header, object())

    async def heading_text(_images, _engine):
        return ["WPA ITEMS"]

    monkeypatch.setattr(live_screen_reader, "_ocr_many", heading_text)
    assert header_is_genuine(frame, header, object())


def test_looks_empty_detects_empty_phrase(monkeypatch):
    async def mock_ocr(*_args, **_kwargs):
        return "No item stands out on win rate right now"

    monkeypatch.setattr(live_screen_reader, "_ocr_image_async", mock_ocr)
    dummy_frame = np.zeros((100, 300, 3), dtype=np.uint8)
    dummy_header = TemplateHit(x=10, y=10, score=1.0, scale=1.0, width=104, height=27)
    assert _looks_empty(dummy_frame, dummy_header, object()) is True


def test_detect_empty_state_pick_build(monkeypatch):
    async def mock_ocr(*_args, **_kwargs):
        return "Pick a build in the Selected Build panel."

    monkeypatch.setattr(live_screen_reader, "_ocr_image_async", mock_ocr)
    dummy_frame = np.zeros((100, 300, 3), dtype=np.uint8)
    dummy_header = TemplateHit(x=10, y=10, score=1.0, scale=1.0, width=104, height=27)
    assert live_screen_reader._detect_empty_state(dummy_frame, dummy_header, object()) == "empty_pick_build"
    assert _looks_empty(dummy_frame, dummy_header, object()) is True


def test_empty_state_does_not_trigger_on_normal_card_win_rate():
    dummy_img = np.zeros((50, 100, 3), dtype=np.uint8)
    # A card that happens to have "WIN RATE +1.5%" must not match empty phrases
    text = "cultist sacrifice wpa +1.5% win rate usually 15:00"
    for phrase in live_screen_reader._EMPTY_PHRASES:
        assert phrase not in text, f"Card text unexpectedly matched empty phrase: {phrase}"


def test_read_live_wpa_screen_detects_empty_without_header(monkeypatch):
    dummy_frame = np.zeros((500, 800, 3), dtype=np.uint8)
    cf = live_screen_reader.CapturedFrame(hwnd=1, rgb=dummy_frame, rect=(0, 0, 800, 500))
    monkeypatch.setattr(live_screen_reader, "capture_statlocker_frame", lambda: cf)
    monkeypatch.setattr(live_screen_reader, "locate_wpa_header", lambda _f: None)

    async def mock_ocr(*_args, **_kwargs):
        return "Pick a build in the Selected Build panel."

    monkeypatch.setattr(live_screen_reader, "_ocr_image_async", mock_ocr)
    monkeypatch.setattr(live_screen_reader, "_get_ocr_engine", lambda: object())

    res = live_screen_reader.read_live_wpa_screen([])
    assert res.status == "empty_pick_build"


def test_read_live_wpa_screen_detects_no_items_without_header(monkeypatch):
    dummy_frame = np.zeros((500, 800, 3), dtype=np.uint8)
    cf = live_screen_reader.CapturedFrame(hwnd=1, rgb=dummy_frame, rect=(0, 0, 800, 500))
    monkeypatch.setattr(live_screen_reader, "capture_statlocker_frame", lambda: cf)
    monkeypatch.setattr(live_screen_reader, "locate_wpa_header", lambda _f: None)

    async def mock_ocr(*_args, **_kwargs):
        return "No item stands out on win rate right now"

    monkeypatch.setattr(live_screen_reader, "_ocr_image_async", mock_ocr)
    monkeypatch.setattr(live_screen_reader, "_get_ocr_engine", lambda: object())

    res = live_screen_reader.read_live_wpa_screen([])
    assert res.status == "empty_no_items"


def test_read_live_wpa_screen_ocr_header_fallback(monkeypatch):
    dummy_frame = np.zeros((500, 800, 3), dtype=np.uint8)
    cf = live_screen_reader.CapturedFrame(hwnd=1, rgb=dummy_frame, rect=(0, 0, 800, 500))
    monkeypatch.setattr(live_screen_reader, "capture_statlocker_frame", lambda: cf)
    monkeypatch.setattr(live_screen_reader, "locate_wpa_header", lambda _f: None)

    # Empty check returns None, then OCR finds header
    monkeypatch.setattr(live_screen_reader, "_detect_empty_state", lambda *_args, **_kwargs: None)
    header_hit = TemplateHit(x=100, y=100, score=0.95, scale=1.0, width=104, height=27)
    monkeypatch.setattr(live_screen_reader, "_locate_header_via_ocr", lambda *_a: header_hit)
    monkeypatch.setattr(live_screen_reader, "header_is_genuine", lambda *_a: True)
    monkeypatch.setattr(live_screen_reader, "detect_statlocker_cards", lambda *_a, **_k: [
        live_screen_reader.CardBox(x=0, y=0, w=100, h=100)
    ])
    monkeypatch.setattr(live_screen_reader, "_ocr_card_row", lambda *_a, **_k: [
        live_screen_reader.CardRead(index=0, box=live_screen_reader.CardBox(x=0, y=0, w=100, h=100), item={"name": "Silencer"}, score=1.0)
    ])
    monkeypatch.setattr(live_screen_reader, "_get_ocr_engine", lambda: object())

    res = live_screen_reader.read_live_wpa_screen([{"name": "Silencer"}])
    assert res.status == "ok"
    assert res.names == ["Silencer"]
