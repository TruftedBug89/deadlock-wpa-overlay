"""Advisor live identity and inventory, from the API, with optional corner ID discovery."""

import time
from typing import Optional

from match_context import MatchContext, build_context
from runtime_policy import LIVE_FRESHNESS_S, game_running


class AdvisorLiveMixin:
    """Live state methods for AdvisorDataSource; all work stays on its worker."""

    def _live_state(self) -> Optional[dict]:
        """Current match identity plus the picker's context, or ``None``."""
        match_id = self.match_id
        self._live_status = "idle"
        self._live_reason = "no confirmed live match"
        if match_id is None and not self.require_match:
            # Preview mode (tests, F6) does not go looking at the live game.
            return None
        if self.account_id is None:
            try:
                from local_account import find_account_id

                self.account_id = find_account_id()
            except Exception:
                self.account_id = None
        if self.account_id is None and self.manual_hero_id is None:
            self._live_status = "needs_account"
            self._live_reason = "set your account ID in overlay settings; local identity is missing or ambiguous"
            self._reset_owned()
            return None
        if match_id is None:
            try:
                from advisor_api import find_active_match
                match_id = find_active_match(self.account_id)
            except Exception:
                match_id = None
        if not match_id and self.read_match_id and game_running():
            from match_code_reader import get_match_id
            match_id = get_match_id(max_age_s=45.0)
        if not match_id:
            if game_running():
                self._live_status = "needs_match"
                self._live_reason = "Deadlock is running; this match is absent from the public watch list"
            self._reset_owned()
            return None
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
            self._live_reason = "match ID known; waiting for the public live broadcast"
            self._reset_owned()
            return None
        me = snapshot.player_for_account(self.account_id)
        if me is None and self.account_id is None and self.manual_hero_id is not None:
            me = snapshot.player_for_hero(self.manual_hero_id)
        if me is None:
            self._live_status = "needs_account"
            self._live_reason = "broadcast connected; account is not in the roster"
            self._reset_owned()
            return None
        from live_match import _now
        age = max(0.0, _now() - snapshot.fetched_at) if snapshot.fetched_at else 0.0
        if age > LIVE_FRESHNESS_S or not me.souls_known:
            self._live_status = "unknown"
            self._live_reason = "broadcast snapshot is stale or incomplete"
            return None
        current_match = int(match_id)
        owner = (me.account_id, me.hero_id, me.team)
        if self._owned_match_id != current_match or self._owned_player != owner:
            self._reset_owned()
        context = build_context(snapshot.players, self.account_id, me.hero_id)
        return {
            "match_id": current_match,
            "hero_id": me.hero_id,
            "owner": owner,
            "context": context,
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
