"""End-to-end advisor flow over one synthetic broadcast.

The network boundary (``live_match.fetch_live_snapshot``) and the corner OCR
entry point are replaced with scripted answers; everything after them is the
real code: row parsing, live cache and miss cache, match identity, stage
ranking, counters and the idle reset.
"""

import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
import os

import advisor_api
import live_match
import match_code_reader
from advisor_source import AdvisorDataSource

from tests import live_fixture

@pytest.fixture(autouse=True)
def no_host_game_dependency(monkeypatch):
    monkeypatch.setattr("advisor_live.game_running", lambda: False)


OUR_ACCOUNT = 1001  # synthetic player on team 2, hero 17
NEW_MATCH_ID = 9002
OWNED_ID = live_fixture.owned_ids(OUR_ACCOUNT)[0]  # real item in the synthetic inventory

HEROES = {
    17: "Grey Talon",
    6: "Enemy Six",
    63: "Enemy SixtyThree",
    66: "Enemy SixtySix",
    14: "Enemy Fourteen",
    86: "Enemy EightySix",
    20: "Enemy Twenty",
    72: "Test Enemy",
}

ASSETS = {
    "items": [
        {"id": OWNED_ID, "name": "Owned Relic", "type": "upgrade", "item_slot_type": "weapon",
         "item_tier": 1, "cost": 500, "image": "owned.png", "shopable": True},
        {"id": 1, "name": "Cheap Starter", "type": "upgrade", "item_slot_type": "weapon",
         "item_tier": 1, "cost": 500, "image": "cheap.png", "shopable": True},
        {"id": 2, "name": "Cheap Spirit", "type": "upgrade", "item_slot_type": "spirit",
         "item_tier": 2, "cost": 500, "image": "spirit.png", "shopable": True},
        {"id": 3, "name": "Cheap Counter", "type": "upgrade", "item_slot_type": "spirit",
         "item_tier": 2, "cost": 500, "image": "counter.png", "shopable": True},
        {"id": 4, "name": "Mid Item", "type": "upgrade", "item_slot_type": "vitality",
         "item_tier": 2, "cost": 3000, "image": "mid.png", "shopable": True},
        {"id": 5, "name": "Late Hammer", "type": "upgrade", "item_slot_type": "weapon",
         "item_tier": 4, "cost": 6400, "image": "late.png", "shopable": True},
        {"id": 6, "name": "Silence", "type": "upgrade", "item_slot_type": "spirit",
         "item_tier": 4, "cost": 6400, "image": "silence.png", "shopable": True},
    ],
    "heroes": [{"id": hero_id, "name": name} for hero_id, name in HEROES.items()],
}

STATS = [
    {"item_id": OWNED_ID, "matches": 5000, "wins": 4000},  # would rank first if owned were ignored
    {"item_id": 1, "matches": 5000, "wins": 3300},  # best unowned raw win rate
    {"item_id": 2, "matches": 5000, "wins": 2750},
    {"item_id": 3, "matches": 5000, "wins": 2700},
    {"item_id": 4, "matches": 5000, "wins": 3000},
    {"item_id": 5, "matches": 5000, "wins": 3250},
    {"item_id": 6, "matches": 5000, "wins": 2900},
]


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _stats(hero, enemy_ids):
    """General rows; the enemy-filtered pool carries a real counter edge."""
    rows = [dict(row) for row in STATS]
    if enemy_ids:
        for row in rows:
            if row["item_id"] == 3:
                row["wins"] = int(row["wins"]) + 150  # +3.0 pp in this matchup
    return rows


def _source(tmp_path: Path) -> AdvisorDataSource:
    return AdvisorDataSource(
        assets_fetcher=lambda: ASSETS,
        stats_fetcher=_stats,
        matchup_fetcher=lambda hero: [
            {"enemy_hero_id": 6, "matches": 5000, "win_rate": 0.42},
            {"enemy_hero_id": 63, "matches": 5000, "win_rate": 0.47},
        ],
        cache_path=tmp_path,
        account_id=OUR_ACCOUNT,
        require_match=True,
    )


def _reset_caches() -> None:
    live_match._CACHE.clear()
    live_match._LAST_TICK.clear()
    live_match._MISSES.clear()


def test_synthetic_match_stage_flip_and_full_reset(monkeypatch, tmp_path):
    _reset_caches()
    clock = Clock()
    screen = {"id": int(live_fixture.load()["match_id"])}
    phase = {"souls": 2500, "alive": True, "custom": None}
    fetch_calls = []

    def fake_fetch(match_id, **kwargs):
        fetch_calls.append(match_id)
        if not phase["alive"]:
            return None
        snapshot = phase["custom"]
        if snapshot is None:
            snapshot = live_fixture.snapshot(souls=phase["souls"], fetched_at=clock.value)
        snapshot.match_id = int(match_id)
        snapshot.tick = int(clock.value * 1000) + 1
        snapshot.fetched_at = clock.value
        me = snapshot.player_for_account(OUR_ACCOUNT)
        me.gold = phase["souls"]
        # The injected catalog describes one recorded owned item. Keep the
        # synthetic inventory consistent with that catalog.
        if me.owned_item_ids is not None:
            me.owned_item_ids = [i for i in me.owned_item_ids if i == OWNED_ID]
        return snapshot

    monkeypatch.setattr(live_match, "_now", clock)
    monkeypatch.setattr(live_match, "fetch_live_snapshot", fake_fetch)
    monkeypatch.setattr(advisor_api, "find_active_match", lambda *args, **kwargs: screen["id"])

    source = _source(tmp_path)

    early = source.get_game_state(max_items=2)
    assert early.scan_status == "ok" and early.is_in_match is True
    assert early.stage == "early"
    assert early.net_worth == 2500
    assert [item.name for item in early.recommended_items] == ["Cheap Starter", "Cheap Spirit"]
    assert all(item.name != "Late Hammer" for item in early.recommended_items)
    assert early.next_buy is not None and early.next_buy.cost == 500
    assert early.next_buy.cost <= early.net_worth
    assert len(early.build_candidates) == 3
    assert all(item.cost <= early.net_worth for item in early.build_candidates)
    owned = set(live_fixture.owned_ids(OUR_ACCOUNT))
    assert OWNED_ID in owned
    assert early.next_buy.item_id not in owned
    assert all(item.item_id not in owned for item in early.recommended_items + early.build_candidates)
    assert all(item.name != "Owned Relic" for item in early.recommended_items)
    assert early.counter_items == []  # +3 points still loses to the enemy pool baseline
    assert early.hero_name == "Grey Talon"

    clock.value = 7.0
    phase["souls"] = 22000
    late = source.get_game_state(max_items=2)
    assert late.stage == "late"
    assert late.net_worth == 22000
    assert late.recommended_items[0].name == "Late Hammer"
    assert late.recommended_items[0].cost == 6400
    assert late.next_buy is not None and late.next_buy.name == "Late Hammer"
    assert late.next_buy.cost <= late.net_worth
    assert late.next_buy.item_id not in owned
    assert all(item.item_id not in owned for item in late.recommended_items + late.build_candidates)
    assert all(item.name != "Owned Relic" for item in late.recommended_items)
    assert late.hero_name == early.hero_name
    assert late.enemy_heroes == early.enemy_heroes

    # 6.05 s later the live cache must have expired; no rows means match over.
    clock.value = 13.05
    phase["alive"] = False
    ended = source.get_game_state()
    assert ended.scan_status == "connecting"
    assert ended.is_in_match is False
    assert ended.recommended_items == []
    assert ended.counter_items == []
    assert ended.next_buy is None
    assert ended.build_candidates == []

    # The corner stamp disappears: idle without needing another network read.
    clock.value = 14.0
    screen["id"] = None
    calls_before = len(fetch_calls)
    gone = source.get_game_state()
    assert gone.scan_status == "connecting" and gone.recommended_items == []
    assert len(fetch_calls) == calls_before

    # A different match id starts with a clean roster; nothing carries over.
    clock.value = 21.0
    screen["id"] = NEW_MATCH_ID
    phase["alive"] = True
    phase["souls"] = 1200
    phase["custom"] = live_match.LiveSnapshot(
        match_id=NEW_MATCH_ID,
        players=[
            live_match.LivePlayer(
                account_id=OUR_ACCOUNT, team=2, hero_id=17, net_worth=1200,
                owned_item_ids=[OWNED_ID],
            ),
            live_match.LivePlayer(account_id=777, team=3, hero_id=72, net_worth=1000),
        ],
        tick=1,
        fetched_at=clock.value,
    )
    fresh = source.get_game_state(max_items=2)
    assert fresh.scan_status == "ok" and fresh.is_in_match is True
    assert fresh.net_worth == 1200 and fresh.stage == "early"
    assert fresh.enemy_heroes == ["Test Enemy"]
    assert fresh.strongest_enemy == ""
    assert fresh.counter_items == []
    assert fresh.next_buy is not None and fresh.next_buy.name == "Cheap Starter"
    assert all(item.cost <= fresh.net_worth for item in fresh.recommended_items)


def _ownership_variant(souls, fetched_at, *, omit_owned=False, drop_item_id=None):
    """Build a snapshot from the recorded rows through the real parser."""
    data = live_fixture.load()
    players = []
    for row in data["rows"]:
        row = dict(row)
        if int(row.get("m_unEconAccountID") or 0) == OUR_ACCOUNT:
            field = "m_PlayerDataGlobal__m_vecUpgrades"
            if omit_owned:
                row.pop(field, None)
            elif drop_item_id is not None:
                raw = row.get(field) or []
                row[field] = [
                    value for value in raw
                    if (int.from_bytes(bytes.fromhex(value), "little") & 0xFFFFFFFF) != drop_item_id
                ]
        player = live_match.parse_player(row)
        if player is None:
            continue
        if souls is not None:
            player = replace(player, net_worth=int(souls), ap_net_worth=0)
        players.append(player)
    return live_match.LiveSnapshot(
        match_id=int(data["match_id"]),
        players=players,
        tick=int(data["rows"][0]["tick"] or 0),
        fetched_at=fetched_at,
    )


def test_missing_ownership_vector_carries_forward_and_sale_is_honoured(monkeypatch, tmp_path):
    _reset_caches()
    clock = Clock()
    match_id = int(live_fixture.load()["match_id"])
    screen = {"id": match_id}
    phase = {"owned": "present", "alive": True, "souls": 2500}

    def fake_fetch(probe_match_id, **kwargs):
        if not phase["alive"]:
            return None
        if phase["owned"] == "missing":
            snapshot = _ownership_variant(phase["souls"], clock.value, omit_owned=True)
        elif phase["owned"] == "sold":
            snapshot = _ownership_variant(phase["souls"], clock.value, drop_item_id=OWNED_ID)
        else:
            snapshot = live_fixture.snapshot(souls=phase["souls"], fetched_at=clock.value)
        snapshot.match_id = int(probe_match_id)
        snapshot.tick = int(clock.value * 1000) + 1
        snapshot.fetched_at = clock.value
        me = snapshot.player_for_account(OUR_ACCOUNT)
        me.gold = phase["souls"]
        # The injected catalog describes one recorded owned item. Keep the
        # synthetic inventory consistent with that catalog.
        if me.owned_item_ids is not None:
            me.owned_item_ids = [i for i in me.owned_item_ids if i == OWNED_ID]
        return snapshot

    monkeypatch.setattr(live_match, "_now", clock)
    monkeypatch.setattr(live_match, "fetch_live_snapshot", fake_fetch)
    monkeypatch.setattr(advisor_api, "find_active_match", lambda *args, **kwargs: screen["id"])
    source = _source(tmp_path)

    def assert_not_owned_anywhere(state):
        assert all(item.name != "Owned Relic" for item in state.recommended_items)
        assert state.next_buy is not None and state.next_buy.item_id != OWNED_ID
        assert state.next_buy.cost <= state.net_worth
        assert all(item.item_id != OWNED_ID for item in state.build_candidates)
        assert any(item.item_id == 1 for item in state.recommended_items), "unowned item must remain"

    first = source.get_game_state(max_items=5)
    assert_not_owned_anywhere(first)

    # Same match, next tick omits the vector: ownership must be carried, not reset.
    clock.value = 7.0
    phase["owned"] = "missing"
    missing = source.get_game_state(max_items=5)
    assert missing.scan_status == "unknown"
    assert missing.recommended_items == [] and missing.next_buy is None

    # A present vector without X is a genuine sale: X must become recommendable.
    clock.value = 14.0
    phase["owned"] = "sold"
    sold = source.get_game_state(max_items=5)
    assert sold.next_buy is not None and sold.next_buy.name == "Owned Relic"
    assert sold.next_buy.item_id == OWNED_ID

    # Match over: ownership clears with the rest of the state.
    clock.value = 21.0
    phase["alive"] = False
    ended = source.get_game_state()
    assert ended.scan_status == "connecting"
    assert ended.next_buy is None
    assert ended.owned_items == set()

    # New match with no vector must not inherit the previous ownership set.
    clock.value = 28.0
    screen["id"] = NEW_MATCH_ID
    phase["alive"] = True
    phase["owned"] = "missing"
    fresh = source.get_game_state(max_items=5)
    assert fresh.owned_items == set()
    assert fresh.scan_status == "unknown"
    assert fresh.recommended_items == [] and fresh.next_buy is None


def test_missing_ownership_field_is_unknown_not_empty():
    from live_match import parse_item_ids, parse_player

    row = dict(live_fixture.load()["rows"][0])
    row.pop("m_PlayerDataGlobal__m_vecUpgrades", None)
    assert parse_player(row).owned_item_ids is None
    assert parse_item_ids(None) is None
    row["m_PlayerDataGlobal__m_vecUpgrades"] = []
    assert parse_player(row).owned_item_ids == []


def test_fresh_process_without_a_match_shows_nothing(monkeypatch, tmp_path):
    _reset_caches()
    clock = Clock()
    monkeypatch.setattr(live_match, "_now", clock)
    monkeypatch.setattr(advisor_api, "find_active_match", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        live_match,
        "fetch_live_snapshot",
        lambda match_id: (_ for _ in ()).throw(AssertionError("must not fetch without a match id")),
    )
    state = _source(tmp_path).get_game_state()
    assert state.scan_status == "idle"
    assert state.is_in_match is False
    assert state.recommended_items == []
    assert state.counter_items == []
    assert state.next_buy is None
    assert state.build_candidates == []


def test_idle_state_renders_no_cards(monkeypatch, tmp_path):
    from models import OverlayConfig
    from ui import counter_panel
    from ui.hud_presentation import get_desired_content

    _reset_caches()
    monkeypatch.setattr(advisor_api, "find_active_match", lambda *args, **kwargs: None)
    state = _source(tmp_path).get_game_state()
    config = OverlayConfig()
    kind, slots = get_desired_content(state, config, True, None, force_visible=True)
    assert kind == "status"
    assert slots == 1
    assert counter_panel.visible_counters(state, config) == []


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="Native Windows OCR needs an interactive desktop; parser logic is tested with mocks")
def test_generated_corner_stamp_can_be_read():
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    from match_code_reader import parse_match_code
    from ocr_engine import get_ocr_engine
    if get_ocr_engine() is None:
        pytest.skip("Windows OCR unavailable")
    frame = Image.new("RGB", (400, 70), "black")
    font = ImageFont.truetype("arial.ttf", 28)
    ImageDraw.Draw(frame).text((5, 10), "MATCH: 123456789", fill="white", font=font)
    assert parse_match_code(np.array(frame)) == 123456789


def test_synthetic_inventory_round_trips():
    from live_match import parse_item_ids
    for row in live_fixture.load()["rows"]:
        raw = row["m_PlayerDataGlobal__m_vecUpgrades"]
        expected = [int.from_bytes(bytes.fromhex(value), "little") for value in raw]
        assert parse_item_ids(raw) == expected


def test_owned_vector_decodes_real_item_ids():
    from live_match import parse_item_id

    assert parse_item_id("e0ab3ee600000000") == 3862866912  # Restorative Shot
    owned = live_fixture.owned_ids(OUR_ACCOUNT)
    assert len(owned) == 8
    assert OWNED_ID in owned
    assert all(value > 0 for value in owned)


def test_corner_code_cache_window(monkeypatch):
    clock = Clock()
    current = {"code": 111}
    monkeypatch.setattr(match_code_reader, "_now", clock)
    monkeypatch.setattr(match_code_reader, "capture_game_frame", lambda: object())
    monkeypatch.setattr(match_code_reader, "parse_match_code", lambda frame: current["code"])
    match_code_reader._CACHE["code"] = None
    match_code_reader._CACHE["at"] = 0.0

    assert match_code_reader.get_match_id() == 111
    current["code"] = 222
    clock.value = 4.0
    assert match_code_reader.get_match_id() == 111  # still cached
    clock.value = 5.1
    assert match_code_reader.get_match_id() == 222  # expired after 5 s
