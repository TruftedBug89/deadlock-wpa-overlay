"""Match context: team lead, stance thresholds, damage share, budget."""

from live_match import LivePlayer
from match_context import (
    MatchContext,
    build_context,
    damage_share,
    find_player,
    stance_for_lead,
)


def player(account, team, hero, souls, gold=None, damage=0, owned=None):
    return LivePlayer(
        account_id=account,
        team=team,
        hero_id=hero,
        net_worth=souls,
        gold=gold,
        hero_damage=damage,
        owned_item_ids=owned,
    )


def test_stance_thresholds_scale_with_stage():
    assert stance_for_lead(1500, "early") == "ahead"
    assert stance_for_lead(1499, "early") == "even"
    assert stance_for_lead(-4000, "mid") == "behind"
    assert stance_for_lead(-3999, "mid") == "even"
    assert stance_for_lead(8000, "late") == "ahead"
    assert stance_for_lead(4000, "") == "ahead"  # default margin


def test_damage_share_is_bounded():
    assert damage_share(3000, 10000) == 0.3
    assert damage_share(0, 10000) is None
    assert damage_share(500, 0) is None
    assert damage_share(20000, 10000) == 1.0


def test_find_player_prefers_account_then_hero():
    players = [player(1, 2, 17, 1000), player(2, 3, 18, 2000)]
    assert find_player(players, 2, None).hero_id == 18
    assert find_player(players, 999, 17).account_id == 1
    assert find_player(players, None, None) is None


def test_build_context_summarises_the_current_game():
    players = [
        player(1, 2, 17, 10000, gold=2400, damage=8000, owned=[1, 2]),
        player(2, 2, 18, 5000, damage=4000),
        player(3, 3, 20, 12000, damage=15000),
        player(4, 3, 21, 9000, damage=3000),
    ]
    ctx = build_context(players, account_id=1)
    assert ctx.known is True
    assert ctx.team == 2
    assert ctx.souls == 10000 and ctx.stage == "mid"
    assert ctx.team_souls == 15000 and ctx.enemy_souls == 21000
    assert ctx.soul_lead == -6000 and ctx.stance == "behind"
    assert ctx.damage_share == 8000 / 12000
    assert ctx.enemy_ids == (20, 21)
    assert ctx.enemy_top_hero_id == 20
    assert ctx.enemy_damage_hero_id == 20 and ctx.enemy_damage == 15000
    assert ctx.owned_item_ids == (1, 2)
    assert ctx.buy_budget == 2400


def test_buy_budget_is_unknown_when_gold_is_unknown():
    ctx = build_context([player(1, 2, 17, 7000)], account_id=1)
    assert ctx.bank is None
    assert ctx.buy_budget is None


def test_unknown_player_is_not_invented():
    ctx = build_context([player(9, 2, 17, 7000)], account_id=1)
    assert ctx == MatchContext()
    assert ctx.known is False and ctx.stance == "unknown"
    assert ctx.buy_budget is None


def test_context_serialises_for_explain():
    ctx = build_context([player(1, 2, 17, 10000, gold=100, damage=500)], account_id=1)
    payload = ctx.to_dict()
    assert payload["souls"] == 10000
    assert payload["buy_budget"] == 100
    assert payload["damage_share"] == 1.0
