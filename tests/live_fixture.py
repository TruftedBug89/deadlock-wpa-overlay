"""Synthetic broadcast rows for deterministic, private-data-free scenarios."""

from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from live_match import LivePlayer, LiveSnapshot, parse_player

FIXTURE = "synthetic broadcast"


def load() -> dict:
    heroes = (17, 1, 2, 3, 4, 5, 6, 63, 66, 14, 86, 20)
    rows = []
    for index, hero in enumerate(heroes):
        items = list(range(100, 108)) if index == 0 else [200 + index]
        rows.append({
            "tick": 1000, "entity_index": index + 1,
            "m_iTeamNum": 2 if index < 6 else 3,
            "m_unEconAccountID": 1001 + index,
            "m_PlayerDataGlobal__m_nHeroID": hero,
            "m_PlayerDataGlobal__m_iGoldNetWorth": 10000 + index * 500,
            "m_PlayerDataGlobal__m_iAPNetWorth": 0,
            "m_PlayerDataGlobal__m_iLevel": 10,
            "m_PlayerDataGlobal__m_vecUpgrades": [
                item.to_bytes(8, "little").hex() for item in items],
        })
    return {"match_id": 9001, "recorded_at": 0, "rows": rows}


def player_rows() -> List[LivePlayer]:
    players = []
    for row in load()["rows"]:
        player = parse_player(row)
        if player is not None:
            players.append(player)
    return players


def our_player(account_id: int) -> LivePlayer:
    for player in player_rows():
        if player.account_id == account_id:
            return player
    raise AssertionError(f"account {account_id} missing from synthetic match")


def owned_ids(account_id: int) -> List[int]:
    """Shop item ids the synthetic player owns (decoded m_vecUpgrades)."""
    return list(our_player(account_id).owned_item_ids)


def snapshot(souls: Optional[int] = None, fetched_at: float = 0.0) -> LiveSnapshot:
    data = load()
    players = []
    for player in player_rows():
        if souls is not None:
            player = replace(player, net_worth=int(souls), ap_net_worth=0)
        players.append(player)
    return LiveSnapshot(
        match_id=int(data["match_id"]),
        players=players,
        tick=int(data["rows"][0]["tick"] or 0),
        fetched_at=fetched_at,
    )
