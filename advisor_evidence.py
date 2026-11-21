"""Comparable analytics cohorts and reproducible counter decisions."""

from dataclasses import replace

from item_stats import (
    COUNTER_BOUND_Z, MIN_MATCHES, bucket_floor, bucket_window, merge_buckets,
    observed_win_rate, wilson_bounds,
)
from models import CounterItem
from recommendation_engine import (
    COUNTER_MIN_GAIN, baseline_win_rate, build_candidate, edge_reliability, rank,
    score_candidate, supported_counter_gain,
)


def _catalog_rows(source, rows):
    return [dict(row) for row in rows if isinstance(row, dict)
            and isinstance(row.get("item_id"), int)
            and source._meta(row["item_id"]) is not None
            and observed_win_rate(row, min_matches=1) is not None]


def _pool(source, hero_id, enemies, souls, bucket):
    rows = source._stats(hero_id, enemies, bucket=bucket)
    rows = merge_buckets(rows, souls) if bucket else rows
    return _catalog_rows(source, rows)


def _indexed(rows):
    return {row["item_id"]: row for row in rows}


def _counts(row):
    if row is None:
        return None
    return {key: row.get(key) for key in ("item_id", "wins", "matches", "bucket")}


def _pool_summary(rows):
    usable = [row for row in rows if observed_win_rate(row) is not None]
    return baseline_win_rate(usable), [_counts(row) for row in usable]


def counter_evidence(general, enemy, pool, enemy_ids, basis, *, pool_summary=None):
    """Every gate uses the same cohort basis. No baseline means no claim."""
    base, pool_counts = _pool_summary(pool) if pool_summary is None else pool_summary
    general_rate = observed_win_rate(general) if general else None
    enemy_rate = observed_win_rate(enemy) if enemy else None
    gain = enemy_rate - general_rate if None not in (enemy_rate, general_rate) else None
    general_upper = wilson_bounds(general_rate, int(general["matches"]))[1] if general_rate is not None else None
    enemy_lower = wilson_bounds(enemy_rate, int(enemy["matches"]))[0] if enemy_rate is not None else None
    supported = max(0.0, enemy_lower - max(base, general_upper)) if None not in (base, enemy_lower, general_upper) else 0.0
    reason = "accepted"
    if general_rate is None:
        reason = "general_sample_missing_or_thin"
    elif enemy_rate is None:
        reason = "enemy_sample_missing_or_thin"
    elif base is None or enemy_rate <= base:
        reason = "does_not_beat_enemy_pool"
    elif gain + 1e-12 < COUNTER_MIN_GAIN:
        reason = "gain_below_threshold"
    elif supported <= 0:
        reason = "gain_within_sampling_uncertainty"
    return {
        "basis": basis, "enemy_hero_ids": list(enemy_ids),
        "filter_semantics": "any", "general": _counts(general), "enemy": _counts(enemy),
        "general_rate": general_rate, "enemy_rate": enemy_rate,
        "enemy_pool": pool_counts,
        "enemy_pool_baseline": base, "gain": gain,
        "bound_z": COUNTER_BOUND_Z, "enemy_lower": enemy_lower,
        "general_upper": general_upper, "supported_gain": supported,
        "minimum_matches": MIN_MATCHES, "minimum_gain": COUNTER_MIN_GAIN,
        "accepted": reason == "accepted", "decision": reason,
    }


def _optional_pool(source, hero_id, enemies, souls, bucket):
    try:
        return _pool(source, hero_id, enemies, souls, bucket), None
    except Exception as err:
        return [], type(err).__name__


def prepare_candidates(source, hero_id, enemies, souls):
    """Keep stage evidence for ranking; fall back only the comparable counter pair."""
    floor = bucket_floor(souls)
    stage = f"bracket-{floor}" if floor is not None else "overall"
    has_stage = floor is not None
    general, general_error = _optional_pool(source, hero_id, [], souls, has_stage)
    overall, overall_error = _optional_pool(source, hero_id, [], souls, False) if has_stage else ([], None)
    enemy, enemy_error = _optional_pool(source, hero_id, enemies, souls, has_stage) if enemies else ([], None)
    overall_enemy, overall_enemy_error = (
        _optional_pool(source, hero_id, enemies, souls, False) if has_stage and enemies else ([], None)
    )
    if not general and not overall and (general_error or overall_error):
        raise RuntimeError(f"Item analytics unavailable ({general_error or overall_error})")
    general_map, enemy_map = _indexed(general), _indexed(enemy)
    all_map, all_enemy_map = _indexed(overall), _indexed(overall_enemy)
    ranking_pools = {stage: _pool_summary(general)}
    matchup_pools = {stage: _pool_summary(enemy)}
    if has_stage:
        ranking_pools["overall"] = _pool_summary(overall)
        matchup_pools["overall"] = _pool_summary(overall_enemy)
    pool_matches = {basis: sum(int(row["matches"]) for row in counts)
                    for basis, (_, counts) in ranking_pools.items()}
    window = list(bucket_window(floor)) if has_stage else None
    candidates, audit = [], []
    for item_id in sorted(set(general_map) | set(all_map)):
        local, vs = general_map.get(item_id), enemy_map.get(item_id)
        all_row, all_vs = all_map.get(item_id), all_enemy_map.get(item_id)
        ranking_basis = "overall" if has_stage and observed_win_rate(local or {}) is None else stage
        row = all_row if has_stage and ranking_basis == "overall" else local
        counter_basis = ranking_basis
        if has_stage and enemies and observed_win_rate(vs or {}) is None:
            if observed_win_rate(all_row or {}) is not None and observed_win_rate(all_vs or {}) is not None:
                counter_basis = "overall"
        use_overall = has_stage and counter_basis == "overall"
        evidence = counter_evidence(all_row if use_overall else local, all_vs if use_overall else vs,
                                    (), enemies, counter_basis, pool_summary=matchup_pools[counter_basis])
        meta = source._meta(item_id)
        baseline, counts = ranking_pools[ranking_basis]
        valid_rate = observed_win_rate(row or {})
        evidence.update(
            item_id=item_id, name=meta["name"], ranking_basis=ranking_basis,
            ranking_general=_counts(row), general_pool_baseline=baseline, general_pool=counts,
            raw_edge=valid_rate - baseline if None not in (valid_rate, baseline) else None,
            edge_reliability=edge_reliability(int(row["matches"])) if valid_rate is not None else None,
            bucket_window=window if counter_basis != "overall" else None,
            ranking_bucket_window=window if ranking_basis != "overall" else None,
            counter_applied_to_rank=evidence["accepted"] and counter_basis == ranking_basis,
            enemy_error=overall_enemy_error if use_overall else enemy_error,
        )
        audit.append(evidence)
        if valid_rate is None:
            continue
        label = source.hero_name(enemies[0]) if len(enemies) == 1 else "LINEUP"
        candidate = build_candidate(meta, {**row, "_pool_matches": pool_matches[ranking_basis]}, counter_enemy=label)
        if candidate is not None:
            gain = evidence["gain"] if evidence["accepted"] else 0.0
            candidates.append(replace(candidate, counter_gain=gain, evidence=evidence))
    bases = {c.evidence["ranking_basis"] for c in candidates}
    return candidates, audit, next(iter(bases)) if len(bases) == 1 else "mixed"


def select_threat(source, hero_id, enemies, context):
    """Live soul and damage leaders drive the filter; historical matchup is fallback."""
    targets = sorted({i for i in (context.enemy_top_hero_id, context.enemy_damage_hero_id)
                      if i in enemies})
    try:
        rows = [r for r in source._matchups(hero_id) if r.get("enemy_hero_id") in enemies
                and r.get("matches", 0) >= 200 and 0 <= r.get("win_rate", -1) <= 1]
    except Exception:
        rows = []
    worst = min(rows, key=lambda r: (r["win_rate"], -r["matches"]), default=None)
    name = source.hero_name(worst["enemy_hero_id"]) if worst else ""
    return targets or sorted(set(enemies)), name, worst["win_rate"] if worst else None


def counter_picks(candidates, context, souls, owned_ids, categories, exclude_ids, preview=False,
                  queue=None, owner=None, interval=150, reserved_components=(), inventory_capacity=None):
    """Apply purchase gates before choosing the three strongest counter signals."""
    usable = [c for c in candidates if c.evidence.get("accepted") and c.item_id not in exclude_ids
              and not set(c.replaces_ids).intersection(reserved_components)]
    eligible = []
    for candidate in usable:
        ranked = rank([candidate], souls=souls, bank=context.bank,
                      owned_ids=owned_ids, owned_categories=categories, inventory_capacity=inventory_capacity)
        if ranked and (ranked[0].affordable_now is True or preview):
            eligible.append(candidate)
    eligible.sort(key=lambda c: (supported_counter_gain(c), c.evidence["enemy"]["matches"]), reverse=True)
    counts = {}
    for item_id in set(owned_ids) | set(exclude_ids):
        category = categories.get(item_id)
        if category:
            counts[category] = counts.get(category, 0) + 1
    selected = []
    for candidate in eligible:
        if counts.get(candidate.category, 0) >= 4:
            continue
        selected.append(candidate)
        counts[candidate.category] = counts.get(candidate.category, 0) + 1
        if len(selected) == 3:
            break
    if queue is not None:
        pool = [replace(score_candidate(c, 0.5, bank=context.bank), score=supported_counter_gain(c))
                for c in eligible]
        selected = [entry.candidate for entry in queue.update(
            pool, owner=owner, limit=3, interval=interval,
            owned_ids=set(owned_ids) | set(exclude_ids), categories=categories,
        )]
    return [CounterItem(
        name=c.name, item_id=c.item_id, category=c.category, score=supported_counter_gain(c),
        samples=c.evidence["enemy"]["matches"],
        enemy_id=c.evidence["enemy_hero_ids"][0] if len(c.evidence["enemy_hero_ids"]) == 1 else None,
        enemy_name=c.counter_enemy, image_url=c.image_url, class_name=c.class_name,
        win_rate=c.evidence["enemy_rate"], gain=c.counter_gain, evidence=c.evidence,
    ) for c in selected]
