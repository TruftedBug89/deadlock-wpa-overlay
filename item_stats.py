"""Statistical primitives over deadlock-api analytics rows.

Every helper here is pure: rows in, numbers out.  The rules that make the
picker trustworthy live here so they can be tested without the network:

* a win rate is never reported from fewer than ``MIN_MATCHES`` games;
* a small prior dampens extreme ranking estimates in smaller samples;
* net-worth buckets are merged around the player's real soul count so the
  number shown is the win rate of that item *at this stage of the match*.
"""

import math
from typing import Dict, List, Optional, Sequence

MIN_MATCHES = 100
PRIOR_MATCHES = 20.0
BUCKET_WIDTH = 5000


def observed_win_rate(row: dict, min_matches: int = MIN_MATCHES) -> Optional[float]:
    """Measured wins / matches; missing or impossible counts are unknown."""
    try:
        matches, wins = int(row["matches"]), int(row["wins"])
        if matches < max(1, min_matches) or not 0 <= wins <= matches:
            return None
        if "losses" in row and int(row["losses"]) != matches - wins:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return wins / matches


def smoothed_win_rate(row: dict, prior: float = PRIOR_MATCHES,
                      min_matches: int = MIN_MATCHES) -> Optional[float]:
    """Ranking estimate only. Display uses the unsmoothed measured rate."""
    if observed_win_rate(row, min_matches) is None:
        return None
    return (int(row["wins"]) + prior / 2.0) / (int(row["matches"]) + prior)


def rank_items(rows: Sequence[dict], limit: int) -> List[tuple]:
    """``[(score, row)]`` ordered best first, ignoring weak samples."""
    scored = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        score = smoothed_win_rate(row)
        if score is None:
            continue
        scored.append((score, row))
    scored.sort(key=lambda pair: (pair[0], int(pair[1].get("matches") or 0)), reverse=True)
    return scored[: max(1, int(limit))]


def bucket_floor(souls: Optional[int], width: int = BUCKET_WIDTH) -> Optional[int]:
    """Lower edge of the net-worth bucket that contains ``souls``."""
    try:
        value = int(souls or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0 or width <= 0:
        return None
    return (value // width) * width


def merge_buckets(
    rows: Sequence[dict],
    souls: Optional[int],
    width: int = BUCKET_WIDTH,
    neighbours: int = 1,
) -> List[dict]:
    """Pool the buckets around ``souls`` into one row per item.

    deadlock-api returns one row per item and net-worth bucket when
    ``bucket=net_worth_by_5000`` is requested.  A single bucket is noisy at low
    soul counts, so the three nearest buckets are summed.  Items whose pooled
    sample is still thin are dropped by :func:`smoothed_win_rate` later.
    """
    floor = bucket_floor(souls, width)
    if floor is None:
        return list(rows or ())
    low = floor - width * max(0, int(neighbours))
    high = floor + width * max(0, int(neighbours))
    pooled: Dict[int, dict] = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        try:
            item_id = int(row.get("item_id"))
            bucket = int(row["bucket"])
        except (KeyError, TypeError, ValueError):
            continue
        if observed_win_rate(row, min_matches=1) is None:
            continue
        if bucket < low or bucket > high:
            continue
        entry = pooled.setdefault(
            item_id,
            {"item_id": item_id, "wins": 0, "losses": 0, "matches": 0, "players": 0,
             "_buy": 0.0, "_buy_weight": 0},
        )
        try:
            entry["wins"] += int(row.get("wins") or 0)
            entry["losses"] += int(row["matches"]) - int(row["wins"])
            entry["matches"] += int(row.get("matches") or 0)
            entry["players"] += int(row.get("players") or 0)
        except (TypeError, ValueError):
            continue
        buy = row.get("avg_buy_time_s")
        matches = int(row.get("matches") or 0)
        if buy is not None and matches > 0:
            try:
                entry["_buy"] += float(buy) * matches
                entry["_buy_weight"] += matches
            except (TypeError, ValueError):
                pass
    merged = []
    for entry in pooled.values():
        weight = entry.pop("_buy_weight")
        buy = entry.pop("_buy")
        entry["avg_buy_time_s"] = (buy / weight) if weight else None
        entry["bucket"] = floor
        merged.append(entry)
    merged.sort(key=lambda row: row["item_id"])
    return merged


def weighted_mean_win_rate(rows: Sequence[dict]) -> Optional[float]:
    """Match-weighted mean win rate of a pool, used as the ranking baseline."""
    wins = matches = 0
    for row in rows or ():
        try:
            count = int(row.get("matches") or 0)
            won = int(row.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if observed_win_rate(row) is None:
            continue
        wins += won
        matches += count
    if matches <= 0:
        return None
    return wins / matches


def pick_rate(row: dict) -> float:
    """Share of observed purchases in this pool, not unique players / matches.

    The API's players field counts distinct accounts buying THIS item. It is
    not the population of hero games and cannot establish a hero pick rate.
    """
    try:
        count = int(row["matches"])
        total = int(row["_pool_matches"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return count / total if 0 < count <= total else 0.0


def log_samples(matches: int) -> float:
    """0..1 confidence weight from a sample size (1k -> 0.5, 10k -> 1)."""
    try:
        value = max(0, int(matches))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, math.log10(value + 1) / 4.0))
