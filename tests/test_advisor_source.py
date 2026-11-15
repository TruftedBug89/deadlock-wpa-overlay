"""Advisor data source: deadlock-api only, deterministic with injected fetchers."""

import tempfile
from pathlib import Path

from advisor_source import AdvisorDataSource, rank_items, smoothed_win_rate

ASSETS = {
    "items": [
        {"id": 1, "name": "Lucky Shot", "class_name": "upgrade_lucky_shot", "type": "upgrade",
         "item_slot_type": "weapon", "item_tier": 4, "cost": 6400, "image": "lucky.png",
         "shopable": True, "disabled": None},
        {"id": 2, "name": "Spirit Burn", "class_name": "upgrade_spirit_burn", "type": "upgrade",
         "item_slot_type": "spirit", "item_tier": 4, "cost": 6400, "image": "burn.png",
         "shopable": True, "disabled": None},
        {"id": 3, "name": "Scourge", "class_name": "upgrade_scourge", "type": "upgrade",
         "item_slot_type": "spirit", "item_tier": 4, "cost": 6400, "image": "scourge.png",
         "shopable": True, "disabled": None},
        {"id": 9, "name": "Disabled Thing", "type": "upgrade", "disabled": True},
        {"id": 10, "name": "Not Shopable", "type": "upgrade", "shopable": False},
    ],
    "heroes": [{"id": 17, "name": "Grey Talon"}, {"id": 11, "name": "Ivy"}],
}


def _stats(hero=None, enemy_ids=None):
    """General rows; the enemy-filtered pool carries a real counter edge."""
    rows = [dict(row) for row in _BASE_STATS]
    if enemy_ids:
        for row in rows:
            if row["item_id"] == 3:
                row["wins"] = int(row["wins"]) + 150
    return rows


_BASE_STATS = [
    {"item_id": 1, "matches": 10000, "wins": 5600},
    {"item_id": 2, "matches": 8000, "wins": 4550},
    {"item_id": 3, "matches": 900, "wins": 500},
    {"item_id": 99, "matches": 5000, "wins": 4000},  # no catalog entry
]


def _source(tmp_path: Path, hero_id=17, enemies=(11,)) -> AdvisorDataSource:
    return AdvisorDataSource(
        hero_id=hero_id,
        enemy_ids=enemies,
        assets_fetcher=lambda: ASSETS,
        stats_fetcher=_stats,
        matchup_fetcher=lambda hero: [
            {"enemy_hero_id": 11, "matches": 5000, "win_rate": 0.44},
            {"enemy_hero_id": 63, "matches": 5000, "win_rate": 0.50},
        ],
        cache_path=tmp_path,
    )


def test_smoothed_win_rate_gates_small_samples():
    assert smoothed_win_rate({"matches": 99, "wins": 99}) is None
    value = smoothed_win_rate({"matches": 100, "wins": 100})
    assert value is not None and value < 1.0


def test_rank_items_sorts_and_limits():
    known = [row for row in _stats() if row["item_id"] != 99]  # 99 has no catalog entry
    ranked = rank_items(known, 2)
    # Spirit Burn (4550/8000) has the better smoothed rate than Lucky Shot.
    assert [row["item_id"] for _score, row in ranked] == [2, 1]


def test_advisor_state_without_statlocker():
    with tempfile.TemporaryDirectory() as tmp:
        state = _source(Path(tmp)).get_game_state(max_items=2)
    assert state.source == "advisor"
    assert state.scan_status == "ok"
    assert state.hero_name == "Grey Talon"
    assert [item.name for item in state.recommended_items] == ["Scourge", "Spirit Burn"]
    assert state.strongest_enemy == "Ivy"
    assert state.strongest_enemy_winrate == 0.44
    assert state.counter_items == []  # the valid counter is now in the main row


def test_advisor_needs_a_hero():
    with tempfile.TemporaryDirectory() as tmp:
        state = AdvisorDataSource(assets_fetcher=lambda: ASSETS, cache_path=Path(tmp)).get_game_state()
    assert state.scan_status == "needs_hero"


def test_advisor_caches_stats_between_calls():
    calls = []

    def stats(hero, ids):
        calls.append((hero, tuple(ids)))
        return _stats()

    with tempfile.TemporaryDirectory() as tmp:
        source = AdvisorDataSource(
            hero_id=17,
            assets_fetcher=lambda: ASSETS,
            stats_fetcher=stats,
            matchup_fetcher=lambda hero: [{"enemy_hero_id": 11, "matches": 5000, "win_rate": 0.44}],
            cache_path=Path(tmp),
        )
        source.get_game_state()
        source.get_game_state()
    assert calls == [(17, ())]


def test_advisor_cycle_next_hero():
    with tempfile.TemporaryDirectory() as tmp:
        source = _source(Path(tmp), hero_id=17)
        source.cycle_next_hero()
        assert source.manual_hero_id == 11


def test_advisor_without_live_match_shows_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        source = AdvisorDataSource(
            assets_fetcher=lambda: ASSETS,
            stats_fetcher=lambda hero, ids: _stats(),
            cache_path=Path(tmp),
            match_id=123,
            account_id=12345,
            require_match=True,
            live_fetcher=lambda match_id: None,
        )
        state = source.get_game_state()
    assert state.scan_status == "connecting"
    assert state.is_in_match is False
    assert state.recommended_items == []
    assert state.counter_items == []


def test_advisor_uses_live_roster_souls_and_next_buy():
    from live_match import LivePlayer, LiveSnapshot

    snapshot = LiveSnapshot(
        match_id=555,
        players=[
            LivePlayer(account_id=42, team=2, hero_id=17, net_worth=18000, ap_net_worth=2000, gold=6400, owned_item_ids=[]),
            LivePlayer(account_id=7, team=3, hero_id=11, net_worth=21000, ap_net_worth=1000),
        ],
        tick=90000,
    )
    with tempfile.TemporaryDirectory() as tmp:
        source = AdvisorDataSource(
            assets_fetcher=lambda: ASSETS,
            stats_fetcher=lambda hero, ids: _stats(),
            matchup_fetcher=lambda hero: [
                {"enemy_hero_id": 11, "matches": 5000, "win_rate": 0.44}
            ],
            cache_path=Path(tmp),
            match_id=555,
            account_id=42,
            require_match=True,
            live_fetcher=lambda match_id: snapshot,
        )
        state = source.get_game_state(max_items=2)
    assert state.is_in_match is True
    assert state.hero_name == "Grey Talon"
    assert state.net_worth == 20000
    assert state.stage == "late"
    assert state.enemy_heroes == ["Ivy"]
    assert [item.name for item in state.recommended_items] == ["Spirit Burn", "Lucky Shot"]
    assert state.next_buy is not None and state.next_buy.name == "Spirit Burn"


def _stage_source(tmp_path: Path, souls: int) -> AdvisorDataSource:
    from live_match import LivePlayer, LiveSnapshot

    assets = {
        "items": [
            {"id": 1, "name": "Cheap Starter", "type": "upgrade", "item_slot_type": "weapon",
             "item_tier": 1, "cost": 500, "image": "cheap.png", "shopable": True},
            {"id": 2, "name": "Late Hammer", "type": "upgrade", "item_slot_type": "weapon",
             "item_tier": 4, "cost": 6400, "image": "late.png", "shopable": True},
        ],
        "heroes": [{"id": 17, "name": "Grey Talon"}, {"id": 11, "name": "Ivy"}],
    }
    stats = [
        {"item_id": 1, "matches": 5000, "wins": 3300},  # higher raw win rate
        {"item_id": 2, "matches": 5000, "wins": 3250},
    ]
    snapshot = LiveSnapshot(
        match_id=1,
        players=[
            LivePlayer(account_id=42, team=2, hero_id=17, net_worth=souls - 2000, ap_net_worth=2000, gold=souls, owned_item_ids=[]),
            LivePlayer(account_id=7, team=3, hero_id=11, net_worth=souls),
        ],
    )
    return AdvisorDataSource(
        assets_fetcher=lambda: assets,
        stats_fetcher=lambda hero, ids: stats,
        matchup_fetcher=lambda hero: [],
        cache_path=tmp_path,
        match_id=1,
        account_id=42,
        require_match=True,
        live_fetcher=lambda match_id: snapshot,
    )


def test_early_souls_only_show_cheap_items():
    with tempfile.TemporaryDirectory() as tmp:
        state = _stage_source(Path(tmp), 1500).get_game_state(max_items=5)
    assert state.stage == "early"
    assert [item.name for item in state.recommended_items] == ["Cheap Starter"]
    assert state.next_buy is not None and state.next_buy.cost == 500


def test_late_souls_switch_to_the_expensive_item():
    with tempfile.TemporaryDirectory() as tmp:
        state = _stage_source(Path(tmp), 20000).get_game_state(max_items=5)
    assert state.stage == "late"
    assert state.recommended_items[0].name == "Late Hammer"
    assert state.recommended_items[0].cost == 6400

def test_advisor_explanation_reports_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        source = _source(Path(tmp))
        state = source.get_game_state(max_items=3)
    payload = source.last_explanation
    assert payload["status"] == "ok"
    assert payload["hero"]["name"] == "Grey Talon"
    assert payload["items"][0]["name"] == state.recommended_items[0].name
    assert set(payload["items"][0]["breakdown"]) == {
        "edge", "popularity", "counter", "tempo", "stance"
    }
    assert payload["items"][0]["matches"] > 0
    assert payload["context"]["known"] is False  # preview mode has no live roster


def test_advisor_uses_the_net_worth_bracket_rows():
    from live_match import LivePlayer, LiveSnapshot

    assets = {
        "items": [
            {"id": 1, "name": "Bracket Winner", "type": "upgrade", "item_slot_type": "weapon",
             "item_tier": 3, "cost": 3200, "image": "a.png", "shopable": True},
            {"id": 2, "name": "Early Winner", "type": "upgrade", "item_slot_type": "weapon",
             "item_tier": 3, "cost": 3200, "image": "b.png", "shopable": True},
        ],
        "heroes": [{"id": 17, "name": "Grey Talon"}, {"id": 11, "name": "Ivy"}],
    }

    def stats(hero, enemy_ids, bucket=False):
        if bucket:
            return [
                {"item_id": 1, "bucket": 20000, "matches": 5000, "wins": 2750, "players": 4000},
                {"item_id": 2, "bucket": 20000, "matches": 5000, "wins": 2600, "players": 4000},
                {"item_id": 2, "bucket": 0, "matches": 9000, "wins": 8100, "players": 8000},
            ]
        return [
            {"item_id": 1, "matches": 5000, "wins": 2500},
            {"item_id": 2, "matches": 5000, "wins": 6000 // 2},
        ]

    snapshot = LiveSnapshot(
        match_id=77,
        players=[
            LivePlayer(account_id=42, team=2, hero_id=17, net_worth=20000, ap_net_worth=0, gold=6400, owned_item_ids=[]),
            LivePlayer(account_id=7, team=3, hero_id=11, net_worth=18000, ap_net_worth=0),
        ],
    )
    with tempfile.TemporaryDirectory() as tmp:
        source = AdvisorDataSource(
            assets_fetcher=lambda: assets,
            stats_fetcher=stats,
            matchup_fetcher=lambda hero: [],
            cache_path=Path(tmp),
            match_id=77,
            account_id=42,
            require_match=True,
            live_fetcher=lambda match_id: snapshot,
        )
        state = source.get_game_state(max_items=2)
    assert source.last_explanation["basis"] == "bracket-20000"
    # The bucket-0 row for item 2 is out of window and must not win the rank.
    assert state.recommended_items[0].name == "Bracket Winner"
    assert state.recommended_items[0].win_rate is not None
