"""Icon resolution tests that do not need a Tk root."""

from pathlib import Path

import pytest

from icon_loader import (
    _candidate_filenames,
    _generate_fallback_icon,
    find_local_icon,
    normalize_item_name,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Diviner's Kevlar", "diviners_kevlar"),
        ("Siphon Bullets", "siphon_bullets"),
        ("  Mystic  Shot  ", "mystic_shot"),
        ("", ""),
    ],
)
def test_normalize_item_name(name, expected):
    assert normalize_item_name(name) == expected


def test_candidate_filenames_cover_catalog_variants():
    candidates = _candidate_filenames("Diviner's Kevlar", "upgrade_kevlar", "https://x/abc_icon.png")
    assert "diviners_kevlar.png" in candidates
    assert "diviner's_kevlar.png" in candidates
    assert "upgrade_kevlar.png" in candidates
    assert "kevlar.png" in candidates  # class name without the upgrade_ prefix
    assert "abc_icon.png" in candidates


def test_fallback_icon_is_explicitly_synthetic():
    image = _generate_fallback_icon("Mystic Unknown Item", size=34, category="spirit")
    assert image.size == (34, 34)
    assert image.mode == "RGBA"


def test_missing_icon_returns_none(tmp_path, monkeypatch):
    import icon_loader

    monkeypatch.setattr(icon_loader, "BUNDLED_ICONS_DIR", tmp_path / "bundled")
    monkeypatch.setattr(icon_loader, "LOCAL_CACHE_DIR", tmp_path / "cache")
    assert find_local_icon("Definitely Not An Item") is None
