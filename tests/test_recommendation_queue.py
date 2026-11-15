"""A steady queue must not preserve stale evidence or illegal purchases."""

from dataclasses import replace

from models import Candidate, Scored
from recommendation_engine import rank
from recommendation_queue import RecommendationQueue


def entry(item_id, score, category="weapon", affordable=True, **kwargs):
    candidate = Candidate(item_id, f"Item {item_id}", category=category,
                          cost=500, matches=500, win_rate=.55, **kwargs)
    return Scored(candidate, score, "low", affordable_now=affordable)


def ids(items):
    return [item.item_id for item in items]


def test_held_order_uses_current_evidence_until_review():
    clock = [0.0]
    queue = RecommendationQueue(lambda: clock[0])
    a, b, c, d = (entry(i, 10 - i) for i in range(1, 5))
    assert ids(queue.update([a, b, c, d], owner=(1, 2), limit=3)) == [1, 2, 3]
    refreshed = replace(a, candidate=replace(a.candidate, win_rate=.58, matches=900))
    d = replace(d, score=20)
    clock[0] = 149
    held = queue.update([d, b, c, refreshed], owner=(1, 2), limit=3)
    assert ids(held) == [1, 2, 3]
    assert held[0].win_rate == .58 and held[0].matches == 900
    clock[0] = 150
    assert ids(queue.update([d, b, c, refreshed], owner=(1, 2), limit=3)) == [1, 2, 4]
    assert queue.explanation["action"] == "reviewed"
    assert queue.explanation["selected_ids"] == [1, 2, 4]


def test_no_rotation_for_its_own_sake_and_no_catchup_burst():
    clock = [0.0]
    queue = RecommendationQueue(lambda: clock[0])
    original = [entry(i, 10-i) for i in range(1, 4)]
    queue.update(original, owner=(1,), limit=3)
    clock[0] = 150
    assert ids(queue.update(original + [entry(4, 1)], owner=(1,), limit=3)) == [1, 2, 3]
    clock[0] = 9000
    pool = [entry(5, 30), entry(6, 20)] + original
    assert ids(queue.update(pool, owner=(1,), limit=3)) == [1, 2, 5]


def test_bought_or_missing_items_leave_before_timer():
    queue = RecommendationQueue(lambda: 1)
    pool = [entry(i, 10-i) for i in range(1, 6)]
    queue.update(pool, owner=(1,), limit=3)
    updated = queue.update(pool[1:], owner=(1,), limit=3, owned_ids=[1], categories={1: "weapon"})
    assert ids(updated) == [2, 3, 4]
    assert queue.explanation["action"] == "invalidated"
    # No previous object can survive if all current evidence is unavailable.
    assert queue.update([], owner=(1,), limit=3) == []


def test_inventory_joint_slots_and_competing_upgrades():
    queue = RecommendationQueue(lambda: 1)
    pool = [entry(10, 3, replaces_ids=(1,)), entry(11, 2, replaces_ids=(1,)), entry(12, 1)]
    picked = queue.update(pool, owner=(1,), limit=3, owned_ids=[1, 2, 3, 4],
                          categories={i: "weapon" for i in range(1, 5)})
    assert ids(picked) == [10]


def test_savings_tags_never_override_affordable_next_buy():
    queue = RecommendationQueue(lambda: 1)
    pool = [entry(1, 3), entry(2, 2)]
    queue.update(pool, owner=(1,), limit=2)
    fresh = [pool[1], replace(pool[0], affordable_now=False, tags=("SAVE 200",))]
    picked = queue.update(fresh, owner=(1,), limit=2)
    assert ids(picked) == [2, 1]
    assert picked[1].tags == ("SAVE 200",)


def test_match_or_stage_change_and_clear_reset_order():
    queue = RecommendationQueue(lambda: 1)
    pool = [entry(1, 2), entry(2, 1)]
    queue.update(pool, owner=(1, "early"), limit=2)
    assert ids(queue.update(list(reversed(pool)), owner=(1, "mid"), limit=2)) == [2, 1]
    queue.clear()
    assert queue.state.item_ids == [] and queue.state.owner is None


def test_full_rank_pool_does_not_drop_valid_held_item_below_top_slots():
    candidates = [entry(i, 10-i).candidate for i in range(1, 7)]
    assert len(rank(candidates, souls=10000, bank=10000, reserve_slots=False)) == 6
    assert len(rank(candidates, souls=10000, bank=10000)) == 4


def test_queue_config_round_trip_and_limits():
    from config import _from_dict, _to_dict
    assert _from_dict({}).queue_seconds == 150
    assert _from_dict({"queue_seconds": 0}).queue_seconds == 60
    assert _to_dict(_from_dict({"queue_seconds": 180}))["queue_seconds"] == 180


def test_counter_chip_queue_keeps_order_across_new_best_signal():
    from advisor_evidence import counter_picks
    from models import MatchContext
    clock = [0]
    queue = RecommendationQueue(lambda: clock[0])
    candidates = [replace(entry(i, 0).candidate, counter_gain=i*.01, counter_enemy="Threat",
                          evidence={"accepted": True, "enemy": {"matches": 500},
                                    "enemy_hero_ids": [2], "enemy_rate": .6}) for i in range(1, 5)]
    def pick():
        return counter_picks(candidates, MatchContext(bank=10000), 20000, [], {}, [],
                             queue=queue, owner=(1,))
    assert ids(pick()) == [4, 3, 2]
    candidates[0] = replace(candidates[0], counter_gain=.2)
    clock[0] = 149
    assert ids(pick()) == [4, 3, 2]
    clock[0] = 150
    assert ids(pick()) == [4, 3, 1]
