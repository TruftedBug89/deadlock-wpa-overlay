"""Live SSE snapshots must be complete and must stop on terminal events."""

import io
import json
import urllib.parse

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


def test_flex_rows_use_the_players_team_and_bounded_tick_lag(monkeypatch):
    tick = 2 * live_match.FLEX_MAX_TICK_LAG
    teams = [dict(tick=tick - 2, entity_index=0, m_iTeamNum=2, row_kind="team", flex_mask=0),
             dict(tick=tick - 1, entity_index=0, m_iTeamNum=2, row_kind="team", flex_mask="0500000000000000"),
             dict(tick=tick + 1, entity_index=0, m_iTeamNum=2, row_kind="team", flex_mask=7),
             dict(tick=tick - live_match.FLEX_MAX_TICK_LAG - 1, entity_index=1,
                  m_iTeamNum=3, row_kind="team", flex_mask=7)]
    rows = teams + stream_rows(tick=tick)
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(sse(rows)))
    snapshot = live_match.fetch_live_snapshot(7)
    assert snapshot.tick == tick and len(snapshot.players) == 12
    assert snapshot.team_flex_slots == {2: 2}


def test_optional_flex_does_not_hold_a_healthy_roster(monkeypatch):
    class OpenStream(io.BytesIO):
        def __iter__(self):
            while line := self.readline():
                yield line
            raise AssertionError("stream was still read after the complete roster")

    teams = [dict(tick=9, entity_index=0, m_iTeamNum=2, row_kind="team", flex_mask=7),
             dict(tick=10, entity_index=0, m_iTeamNum=2, row_kind="team", flex_mask="0f00000000000000"),
             dict(tick=11, entity_index=1, m_iTeamNum=3, row_kind="team", flex_mask=7)]
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: OpenStream(sse(teams + stream_rows())))
    snapshot = live_match.fetch_live_snapshot(7)
    assert snapshot.tick == 10 and snapshot.team_flex_slots == {}


def test_combined_query_falls_back_to_controller_only_after_validation_error(monkeypatch):
    queries = []
    monkeypatch.setattr(live_match, "_FLEX_UNSUPPORTED", {})

    def response(request, **_kwargs):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["query"][0]
        queries.append(query)
        if "UNION ALL" in query:
            return io.BytesIO(b'event: error\ndata: {"status":400,"error":"Invalid query"}\n\n')
        return io.BytesIO(sse(stream_rows()))

    monkeypatch.setattr(live_match.urllib.request, "urlopen", response)
    assert live_match.fetch_live_snapshot(7).team_flex_slots == {}
    assert live_match.fetch_live_snapshot(7).tick == 10
    assert queries == [live_match.FLEX_QUERY, live_match.QUERY, live_match.QUERY]


def test_partial_ticks_are_not_mixed_into_fake_complete_roster(monkeypatch):
    rows = stream_rows(6) + stream_rows(12, 11)[6:]
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(sse(rows)))
    assert live_match.fetch_live_snapshot(7) is None


def test_reconnect_reads_new_tick_after_a_complete_replayed_tick(monkeypatch):
    monkeypatch.setattr(live_match, "_CACHE", {})
    monkeypatch.setattr(live_match, "_MISSES", {})
    monkeypatch.setattr(live_match, "_LAST_TICK", {7: 10})
    buffered = sse(stream_rows(tick=10) + stream_rows(tick=14))
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(buffered))
    snapshot = live_match.get_live_snapshot(7)
    assert snapshot.tick == 14
    assert live_match._LAST_TICK[7] == 14


def test_terminal_event_clears_partial_rows(monkeypatch):
    monkeypatch.setattr(live_match.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(sse(stream_rows(2), "event: end\r\n\r\n")))
    assert live_match.fetch_live_snapshot(7) is None


def test_startup_waits_past_old_deadline_and_records_numeric_error(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(live_match.time, "monotonic", lambda: now[0])
    class Delayed(io.BytesIO):
        def __iter__(self):
            yield b"event: status\n"
            yield b"data: {}\n"
            yield b"\n"
            now[0] = 58.0
            while line := self.readline():
                yield line

    def response(_request, timeout):
        assert timeout > 15
        return Delayed(sse(stream_rows()))

    monkeypatch.setattr(live_match.urllib.request, "urlopen", response)
    assert live_match.fetch_live_snapshot(7).tick == 10
    now[0] = 0.0
    monkeypatch.setattr(live_match.urllib.request, "urlopen", lambda *a, **kw: Delayed(
        b'event: error\ndata: {"status":502,"error":"omitted downstream details"}\n\n'))
    assert live_match.fetch_live_snapshot(7) is None
    assert live_match.last_broadcast_read() == ("relay_error", 502)


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
                        lambda _, **kwargs: live_match.LiveSnapshot(7, tick=10, fetched_at=20))
    assert live_match.get_live_snapshot(7) is None
    assert 7 not in live_match._CACHE
    monkeypatch.setattr(live_match, "_now", lambda: 30)
    assert live_match.get_live_snapshot(7) is None
    live_match._MISSES.clear()
    live_match._LAST_TICK.clear()


def test_malformed_inventory_is_unknown_not_partially_empty():
    assert live_match.parse_item_ids([123, "invalid"]) is None
    assert live_match.parse_item_ids([0, "0000000000000000"]) == []
