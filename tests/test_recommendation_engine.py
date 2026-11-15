"""Picker rules: relative edges, budget truth, slot limits, sample gates."""

from item_stats import merge_buckets, smoothed_win_rate
from match_context import MatchContext
from recommendation_engine import (
    Candidate,
    baseline_win_rate,
    build_candidate,
    confidence_for,
    rank,
    rank_counters,
    score_candidate,
)

ITEM = {
    "id": 10,
    "name": "Test Blade",
    "category": "weapon",
    "cost": 3200,
    "item_tier": 3,
    "image": "blade.png",
    "class_name": "upgrade_test_blade",
}


def candidate(item_id=10, name="Test Blade", win_rate=0.52, matches=5000, cost=3200,
              category="weapon", pick_rate=0.4, counter_gain=0.0, counter_enemy=""):
    return Candidate(
        item_id=item_id,
        name=name,
        category=category,
        cost=cost,
        tier=3,
        win_rate=win_rate,
        matches=matches,
        pick_rate=pick_rate,
        counter_gain=counter_gain,
        counter_enemy=counter_enemy,
    )


def test_build_candidate_rejects_thin_samples():
    assert build_candidate(ITEM, {"item_id": 10, "matches": 99, "wins": 90}) is None
    built = build_candidate(ITEM, {"item_id": 10, "matches": 100, "wins": 60, "players": 50})
    assert built is not None and built.win_rate is not None
    assert 0.5 < built.win_rate < 0.7


def test_build_candidate_requires_a_price_and_name():
    assert build_candidate({**ITEM, "cost": None}, {"matches": 500, "wins": 260}) is not None
    assert build_candidate({**ITEM, "name": ""}, {"matches": 500, "wins": 260}) is None


def test_counter_gain_only_counts_positive_matchup_edges():
    general = {"matches": 5000, "wins": 2500}
    better = build_candidate(ITEM, general, {"matches": 4000, "wins": 2200}, "Haze", counter_baseline=0.5)
    worse = build_candidate(ITEM, general, {"matches": 4000, "wins": 1800}, "Haze", counter_baseline=0.5)
    assert better is not None and better.counter_gain > 0
    assert worse is not None and worse.counter_gain == 0.0


def test_relative_edge_beats_absolute_win_rate():
    rows = [
        {"matches": 5000, "wins": 2500},
        {"matches": 5000, "wins": 2600},
        {"matches": 5000, "wins": 2600},
    ]
    base = baseline_win_rate(rows)
    assert abs(base - 0.5133) < 0.01
    scored = score_candidate(candidate(win_rate=0.53), base, bank=6400)
    assert scored.breakdown["edge"] > 0
    assert scored.tags == ("POPULAR",)


def test_score_prefers_the_popular_item_on_equal_win_rate():
    base = 0.5
    popular = score_candidate(candidate(item_id=1, pick_rate=0.6), base)
    obscure = score_candidate(candidate(item_id=2, pick_rate=0.05), base)
    assert popular.score > obscure.score


def test_counter_bonus_is_capped_and_visible_in_tags():
    scored = score_candidate(
        candidate(item_id=3, win_rate=0.52, counter_gain=0.10, counter_enemy="Haze"),
        0.5, bank=6400,
    )
    assert scored.breakdown["counter"] <= 3.0 * 0.8 + 1e-9
    assert "VS HAZE" in scored.tags


def test_rank_excludes_unearned_items():
    ctx = MatchContext(known=True, souls=1200, stage="early")
    ranked = rank([candidate(cost=6400), candidate(item_id=11, name="Cheap", cost=500)],
                  souls=ctx.souls, target_cost=ctx.target_cost)
    assert [entry.name for entry in ranked] == ["Cheap"]


def test_rank_keeps_saving_targets_last_and_labels_them():
    ctx = MatchContext(known=True, souls=20000, bank=500, stage="late")
    ranked = rank([candidate(cost=6400)], souls=ctx.souls, bank=ctx.bank,
                  target_cost=ctx.target_cost)
    assert len(ranked) == 1
    assert ranked[0].affordable_now is False
    assert any(tag.startswith("SAVE") for tag in ranked[0].tags)


def test_rank_respects_the_four_slots_per_category():
    owned = {1: "weapon", 2: "weapon", 3: "weapon", 4: "weapon"}
    ranked = rank(
        [candidate(item_id=10, category="weapon"),
         candidate(item_id=11, name="Vitality Thing", category="vitality")],
        souls=20000,
        target_cost=6400,
        owned_ids=list(owned),
        owned_categories=owned,
    )
    assert [entry.category for entry in ranked] == ["vitality"]


def test_rank_is_deterministic_and_never_emits_a_priceless_item():
    items = [candidate(item_id=1), candidate(item_id=2, name="Other"), candidate(item_id=3, name="No Price", cost=None)]
    first = rank(items, souls=20000, target_cost=6400)
    second = rank(items, souls=20000, target_cost=6400)
    assert [entry.item_id for entry in first] == [entry.item_id for entry in second]
    assert all(entry.cost for entry in first)


def test_rank_counters_needs_positive_gain_and_skips_shown_items():
    picks = [
        candidate(item_id=1, counter_gain=0.02),
        candidate(item_id=2, counter_gain=0.05, name="Best Counter"),
        candidate(item_id=3, counter_gain=0.0, name="No Counter"),
    ]
    ranked = rank_counters(picks, exclude_ids=[2])
    assert [entry.item_id for entry in ranked] == [1]


def test_confidence_labels_track_sample_size():
    assert confidence_for(50) == "low"
    assert confidence_for(1000) == "medium"
    assert confidence_for(5000) == "high"


def test_merge_buckets_windows_around_the_current_souls():
    rows = [
        {"item_id": 1, "bucket": 0, "matches": 1000, "wins": 520, "players": 500, "avg_buy_time_s": 300.0},
        {"item_id": 1, "bucket": 15000, "matches": 400, "wins": 220, "players": 200, "avg_buy_time_s": 900.0},
        {"item_id": 1, "bucket": 20000, "matches": 600, "wins": 300, "players": 300, "avg_buy_time_s": 1000.0},
        {"item_id": 1, "bucket": 40000, "matches": 900, "wins": 450, "players": 400, "avg_buy_time_s": 1500.0},
    ]
    merged = merge_buckets(rows, 20000)
    assert len(merged) == 1
    assert merged[0]["matches"] == 1000  # 15000 + 20000, not 0 or 40000
    assert merged[0]["wins"] == 520
    assert 900 <= merged[0]["avg_buy_time_s"] <= 1000


def test_merge_buckets_without_souls_returns_rows_untouched():
    rows = [{"item_id": 1, "bucket": 0, "matches": 10, "wins": 5}]
    assert merge_buckets(rows, 0) == rows


def test_stage_price_buries_a_starter_at_late_souls():
    starter = candidate(item_id=1, name="Starter", cost=500, win_rate=0.545)
    core = candidate(item_id=2, name="Core", cost=6400, win_rate=0.535)
    ranked = rank([starter, core], souls=22000, target_cost=6400)
    assert [entry.name for entry in ranked] == ["Core", "Starter"]


def test_smoothed_win_rate_prior_is_stable():
    tiny = smoothed_win_rate({"matches": 120, "wins": 120})
    huge = smoothed_win_rate({"matches": 200000, "wins": 112000})
    assert tiny is not None and huge is not None
    assert huge < 0.60 < tiny
