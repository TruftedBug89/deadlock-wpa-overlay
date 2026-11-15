"""Build-aware counter selection: strongest enemy + a counter from your build.

Pure logic only (no I/O), so it is trivially testable:

* the *build pool* is the hero's Statlocker build page (core + situational);
* the *strongest enemy* is the one this hero wins against least;
* the *counter pick* is the highest win-rate item from that build in matches
  against that enemy.
"""

from typing import Dict, Iterable, List, Optional, Sequence


def build_pool(body: dict) -> Dict[int, dict]:
    """``itemId -> item`` for the hero's current build (core + situational)."""
    pool: Dict[int, dict] = {}
    if not isinstance(body, dict):
        return pool

    sections: List[dict] = []
    recommended = body.get("recommended")
    if isinstance(recommended, dict):
        sections.extend(item for item in (recommended.get("items") or []) if isinstance(item, dict))
    sections.extend(item for item in (body.get("situational") or []) if isinstance(item, dict))
    values = body.get("itemValues")
    if isinstance(values, dict):
        sections.extend(item for item in (values.get("items") or []) if isinstance(item, dict))

    for item in sections:
        try:
            item_id = int(item.get("itemId"))
        except (TypeError, ValueError):
            continue
        if item_id <= 0:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        pool.setdefault(
            item_id,
            {
                "item_id": item_id,
                "name": name,
                "slot_type": str(item.get("slotType") or "").lower(),
                "tier": item.get("tier") or 0,
                "class_name": item.get("className") or "",
            },
        )
    return pool


def strongest_enemy(
    rows: Sequence[dict],
    hero_id: int,
    enemy_ids: Iterable[int] = (),
) -> Optional[dict]:
    """The enemy this hero performs worst against (lowest win rate)."""
    wanted = {int(e) for e in enemy_ids}
    best: Optional[tuple] = None
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("hero_id")) != int(hero_id):
                continue
            enemy_id = int(row.get("enemy_hero_id"))
            matches = int(row.get("matches") or 0)
            win_rate = float(row.get("win_rate") or 0.0)
        except (TypeError, ValueError):
            continue
        if wanted and enemy_id not in wanted:
            continue
        key = (win_rate, -matches)
        if best is None or key < best[0]:
            best = (key, {"enemy_id": enemy_id, "win_rate": win_rate, "matches": matches})
    return best[1] if best else None


def rank_pool_items(
    pool: Dict[int, dict],
    stat_rows: Sequence[dict],
    limit: int = 3,
    exclude: Iterable[str] = (),
) -> List[dict]:
    """Build items ranked by win rate in the current matchup."""
    skip = {str(name).strip().lower() for name in exclude if name}
    ranked: List[dict] = []
    for row in stat_rows or ():
        if not isinstance(row, dict):
            continue
        try:
            item_id = int(row.get("item_id"))
        except (TypeError, ValueError):
            continue
        item = pool.get(item_id)
        if not item or item["name"].lower() in skip:
            continue
        vs = row.get("vs") or {}
        ns = row.get("n") or {}
        if not isinstance(vs, dict) or not vs:
            continue
        enemy = max(vs, key=lambda key: (float(vs[key] or 0), float(ns.get(key, 0) or 0)))
        ranked.append(
            dict(
                item,
                win_rate=float(vs[enemy] or 0.0),
                samples=int(ns.get(enemy, 0) or 0),
            )
        )

    ranked.sort(key=lambda entry: (entry["win_rate"], entry["samples"]), reverse=True)

    picks: List[dict] = []
    seen = set()
    for item in ranked:
        name = item["name"].lower()
        if name in seen:
            continue
        seen.add(name)
        picks.append(item)
        if len(picks) >= max(1, int(limit)):
            break
    return picks
