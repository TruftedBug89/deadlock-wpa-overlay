"""Owned items change upgrade eligibility without guessed synergies or prices."""

from item_inventory import component_graph, apply_inventory
from recommendation_engine import rank
from tests.test_recommendation_engine import candidate


def test_catalog_components_resolve_and_owned_upgrades_hide_their_ingredients():
    items = {1: {"class_name": "base"}, 2: {"class_name": "mid", "component_items": ["base"]},
             3: {"class_name": "high", "component_items": ["mid"]}}
    graph = component_graph(items)
    picks = apply_inventory([candidate(item_id=i) for i in (1, 2, 3)], [3], graph)
    assert picks == []


def test_upgrade_can_reuse_full_category_slot_with_honest_catalog_price():
    items = apply_inventory([candidate(item_id=10, cost=3200)], [1, 2, 3, 4], {10: (1,)})
    assert items[0].replaces_ids == (1,)
    assert items[0].cost == 3200  # no guessed discount
    picks = rank(items, bank=3200, souls=20000, owned_ids=[1, 2, 3, 4],
                 owned_categories={i: "weapon" for i in (1, 2, 3, 4)})
    assert [p.item_id for p in picks] == [10]
    assert rank(items, bank=200, souls=20000)[0].affordable_now is False


def test_missing_relationships_do_not_invent_an_upgrade():
    graph = component_graph({1: {"class_name": "base"}, 2: {"component_items": ["missing"]}})
    result = apply_inventory([candidate(item_id=2)], [1], graph)
    assert not result[0].replaces_ids


def test_catalog_cycles_terminate_without_recommending_owned_items():
    graph = {1: (2,), 2: (1,)}
    assert apply_inventory([candidate(item_id=1), candidate(item_id=2)], [1], graph) == []
