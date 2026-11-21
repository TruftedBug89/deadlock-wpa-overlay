"""Current-match build planning over freshly validated item evidence."""

from advisor_evidence import counter_picks
from item_economy import stage_for_souls
from item_inventory import BASE_INVENTORY_CAPACITY, confirmed_capacity
from inventory_replacement import choose_replacement
from models import BuildAdvice, WpaItem
from recommendation_engine import rank, select_legal


CONFIDENCE = {"high": 0.95, "medium": 0.75, "low": 0.5}
BUILD_LIMIT = 12
BUILD_NOTE = "Current evidence. SAVE targets need more souls; prices are per item."


def threat_summary(context, hero_name):
    """Describe only measured enemy leaders; an unknown leader stays unknown."""
    parts = []
    if context.enemy_top_hero_id is not None:
        parts.append(f"{hero_name(context.enemy_top_hero_id)} leads souls: {context.enemy_top_souls:,}")
    if context.enemy_damage_hero_id is not None:
        parts.append(f"{hero_name(context.enemy_damage_hero_id)} leads damage: {context.enemy_damage:,}")
    return " / ".join(parts) if parts else "Enemy threat data unknown"


def extend_plan(queue, prefix, pool, *, owner, interval, owned_ids, categories, inventory_capacity=None):
    """Add a stable tail without reusing slots or components reserved by the queue."""
    prefix_ids = {entry.item_id for entry in prefix}
    consumed = {item for entry in prefix for item in entry.candidate.replaces_ids}
    ingredients = {item for entry in prefix for item in entry.candidate.evidence.get("catalog_ancestors", ())}
    remaining = set(owned_ids) - consumed
    reserved = remaining | prefix_ids
    category_map = dict(categories)
    category_map.update({entry.item_id: entry.category for entry in prefix})
    usable = [entry for entry in pool if entry.item_id not in prefix_ids | ingredients
              and not consumed.intersection(entry.candidate.replaces_ids)
              and not prefix_ids.intersection(entry.candidate.evidence.get("catalog_ancestors", ()))]
    tail = queue.update(usable, owner=owner, limit=max(1, BUILD_LIMIT - len(prefix)),
                        interval=interval, owned_ids=reserved, categories=category_map,
                        inventory_capacity=inventory_capacity)
    return prefix + tail


class AdvisorBuildMixin:
    """Build two views of the same evidence; keep network reads in the source."""

    def _to_wpa(self, scored) -> WpaItem:
        reason = " / ".join(scored.tags)
        if reason == "UPGRADE":
            component = self._meta(scored.candidate.replaces_ids[0])
            reason = f"Upgrade {component['name']}" if component else "Upgrade owned item"
        return WpaItem(
            name=scored.name, category=scored.category, cost=scored.cost,
            tier=scored.tier, image_url=scored.image_url, class_name=scored.class_name,
            confidence=CONFIDENCE.get(scored.confidence, 0.5),
            can_buy=scored.affordable_now is True, item_id=scored.item_id,
            win_rate=scored.win_rate, samples=scored.matches,
            reason=reason,
        )

    def _make_advice(self, candidates, measured, context, live, hero_id, souls, target_cost,
                     baseline, owned_ids, max_items, queue_seconds) -> BuildAdvice:
        categories = self._owned_categories()
        capacity = confirmed_capacity(context.inventory_capacity, len(owned_ids)) if live else None
        slot_limit = (capacity or max(BASE_INVENTORY_CAPACITY, len(owned_ids))) if live else None
        pool = rank(candidates, stance=context.stance, damage_share=context.damage_share,
                    target_cost=target_cost, souls=souls, bank=context.bank,
                    baseline=baseline, reserve_slots=False,
                    owned_ids=owned_ids, owned_categories=categories, inventory_capacity=slot_limit)
        owner = ((live or {}).get("match_id"), (live or {}).get("owner"),
                 hero_id, stage_for_souls(souls))
        if live:
            ranked = self._item_queue.update(
                pool, owner=owner, limit=max(1, min(5, int(max_items))),
                interval=queue_seconds, owned_ids=owned_ids, categories=categories, inventory_capacity=slot_limit)
            plan = extend_plan(self._plan_queue, ranked, pool, owner=owner,
                               interval=queue_seconds, owned_ids=owned_ids, categories=categories,
                               inventory_capacity=slot_limit)
        else:
            ranked = select_legal(pool, max(3, min(5, int(max_items))), owned_ids, categories)
            plan = []  # A future full build cannot be inferred from a hero preview.
        items = [self._to_wpa(entry) for entry in ranked][:max(1, min(5, int(max_items)))]
        selected = {entry.item_id for entry in ranked}
        choices = select_legal(ranked + [entry for entry in pool if entry.item_id not in selected],
                               3, owned_ids, categories, inventory_capacity=slot_limit)
        counters = counter_picks(
            candidates, context, souls, owned_ids, categories, [item.item_id for item in items],
            preview=not live, queue=self._counter_queue if live else None, owner=owner,
            interval=queue_seconds, inventory_capacity=slot_limit,
            reserved_components={item for entry in ranked for item in entry.candidate.replaces_ids})
        replacement = choose_replacement(measured, candidates, plan, context=context, capacity=capacity,
                                         owned_ids=owned_ids, item_meta=self._meta, to_item=self._to_wpa) if live else None
        return BuildAdvice(
            ranked=ranked, plan=plan, items=items,
            choices=[self._to_wpa(entry) for entry in choices] if live else [],
            next_buy=next((item for item in items if item.can_buy), None) if live else None,
            replacement=replacement,
            counters=counters,
        )
