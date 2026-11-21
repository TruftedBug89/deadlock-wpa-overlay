"""A full plan uses current evidence and shares a legal inventory footprint."""

from collections import Counter
from dataclasses import replace
import time

from advisor_build import extend_plan, threat_summary
from advisor_source import AdvisorDataSource
from live_match import LivePlayer, LiveSnapshot
from models import Candidate, MatchContext, Scored
from recommendation_queue import RecommendationQueue


def entry(item_id, category="weapon", score=1, replaces=()):
    return Scored(Candidate(item_id, f"Item {item_id}", category=category, cost=500,
                            matches=1000, win_rate=.55, replaces_ids=tuple(replaces)),
                  score, "medium", affordable_now=True)


def test_full_plan_reserves_prefix_slots_and_upgrade_components():
    prefix = [entry(20, replaces=(1,)), entry(21, "spirit")]
    pool = prefix + [entry(22, replaces=(1,)), entry(23), entry(24, "spirit")]
    plan = extend_plan(RecommendationQueue(), prefix, pool, owner=(1,), interval=150,
                       owned_ids=[1, 2, 3, 4], categories={i: "weapon" for i in range(1, 5)})
    assert [item.item_id for item in plan] == [20, 21, 24]
    # Component 1 cannot free its slot twice, and the weapon category stays full.
    assert 22 not in [item.item_id for item in plan]
    assert 23 not in [item.item_id for item in plan]


def test_plan_tail_is_stable_until_review_and_revalidates_held_evidence():
    clock = [0]
    queue = RecommendationQueue(lambda: clock[0])
    prefix = [entry(1)]
    first = [entry(i, score=20-i) for i in range(2, 6)]
    def update(pool):
        return extend_plan(queue, prefix, prefix + pool, owner=(1,), interval=150,
                           owned_ids=[], categories={})
    assert [item.item_id for item in update(first)] == [1, 2, 3, 4]
    upgraded = replace(first[0], candidate=replace(first[0].candidate, win_rate=.62))
    pool = [replace(first[-1], score=50), upgraded, first[1], first[2]]
    clock[0] = 149
    held = update(pool)
    assert [item.item_id for item in held] == [1, 2, 3, 4]
    assert held[1].win_rate == .62
    clock[0] = 150
    assert [item.item_id for item in update(pool)] == [1, 2, 3, 5]


def test_threat_summary_never_invents_an_unknown_leader():
    names = {2: "Seven", 3: "Haze"}
    assert threat_summary(MatchContext(), names.get) == "Enemy threat data unknown"
    context = MatchContext(enemy_top_hero_id=2, enemy_top_souls=23456,
                           enemy_damage_hero_id=3, enemy_damage=9876)
    assert threat_summary(context, names.get) == "Seven leads souls: 23,456 / Haze leads damage: 9,876"


def live_source(tmp_path, flex=3):
    assets = {"items": [
        dict(id=i, name=f"Item {i}", type="upgrade", item_slot_type=category,
             cost=500, shopable=True, component_items=[], is_active_item=False)
        for category, ids in (("weapon", range(1, 6)), ("spirit", range(6, 11)),
                              ("vitality", range(11, 16))) for i in ids],
        "heroes": [dict(id=1, name="Our Hero"), dict(id=2, name="Threat")]}
    players = [LivePlayer(1001, 2, 1, 10000, gold=500, owned_item_ids=[]),
               LivePlayer(1002, 3, 2, 22000, hero_damage=9000, gold=1000, owned_item_ids=[])]
    snapshot = LiveSnapshot(9001, players, fetched_at=time.time(),
                            team_flex_slots={2: flex} if flex is not None else {})
    source = AdvisorDataSource(account_id=1001, match_id=9001, require_match=True,
                               assets_fetcher=lambda: assets,
                               stats_fetcher=lambda *_: [dict(item_id=i, wins=550, matches=1000)
                                                         for i in range(1, 16)],
                               matchup_fetcher=lambda *_: [], cache_path=tmp_path,
                               live_fetcher=lambda _: snapshot)
    return source, snapshot


def test_full_plan_source_has_legal_slots_fresh_save_labels_and_explanation(tmp_path):
    source, snapshot = live_source(tmp_path)
    state = source.get_game_state(max_items=5)
    assert len(state.recommended_items) == 5
    assert len(state.build_plan) == 12
    assert state.inventory_capacity == 12
    assert state.build_plan[:5] == state.recommended_items
    assert max(Counter(item.category for item in state.build_plan).values()) == 4
    assert {item.item_id for item in state.build_plan} == {
        row["item_id"] for row in source.last_explanation["build_plan"]}
    assert state.threat_summary == "Threat leads souls: 22,000 / Threat leads damage: 9,000"
    snapshot.players[0].gold = 0
    snapshot.players[0].owned_item_ids = [state.build_plan[0].item_id]
    refreshed = source.get_game_state()
    assert refreshed.next_buy is None
    assert len(refreshed.build_plan) <= 11
    assert all(item.item_id not in snapshot.players[0].owned_item_ids for item in refreshed.build_plan)
    assert all(not item.can_buy and item.reason.startswith("SAVE") for item in refreshed.build_plan)
    snapshot.players[0].owned_item_ids = None
    unknown = source.get_game_state()
    assert unknown.scan_status == "unknown"
    assert unknown.build_plan == []
    assert source._plan_queue.state.item_ids == []


def test_identity_failure_is_reported_before_catalog_requests(tmp_path):
    def forbidden():
        raise AssertionError("No catalog request before live identity is ready")
    source = AdvisorDataSource(account_id=1001, match_id=9001, require_match=True,
                               live_fetcher=lambda _: None, assets_fetcher=forbidden,
                               cache_path=tmp_path)
    state = source.get_game_state()
    assert state.scan_status == "connecting"
    assert "broadcast" in state.last_error
    assert not state.build_plan


def test_sale_replaces_one_item_only_at_confirmed_capacity(tmp_path):
    source, snapshot = live_source(tmp_path, flex=0)
    snapshot.players[0].owned_item_ids = [1, 2, 3, 6, 7, 8, 11, 12, 13]
    source._stats_fetcher = lambda _hero, _ids, _bucket: [
        dict(item_id=i, wins=700 if i == 4 else 390 if i == 1 else 500,
             matches=1000, bucket=10000 if _bucket else None)
        for i in range(1, 16)
    ]
    full = source.get_game_state()
    assert full.inventory_capacity == 9 and full.next_buy is None and not full.recommended_items
    assert full.replacement.sell_id == 1 and full.replacement.buy.item_id == 4
    assert source.last_explanation["inventory_replacement"]["slot_limit"] == 9
    snapshot.team_flex_slots[2] = 1
    opened = source.get_game_state()
    assert opened.inventory_capacity == 10 and opened.replacement is None
    assert opened.next_buy.item_id == 4
    snapshot.team_flex_slots.clear()
    uncertain = source.get_game_state()
    assert uncertain.inventory_capacity is None and uncertain.replacement is None
    assert uncertain.next_buy is None
