"""Live SSE snapshots must be complete and must stop on terminal events."""

import io
import json

import live_match


def stream_rows(count=12, tick=10):
    return [dict(tick=tick, entity_index=i, m_iTeamNum=2 if i < 6 else 3,
                 m_PlayerDataGlobal__m_nHeroID=i + 1,
                 m_PlayerDataGlobal__m_iGoldNetWorth=20000,
                 m_PlayerDataGlobal__m_iAPNetWorth=0,
                 m_PlayerDataGlobal__m_iGold=1000,
                 m_PlayerDataGlobal__m_vecUpgrades=[])
            for i in range(count)]


def sse(rows, terminal=""):
    return ("".join("data: " + json.dumps(r) + "\r\n\r\n" for r in rows) + terminal).encode()


def test_crlf_sse_retains_a_complete_single_tick(monkeypatch):
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(sse(stream_rows())))
    snapshot = live_match.fetch_live_snapshot(7)
    assert snapshot.tick == 10 and len(snapshot.players) == 12
    assert snapshot.players[0].gold == 1000


def test_partial_ticks_are_not_mixed_into_fake_complete_roster(monkeypatch):
    rows = stream_rows(6) + stream_rows(12, 11)[6:]
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(sse(rows)))
    assert live_match.fetch_live_snapshot(7) is None


def test_terminal_event_clears_partial_rows(monkeypatch):
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(sse(stream_rows(2), "event: end\r\n\r\n")))
    assert live_match.fetch_live_snapshot(7) is None


def test_missing_numeric_fields_do_not_create_lead_or_damage_claims():
    row = stream_rows(1)[0]
    row.pop("m_PlayerDataGlobal__m_iGoldNetWorth")
    player = live_match.parse_player(row)
    assert not player.souls_known and not player.damage_known


def test_replayed_old_tick_is_not_made_fresh_by_receiving_it_again(monkeypatch):
    live_match._CACHE.clear()
    live_match._LAST_TICK.clear()
    live_match._MISSES.clear()
    live_match._CACHE[7] = live_match.LiveSnapshot(7, tick=10, fetched_at=1)
    monkeypatch.setattr(live_match, "_now", lambda: 20)
    monkeypatch.setattr(live_match, "fetch_live_snapshot",
                        lambda _: live_match.LiveSnapshot(7, tick=10, fetched_at=20))
    assert live_match.get_live_snapshot(7) is None
    assert 7 not in live_match._CACHE
    monkeypatch.setattr(live_match, "_now", lambda: 30)
    assert live_match.get_live_snapshot(7) is None
    live_match._MISSES.clear()
    live_match._LAST_TICK.clear()


def test_malformed_inventory_is_unknown_not_partially_empty():
    assert live_match.parse_item_ids([123, "invalid"]) is None
    assert live_match.parse_item_ids([0, "0000000000000000"]) == []
