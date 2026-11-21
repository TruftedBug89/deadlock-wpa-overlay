"""Advisor live identity and inventory, from the API, with optional corner ID discovery."""

import time
from dataclasses import replace
from typing import Optional

from item_inventory import BASE_INVENTORY_CAPACITY, MAX_INVENTORY_CAPACITY
from match_context import MatchContext, build_context
from runtime_policy import LIVE_FRESHNESS_S, game_running


class AdvisorLiveMixin:
    """Live state methods for AdvisorDataSource; all work stays on its worker."""

    def reset_connection(self) -> None:
        """Forget discovery misses on an explicit retry or identity change."""
        from advisor_api import clear_active_match_cache
        from match_code_reader import clear_match_id_cache
        from live_match import clear_live_cache
        clear_active_match_cache(self.account_id)
        clear_match_id_cache()
        for match in (self.match_id, getattr(self, "_confirmed_match", None)):
            if match:
                clear_live_cache(match)
        flex_probe = getattr(self, "_flex_probe", None)
        if flex_probe is not None:
            flex_probe.reset()
        self._connection_identity = (self.account_id, self.match_id)
        self._confirmed_match = None
        self._confirmed_until = 0.0
        self._detected_match = None
        self._detected_until = 0.0
        self._unavailable_match = None
        self._candidate_failures = {}
        self._reset_owned()

    def _live_state(self) -> Optional[dict]:
        """Confirm current identity; discovery absence never fabricates a match."""
        self._live_status, self._live_reason = "idle", "No confirmed live match."
        if self.match_id is None and not self.require_match:
            return None
        if self.account_id is None:
            try:
                from local_account import find_account_id
                self.account_id = find_account_id()
            except Exception:
                self.account_id = None
        if self.account_id is None and self.manual_hero_id is None:
            self._live_status = "needs_account"
            self._live_reason = "Set your account ID in settings; local identity is missing or ambiguous."
            self._reset_owned()
            return None
        identity = (self.account_id, self.match_id)
        if getattr(self, "_connection_identity", None) != identity:
            self.reset_connection()
        candidates = self._match_candidates()
        if not candidates:
            self._reset_owned()
            return None
        self._candidate_failures = {match: until for match, until in self._candidate_failures.items()
                                    if until > time.monotonic()}
        attempts = 0
        for match_id, origin in candidates:
            if time.monotonic() < self._candidate_failures.get(match_id, 0):
                self._live_status = "broadcast_unavailable" if match_id == self._unavailable_match else "connecting"
                self._live_reason = "Broadcast unavailable; retrying shortly. Settings can retry now."
                continue
            if attempts >= 2:
                break
            attempts += 1
            live = self._read_candidate(match_id, origin)
            if live is not None:
                self._unavailable_match = None
                self._confirmed_match = match_id
                self._confirmed_until = time.monotonic() + 120
                self._candidate_failures.pop(match_id, None)
                return live
            # A bad automatic candidate must not suppress a different corner ID.
            delay = 60 if self._live_status == "broadcast_unavailable" else 30
            self._candidate_failures[match_id] = time.monotonic() + delay
        self._reset_owned()
        return None

    def _match_candidates(self):
        if self.match_id is not None:
            return [(int(self.match_id), "manual")]
        candidates = []
        running = game_running()
        corner_reason = "Corner reading is disabled; enable it or enter the match ID."
        if self.read_match_id and running:
            from match_code_reader import get_match_id, match_id_status
            code = get_match_id(max_age_s=45.0)
            if code:
                candidates.append((code, "corner"))
                self._detected_match, self._detected_until = code, time.monotonic() + 180
            corner_reason = match_id_status()
        try:
            from advisor_api import find_active_match
            active = find_active_match(self.account_id)
            if active:
                candidates.append((active, "watch_list"))
                if len(candidates) == 1:
                    self._detected_match, self._detected_until = active, time.monotonic() + 180
            list_reason = "Your match is absent from the public watch list."
        except Exception:
            list_reason = "The public match list is temporarily unavailable."
        if self._confirmed_match and time.monotonic() < self._confirmed_until:
            candidates.append((self._confirmed_match, "verified_previous"))
        if running and self._detected_match and time.monotonic() < self._detected_until:
            candidates.append((self._detected_match, "detected_previous"))
        unique = []
        seen = set()
        for match, origin in candidates:
            if match not in seen:
                unique.append((match, origin))
                seen.add(match)
        if not unique and running:
            self._live_status = "needs_match"
            self._live_reason = f"{list_reason} {corner_reason} Automatic discovery will retry."
        return unique

    def _read_candidate(self, match_id, origin):
        result, status_code = "unavailable", None
        announce = getattr(self, "_on_broadcast_start", None)
        if announce is not None and match_id not in (self._confirmed_match, self._unavailable_match):
            announce()
        try:
            if self._live_fetcher is not None:
                snapshot = self._live_fetcher(int(match_id))
            else:
                from live_match import get_live_snapshot, last_broadcast_read
                snapshot = get_live_snapshot(int(match_id))
                result, status_code = last_broadcast_read()
        except Exception:
            snapshot = None
        if snapshot is None or snapshot.match_id != int(match_id):
            if result in ("relay_error", "http_error", "ended") or match_id == self._unavailable_match:
                self._unavailable_match = match_id
                self._live_status = "broadcast_unavailable"
            else:
                self._live_status = "connecting"
            prefix = "Manual match ID" if origin == "manual" else "Match ID found"
            detail = _broadcast_detail(result, status_code)
            self._live_reason = f"{prefix}. {detail}"
            return None
        me = snapshot.player_for_account(self.account_id)
        if me is None and self.account_id is None and self.manual_hero_id is not None:
            me = snapshot.player_for_hero(self.manual_hero_id)
        if me is None:
            self._live_status = "needs_account"
            self._live_reason = "This broadcast does not contain your account. Check account and match IDs."
            return None
        from live_match import _now
        age = max(0.0, _now() - snapshot.fetched_at) if snapshot.fetched_at else 0.0
        if age > LIVE_FRESHNESS_S or not me.souls_known:
            self._live_status = "unknown"
            self._live_reason = "Broadcast data is stale or incomplete; advice is hidden."
            return None
        owner = (me.account_id, me.hero_id, me.team)
        if self._owned_match_id != int(match_id) or self._owned_player != owner:
            self._reset_owned()
        context = build_context(snapshot.players, self.account_id, me.hero_id)
        held = len(set(context.owned_item_ids))
        flex_slots = self._available_flex(snapshot, me.team, held) if context.ownership_known else None
        if type(flex_slots) is int and 0 <= flex_slots <= MAX_INVENTORY_CAPACITY - BASE_INVENTORY_CAPACITY:
            capacity = BASE_INVENTORY_CAPACITY + flex_slots
            if held <= capacity:
                context = replace(context, inventory_capacity=capacity)
        self._live_status, self._live_reason = "ok", "Connected to a verified live broadcast."
        return {
            "match_id": int(match_id), "hero_id": me.hero_id, "owner": owner,
            "context": context, "connection_source": origin,
            "valid_until": time.time() + max(0.0, LIVE_FRESHNESS_S - age),
            "tick": snapshot.tick,
        }

    def _available_flex(self, snapshot, team, held):
        slots = snapshot.team_flex_slots.get(team)
        notify = getattr(self, "_on_capacity_ready", None)
        if (slots is not None or notify is None or self._live_fetcher is not None
                or not BASE_INVENTORY_CAPACITY <= held < MAX_INVENTORY_CAPACITY):
            return slots
        from live_flex import TeamFlexProbe
        if getattr(self, "_flex_probe", None) is None:
            self._flex_probe = TeamFlexProbe()
        return self._flex_probe.value_or_schedule(snapshot.match_id, team, snapshot.tick, notify)

    def _known_owned(self, context: MatchContext, match_id: Optional[int], owner=None) -> set:
        """Owned ids with the no-flash-back rule from the old implementation."""
        if context.ownership_known:
            known = {int(item_id) for item_id in context.owned_item_ids}
            self._owned_match_id = match_id
            self._owned_player = owner
            self._owned_ids = set(known)
            return known
        if self._owned_match_id == match_id and self._owned_player == owner:
            return set(self._owned_ids)
        return set()

    def _reset_owned(self) -> None:
        self._owned_match_id = None
        self._owned_player = None
        self._owned_ids = set()


def _broadcast_detail(result, code):
    if code == 429:
        return "The public API rate limit was reached. Retrying automatically."
    if code == 502:
        return "The public API could not start the spectator broadcast. Retrying automatically."
    if code is not None:
        return f"The public broadcast returned status {code}. Retrying automatically."
    return {
        "ended": "The public broadcast ended before a fresh roster arrived.",
        "relay_starting": "The public broadcast is still starting. Retrying automatically.",
        "incomplete_roster": "The public broadcast has not sent a complete roster yet.",
    }.get(result, "The public broadcast is warming up or unavailable.")
