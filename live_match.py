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
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
from urllib.error import HTTPError

from item_inventory import BASE_INVENTORY_CAPACITY, MAX_INVENTORY_CAPACITY

API = "https://api.deadlock-api.com/v1/matches/demo/live/query"
USER_AGENT = "DeadlockWPAOverlay/2.0 (live match)"
# The relay can retry for a full minute and sends 15-second keepalives.
JOIN_TIMEOUT_S = 68.0
READ_TIMEOUT_S = 22.0
SOCKET_TIMEOUT_S = 19.0
SNAPSHOT_TTL_S = 6.0
MISS_TTL_S = 4.0
PLAYING_TEAMS = (2, 3)
# A recent team row may arrive just before the complete controller tick.
FLEX_MAX_TICK_LAG = 120
_FLEX_ROW_HISTORY = 128
_FLEX_FALLBACK_S = 3600.0
_FLEX_SLOT_MASK = 0x0F  # The four EFlexSlotTypes_t flags in the game schema.

STEAM64_BASE = 76561197960265728

_PLAYER_COLUMNS = (
    "m_unEconAccountID", "m_steamID", "m_PlayerDataGlobal__m_nHeroID",
    "m_PlayerDataGlobal__m_iGoldNetWorth", "m_PlayerDataGlobal__m_iAPNetWorth",
    "m_PlayerDataGlobal__m_iGold", "m_PlayerDataGlobal__m_iLevel",
    "m_PlayerDataGlobal__m_iPlayerKills", "m_PlayerDataGlobal__m_iPlayerAssists",
    "m_PlayerDataGlobal__m_iDeaths", "m_PlayerDataGlobal__m_iHeroDamage",
    "m_PlayerDataGlobal__m_iHeroHealing", "m_PlayerDataGlobal__m_iObjectiveDamage",
    "m_PlayerDataGlobal__m_vecUpgrades",
)
_COLUMNS_SQL = ", ".join(f'"{column}"' for column in _PLAYER_COLUMNS)
_NULL_COLUMNS_SQL = ", ".join(f'NULL AS "{column}"' for column in _PLAYER_COLUMNS)
QUERY = f'SELECT tick, entity_index, "m_iTeamNum", {_COLUMNS_SQL} FROM CCitadelPlayerController'
# UNION ALL streams both branches without waiting for the broadcast to end.
# A team row is optional and is never part of the controller roster.
FLEX_QUERY = (
    'SELECT \'team\' AS row_kind, tick, entity_index, "m_iTeamNum", '
    f'"m_nFlexSlotsUnlocked" AS flex_mask, {_NULL_COLUMNS_SQL} FROM CCitadelTeam '
    "UNION ALL "
    'SELECT \'player\' AS row_kind, tick, entity_index, "m_iTeamNum", '
    f'NULL AS flex_mask, {_COLUMNS_SQL} FROM CCitadelPlayerController'
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
    team_flex_slots: Dict[int, int] = field(default_factory=dict)

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


_READ_STATE = threading.local()


def last_broadcast_read() -> tuple[str, Optional[int]]:
    """Return a coarse result for this worker, without relay or roster data."""
    return getattr(_READ_STATE, "result", ("unavailable", None))


def _status_code(payload):
    value = payload.get("status") if isinstance(payload, dict) else None
    return value if type(value) is int and 400 <= value < 600 else None


def _sse_events(response, deadline):
    event, lines = "message", []
    for raw in response:
        if time.monotonic() >= deadline:
            return
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip())
        elif not line:
            if lines or event in ("end", "error"):
                try:
                    payload = json.loads("\n".join(lines)) if lines and event != "status" else None
                except (TypeError, ValueError):
                    payload = None
                yield event, payload
            event, lines = "message", []


def _flex_count(value):
    """Decode the broadcast's little-endian enum mask without guessing capacity."""
    if isinstance(value, str) and len(value) == 16:
        try:
            raw = bytes.fromhex(value)
        except ValueError:
            return None
        if len(raw) != 8:
            return None
        value = int.from_bytes(raw, "little")
    if type(value) is not int or not 0 <= value <= _FLEX_SLOT_MASK:
        return None
    count = value.bit_count()
    return count if count <= MAX_INVENTORY_CAPACITY - BASE_INVENTORY_CAPACITY else None


def _record_flex_row(teams, row, tick):
    """Keep bounded team history because UNION ALL can interleave by source."""
    team = row.get("m_iTeamNum")
    if type(team) is not int or team not in PLAYING_TEAMS or tick < 0:
        return
    value = _flex_count(row.get("flex_mask"))
    history = teams.get(team)
    if history is None:
        history = teams[team] = deque(maxlen=_FLEX_ROW_HISTORY)
    previous_tick, previous_value = history[-1] if history else (-1, None)
    if tick > previous_tick:
        history.append((tick, value))
    elif tick == previous_tick and value != previous_value:
        history[-1] = (tick, None)


def _flex_for_roster(teams, roster_tick):
    verified = {}
    for team, history in teams.items():
        for tick, count in reversed(history):
            if tick > roster_tick:
                continue
            if count is not None and roster_tick - tick <= FLEX_MAX_TICK_LAG:
                verified[team] = count
            break
    return verified


def _read_roster(events, after_tick):
    players, active_tick = {}, -1
    teams = {}
    progress = False
    for event, row in events:
        if event == "status":
            progress = True
            continue
        if event == "end":
            _READ_STATE.result = ("ended", None)
            return None
        if event == "error" or (isinstance(row, dict) and "error" in row):
            _READ_STATE.result = ("relay_error", _status_code(row))
            return None
        if not isinstance(row, dict):
            continue
        try:
            entity = int(row.get("entity_index"))
            tick = int(row.get("tick") or 0)
        except (TypeError, ValueError):
            continue
        if row.get("row_kind") == "team":
            _record_flex_row(teams, row, tick)
            continue
        if tick <= after_tick or tick < active_tick:
            continue
        player = parse_player(row)
        if player is None:
            continue
        if tick != active_tick:
            players.clear()
            active_tick = tick
        players[entity] = player
        if len(players) == 12:
            _READ_STATE.result = ("ready", None)
            return active_tick, list(players.values()), _flex_for_roster(teams, active_tick)
    _READ_STATE.result = ("incomplete_roster" if players else "relay_starting" if progress else "no_rows", None)
    return None


def fetch_live_snapshot(match_id: int, timeout_s: Optional[float] = None, *,
                        after_tick: int = -1) -> Optional[LiveSnapshot]:
    """Read a complete roster newer than the watermark, without mixing ticks."""
    match_id = int(match_id)
    if timeout_s is None:
        timeout_s = JOIN_TIMEOUT_S if after_tick < 0 else READ_TIMEOUT_S
    started = time.monotonic()
    deadline = started + timeout_s
    with _LOCK:
        flex_enabled = started >= _FLEX_UNSUPPORTED.get(match_id, 0)
    roster = _query_roster(match_id, FLEX_QUERY if flex_enabled else QUERY, deadline, after_tick)
    result, status = last_broadcast_read()
    if roster is None and flex_enabled and status == 400 and result in ("http_error", "relay_error"):
        # Upstream reports missing columns and other SQL planning errors as 400.
        with _LOCK:
            expired = [key for key, until in _FLEX_UNSUPPORTED.items() if until <= started]
            for key in expired:
                _FLEX_UNSUPPORTED.pop(key)
            _FLEX_UNSUPPORTED[match_id] = started + _FLEX_FALLBACK_S
        roster = _query_roster(match_id, QUERY, deadline, after_tick)
    if roster is None:
        return None
    tick, players, flex = roster
    return LiveSnapshot(match_id=match_id, players=players, tick=tick,
                        fetched_at=_now(), team_flex_slots=flex)


def _query_roster(match_id, query, deadline, after_tick):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    url = f"{API}?{urllib.parse.urlencode({'match_id': match_id, 'query': query})}"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/event-stream"}
    )
    _READ_STATE.result = ("unavailable", None)
    try:
        with urllib.request.urlopen(request, timeout=min(remaining, SOCKET_TIMEOUT_S)) as response:
            return _read_roster(_sse_events(response, deadline), after_tick)
    except HTTPError as error:
        _READ_STATE.result = ("http_error", error.code)
    except Exception:
        return None


_LOCK = threading.Lock()
_CACHE: Dict[int, LiveSnapshot] = {}
_MISSES: Dict[int, float] = {}
_LAST_TICK: Dict[int, int] = {}
_FLEX_UNSUPPORTED: Dict[int, float] = {}


def _now() -> float:
    """Clock hook so cache expiry is testable without sleeping."""
    return time.time()


def get_live_snapshot(match_id: int, max_age_s: float = SNAPSHOT_TTL_S) -> Optional[LiveSnapshot]:
    """Cached snapshot: at most one broadcast read per ``max_age_s``.

    Failures are cached for a few seconds too: when a match ends the overlay
    must stop showing items without hammering the API on every UI poll.
    """
    key = int(match_id)
    _READ_STATE.result = ("unavailable", None)
    now = _now()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached.fetched_at <= max_age_s:
            return cached
        missed_at = _MISSES.get(key)
        if missed_at and now - missed_at <= MISS_TTL_S:
            return None
        watermark = _LAST_TICK.get(key, cached.tick if cached is not None else -1)
    snapshot = fetch_live_snapshot(key, after_tick=watermark)
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
