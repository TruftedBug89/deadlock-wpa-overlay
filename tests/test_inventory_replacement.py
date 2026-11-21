"""Inventory advice compares measured stage evidence and never budgets a sale."""

from dataclasses import replace

import pytest

from inventory_replacement import choose_replacement
from item_inventory import confirmed_capacity
from models import MatchContext, WpaItem
from recommendation_engine import rank, score_candidate
from tests.test_recommendation_engine import candidate


OWNED = set(range(1, 10))
STAGE = {"ranking_basis": "bracket-20000", "general_pool_baseline": .5}
HELD = replace(candidate(item_id=1, name="Held", win_rate=.43), evidence=STAGE)
BUY = replace(candidate(item_id=10, name="Buy", win_rate=.57), evidence=STAGE)
CONTEXT = MatchContext(known=True, ownership_known=True, souls=20000, bank=3500)


def suggest(held=HELD, buy=BUY, context=CONTEXT, capacity=9, plan=(), active=None):
    flags = {1: False, 10: False} if active is None else active

    def to_item(scored):
        return WpaItem(scored.name, item_id=scored.item_id, cost=scored.cost)

    return choose_replacement([held], [buy], plan, context=context, capacity=capacity,
                              owned_ids=OWNED, item_meta=lambda item_id: {"is_active_item": flags.get(item_id)},
                              to_item=to_item)


def test_full_capacity_with_stronger_same_stage_item_suggests_one_replacement():
    swap = suggest()
    assert swap is not None
    assert (swap.sell_id, swap.buy.item_id, swap.buy.cost) == (1, 10, 3200)
    assert swap.slots_used == swap.slot_limit == 9
    assert swap.held_win_rate == .43 and swap.buy_win_rate == .57
    assert swap.supported_gap == pytest.approx(swap.buy_lower - swap.held_upper)


@pytest.mark.parametrize("capacity", [None, 10, 12])
def test_missing_capacity_or_free_slot_does_not_suggest_a_sale(capacity):
    assert suggest(capacity=capacity) is None


@pytest.mark.parametrize("context", [replace(CONTEXT, bank=3199), replace(CONTEXT, bank=None),
                                    replace(CONTEXT, ownership_known=False)])
def test_sale_never_assumes_refund_or_fills_unknown_live_fields(context):
    assert suggest(context=context) is None


def test_upgrade_or_useful_current_counter_is_protected():
    upgrade = replace(BUY, replaces_ids=(1,))
    assert suggest(plan=[score_candidate(upgrade, .5, bank=3500)]) is None
    protected = replace(HELD, evidence={**STAGE, "counter_applied_to_rank": True})
    assert suggest(held=protected) is None


@pytest.mark.parametrize("buy", [replace(BUY, matches=599), replace(BUY, win_rate=.44),
                                replace(BUY, evidence={**STAGE, "ranking_basis": "overall"}),
                                replace(BUY, category="vitality")])
def test_sale_requires_large_comparable_stage_samples(buy):
    assert suggest(buy=buy) is None


def test_sale_preserves_activation_type():
    assert suggest(active={1: False, 10: True}) is None
    assert suggest(active={1: False}) is None


def test_inventory_limit_applies_to_a_whole_recommendation_sequence():
    options = [BUY, replace(BUY, item_id=11, category="vitality")]
    assert len(rank(options, bank=3500, owned_ids=OWNED, inventory_capacity=10)) == 1
    assert not rank(options, bank=3500, owned_ids=OWNED, inventory_capacity=9)
    upgrade = replace(BUY, replaces_ids=(1,))
    assert rank([upgrade], bank=3500, owned_ids=OWNED, inventory_capacity=9)[0].item_id == 10


def test_size_inference_requires_verified_flex_slots_or_the_known_maximum():
    assert confirmed_capacity(None, 11) is None
    assert confirmed_capacity(None, 12) == 12
    assert confirmed_capacity(9, 10) is None
    assert confirmed_capacity(11, 10) == 11
