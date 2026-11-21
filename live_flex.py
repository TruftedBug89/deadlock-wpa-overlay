"""Optional team state over the public live query, isolated from roster reads."""

import time
import urllib.parse
import urllib.request
from threading import Lock, Thread
from typing import Optional

from live_match import API, FLEX_MAX_TICK_LAG, PLAYING_TEAMS, USER_AGENT, _flex_count, _sse_events
from runtime_policy import LIVE_FRESHNESS_S


_REQUEST_BUDGET_S = 8.0
_COOLDOWN_S = 45.0


def fetch_team_flex(match_id: int, team: int, roster_tick: int):
    """Return a measured (tick, count) near the already-verified roster tick."""
    if team not in PLAYING_TEAMS or roster_tick < 0:
        return None
    floor = max(0, roster_tick - FLEX_MAX_TICK_LAG)
    query = (
        'SELECT tick, "m_iTeamNum", "m_nFlexSlotsUnlocked" AS flex_mask FROM CCitadelTeam '
        f'WHERE "m_iTeamNum" = {team} AND tick BETWEEN {floor} AND {roster_tick}'
    )
    url = f"{API}?{urllib.parse.urlencode({'match_id': int(match_id), 'query': query})}"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/event-stream"}
    )
    deadline = time.monotonic() + _REQUEST_BUDGET_S
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_BUDGET_S) as response:
            for event, row in _sse_events(response, deadline):
                if event in ("end", "error"):
                    return None
                if event != "message" or not isinstance(row, dict) or row.get("m_iTeamNum") != team:
                    continue
                tick = row.get("tick")
                if type(tick) is not int or not floor <= tick <= roster_tick:
                    continue
                count = _flex_count(row.get("flex_mask"))
                if count is not None:
                    return tick, count
    except (OSError, ValueError):
        return None


class TeamFlexProbe:
    """Single optional request in flight. Results cannot outlive their identity."""

    def __init__(self):
        self._lock = Lock()
        self._scope = None
        self._result = None
        self._attempts = {}
        self._active = False

    def reset(self) -> None:
        """Invalidate the result of an in-flight request after connection changes."""
        with self._lock:
            self._scope = None
            self._result = None

    def value_or_schedule(self, match_id, team, roster_tick, notify) -> Optional[int]:
        """Read a recent result or schedule a bounded request, returning immediately."""
        key = (match_id, team)
        now = time.monotonic()
        with self._lock:
            if self._scope != key:
                self._scope = key
                self._result = None
            if self._result is not None:
                tick, count, received_at = self._result
                if 0 <= roster_tick - tick <= FLEX_MAX_TICK_LAG and now - received_at <= LIVE_FRESHNESS_S:
                    return count
            if self._active or now - self._attempts.get(match_id, float("-inf")) < _COOLDOWN_S:
                return None
            scope = self._scope
            self._active = True
            self._attempts = {match: started for match, started in self._attempts.items()
                              if now - started < _COOLDOWN_S}
            self._attempts[match_id] = now
        thread = Thread(target=self._refresh, args=(scope, roster_tick, notify),
                        daemon=True, name="WpaTeamFlex")
        try:
            thread.start()
        except RuntimeError:
            with self._lock:
                self._active = False
        return None

    def _refresh(self, scope, roster_tick, notify):
        observed = None
        try:
            observed = fetch_team_flex(*scope, roster_tick)
        finally:
            with self._lock:
                self._active = False
                accepted = observed is not None and self._scope is scope
                if accepted:
                    self._result = (*observed, time.monotonic())
        if accepted:
            notify()
