"""Opt-in local health reporting for an interactive match test."""

from collections import Counter
import json
import os
from pathlib import Path
import time


_CONNECTIONS = {"corner", "manual", "watch_list", "verified_previous", "detected_previous"}
_REASONS = (
    ("does not contain your account", "roster_account_mismatch"),
    ("corner id unreadable", "unreadable_corner"),
    ("corner match id unreadable", "unreadable_corner"),
    ("focus deadlock", "game_not_in_foreground"),
    ("corner capture unavailable", "corner_capture_unavailable"),
    ("ocr is unavailable", "ocr_unavailable"),
    ("watch list", "watch_list_miss"),
    ("match list is temporarily unavailable", "watch_list_unavailable"),
    ("broadcast is warming up", "broadcast_unavailable"),
    ("broadcast is still starting", "relay_starting"),
    ("could not start the spectator broadcast", "relay_failed"),
    ("has not sent a complete roster", "incomplete_roster"),
    ("public api rate limit", "api_rate_limit"),
    ("broadcast unavailable", "broadcast_retry"),
    ("account id in settings", "account_needed"),
    ("budget, inventory", "inventory_or_economy_unknown"),
    ("wallet and inventory", "inventory_or_economy_unknown"),
    ("snapshot expired", "snapshot_expired_during_scan"),
    ("fresh public broadcast", "snapshot_expired"),
    ("stale or incomplete", "snapshot_invalid"),
    ("assets unavailable", "catalog_unavailable"),
)


class PlaytestHealth:
    """Atomically record coarse state and counters without game identifiers."""

    def __init__(self, path):
        self.path = Path(path)
        self.status_counts = Counter()
        self.reason_counts = Counter()
        self.connections = Counter()
        self.shown_scans = 0
        self.last_live_at = None

    def record(self, state, kind, explanation=None):
        explanation = explanation or {}
        connection = explanation.get("connection_source")
        if connection not in _CONNECTIONS or not state.is_in_match:
            connection = None
        reason = "" if state.scan_status == "idle" else str(
            state.last_error or explanation.get("reason") or ""
        ).lower()
        reasons = [label for marker, label in _REASONS if marker in reason]
        self.status_counts[state.scan_status] += 1
        self.reason_counts.update(reasons)
        if connection:
            self.connections[connection] += 1
        now = time.time()
        if connection and state.recommended_items:
            self.shown_scans += 1
            self.last_live_at = now
        report = {
            "pid": os.getpid(), "updated_at": now,
            "status": state.scan_status, "view": kind,
            "connection": connection, "reasons": reasons,
            "recommended": len(state.recommended_items), "plan": len(state.build_plan),
            "owned": state.known_owned_items,
            "snapshot_time_left_s": (round(max(0, state.valid_until - now), 1)
                                     if state.valid_until is not None else None),
            "status_counts": self.status_counts, "reason_counts": self.reason_counts,
            "connections": self.connections,
            "shown_scans": self.shown_scans, "last_live_at": self.last_live_at,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".part")
            temporary.write_text(json.dumps(report), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass
