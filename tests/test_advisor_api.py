"""HTTP/cache boundaries without network traffic or personal data."""

import json
import os
from urllib.parse import parse_qs, urlparse

import advisor_api
from tests.test_advisor_evidence import row, source


def test_bucket_query_keeps_small_rows_for_local_pooling(monkeypatch):
    calls = []
    monkeypatch.setattr(advisor_api, "http_json", lambda url, **kw: calls.append(url) or [])
    advisor_api.fetch_item_stats(1, [3, 2, 3], bucket=True)
    params = parse_qs(urlparse(calls[0]).query)
    assert params == {"hero_id": ["1"], "enemy_hero_ids": ["2,3"],
                      "bucket": ["net_worth_by_5000"], "min_matches": ["1"]}


def test_expired_cache_is_not_served_on_failure(tmp_path):
    path = tmp_path / "stats.json"
    advisor_api.write_cache(path, [row(1, 900)])
    os.utime(path, (1, 1))
    assert advisor_api.read_cache(path, advisor_api.CACHE_TTL_STATS) is None


def test_assets_expire_in_a_running_process_and_removed_items_disappear(tmp_path):
    advisor = source(tmp_path, lambda *args: [row(1, 550)], enemies=())
    assert advisor.get_game_state().recommended_items
    advisor._assets_loaded_at = 1
    os.utime(tmp_path / "assets.json", (1, 1))
    advisor._assets_fetcher = lambda: {"items": [], "heroes": []}
    state = advisor.get_game_state()
    assert state.scan_status == "error" and not state.recommended_items


def test_explanation_is_cleared_after_refresh_failure(tmp_path):
    advisor = source(tmp_path, lambda *args: [row(1, 550)], enemies=())
    advisor.get_game_state()
    advisor._assets_loaded_at = 1
    os.utime(tmp_path / "assets.json", (1, 1))
    def fail():
        raise TimeoutError()
    advisor._assets_fetcher = fail
    state = advisor.get_game_state()
    assert state.scan_status == "error"
    assert "items" not in advisor.last_explanation


def test_active_match_discovery_requires_unique_match_and_never_guesses(monkeypatch):
    advisor_api._ACTIVE_CACHE.clear()
    monkeypatch.setattr(advisor_api, "http_json", lambda *a, **k: [{"match_id": 1}, {"match_id": 2}])
    assert advisor_api.find_active_match(12345) is None
    assert advisor_api.find_active_match(None) is None


def test_api_retry_after_prevents_immediate_repeat(monkeypatch):
    from urllib.error import HTTPError
    calls = []
    def limited(*args, **kwargs):
        calls.append(1)
        raise HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "120"}, None)
    monkeypatch.setattr(advisor_api.urllib.request, "urlopen", limited)
    import pytest
    with pytest.raises(HTTPError):
        advisor_api.http_json("https://example.invalid/test")
    with pytest.raises(RuntimeError):
        advisor_api.http_json("https://example.invalid/test")
    assert calls == [1]
    advisor_api._RETRY_UNTIL.clear()
