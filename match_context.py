"""Match context: who is ahead, who hits hardest, who is fed.

The picker does not guess these numbers.  They come from the live broadcast
row of every player (``CCitadelPlayerController``): gold net worth, AP net
worth, unspent gold, level, KDA and hero damage.  When a field is missing the
context says "unknown" instead of assuming zero.

Pure module: no I/O, no network, no UI.  ``tests/test_match_context.py`` pins
the thresholds.
"""

from typing import Optional, Sequence, Tuple

from models import MatchContext
from item_economy import stage_for_souls, stage_target_cost

# A team is "ahead" once the soul lead clears this stage-scaled margin.
LEAD_THRESHOLDS = {"early": 1500, "mid": 4000, "late": 8000}
DEFAULT_LEAD = 4000



def stance_for_lead(lead: int, stage: str) -> str:
    """``ahead`` / ``even`` / ``behind`` for a team soul lead at this stage."""
    try:
        value = int(lead or 0)
    except (TypeError, ValueError):
        return "unknown"
    threshold = LEAD_THRESHOLDS.get(stage, DEFAULT_LEAD)
    if value >= threshold:
        return "ahead"
    if value <= -threshold:
        return "behind"
    return "even"


def damage_share(mine: int, team: int) -> Optional[float]:
    """Fraction of the team's hero damage dealt by this player (0..1)."""
    try:
        mine_value = max(0, int(mine or 0))
        team_value = max(0, int(team or 0))
    except (TypeError, ValueError):
        return None
    if mine_value <= 0 or team_value <= 0:
        return None
    return max(0.0, min(1.0, mine_value / team_value))


def _account(player) -> Optional[int]:
    value = getattr(player, "account_id", None)
    return int(value) if value else None


def find_player(players: Sequence, account_id: Optional[int], hero_id: Optional[int]):
    """Locate the local player by account id first, then by hero id."""
    if account_id is not None:
        for player in players:
            if _account(player) == int(account_id):
                return player
    if hero_id is not None:
        for player in players:
            if int(getattr(player, "hero_id", 0) or 0) == int(hero_id):
                return player
    return None


def build_context(
    players: Sequence,
    account_id: Optional[int] = None,
    hero_id: Optional[int] = None,
) -> MatchContext:
    """Turn a live roster into the context the picker needs."""
    players = list(players or ())
    me = find_player(players, account_id, hero_id)
    if me is None:
        return MatchContext()
    team = int(getattr(me, "team", 0) or 0)
    mates = [p for p in players if int(getattr(p, "team", 0) or 0) == team]
    enemies = [p for p in players if int(getattr(p, "team", 0) or 0) != team]
    souls = int(getattr(me, "souls", 0) or 0)
    team_souls = sum(int(getattr(p, "souls", 0) or 0) for p in mates)
    enemy_souls = sum(int(getattr(p, "souls", 0) or 0) for p in enemies)
    lead = team_souls - enemy_souls
    stage = stage_for_souls(souls)
    my_damage = int(getattr(me, "hero_damage", 0) or 0)
    team_damage = sum(int(getattr(p, "hero_damage", 0) or 0) for p in mates)
    top = max(enemies, key=lambda p: int(getattr(p, "souls", 0) or 0), default=None)
    hitter = max(enemies, key=lambda p: int(getattr(p, "hero_damage", 0) or 0), default=None)
    bank = getattr(me, "gold", None)
    owned = getattr(me, "owned_item_ids", None)
    return MatchContext(
        known=True,
        souls=souls,
        bank=int(bank) if bank is not None else None,
        level=int(getattr(me, "level", 0) or 0),
        stage=stage,
        team=team,
        team_souls=team_souls,
        enemy_souls=enemy_souls,
        soul_lead=lead,
        stance=stance_for_lead(lead, stage) if mates and enemies and all(getattr(p, "souls_known", True) for p in players) else "unknown",
        my_damage=my_damage,
        team_damage=team_damage,
        damage_share=damage_share(my_damage, team_damage) if all(getattr(p, "damage_known", True) for p in mates) else None,
        enemy_ids=tuple(int(getattr(p, "hero_id", 0) or 0) for p in enemies),
        enemy_top_souls=int(getattr(top, "souls", 0) or 0) if top else 0,
        enemy_top_hero_id=int(getattr(top, "hero_id", 0) or 0) if top and top.souls > 0 and all(getattr(p, "souls_known", True) for p in enemies) else None,
        enemy_damage=int(getattr(hitter, "hero_damage", 0) or 0) if hitter else 0,
        enemy_damage_hero_id=int(getattr(hitter, "hero_id", 0) or 0) if hitter and hitter.hero_damage > 0 and all(getattr(p, "damage_known", True) for p in enemies) else None,
        ownership_known=owned is not None,
        owned_item_ids=tuple(int(i) for i in (owned or ())),
        target_cost=stage_target_cost(souls),
    )
