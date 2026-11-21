"""Stable purchase order with fresh evidence and bounded suggestion changes."""

import time

from models import RecommendationQueueState
from recommendation_engine import select_legal


def priority(entry):
    """Same ordering as the evidence scorer; an affordable item wins ties."""
    return (entry.affordable_now is True, entry.score, entry.matches, entry.win_rate or 0)


class RecommendationQueue:
    """Retain IDs, never old item objects, rates, budgets or evidence."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = RecommendationQueueState()
        self.explanation = {}

    def clear(self):
        self.state = RecommendationQueueState()
        self.explanation = {"action": "cleared"}

    def update(self, pool, *, owner, limit, interval=150, owned_ids=(), categories=None,
               inventory_capacity=None):
        """Refresh valid entries in place; append at most one new entry per review."""
        now = self.clock()
        interval = max(60.0, min(600.0, float(interval)))
        limit = max(1, int(limit))
        by_id = {entry.item_id: entry for entry in pool}
        choose = lambda entries: select_legal(entries, limit, owned_ids, categories,
                                              inventory_capacity=inventory_capacity)
        previous = list(self.state.item_ids)
        if self.state.owner != owner:
            selected, action = choose(pool), "new_match"
            self.state = RecommendationQueueState(owner=owner, reviewed_at=now)
        else:
            held = [by_id[item_id] for item_id in previous if item_id in by_id]
            # Purchase affordability is refreshed now, never held for the timer.
            held.sort(key=lambda entry: entry.affordable_now is True, reverse=True)
            selected = choose(held)
            invalidated = len(selected) < len(previous)
            due = now - self.state.reviewed_at >= interval
            action = "held"
            if due or invalidated or len(selected) < limit:
                selected, added = self._append_one(selected, pool, choose, limit, due)
                action = "invalidated" if invalidated else "reviewed" if due else "refilled"
                if added or due:
                    self.state.reviewed_at = now
        self.state.item_ids = [entry.item_id for entry in selected]
        self.explanation = {
            "action": action, "interval_seconds": interval,
            "seconds_until_review": max(0, round(interval - (now - self.state.reviewed_at), 1)),
            "previous_ids": previous, "selected_ids": self.state.item_ids,
            "evidence": "freshly revalidated on every live poll",
        }
        return selected

    @staticmethod
    def _append_one(held, pool, choose, limit, due):
        ids = {entry.item_id for entry in held}
        for outsider in pool:
            if outsider.item_id in ids:
                continue
            remaining = held
            if len(held) >= limit:
                if not due:
                    return held, False
                weakest = min(held, key=priority)
                if priority(outsider) <= priority(weakest):
                    continue
                remaining = [entry for entry in held if entry.item_id != weakest.item_id]
            proposal = choose(remaining + [outsider])
            if due and outsider.item_id not in {entry.item_id for entry in proposal}:
                # A category can be full even when the overall plan has gaps.
                for weaker in sorted(held, key=priority):
                    if priority(outsider) <= priority(weaker):
                        continue
                    attempt = choose([entry for entry in held if entry.item_id != weaker.item_id] + [outsider])
                    if outsider.item_id in {entry.item_id for entry in attempt}:
                        proposal = attempt
                        break
            if outsider.item_id in {entry.item_id for entry in proposal}:
                # A newly affordable alternative precedes savings-only targets.
                proposal.sort(key=lambda entry: entry.affordable_now is True, reverse=True)
                return proposal, True
        return held, False
