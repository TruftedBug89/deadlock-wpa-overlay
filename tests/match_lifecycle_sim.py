"""No-game match lifecycle simulation through the real overlay pipeline.

The network boundary is scripted, but everything after it is production code:
the real AdvisorDataSource, live_match cache, OverlayWindow.poll_once worker
path, queue drain, renderer and idle/parked HUD.  No game process is needed.
"""

import sqlite3
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import live_match
import advisor_api
from advisor_source import API, AdvisorDataSource
from models import OverlayConfig
from ui.main_window import OverlayWindow

ACCOUNT = 1001
MATCH_A = 9001
MATCH_B = 9002
HERO_A = 17
HERO_B = 72

ASSETS = {
    "items": [
        {"id": 101, "name": "Talon Trick", "class_name": "upgrade_talon_trick",
         "type": "upgrade", "item_slot_type": "weapon", "item_tier": 1, "cost": 500,
         "image": "talon_trick.png", "shopable": True},
        {"id": 201, "name": "Mystic Sign", "class_name": "upgrade_mystic_sign",
         "type": "upgrade", "item_slot_type": "spirit", "item_tier": 1, "cost": 500,
         "image": "mystic_sign.png", "shopable": True},
        {"id": 102, "name": "Cheap Blade", "class_name": "upgrade_cheap_blade",
         "type": "upgrade", "item_slot_type": "weapon", "item_tier": 1, "cost": 500,
         "image": "cheap_blade.png", "shopable": True},
        {"id": 111, "name": "Alt Charm", "class_name": "upgrade_alt_charm",
         "type": "upgrade", "item_slot_type": "spirit", "item_tier": 1, "cost": 500,
         "image": "alt_charm.png", "shopable": True},
        {"id": 103, "name": "Mid Relic", "class_name": "upgrade_mid_relic",
         "type": "upgrade", "item_slot_type": "vitality", "item_tier": 2, "cost": 5000,
         "image": "mid_relic.png", "shopable": True},
        {"id": 104, "name": "Late Hammer", "class_name": "upgrade_late_hammer",
         "type": "upgrade", "item_slot_type": "weapon", "item_tier": 4, "cost": 6400,
         "image": "late_hammer.png", "shopable": True},
    ],
    "heroes": [{"id": HERO_A, "name": "Grey Talon"}, {"id": HERO_B, "name": "Test Enemy"}],
}

# 5000-match samples: hero items score highest at the soul count where their
# cost fits.  First-buy tiers therefore move 1 -> 2 -> 4 across the match.
STATS = {
    HERO_A: [
        {"item_id": 101, "matches": 5000, "wins": 3330},
        {"item_id": 102, "matches": 5000, "wins": 3270},
        {"item_id": 111, "matches": 5000, "wins": 3240},
        {"item_id": 103, "matches": 5000, "wins": 3200},
        {"item_id": 104, "matches": 5000, "wins": 3136},
    ],
    HERO_B: [
        {"item_id": 201, "matches": 5000, "wins": 3330},
        {"item_id": 102, "matches": 5000, "wins": 3270},
        {"item_id": 111, "matches": 5000, "wins": 3240},
        {"item_id": 103, "matches": 5000, "wins": 3200},
        {"item_id": 104, "matches": 5000, "wins": 3136},
    ],
}

MATCHUPS = {
    HERO_A: [{"enemy_hero_id": HERO_B, "matches": 5000, "win_rate": 0.42}],
    HERO_B: [{"enemy_hero_id": HERO_A, "matches": 5000, "win_rate": 0.45}],
}


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def _player_row(entity, account, team, hero, souls, tick):
    return {
        "tick": tick,
        "entity_index": entity,
        "m_iTeamNum": team,
        "m_unEconAccountID": account,
        "m_PlayerDataGlobal__m_nHeroID": hero,
        "m_PlayerDataGlobal__m_iGoldNetWorth": int(souls),
        "m_PlayerDataGlobal__m_iAPNetWorth": 0,
        "m_PlayerDataGlobal__m_iGold": int(souls),
        "m_PlayerDataGlobal__m_vecUpgrades": [],
    }


def _snapshot(match_id, hero_id, souls, enemy_id, fetched_at):
    tick = int(fetched_at * 1000)
    rows = [
        _player_row(76, ACCOUNT, 2, hero_id, souls, tick),
        _player_row(77, 777, 3, enemy_id, max(0, int(souls) - 500), tick),
    ]
    players = [p for p in (live_match.parse_player(row) for row in rows) if p is not None]
    return live_match.LiveSnapshot(
        match_id=int(match_id), players=players, tick=tick, fetched_at=fetched_at,
    )


def _skills(hero_id, _enemies):
    """General rows; filtered rows carry a real counter edge on item 111."""
    rows = [dict(row) for row in STATS[hero_id]]
    if _enemies:
        for row in rows:
            if row["item_id"] == 111:
                row["wins"] = int(row["wins"]) + 50  # +1.0 pp: evidence without dominating the main pick
    return rows


def _matchups(hero_id):
    return MATCHUPS[hero_id]


def _assert_hud_items(window, state):
    assert window._current_state is state
    assert window._content_kind == "items", window._content_kind
    assert window._view is not None
    assert window._view.item_names == [item.name for item in state.recommended_items]
    assert window._counter_view is not None
    assert window._counter_view.item_names == [item.name for item in state.counter_items]
    if state.next_buy is not None:
        subtitle = window._counter_view._subtitle.cget("text")
        assert subtitle == f"VS {state.counter_items[0].enemy_name.upper()[:10]} / GAIN"


def run(verbose=False):
    """Run the lifecycle and return observable phase data. Raises on failure."""
    clock = Clock()
    screen = {"id": MATCH_A}
    phase = {"match": MATCH_A, "hero": HERO_A, "souls": 2500, "enemy": HERO_B, "alive": True}

    def fake_fetch(match_id):
        if not phase["alive"]:
            return None
        return _snapshot(match_id, phase["hero"], phase["souls"], phase["enemy"], clock.value)

    live_match._CACHE.clear()
    live_match._LAST_TICK.clear()
    live_match._MISSES.clear()
    try:
        with tempfile.TemporaryDirectory() as cache:
            source = AdvisorDataSource(
                account_id=ACCOUNT,
                require_match=True,
                assets_fetcher=lambda: ASSETS,
                stats_fetcher=_skills,
                matchup_fetcher=_matchups,
                cache_path=Path(cache),
            )
            config = OverlayConfig(
                layout="horizontal", max_items=1, standby_badge=False,
                show_counters=True, source="advisor", only_in_game=False, opacity=0.3,
            )
            with patch.object(live_match, "_now", clock), \
                    patch.object(live_match, "fetch_live_snapshot", side_effect=fake_fetch), \
                    patch.object(advisor_api, "find_active_match",
                                 side_effect=lambda *a, **k: screen["id"]), \
                    patch("ui.main_window.save_config", return_value=None), \
                    patch("icon_loader.prewarm_icon", return_value=None), \
                    patch.object(sqlite3, "connect",
                                 side_effect=AssertionError("advisor must not open a database")):
                try:
                    window = OverlayWindow(
                        config=config,
                        data_source=source,
                        enable_tray=False,
                        enable_dpi=False,
                        enable_hotkeys=False,
                        enable_worker=False,
                    )
                except tk.TclError as err:  # pragma: no cover - headless host
                    raise RuntimeError(f"Tk unavailable: {err}") from err

                def poll():
                    state = window.poll_once()
                    window._drain_queue()
                    window.root.update_idletasks()
                    return state

                try:
                    early = poll()
                    assert early.source == "advisor"
                    assert early.match_id == str(MATCH_A)
                    assert early.stage == "early" and early.net_worth == 2500
                    assert early.hero_name == "Grey Talon"
                    assert early.next_buy is not None
                    assert early.next_buy.name == "Talon Trick"
                    assert early.next_buy.tier == 1
                    assert early.recommended_items[0].name == early.next_buy.name
                    assert early.build_candidates[0].name == early.next_buy.name
                    assert all(item.tier <= 2 for item in early.recommended_items)
                    assert all(item.cost <= early.net_worth for item in early.recommended_items)
                    assert all(item.name != "Mystic Sign" for item in early.recommended_items)
                    assert early.counter_items, "early build counter should be present"
                    _assert_hud_items(window, early)

                    clock.value = 7.0
                    phase["souls"] = 10000
                    mid = poll()
                    assert mid.stage == "mid" and mid.net_worth == 10000
                    assert mid.next_buy is not None
                    assert mid.next_buy.name == "Mid Relic"
                    assert mid.next_buy.tier == 2 and mid.next_buy.cost == 5000
                    assert mid.next_buy.cost <= mid.net_worth
                    assert mid.recommended_items[0].name == "Mid Relic"
                    assert mid.next_buy.tier > early.next_buy.tier
                    assert all(item.cost <= mid.net_worth for item in mid.recommended_items)
                    assert all(item.name != "Mystic Sign" for item in mid.recommended_items)
                    assert len(mid.build_candidates) == 3
                    assert mid.build_candidates[0].name == mid.next_buy.name
                    assert mid.counter_items
                    _assert_hud_items(window, mid)

                    clock.value = 14.0
                    phase["souls"] = 22000
                    late = poll()
                    assert late.stage == "late" and late.net_worth == 22000
                    assert late.next_buy is not None
                    assert late.next_buy.name == "Late Hammer"
                    assert late.next_buy.tier == 4 and late.next_buy.cost == 6400
                    assert late.next_buy.tier > mid.next_buy.tier
                    assert late.next_buy.cost > mid.next_buy.cost
                    assert late.recommended_items[0].name == "Late Hammer"
                    assert all(item.cost <= late.net_worth for item in late.recommended_items)
                    assert late.build_candidates[0].name == late.next_buy.name
                    assert late.counter_items
                    _assert_hud_items(window, late)

                    clock.value = 20.05
                    phase["alive"] = False
                    ended = poll()
                    assert ended.scan_status == "connecting" and ended.is_in_match is False
                    assert ended.match_id is None and ended.net_worth == 0 and ended.stage == ""
                    assert ended.hero_name == "Unknown" and ended.hero_id is None
                    assert ended.recommended_items == [] and ended.build_candidates == []
                    assert ended.next_buy is None and ended.counter_items == []
                    assert ended.enemy_heroes == [] and ended.strongest_enemy == ""
                    assert ended.strongest_enemy_winrate is None and ended.owned_items == set()
                    assert window._current_state is ended
                    assert window._content_kind == "status"
                    assert window._parked is False
                    assert window._view is not None and window._counter_view is None
                    assert window.container.winfo_children()
                    assert window.root.winfo_x() > -10000

                    clock.value = 27.0
                    screen["id"] = MATCH_B
                    phase.update(
                        match=MATCH_B, hero=HERO_B, souls=1200, enemy=HERO_A, alive=True,
                    )
                    restarted = poll()
                    assert restarted.scan_status == "ok" and restarted.is_in_match is True
                    assert restarted.match_id == str(MATCH_B)
                    assert restarted.hero_id == HERO_B and restarted.hero_name == "Test Enemy"
                    assert restarted.stage == "early" and restarted.net_worth == 1200
                    assert restarted.next_buy is not None
                    assert restarted.next_buy.name == "Mystic Sign"
                    assert restarted.next_buy.tier == 1
                    assert all(item.name != "Talon Trick" for item in restarted.recommended_items)
                    assert all(item.name != "Talon Trick" for item in restarted.build_candidates)
                    assert restarted.enemy_heroes == ["Grey Talon"]
                    assert restarted.strongest_enemy == "Grey Talon"
                    _assert_hud_items(window, restarted)

                    report = {
                        "early": _brief(early),
                        "mid": _brief(mid),
                        "late": _brief(late),
                        "ended": _brief(ended),
                        "restarted": _brief(restarted),
                        "hud": {
                            "ended_kind": "status",
                            "ended_parked": False,
                            "ended_children": 1,
                            "restarted_kind": window._content_kind,
                            "restarted_cards": window._view.item_names,
                        },
                        "source": {
                            "class": type(source).__name__,
                            "advisor": source.is_advisor,
                            "api": API,
                            "database_connections": 0,
                        },
                    }
                    if verbose:
                        for name in ("early", "mid", "late", "ended", "restarted"):
                            print(f"{name.upper():9} {report[name]}")
                    return report
                finally:
                    window.close()
    finally:
        live_match._CACHE.clear()
        live_match._LAST_TICK.clear()
        live_match._MISSES.clear()


def _brief(state):
    return {
        "match_id": state.match_id,
        "hero": state.hero_name,
        "stage": state.stage,
        "souls": state.net_worth,
        "items": [(item.name, item.tier, item.cost) for item in state.recommended_items],
        "next": (state.next_buy.name, state.next_buy.tier, state.next_buy.cost)
        if state.next_buy else None,
        "candidates": [item.name for item in state.build_candidates],
        "counters": [item.name for item in state.counter_items],
        "status": state.scan_status,
        "in_match": state.is_in_match,
    }
