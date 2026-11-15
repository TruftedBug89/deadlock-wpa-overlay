"""Five-term ranking over measured evidence and explicit context heuristics.

Edge uses a smoothed estimate against the same purchase pool's baseline.
Popularity uses purchase share, not the API's distinct buyer count. Counter
bonuses require comparable pools, adequate samples and an enemy-pool edge.
Tempo and the bounded 0.3 stance/carry nudge are policy, not measured uplift.
The card win rate is raw wins / matches; every score term stays in --explain.
"""

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from item_stats import MIN_MATCHES, pick_rate, smoothed_win_rate, weighted_mean_win_rate, observed_win_rate
from models import Candidate, Scored

SLOTS_PER_CATEGORY = 4
COUNTER_MIN_GAIN = 0.004  # 0.4 win-rate points before it is called a counter
MAX_EDGE_POINTS = 5.0
MAX_COUNTER_POINTS = 3.0
EDGE_WEIGHT = 1.0
POPULARITY_WEIGHT = 0.5
COUNTER_WEIGHT = 0.8
TEMPO_WEIGHT = 6.5
STANCE_BONUS = 0.3
SAVING_PENALTY = 0.6
UPGRADE_BONUS = 0.3
CORE_PICK_RATE = 0.35
HIGH_SAMPLE = 3000
MEDIUM_SAMPLE = 600



def build_candidate(
    item: Mapping,
    row: Mapping,
    counter_row: Optional[Mapping] = None,
    counter_enemy: str = "",
    counter_baseline: Optional[float] = None,
) -> Optional[Candidate]:
    """Join catalog metadata with a stats row; ``None`` when evidence is thin."""
    if not isinstance(row, Mapping):
        return None
    win_rate = observed_win_rate(dict(row), min_matches=MIN_MATCHES)
    if win_rate is None:
        return None
    try:
        item_id = int(item.get("id"))
        name = str(item.get("name") or "").strip()
        matches = int(row.get("matches") or 0)
    except (TypeError, ValueError):
        return None
    if not name or item_id <= 0 or matches <= 0:
        return None
    try:
        cost = int(item.get("cost")) if item.get("cost") is not None else None
        tier = int(item.get("item_tier")) if item.get("item_tier") is not None else None
    except (TypeError, ValueError):
        cost = tier = None
    gain = 0.0
    if counter_row is not None:
        vs_rate = observed_win_rate(dict(counter_row), min_matches=MIN_MATCHES)
        if (vs_rate is not None and counter_baseline is not None
                and vs_rate > counter_baseline and vs_rate > win_rate):
            gain = vs_rate - win_rate
    return Candidate(
        item_id=item_id,
        name=name,
        category=str(item.get("category") or "weapon"),
        cost=cost,
        tier=tier,
        image_url=item.get("image"),
        class_name=item.get("class_name"),
        win_rate=win_rate,
        matches=matches,
        pick_rate=pick_rate(dict(row)),
        counter_gain=gain,
        counter_enemy=counter_enemy,
        ranking_rate=smoothed_win_rate(dict(row)),
    )


def baseline_win_rate(rows: Sequence[Mapping]) -> Optional[float]:
    """Purchase-weighted item pool baseline, unknown without valid evidence."""
    return weighted_mean_win_rate([dict(row) for row in rows or ()])


def _format_souls(value: int) -> str:
    value = max(0, int(value))
    if value >= 1000:
        text = f"{value / 1000:.1f}k"
        return text.replace(".0k", "k")
    return str(value)


def confidence_for(matches: int) -> str:
    """Sample-size label shown in ``--explain`` and available to the UI."""
    try:
        value = int(matches)
    except (TypeError, ValueError):
        return "low"
    if value >= HIGH_SAMPLE:
        return "high"
    if value >= MEDIUM_SAMPLE:
        return "medium"
    return "low"


def _tempo_points(cost: Optional[int], target: int) -> float:
    if not cost or not target:
        return 0.0
    distance = abs(int(cost) - int(target)) / float(max(target, 1))
    return -min(1.0, distance) * TEMPO_WEIGHT


def _stance_points(category: str, stance: str) -> float:
    if stance == "ahead" and category in ("weapon", "spirit"):
        return STANCE_BONUS
    if stance == "behind" and category == "vitality":
        return STANCE_BONUS
    return 0.0


def score_candidate(
    candidate: Candidate,
    baseline: float,
    *,
    stance: str = "unknown",
    target_cost: int = 0,
    souls: int = 0,
    bank: Optional[int] = None,
    damage_share: Optional[float] = None,
) -> Scored:
    """Score one candidate against the hero baseline and the live context."""
    baseline = candidate.evidence.get("general_pool_baseline", baseline)
    win_rate = candidate.ranking_rate if candidate.ranking_rate is not None else candidate.win_rate
    edge = max(-MAX_EDGE_POINTS, min(MAX_EDGE_POINTS, (win_rate - baseline) * 100.0)) * EDGE_WEIGHT
    popularity = min(1.0, candidate.pick_rate * 2.0) * POPULARITY_WEIGHT
    counter = min(MAX_COUNTER_POINTS, candidate.counter_gain * 100.0) * COUNTER_WEIGHT
    tempo = _tempo_points(candidate.cost, target_cost)
    if candidate.replaces_ids:
        tempo += UPGRADE_BONUS
    stance_points = _stance_points(candidate.category, stance)
    if damage_share is not None and damage_share >= 1 / 3:
        stance_points = STANCE_BONUS if candidate.category == "vitality" else 0.0
    affordable_now = None if bank is None else True
    saving = 0
    if bank is not None and candidate.cost and int(candidate.cost) > int(bank):
        affordable_now = False
        saving = int(candidate.cost) - int(bank)
        tempo -= SAVING_PENALTY
    breakdown = {
        "edge": edge,
        "popularity": popularity,
        "counter": counter,
        "tempo": tempo,
        "stance": stance_points,
    }
    score = edge + popularity + counter + tempo + stance_points

    tags: List[str] = []
    if affordable_now is False and saving > 0:
        tags.append(f"SAVE {_format_souls(saving)}")
    elif affordable_now is None:
        tags.append("BUDGET UNKNOWN")
    elif candidate.counter_gain >= COUNTER_MIN_GAIN and candidate.counter_enemy:
        tags.append(f"VS {candidate.counter_enemy.upper()[:10]}")
    elif damage_share is not None and damage_share >= 1 / 3 and candidate.category == "vitality":
        tags.append("PROTECT CARRY")
    elif stance == "ahead":
        tags.append("AHEAD")
    elif stance == "behind":
        tags.append("BEHIND")
    elif candidate.pick_rate >= CORE_PICK_RATE:
        tags.append("POPULAR")
    elif candidate.replaces_ids:
        tags.append("UPGRADE")
    else:
        tags.append("MEASURED EDGE")
    return Scored(
        candidate=candidate,
        score=score,
        confidence=confidence_for(candidate.matches),
        tags=tuple(tags[:3]),
        affordable_now=affordable_now,
        breakdown=breakdown,
    )


def _category_counts(
    owned_ids: Iterable[int],
    category_of: Mapping[int, str],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item_id in owned_ids or ():
        try:
            category = category_of.get(int(item_id))
        except (TypeError, ValueError):
            continue
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts


def rank(
    candidates: Sequence[Candidate],
    *,
    stance: str = "unknown",
    target_cost: int = 0,
    souls: int = 0,
    bank: Optional[int] = None,
    baseline: Optional[float] = None,
    limit: int = 5,
    owned_ids: Iterable[int] = (),
    owned_categories: Optional[Mapping[int, str]] = None,
    damage_share: Optional[float] = None,
    reserve_slots: bool = True,
) -> List[Scored]:
    """Rank buyable, unowned, slot-legal items for the current game."""
    owned = {int(item_id) for item_id in owned_ids or ()}
    counts = _category_counts(owned, owned_categories or {})
    pool = [
        candidate
        for candidate in candidates or ()
        if candidate.cost
        and candidate.cost > 0
        and candidate.item_id not in owned
        and candidate.matches >= MIN_MATCHES
        and candidate.win_rate is not None and 0 <= candidate.win_rate <= 1
        and (not souls or int(candidate.cost) <= int(souls))
    ]
    base = baseline if baseline is not None else _row_baseline(pool)
    if base is None:
        return []
    scored: List[Scored] = []
    for candidate in pool:
        freed = sum(1 for i in candidate.replaces_ids if i in owned
                    and (owned_categories or {}).get(i) == candidate.category)
        filled = counts.get(candidate.category, 0) - freed
        if filled >= SLOTS_PER_CATEGORY:
            continue
        scored.append(
            score_candidate(
                candidate,
                base,
                stance=stance,
                target_cost=target_cost,
                souls=souls,
                bank=bank,
                damage_share=damage_share,
            )
        )
    scored.sort(
        key=lambda entry: (
            entry.affordable_now is True,
            entry.score,
            entry.matches,
            entry.win_rate or 0.0,
        ),
        reverse=True,
    )
    if not reserve_slots:
        return scored
    return select_legal(scored, limit, owned, owned_categories or {})


def select_legal(scored, limit, owned_ids=(), owned_categories=None):
    """Keep an ordered subset that can share the remaining category slots."""
    owned = set(owned_ids)
    counts = _category_counts(owned, owned_categories or {})
    selected = []
    replaced = set()
    for entry in scored:
        released = {i for i in entry.candidate.replaces_ids if i in owned and i not in replaced
                    and (owned_categories or {}).get(i) == entry.category}
        if counts.get(entry.category, 0) - len(released) >= SLOTS_PER_CATEGORY:
            continue
        selected.append(entry)
        counts[entry.category] = counts.get(entry.category, 0) - len(released) + 1
        replaced.update(released)
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def _row_baseline(candidates: Sequence[Candidate]) -> Optional[float]:
    """Match-weighted pool baseline from candidate observed rates."""
    wins = 0.0
    matches = 0
    for candidate in candidates:
        if candidate.win_rate is None or candidate.matches <= 0:
            continue
        wins += candidate.win_rate * candidate.matches
        matches += candidate.matches
    return (wins / matches) if matches else None


def rank_counters(
    candidates: Sequence[Candidate],
    *,
    limit: int = 3,
    exclude_ids: Iterable[int] = (),
    owned_ids: Iterable[int] = (),
    min_gain: float = COUNTER_MIN_GAIN,
) -> List[Candidate]:
    """Counter picks: real matchup gain, then sample size.

    ``min_gain`` is the smallest win-rate gain worth calling a counter; a
    positive-but-tiny gain is noise, not advice.
    """
    excluded = {int(item_id) for item_id in exclude_ids or ()} | {
        int(item_id) for item_id in owned_ids or ()
    }
    usable = [
        candidate
        for candidate in candidates or ()
        if candidate.counter_gain >= min_gain and candidate.item_id not in excluded
    ]
    usable.sort(key=lambda entry: (entry.counter_gain, entry.matches), reverse=True)
    return usable[: max(1, int(limit))]
