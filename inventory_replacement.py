"""Evidence for a single optional sale and immediately affordable replacement."""

from item_stats import wilson_bounds
from models import ItemReplacement
from recommendation_engine import MEDIUM_SAMPLE, score_candidate

REPLACEMENT_BOUND_Z = 1.6448536269514722
MIN_SUPPORTED_GAP = 0.015


def _stage_bounds(candidate):
    basis = candidate.evidence.get("ranking_basis", "")
    if basis.startswith("bracket-") and candidate.matches >= MEDIUM_SAMPLE:
        lower, upper = wilson_bounds(candidate.win_rate, candidate.matches, REPLACEMENT_BOUND_Z)
        return basis, lower, upper
    return None


def choose_replacement(measured, available, plan, *, context, capacity, owned_ids, item_meta, to_item):
    """Compare only purchases from the same stage, category and activation type."""
    owned = set(owned_ids)
    if not context.ownership_known or context.bank is None or capacity != len(owned):
        return None
    if any(entry.affordable_now is True and entry.candidate.replaces_ids for entry in plan):
        return None
    reserved = {component for entry in plan for component in entry.candidate.replaces_ids}
    held = []
    for candidate in measured:
        if candidate.item_id not in owned or candidate.item_id in reserved:
            continue
        if candidate.evidence.get("counter_applied_to_rank"):
            continue
        bounds = _stage_bounds(candidate)
        meta = item_meta(candidate.item_id)
        if bounds is not None and type(meta.get("is_active_item")) is bool:
            held.append((candidate, bounds, meta["is_active_item"]))
    if not held:
        return None

    best = None
    for buy in available:
        if buy.replaces_ids or not buy.cost or not 0 < buy.cost <= min(context.bank, context.souls):
            continue
        bounds = _stage_bounds(buy)
        if bounds is None:
            continue
        basis, lower, _ = bounds
        baseline = buy.evidence["general_pool_baseline"]
        if baseline is None or lower <= baseline:
            continue
        active = item_meta(buy.item_id).get("is_active_item")
        for sell, (sell_basis, _, upper), sell_active in held:
            gap = lower - upper
            if (basis != sell_basis or buy.category != sell.category
                    or active is not sell_active or gap < MIN_SUPPORTED_GAP):
                continue
            priority = gap, buy.matches, sell.matches, -buy.cost, -buy.item_id, -sell.item_id
            if best is None or priority > best[0]:
                best = priority, sell, buy, bounds, upper
    if best is None:
        return None
    priority, sell, buy, (basis, lower, _), upper = best
    baseline = buy.evidence["general_pool_baseline"]
    item = to_item(score_candidate(buy, baseline, bank=context.bank))
    return ItemReplacement(
        sell_id=sell.item_id, sell_name=sell.name, buy=item, held_win_rate=sell.win_rate,
        buy_win_rate=buy.win_rate, supported_gap=priority[0], basis=basis, sell_matches=sell.matches,
        buy_matches=buy.matches, slots_used=len(owned), slot_limit=capacity, held_upper=upper,
        buy_lower=lower, pool_baseline=baseline, minimum_supported_gap=MIN_SUPPORTED_GAP,
    )
