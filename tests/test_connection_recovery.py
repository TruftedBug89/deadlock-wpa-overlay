"""Discovery is recoverable without trusting a stale public watch-list ID."""

import ctypes
from ctypes import wintypes
from types import SimpleNamespace

import advisor_api
import advisor_live
from advisor_source import AdvisorDataSource
import live_match
import match_code_reader
from match_corner_capture import game_window


def source(monkeypatch, active=None, corner=None, fetcher=None):
    monkeypatch.setattr(advisor_live, "game_running", lambda: True)
    monkeypatch.setattr(advisor_api, "find_active_match", lambda _: active)
    monkeypatch.setattr(match_code_reader, "get_match_id", lambda **_: corner)
    return AdvisorDataSource(account_id=1001, require_match=True,
                             read_match_id=True, live_fetcher=fetcher)


def snapshot(match):
    player = live_match.LivePlayer(1001, 2, 1, 1000, gold=500, owned_item_ids=[])
    return live_match.LiveSnapshot(match, [player], tick=100, fetched_at=0)


def test_corner_candidate_beats_stale_public_id(monkeypatch):
    calls = []
    advisor = source(monkeypatch, active=9001, corner=9002,
                     fetcher=lambda match: calls.append(match) or snapshot(match))
    state = advisor._live_state()
    assert state["match_id"] == 9002 and state["connection_source"] == "corner"
    assert calls == [9002]


def test_public_candidate_still_works_after_bad_corner(monkeypatch):
    advisor = source(monkeypatch, active=9001, corner=9002,
                     fetcher=lambda match: snapshot(match) if match == 9001 else None)
    assert advisor._live_state()["match_id"] == 9001


def test_verified_broadcast_survives_watch_list_disappearance(monkeypatch):
    advisor = source(monkeypatch, active=9001, fetcher=snapshot)
    assert advisor._live_state()["match_id"] == 9001
    monkeypatch.setattr(advisor_api, "find_active_match", lambda _: None)
    state = advisor._live_state()
    assert state["match_id"] == 9001
    assert state["connection_source"] == "verified_previous"


def test_account_change_forgets_confirmed_match(monkeypatch):
    advisor = source(monkeypatch, active=9001, fetcher=snapshot)
    assert advisor._live_state()
    advisor.account_id = 1002
    monkeypatch.setattr(advisor_api, "find_active_match", lambda _: None)
    assert advisor._live_state() is None
    assert advisor._confirmed_match is None


def test_manual_id_never_silently_changes(monkeypatch):
    calls = []
    advisor = source(monkeypatch, active=9001, corner=9002,
                     fetcher=lambda match: calls.append(match))
    advisor.match_id = 9003
    assert advisor._live_state() is None
    assert calls == [9003]
    assert "Manual match ID" in advisor._live_reason


def test_explicit_retry_clears_miss_but_not_replay_watermark(monkeypatch):
    advisor = source(monkeypatch)
    advisor.match_id = 9003
    live_match._CACHE[9003] = snapshot(9003)
    live_match._MISSES[9003] = 10
    live_match._LAST_TICK[9003] = 100
    advisor.reset_connection()
    assert 9003 not in live_match._CACHE and 9003 not in live_match._MISSES
    assert live_match._LAST_TICK.pop(9003) == 100


def test_watch_list_malformed_response_is_unknown(monkeypatch):
    monkeypatch.setattr(advisor_api, "_ACTIVE_CACHE", {})
    monkeypatch.setattr(advisor_api, "http_json", lambda *a, **kw: {"error": "busy"})
    assert advisor_api.find_active_match(1001) is None


def test_game_window_uses_process_and_client_bounds_without_title():
    def rect(_hwnd, output):
        value = ctypes.cast(output, ctypes.POINTER(wintypes.RECT)).contents
        value.right, value.bottom = 1920, 1080
        return True
    api = SimpleNamespace(GetForegroundWindow=lambda: 42, IsIconic=lambda _: False,
                          GetWindowThreadProcessId=lambda *a: None, GetClientRect=rect)
    assert game_window(api, lambda _: "C:/Games/Deadlock/deadlock.exe") == (42, 1920, 1080)
    assert game_window(api, lambda _: "C:/Apps/browser.exe") is None


def test_sse_status_events_cannot_bypass_total_deadline(monkeypatch):
    import io
    clock = iter(range(100))
    monkeypatch.setattr(live_match.time, "monotonic", lambda: next(clock))
    response = io.BytesIO(b"event: status\ndata: {}\n\n" * 100)
    monkeypatch.setattr(live_match.urllib.request, "urlopen", lambda *a, **kw: response)
    assert live_match.fetch_live_snapshot(9001, timeout_s=3) is None
    assert next(clock) < 10
