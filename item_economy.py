"""Stage-aware item economy: what is worth buying at a given soul count.

Pure functions only.  Early match souls should buy cheap, efficient items;
late match souls should push the expensive tier-4 items.  The penalty is
subtracted from a win-rate score, so a great item that is wildly out of
budget does not crowd out the item the player can actually buy now.
"""

from typing import Optional

EARLY_SOULS = 6_000
MID_SOULS = 14_000
MAX_ITEM_COST = 6_400
PENALTY_WEIGHT = 0.06


def stage_for_souls(souls: Optional[int]) -> str:
    """``early`` (< 6k), ``mid`` (< 14k) or ``late``."""
    try:
        value = int(souls or 0)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value < EARLY_SOULS:
        return "early"
    if value < MID_SOULS:
        return "mid"
    return "late"


def stage_target_cost(souls: Optional[int]) -> int:
    """Comfortable item price for this soul count (roughly half the bank)."""
    try:
        value = int(souls or 0)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return max(500, min(int(value * 0.55), MAX_ITEM_COST))


def stage_penalty(cost: Optional[int], souls: Optional[int]) -> float:
    """Win-rate penalty for an item that does not fit the current stage."""
    if not souls or not cost:
        return 0.0
    gap = abs(int(cost) - stage_target_cost(souls))
    return (gap / MAX_ITEM_COST) * PENALTY_WEIGHT


def affordable(cost: Optional[int], souls: Optional[int]) -> bool:
    """True when the item can be bought with the current souls."""
    if not souls:
        return True
    if not cost:
        return True
    try:
        return int(souls) >= int(cost)
    except (TypeError, ValueError):
        return True
