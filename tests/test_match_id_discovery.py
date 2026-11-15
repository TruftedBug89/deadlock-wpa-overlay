"""Corner OCR supplies identity only and cannot bypass API verification."""

from types import SimpleNamespace

import numpy as np

import match_code_reader as reader
from advisor_source import AdvisorDataSource
from live_match import LivePlayer, LiveSnapshot


def test_failed_corner_reads_back_off(monkeypatch):
    now, calls = [10.0], []
    monkeypatch.setattr(reader, "_CACHE", {"code": None, "at": 0.0})
    monkeypatch.setattr(reader, "_now", lambda: now[0])
    monkeypatch.setattr(reader, "capture_game_frame", lambda: calls.append(1))
    assert reader.get_match_id(45) is None
    now[0] = 40
    assert reader.get_match_id(45) is None
    assert len(calls) == 1
    now[0] = 56
    assert reader.get_match_id(45) is None
    assert len(calls) == 2


def test_single_ocr_vote_is_not_identity(monkeypatch):
    responses = iter(["MATCH: 123456789"] + [""] * 8)
    monkeypatch.setattr(reader, "_get_ocr_engine", lambda: object())
    monkeypatch.setattr(reader, "run_ocr", lambda *_: SimpleNamespace(
        lines=[SimpleNamespace(text=next(responses))]))
    assert reader.parse_match_code(np.zeros((54, 172, 3), dtype=np.uint8)) is None


def test_wrong_account_cannot_fall_back_to_manual_hero(monkeypatch):
    monkeypatch.setattr("advisor_live.game_running", lambda: True)
    monkeypatch.setattr("advisor_api.find_active_match", lambda _: None)
    monkeypatch.setattr(reader, "get_match_id", lambda **_: 123456789)
    snapshot = LiveSnapshot(123456789, [LivePlayer(999, 2, 1, 1000)])
    source = AdvisorDataSource(hero_id=1, account_id=123, require_match=True,
                               read_match_id=True, live_fetcher=lambda _: snapshot)
    assert source._live_state() is None
    assert source._live_status == "needs_account"


def test_corner_read_is_opt_in(monkeypatch):
    monkeypatch.setattr("advisor_live.game_running", lambda: True)
    monkeypatch.setattr("advisor_api.find_active_match", lambda _: None)
    def forbidden(**kwargs):
        raise AssertionError("OCR must not run without opt in")
    monkeypatch.setattr(reader, "get_match_id", forbidden)
    source = AdvisorDataSource(account_id=123, require_match=True)
    assert source._live_state() is None
    assert source._live_status == "needs_match"


def test_tied_ocr_votes_are_unknown(monkeypatch):
    responses = iter(["MATCH: 123456789"] * 4 + ["MATCH: 987654321"] * 4 + [""])
    monkeypatch.setattr(reader, "_get_ocr_engine", lambda: object())
    monkeypatch.setattr(reader, "run_ocr", lambda *_: SimpleNamespace(
        lines=[SimpleNamespace(text=next(responses))]))
    assert reader.parse_match_code(np.zeros((54, 172, 3), dtype=np.uint8)) is None


def test_missing_account_requests_setup_without_network(monkeypatch):
    monkeypatch.setattr("local_account.find_account_id", lambda: None)
    def forbidden(*args):
        raise AssertionError("Configure identity before network discovery")
    monkeypatch.setattr("advisor_api.find_active_match", forbidden)
    source = AdvisorDataSource(require_match=True)
    assert source._live_state() is None
    assert source._live_status == "needs_account"
