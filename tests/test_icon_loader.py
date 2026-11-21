"""Authentic shop artwork is cached by the catalog's exact URL."""

import io
import os

import pytest
from PIL import Image, ImageTk

import icon_loader

ART_ROOT = "https://assets-bucket.deadlock-api.com/assets-api-res/images/items/"
ITEM_ART = ART_ROOT + "weapon/shop_item.png"


@pytest.fixture
def disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(icon_loader, "LOCAL_CACHE_DIR", tmp_path)
    monkeypatch.setattr(icon_loader, "_RETRY_AT", {})
    monkeypatch.setattr(icon_loader, "_INVALID_ART", {})
    monkeypatch.setattr(icon_loader, "_PHOTO_CACHE", {})
    return tmp_path


def test_missing_art_does_not_use_loose_icons(disk_cache):
    Image.new("RGBA", (12, 12)).save(disk_cache / "shop_item.png")
    assert icon_loader.get_item_photo(None, 32) is None
    assert icon_loader.get_item_photo(ITEM_ART, 32) is None


def test_disallowed_art_url_does_not_trigger_a_request(disk_cache, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Unapproved icon URL was requested")

    monkeypatch.setattr(icon_loader.urllib.request, "urlopen", unexpected)
    for url in (None, "https://example.invalid/shop_item.png", ITEM_ART.replace("https", "http")):
        assert not icon_loader.can_prewarm(url)
        assert not icon_loader.prewarm_icon(url)


def test_worker_cache_uses_exact_url_and_ui_preserves_art_ratio(disk_cache, monkeypatch):
    class ArtResponse(io.BytesIO):
        def geturl(self):
            return ITEM_ART

    png = io.BytesIO()
    Image.new("RGBA", (32, 16), "#1ca298").save(png, "PNG")
    calls = []

    def fetch(request, **kwargs):
        calls.append(request.full_url)
        return ArtResponse(png.getvalue())

    monkeypatch.setattr(icon_loader.urllib.request, "urlopen", fetch)
    monkeypatch.setattr(ImageTk, "PhotoImage", lambda image: image)
    assert icon_loader.prewarm_icon(ITEM_ART)
    assert not icon_loader.can_prewarm(ITEM_ART)
    assert not icon_loader.prewarm_icon(ITEM_ART)
    assert icon_loader.can_prewarm(ART_ROOT + "spirit/shop_item.png")
    assert icon_loader.get_item_photo(ART_ROOT + "spirit/shop_item.png", 24) is None
    photo = icon_loader.get_item_photo(ITEM_ART, 24)
    assert photo.size == (24, 12)
    assert photo.getpixel((0, 0)) == (28, 162, 152, 255)
    assert calls == [ITEM_ART]


def test_expired_or_corrupt_art_is_text_only_until_refreshed(disk_cache):
    cache_file = icon_loader._cache_path(ITEM_ART)
    Image.new("RGBA", (12, 12)).save(cache_file)
    os.utime(cache_file, (1, 1))
    assert icon_loader.get_item_photo(ITEM_ART, 32) is None
    assert icon_loader.can_prewarm(ITEM_ART)
    cache_file.write_bytes(b"invalid PNG")
    assert icon_loader.get_item_photo(ITEM_ART, 32) is None
    assert icon_loader.can_prewarm(ITEM_ART)
