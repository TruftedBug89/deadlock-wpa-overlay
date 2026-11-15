"""Unit tests for OCR text cleaning, gating, and catalog fuzzy matching."""

from ocr_matcher import (
    _EMPTY_PHRASES,
    _rank_catalog_matches,
    clean_card_text,
    looks_like_item_name,
    match_catalog_item,
    match_catalog_item_ex,
)

CATALOG = [
    {"name": "Silencer", "type": "upgrade"},
    {"name": "Siphon Bullets", "type": "upgrade"},
    {"name": "Diviner's Kevlar", "type": "upgrade"},
    {"name": "Inhibitor", "type": "upgrade"},
    {"name": "Mercurial Magnum", "type": "upgrade"},
    {"name": "Warp Stone", "type": "upgrade"},
    {"name": "Arcane Surge", "type": "upgrade"},
    {"name": "Glass Cannon", "type": "upgrade"},
    {"name": "Hero Ability", "type": "ability"},  # Non-upgrade, should be ignored
]


def test_clean_card_text_can_buy_edge_cases():
    # Leading newline before CAN BUY
    assert clean_card_text("\nCAN BUY\nSIPHON BULLETS") == "SIPHON BULLETS"
    # Leading spaces before CAN BUY
    assert clean_card_text("  CAN BUY  SIPHON BULLETS") == "SIPHON BULLETS"
    # Trailing newline after CAN BUY
    assert clean_card_text("SIPHON BULLETS\nCAN BUY\n") == "SIPHON BULLETS"
    # CAN BUY at both ends
    assert clean_card_text("CAN BUY\nSIPHON BULLETS\nCAN BUY") == "SIPHON BULLETS"
    # Fused CANBUY
    assert clean_card_text("CANBUY FLEETFOOT") == "FLEETFOOT"
    # Standalone CAN at boundaries
    assert clean_card_text("CAN SIPHON BULLETS") == "SIPHON BULLETS"
    assert clean_card_text("SIPHON BULLETS CAN") == "SIPHON BULLETS"
    # Does NOT strip 'CAN' inside real item words (Arcane Surge, Glass Cannon)
    assert clean_card_text("ARCANE SURGE") == "ARCANE SURGE"
    assert clean_card_text("GLASS CANNON") == "GLASS CANNON"


def test_clean_card_text_stat_markers_and_noise():
    assert clean_card_text("SILENCER WPA +2.3% USUALLY 34:31") == "SILENCER"
    assert clean_card_text("SIPHON BULLE... WPA +2.2% USUALLY 34:04") == "SIPHON BULLE"
    assert clean_card_text('"DIVINER\'S KEVLAR"') == "DIVINER'S KEVLAR"
    assert clean_card_text("") == ""
    assert clean_card_text("WPA +1.0%") == ""


def test_looks_like_item_name():
    assert looks_like_item_name("SILENCER")
    assert looks_like_item_name("SIPHON BULLETS")
    assert looks_like_item_name("DIVINER'S KEVLAR")
    assert not looks_like_item_name("")
    assert not looks_like_item_name("AB")  # Too short (< 3 chars)
    assert not looks_like_item_name("12345")  # No letters
    assert not looks_like_item_name("THIS IS A RIDICULOUSLY LONG ITEM NAME WITH TOO MANY WORDS")


def test_rank_catalog_matches_normalized_prefix():
    # Item with spaces (Warp Stone -> WARPSTONE) matching OCR with extra tokens (WARP STONE TIER 2)
    matches = _rank_catalog_matches("WARP STONE TIER 2", CATALOG)
    assert matches
    top_item, score = matches[0]
    assert top_item["name"] == "Warp Stone"
    assert score >= 0.96

    # Preferred name boost
    matches_boosted = _rank_catalog_matches("WARP STONE TIER 2", CATALOG, preferred_names=["Warp Stone"])
    assert matches_boosted[0][1] >= score


def test_match_catalog_item_ignores_non_upgrades():
    item, score = match_catalog_item("HERO ABILITY", CATALOG)
    # Should not match 'Hero Ability' because its type is 'ability', not 'upgrade'
    assert item is None or item["name"] != "Hero Ability"


def test_match_catalog_item_ex_ambiguity():
    # Two similar items
    ambiguous_catalog = [
        {"name": "Bullet Armor", "type": "upgrade"},
        {"name": "Spirit Armor", "type": "upgrade"},
    ]
    item, score, ambiguous = match_catalog_item_ex("ARMOR", ambiguous_catalog)
    assert item is not None
    # Both match equally with score 0.90, so ambiguous should be True
    assert ambiguous is True


def test_empty_phrases():
    assert "no item stands out" in _EMPTY_PHRASES
    assert "pick a build" in _EMPTY_PHRASES


def test_restrict_to_only_allows_current_wpa_names():
    # Normally a garbled card still resolves to its closest catalog item.
    item, score = match_catalog_item("SILENCER", CATALOG)
    assert item and item["name"] == "Silencer"

    # Restricted to Statlocker's current list, an off-list name is rejected
    # instead of being guessed.
    item, score, ambiguous = match_catalog_item_ex(
        "SILENCER", CATALOG, restrict_to=["Fortitude", "Warp Stone"]
    )
    assert item is None
    assert score == 0.0
    assert ambiguous is False


def test_restrict_to_keeps_allowed_names():
    item, score = match_catalog_item("WARP STONE", CATALOG, restrict_to=["Warp Stone"])
    assert item and item["name"] == "Warp Stone"
    assert score >= 0.9


def test_restrict_to_case_insensitive():
    item, _score = match_catalog_item("SIPHON BULLETS", CATALOG, restrict_to=["siphon bullets"])
    assert item and item["name"] == "Siphon Bullets"
