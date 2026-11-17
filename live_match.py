"""Live match state from deadlock-api's broadcast query (SSE).

Given a match id, the API spectates the lobby and streams SQL rows from the
live broadcast.  We require a complete roster from one tick and return heroes, teams,
net worth, unspent gold, damage and inventory.  That is the real match state
(enemy lineup + souls) with no screen reading and no companion database.

The caller supplies the match ID from ``--match-id``, the API active list,
or the optional corner-stamp reader. No gameplay values come from OCR.
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

API = "https://api.deadlock-api.com/v1/matches/demo/live/query"
USER_AGENT = "DeadlockWPAOverlay/2.0 (live match)"
READ_TIMEOUT_S = 8.0
SNAPSHOT_TTL_S = 6.0
MISS_TTL_S = 4.0
PLAYING_TEAMS = (2, 3)

STEAM64_BASE = 76561197960265728

QUERY = (
    'SELECT tick, entity_index, "m_iTeamNum", "m_unEconAccountID", "m_steamID", '
    '"m_PlayerDataGlobal__m_nHeroID", "m_PlayerDataGlobal__m_iGoldNetWorth", '
    '"m_PlayerDataGlobal__m_iAPNetWorth", "m_PlayerDataGlobal__m_iGold", '
    '"m_PlayerDataGlobal__m_iLevel", "m_PlayerDataGlobal__m_iPlayerKills", '
    '"m_PlayerDataGlobal__m_iPlayerAssists", "m_PlayerDataGlobal__m_iDeaths", '
    '"m_PlayerDataGlobal__m_iHeroDamage", "m_PlayerDataGlobal__m_iHeroHealing", '
    '"m_PlayerDataGlobal__m_iObjectiveDamage", "m_PlayerDataGlobal__m_vecUpgrades" '
    "FROM CCitadelPlayerController"
)


@dataclass
class LivePlayer:
    account_id: Optional[int]
    team: int
    hero_id: int
    net_worth: int
    steam_id: Optional[int] = None
    ap_net_worth: int = 0
    level: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    hero_damage: int = 0
    hero_healing: int = 0
    objective_damage: int = 0
    # Unspent gold (what the shop will actually charge against). ``None`` means
    # the tick did not carry the field, never "no gold".
    gold: Optional[int] = None
    # ``None`` means the tick did not carry the ownership vector (unknown).
    # An empty list means the vector was present and the player owns nothing.
    owned_item_ids: Optional[List[int]] = None
    souls_known: bool = True
    damage_known: bool = True


    @property
    def souls(self) -> int:
        return int(self.net_worth) + int(self.ap_net_worth)


@dataclass
class LiveSnapshot:
    match_id: int
    players: List[LivePlayer] = field(default_factory=list)
    tick: int = 0
    fetched_at: float = 0.0

    def player_for_account(self, account_id: Optional[int]) -> Optional[LivePlayer]:
        if account_id is None:
            return None
        account = int(account_id)
        for player in self.players:
            if player.account_id == account:
                return player
        steam64 = STEAM64_BASE + account
        for player in self.players:
            if player.steam_id == steam64:
                return player
        return None

    def player_for_hero(self, hero_id: Optional[int]) -> Optional[LivePlayer]:
        if hero_id is None:
            return None
        for player in self.players:
            if player.hero_id == int(hero_id):
                return player
        return None

    def enemies(self, account_id: Optional[int] = None, hero_id: Optional[int] = None) -> List[LivePlayer]:
        me = self.player_for_account(account_id) or self.player_for_hero(hero_id)
        if me is None:
            return []
        return [player for player in self.players if player.team != me.team]


def parse_item_id(value) -> Optional[int]:
    """Decode one ``m_vecUpgrades`` entry into a shop item id.

    The broadcast returns little-endian 64-bit values as hex strings, for
    example ``"e0ab3ee600000000"``.  The item id is the low 32 bits and maps
    directly to ``/v1/assets/items`` ids (that value is Restorative Shot).
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = int.from_bytes(bytes.fromhex(text), "little")
        except ValueError:
            return None
    else:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
    item_id = number & 0xFFFFFFFF
    return item_id or None


def parse_item_ids(values) -> Optional[List[int]]:
    """Owned ids, or ``None`` when the tick omitted the ownership vector."""
    if values is None or not isinstance(values, (list, tuple)):
        return None
    ids = []
    for value in values:
        item_id = parse_item_id(value)
        if item_id is not None:
            ids.append(item_id)
        elif value not in (0, "0000000000000000", "00000000"):
            return None
    return ids


def parse_player(row: dict) -> Optional[LivePlayer]:
    try:
        team = int(row.get("m_iTeamNum") or 0)
        hero_id = int(row.get("m_PlayerDataGlobal__m_nHeroID") or 0)
    except (TypeError, ValueError):
        return None
    if team not in PLAYING_TEAMS or hero_id <= 0:
        return None
    try:
        account_id = int(row.get("m_unEconAccountID") or 0) or None
    except (TypeError, ValueError):
        account_id = None
    try:
        steam_id = int(row.get("m_steamID") or 0) or None
    except (TypeError, ValueError):
        steam_id = None
    def number(key: str) -> int:
        try:
            return int(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    def optional(key: str) -> Optional[int]:
        if key not in row or row.get(key) is None:
            return None
        try:
            return int(row.get(key))
        except (TypeError, ValueError):
            return None

    return LivePlayer(
        account_id=account_id,
        team=team,
        hero_id=hero_id,
        steam_id=steam_id,
        net_worth=number("m_PlayerDataGlobal__m_iGoldNetWorth"),
        ap_net_worth=number("m_PlayerDataGlobal__m_iAPNetWorth"),
        level=number("m_PlayerDataGlobal__m_iLevel"),
        kills=number("m_PlayerDataGlobal__m_iPlayerKills"),
        deaths=number("m_PlayerDataGlobal__m_iDeaths"),
        assists=number("m_PlayerDataGlobal__m_iPlayerAssists"),
        hero_damage=number("m_PlayerDataGlobal__m_iHeroDamage"),
        hero_healing=number("m_PlayerDataGlobal__m_iHeroHealing"),
        objective_damage=number("m_PlayerDataGlobal__m_iObjectiveDamage"),
        gold=optional("m_PlayerDataGlobal__m_iGold"),
        owned_item_ids=parse_item_ids(row.get("m_PlayerDataGlobal__m_vecUpgrades")),
        souls_known=all(optional(key) is not None for key in (
            "m_PlayerDataGlobal__m_iGoldNetWorth", "m_PlayerDataGlobal__m_iAPNetWorth")),
        damage_known=optional("m_PlayerDataGlobal__m_iHeroDamage") is not None,
    )


def fetch_live_snapshot(match_id: int, timeout_s: float = READ_TIMEOUT_S) -> Optional[LiveSnapshot]:
    """Read one complete live roster without mixing partial ticks."""
    url = f"{API}?{urllib.parse.urlencode({'match_id': int(match_id), 'query': QUERY})}"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/event-stream"}
    )
    players: Dict[int, LivePlayer] = {}
    ticks_seen: List[int] = []
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            buffer: List[str] = []
            event = "message"
            for raw in response:
                # Status and malformed events must not bypass the total deadline.
                if time.monotonic() - started > timeout_s:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                    if event in ("end", "error"):
                        return None
                elif line.startswith("data:"):
                    buffer.append(line[5:].lstrip())
                elif not line and buffer:
                    payload = "\n".join(buffer)
                    buffer = []
                    if event == "status":
                        event = "message"
                        continue
                    try:
                        row = json.loads(payload)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if "error" in row:
                        return None
                    player = parse_player(row)
                    if player is None:
                        continue
                    try:
                        entity = int(row.get("entity_index"))
                        tick = int(row.get("tick") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not ticks_seen or tick != ticks_seen[-1]:
                        if ticks_seen and tick < ticks_seen[-1]:
                            continue
                        players.clear()
                        ticks_seen.append(tick)
                    players[entity] = player
                    if len(players) >= 12:
                        break
                if time.monotonic() - started > timeout_s:
                    break
    except Exception:
        return None
    if len(players) != 12:
        return None
    return LiveSnapshot(
        match_id=int(match_id),
        players=list(players.values()),
        tick=ticks_seen[-1] if ticks_seen else 0,
        fetched_at=_now(),
    )


_LOCK = threading.Lock()
_CACHE: Dict[int, LiveSnapshot] = {}
_MISSES: Dict[int, float] = {}
_LAST_TICK: Dict[int, int] = {}


def _now() -> float:
    """Clock hook so cache expiry is testable without sleeping."""
    return time.time()


def get_live_snapshot(match_id: int, max_age_s: float = SNAPSHOT_TTL_S) -> Optional[LiveSnapshot]:
    """Cached snapshot: at most one broadcast read per ``max_age_s``.

    Failures are cached for a few seconds too: when a match ends the overlay
    must stop showing items without hammering the API on every UI poll.
    """
    key = int(match_id)
    now = _now()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached.fetched_at <= max_age_s:
            return cached
        missed_at = _MISSES.get(key)
        if missed_at and now - missed_at <= MISS_TTL_S:
            return None
    snapshot = fetch_live_snapshot(key)
    with _LOCK:
        # A reconnect may replay an old tick. Receipt time is not game progress.
        previous_tick = _LAST_TICK.get(key, cached.tick if cached is not None else -1)
        if previous_tick >= 0:
            _LAST_TICK[key] = previous_tick
        if snapshot is not None and snapshot.tick <= previous_tick:
            snapshot = None
        if snapshot is not None:
            _LAST_TICK[key] = snapshot.tick
            _CACHE[key] = snapshot
            _MISSES.pop(key, None)
        else:
            _MISSES[key] = _now()
            _CACHE.pop(key, None)
    return snapshot


def strongest_enemy(snapshot: LiveSnapshot, account_id: Optional[int], hero_id: Optional[int]) -> Optional[LivePlayer]:
    """Fed enemy: highest soul count on the opposing team."""
    enemies = snapshot.enemies(account_id, hero_id)
    if not enemies:
        return None
    return max(enemies, key=lambda player: player.souls)


def sum_souls(players: Sequence[LivePlayer]) -> int:
    return sum(player.souls for player in players)


def clear_live_cache(match_id: int) -> None:
    """Retry a broadcast now, retaining the replay watermark for safety."""
    with _LOCK:
        _CACHE.pop(int(match_id), None)
        _MISSES.pop(int(match_id), None)
