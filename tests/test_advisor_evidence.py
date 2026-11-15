"""Counter regressions and live purchase truth, using synthetic API evidence."""

from dataclasses import replace

import pytest

from advisor_evidence import counter_evidence
from advisor_source import AdvisorDataSource
from item_stats import observed_win_rate, smoothed_win_rate, pick_rate
from live_match import LivePlayer, LiveSnapshot
from recommendation_engine import rank
from tests.test_recommendation_engine import candidate


def row(item, wins, matches=1000, bucket=20000):
    return dict(item_id=item, wins=wins, matches=matches, bucket=bucket)


def source(tmp_path, stats, snapshot=None, enemies=(2, 3)):
    assets = {"items": [dict(id=i, name=name, type="upgrade", item_slot_type=category,
                             cost=cost, shopable=True)
                         for i, name, category, cost in (
                             (1, "Magic Carpet", "spirit", 3200),
                             (2, "Golden Goose Egg", "weapon", 3200),
                             (3, "Measured Winner", "vitality", 3200),
                             (4, "Pool Anchor", "spirit", 3200))],
              "heroes": [dict(id=1, name="Infernus"), dict(id=2, name="Seven"), dict(id=3, name="Haze")]}
    return AdvisorDataSource(hero_id=1, enemy_ids=enemies, preview_souls=20000,
                             assets_fetcher=lambda: assets, stats_fetcher=stats,
                             matchup_fetcher=lambda _: [], cache_path=tmp_path,
                             match_id=7 if snapshot else None, account_id=42,
                             require_match=snapshot is not None,
                             live_fetcher=lambda _: snapshot)


def test_carpet_and_goose_positive_gains_are_not_counter_evidence(tmp_path):
    general = [row(1, 249), row(2, 375), row(3, 500), row(4, 600, 1000)]
    enemy = [row(1, 371), row(2, 415), row(3, 600), row(4, 550)]
    advisor = source(tmp_path, lambda hero, ids, bucket: enemy if ids else general)
    advisor.get_game_state(max_items=1)
    evidence = {r["item_id"]: r for r in advisor.last_explanation["candidate_evidence"]}
    for i in (1, 2):
        assert evidence[i]["gain"] > 0
        assert evidence[i]["decision"] == "does_not_beat_enemy_pool"
        assert not evidence[i]["accepted"]
    assert evidence[3]["accepted"]
    assert advisor.last_explanation["items"][0]["breakdown"]["counter"] > 0


@pytest.mark.parametrize("count", [0, 1, 99])
def test_enemy_sample_gate_is_independent(count):
    evidence = counter_evidence(row(1, 500), row(1, count, count),
                                [row(2, 400)], [2], "overall")
    assert evidence["decision"] == "enemy_sample_missing_or_thin"


def test_weighted_pool_and_counts_reproduce_counter_gain():
    pool = [row(1, 600), row(2, 4500, 10000)]
    evidence = counter_evidence(row(1, 500), pool[0], pool, [2, 3], "bracket-20000")
    counts = evidence["enemy_pool"]
    assert evidence["enemy_pool_baseline"] == sum(r["wins"] for r in counts) / sum(r["matches"] for r in counts)
    assert evidence["gain"] == evidence["enemy"]["wins"] / evidence["enemy"]["matches"] - .5
    assert evidence["accepted"] and evidence["filter_semantics"] == "any"


def test_thin_bracket_pair_falls_back_together(tmp_path):
    def stats(hero, ids, bucket):
        if bucket:
            return [row(1, 98, 99)] if ids else [row(1, 100)]
        return [row(1, 550), row(2, 450)] if ids else [row(1, 500), row(2, 500)]
    advisor = source(tmp_path, stats)
    advisor.get_game_state()
    evidence = advisor.last_explanation["candidate_evidence"][0]
    assert evidence["basis"] == "overall"
    assert evidence["general"]["wins"] == 500
    assert evidence["gain"] == pytest.approx(.05)


def test_missing_overall_enemy_data_cannot_make_a_counter(tmp_path):
    def stats(hero, ids, bucket):
        return [] if ids else [row(1, 600)]
    advisor = source(tmp_path, stats)
    state = advisor.get_game_state()
    assert state.counter_items == []
    assert all(r["breakdown"]["counter"] == 0 for r in advisor.last_explanation["items"])


def snapshot(bank=3500, owned=()):
    return LiveSnapshot(7, [
        LivePlayer(42, 2, 1, 20000, gold=bank, owned_item_ids=list(owned) if owned is not None else None,
                   hero_damage=2000),
        LivePlayer(43, 2, 4, 20000, hero_damage=10000),
        LivePlayer(44, 3, 2, 30000, hero_damage=9000),
        LivePlayer(45, 3, 3, 20000, hero_damage=1000),
    ])


@pytest.mark.parametrize("bank,owned", [(None, []), (3500, None)])
def test_unknown_live_budget_or_inventory_hides_purchase_advice(tmp_path, bank, owned):
    advisor = source(tmp_path, lambda *args: [row(1, 550)], snapshot(bank, owned))
    state = advisor.get_game_state()
    assert state.scan_status == "unknown"
    assert not state.recommended_items and not state.counter_items and state.next_buy is None


def test_unknown_owned_catalog_id_cannot_bypass_slot_limits(tmp_path):
    advisor = source(tmp_path, lambda *args: [row(1, 550)], snapshot(3500, [999]))
    state = advisor.get_game_state()
    assert state.scan_status == "unknown" and not state.recommended_items


def test_live_gold_ownership_and_threat_changes_are_recomputed(tmp_path):
    live = snapshot()
    def stats(hero, ids, bucket):
        return [row(1, 700 if ids == [2] else 500), row(2, 600 if ids == [3] else 500),
                row(3, 500), row(4, 500)]
    advisor = source(tmp_path, stats, live)
    first = advisor.get_game_state()
    assert first.next_buy.item_id == 1
    assert advisor.last_explanation["target_enemy_ids"] == [2]
    live.players[0].gold = 0
    live.players[0].owned_item_ids = [1]
    saving = advisor.get_game_state()
    assert saving.next_buy is None and not saving.counter_items
    assert all(i.item_id != 1 and not i.can_buy and i.reason.startswith("SAVE") for i in saving.recommended_items)
    live.players[0].gold = 3500
    live.players[0].owned_item_ids = []  # a real sale of the final owned item
    live.players[3].net_worth = 40000
    live.players[3].hero_damage = 12000
    changed = advisor.get_game_state()
    # The displayed queue keeps its valid order while each item's claim refreshes.
    assert changed.next_buy.item_id == saving.recommended_items[0].item_id
    assert [item.item_id for item in changed.recommended_items[:len(saving.recommended_items)]] == [
        item.item_id for item in saving.recommended_items
    ]
    refreshed = next(item for item in advisor.last_explanation["items"] if item["item_id"] == 2)
    assert refreshed["breakdown"]["counter"] > 0
    assert changed.known_owned_items == 0
    assert advisor.last_explanation["target_enemy_ids"] == [3]


def test_best_item_is_not_dropped_by_input_order_slot_limit():
    items = [candidate(item_id=i, win_rate=.50 + i / 100) for i in range(1, 7)]
    result = rank(items, souls=20000, bank=4000, limit=5)
    assert [r.item_id for r in result] == [6, 5, 4, 3]


def test_damage_carry_nudge_is_small_and_changes_with_damage_share():
    items = [candidate(item_id=1), candidate(item_id=2, category="vitality")]
    normal = rank(items, bank=4000, stance="ahead", damage_share=.1)
    carry = rank(items, bank=4000, stance="ahead", damage_share=.5)
    assert normal[0].item_id == 1 and carry[0].item_id == 2
    assert carry[0].breakdown["stance"] == .3
    assert carry[0].tags == ("PROTECT CARRY",)


@pytest.mark.parametrize("bad", [{"matches": 200}, row(1, 201, 200), row(1, -1),
                                  dict(row(1, 500), losses=400)])
def test_invalid_counts_are_unknown(bad):
    assert observed_win_rate(bad) is None and smoothed_win_rate(bad) is None


def test_unique_buyers_are_not_a_pick_rate():
    assert pick_rate({"players": 700, "matches": 1000}) == 0
    assert pick_rate({"matches": 1000, "_pool_matches": 10000}) == .1
