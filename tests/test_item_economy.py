"""Stage-aware economy rules used to rank recommendations."""

from item_economy import affordable, stage_for_souls, stage_penalty, stage_target_cost


def test_stage_thresholds():
    assert stage_for_souls(0) == ""
    assert stage_for_souls(1200) == "early"
    assert stage_for_souls(6000) == "mid"
    assert stage_for_souls(13999) == "mid"
    assert stage_for_souls(14000) == "late"


def test_target_cost_rises_with_souls():
    assert stage_target_cost(0) == 0
    assert stage_target_cost(1000) == 550
    assert stage_target_cost(20000) == 6400


def test_penalty_prefers_items_near_the_stage_budget():
    early_cheap = stage_penalty(500, 1500)
    early_expensive = stage_penalty(6400, 1500)
    late_expensive = stage_penalty(6400, 20000)
    late_cheap = stage_penalty(500, 20000)
    assert early_cheap < early_expensive
    assert late_expensive < late_cheap


def test_affordable():
    assert affordable(500, 0) is True  # unknown souls: do not filter
    assert affordable(500, 1200) is True
    assert affordable(6400, 1200) is False
    assert affordable(None, 1200) is True
