"""Comparable analytics cohorts and reproducible counter decisions."""

from dataclasses import replace

from item_stats import MIN_MATCHES, bucket_floor, merge_buckets, observed_win_rate
from models import CounterItem
from recommendation_engine import COUNTER_MIN_GAIN, baseline_win_rate, build_candidate, rank


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


def counter_evidence(general, enemy, pool, enemy_ids, basis):
    """Every gate uses the same cohort basis. No baseline means no claim."""
    base = baseline_win_rate(pool)
    general_rate = observed_win_rate(general) if general else None
    enemy_rate = observed_win_rate(enemy) if enemy else None
    gain = enemy_rate - general_rate if None not in (enemy_rate, general_rate) else None
    reason = "accepted"
    if general_rate is None:
        reason = "general_sample_missing_or_thin"
    elif enemy_rate is None:
        reason = "enemy_sample_missing_or_thin"
    elif base is None or enemy_rate <= base:
        reason = "does_not_beat_enemy_pool"
    elif gain + 1e-12 < COUNTER_MIN_GAIN:
        reason = "gain_below_threshold"
    valid_pool = [row for row in pool if observed_win_rate(row) is not None]
    return {
        "basis": basis, "enemy_hero_ids": list(enemy_ids),
        "filter_semantics": "any", "general": _counts(general), "enemy": _counts(enemy),
        "general_rate": general_rate, "enemy_rate": enemy_rate,
        "enemy_pool": [_counts(row) for row in valid_pool],
        "enemy_pool_baseline": base, "gain": gain,
        "minimum_matches": MIN_MATCHES, "minimum_gain": COUNTER_MIN_GAIN,
        "accepted": reason == "accepted", "decision": reason,
    }


def prepare_candidates(source, hero_id, enemies, souls):
    """Prefer three local buckets; thin pairs fall back together to overall."""
    stage = f"bracket-{bucket_floor(souls)}" if souls else "overall"
    general = _pool(source, hero_id, [], souls, bool(souls))
    enemy_error = None
    try:
        enemy = _pool(source, hero_id, enemies, souls, bool(souls)) if enemies else []
    except Exception as err:
        enemy, enemy_error = [], type(err).__name__
    general_map, enemy_map = _indexed(general), _indexed(enemy)
    # Overall also covers items absent from the bracket response entirely.
    needs_overall = bool(souls)
    overall, overall_enemy = [], []
    if needs_overall:
        overall = _pool(source, hero_id, [], souls, False)
        try:
            overall_enemy = _pool(source, hero_id, enemies, souls, False) if enemies else []
        except Exception as err:
            enemy_error = type(err).__name__
    all_map, all_enemy_map = _indexed(overall), _indexed(overall_enemy)
    candidates, audit = [], []
    for item_id in sorted(set(general_map) | set(all_map)):
        row, vs = general_map.get(item_id), enemy_map.get(item_id)
        pool, vs_pool, basis = general, enemy, stage
        if needs_overall and (observed_win_rate(row or {}) is None
                             or (enemies and observed_win_rate(vs or {}) is None)):
            if (observed_win_rate(row or {}) is None or
                    (observed_win_rate(all_map.get(item_id, {})) is not None and
                     observed_win_rate(all_enemy_map.get(item_id, {})) is not None)):
                row, vs = all_map.get(item_id), all_enemy_map.get(item_id)
                pool, vs_pool, basis = overall, overall_enemy, "overall"
        if row is None:
            continue
        evidence = counter_evidence(row, vs, vs_pool, enemies, basis)
        evidence["item_id"] = item_id
        evidence["name"] = source._meta(item_id)["name"]
        evidence["general_pool_baseline"] = baseline_win_rate(pool)
        evidence["general_pool"] = [_counts(r) for r in pool if observed_win_rate(r) is not None]
        evidence["bucket_window"] = [max(0, bucket_floor(souls) - 5000), bucket_floor(souls) + 5000] if souls and basis != "overall" else None
        evidence["enemy_error"] = enemy_error
        audit.append(evidence)
        row = {**row, "_pool_matches": sum(r["matches"] for r in pool if observed_win_rate(r) is not None)}
        label = source.hero_name(enemies[0]) if len(enemies) == 1 else "LINEUP"
        candidate = build_candidate(source._meta(item_id), row, vs, label,
                                    evidence["enemy_pool_baseline"])
        if candidate is not None:
            gain = evidence["gain"] if evidence["accepted"] else 0.0
            candidates.append(replace(candidate, counter_gain=gain, evidence=evidence))
    bases = {c.evidence["basis"] for c in candidates}
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
                  queue=None, owner=None, interval=150, reserved_components=()):
    """Apply purchase gates before choosing the three strongest counter signals."""
    usable = [c for c in candidates if c.evidence.get("accepted") and c.item_id not in exclude_ids
              and not set(c.replaces_ids).intersection(reserved_components)]
    eligible = []
    for candidate in usable:
        ranked = rank([candidate], souls=souls, bank=context.bank,
                      owned_ids=owned_ids, owned_categories=categories)
        if ranked and (ranked[0].affordable_now is True or preview):
            eligible.append(candidate)
    eligible.sort(key=lambda c: (c.counter_gain, c.evidence["enemy"]["matches"]), reverse=True)
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
        from dataclasses import replace
        from recommendation_engine import score_candidate
        pool = [replace(score_candidate(c, 0.5, bank=context.bank), score=c.counter_gain)
                for c in eligible]
        selected = [entry.candidate for entry in queue.update(
            pool, owner=owner, limit=3, interval=interval,
            owned_ids=set(owned_ids) | set(exclude_ids), categories=categories,
        )]
    return [CounterItem(
        name=c.name, item_id=c.item_id, category=c.category, score=c.counter_gain,
        samples=c.evidence["enemy"]["matches"],
        enemy_id=c.evidence["enemy_hero_ids"][0] if len(c.evidence["enemy_hero_ids"]) == 1 else None,
        enemy_name=c.counter_enemy, image_url=c.image_url, class_name=c.class_name,
        win_rate=c.evidence["enemy_rate"], gain=c.counter_gain, evidence=c.evidence,
    ) for c in selected]
