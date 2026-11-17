"""Advisor live identity and inventory, from the API, with optional corner ID discovery."""

import time
from typing import Optional

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
        self._connection_identity = (self.account_id, self.match_id)
        self._confirmed_match = None
        self._confirmed_until = 0.0
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
        for match_id, origin in candidates[:2]:
            if time.monotonic() < self._candidate_failures.get(match_id, 0):
                self._live_status = "connecting"
                self._live_reason = "Broadcast unavailable; retrying shortly. Settings can retry now."
                continue
            live = self._read_candidate(match_id, origin)
            if live is not None:
                self._confirmed_match = match_id
                self._confirmed_until = time.monotonic() + 120
                self._candidate_failures.pop(match_id, None)
                return live
            # A bad automatic candidate must not suppress a different corner ID.
            self._candidate_failures[match_id] = time.monotonic() + 30
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
            corner_reason = match_id_status()
        try:
            from advisor_api import find_active_match
            active = find_active_match(self.account_id)
            if active:
                candidates.append((active, "watch_list"))
            list_reason = "Your match is absent from the public watch list."
        except Exception:
            list_reason = "The public match list is temporarily unavailable."
        if self._confirmed_match and time.monotonic() < self._confirmed_until:
            candidates.append((self._confirmed_match, "verified_previous"))
        unique = []
        seen = set()
        for match, origin in candidates:
            if match not in seen:
                unique.append((match, origin))
                seen.add(match)
        if not unique and running:
            self._live_status = "needs_match"
            self._live_reason = f"{list_reason} {corner_reason}"
        return unique

    def _read_candidate(self, match_id, origin):
        try:
            if self._live_fetcher is not None:
                snapshot = self._live_fetcher(int(match_id))
            else:
                from live_match import get_live_snapshot
                snapshot = get_live_snapshot(int(match_id))
        except Exception:
            snapshot = None
        if snapshot is None or snapshot.match_id != int(match_id):
            self._live_status = "connecting"
            prefix = "Manual match ID" if origin == "manual" else "Match ID found"
            self._live_reason = f"{prefix}; the public broadcast is warming up or unavailable."
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
        self._live_status, self._live_reason = "ok", "Connected to a verified live broadcast."
        return {
            "match_id": int(match_id), "hero_id": me.hero_id, "owner": owner,
            "context": context, "connection_source": origin,
            "valid_until": time.time() + max(0.0, LIVE_FRESHNESS_S - age),
            "tick": snapshot.tick,
        }

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
