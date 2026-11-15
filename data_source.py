"""State assembly: Statlocker database + companion log + live screen OCR.

Truth policy
------------
* Recommended items come from the cards Statlocker is rendering *right now*.
* The database is only used for catalog metadata, icon URLs and the explicit
  F6 hero preview.  It is never used to invent "probably good" items during a
  match (that was the source of the stale/fake recommendations).
* Anything unknown stays ``None``; nothing is filled with a default percentage
  or timestamp.
"""

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from capture_archiver import StatlockerCaptureArchiver
from counter_remote import RemoteCounters
from live_screen_reader import ScreenReadResult, read_live_wpa_screen
from log_tracker import (
    LogSnapshot,
    MatchLogTracker,
    detect_active_hero_from_logs,
    get_latest_log_path,
)
from models import GameState
from statlocker_counters import CounterMixin
from statlocker_discovery import find_statlocker_paths
from wpa_item_builder import WpaItemMixin

class StatlockerDataSource(CounterMixin, WpaItemMixin):
    """Combine companion log, SQLite catalog and live screen into a GameState."""

    def __init__(self, db_path: Optional[Path] = None, log_dir: Optional[Path] = None):
        if db_path is None or log_dir is None:
            discovered_db, discovered_log = find_statlocker_paths()
            self.db_path = db_path or discovered_db
            self.log_dir = log_dir or discovered_log
        else:
            self.db_path = db_path
            self.log_dir = log_dir

        self.manual_hero_id: Optional[int] = None
        self.manual_enemy_heroes: Optional[List[int]] = None
        self.manual_match_id: Optional[int] = None
        self.manual_account_id: Optional[int] = None
        self._remote_counters = RemoteCounters()
        self._last_threat: Optional[dict] = None
        self._catalog_items: Dict[str, dict] = {}
        self._catalog_items_by_id: Dict[int, dict] = {}
        self._catalog_items_by_class: Dict[str, dict] = {}
        self._matchable_items: List[dict] = []
        self._heroes_map: Dict[int, str] = {}
        self._catalog_loaded = False
        self._catalog_error: Optional[str] = None
        self._tracker = MatchLogTracker()
        self._last_state = GameState()
        self._archiver = StatlockerCaptureArchiver()

    # ---------------------------------------------------------------- catalog
    def open_connection(self) -> Optional[sqlite3.Connection]:
        """Open a read-only SQLite connection (WAL safe)."""
        if not self.db_path or not self.db_path.exists():
            discovered_db, discovered_log = find_statlocker_paths()
            if discovered_db.exists():
                self.db_path = discovered_db
                self.log_dir = discovered_log
            else:
                return None
        try:
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as err:
            self._catalog_error = f"db connect failed: {err}"
            return None

    def load_catalog(self) -> bool:
        """Cache the static item catalog and hero roster."""
        if self._catalog_loaded:
            return bool(self._catalog_items)
        conn = self.open_connection()
        if not conn:
            self._catalog_error = self._catalog_error or "Statlocker database not found"
            return False
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = 'catalog'").fetchone()
            if not row or not row[0]:
                self._catalog_error = "catalog setting missing"
                return False
            catalog = json.loads(row[0])
            for item in catalog.get("items", []):
                self._index_item(item)
            for hero in catalog.get("heroes", []):
                hero_id, hero_name = hero.get("id"), hero.get("name")
                if hero_id is not None and hero_name:
                    self._heroes_map[int(hero_id)] = hero_name
            self._matchable_items = [
                item
                for item in self._catalog_items.values()
                if item.get("type") == "upgrade"
                and not item.get("disabled")
                and item.get("shopable") is not False
            ]
            self._catalog_loaded = True
            return bool(self._catalog_items)
        except Exception as err:
            self._catalog_error = f"catalog parse failed: {err}"
            return False
        finally:
            conn.close()

    def _index_item(self, item: dict) -> None:
        name = item.get("name")
        item_id = item.get("id")
        class_name = item.get("class_name")
        is_valid = (
            item.get("type") == "upgrade"
            and not item.get("disabled")
            and item.get("shopable") is not False
        )
        if name:
            key = name.lower()
            if key not in self._catalog_items or is_valid:
                self._catalog_items[key] = item
        if item_id is not None:
            try:
                numeric_id = int(item_id)
            except (TypeError, ValueError):
                numeric_id = None
            if numeric_id is not None and (numeric_id not in self._catalog_items_by_id or is_valid):
                self._catalog_items_by_id[numeric_id] = item
        if class_name:
            key = class_name.lower()
            if key not in self._catalog_items_by_class or is_valid:
                self._catalog_items_by_class[key] = item

    def catalog_items(self) -> List[dict]:
        """Valid catalog entries used for OCR matching."""
        self.load_catalog()
        return self._matchable_items

    @property
    def catalog_error(self) -> Optional[str]:
        """Last catalog/database problem, if any."""
        return self._catalog_error

    # ------------------------------------------------------------------ hero
    def _resolve_hero(self, conn: Optional[sqlite3.Connection], log_hero: Optional[int]):
        if self.manual_hero_id is not None:
            return self.manual_hero_id, self._heroes_map.get(self.manual_hero_id, "Hero")
        if log_hero is not None:
            return log_hero, self._heroes_map.get(log_hero, "Hero")
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key = 'hero_builds_pending'"
                ).fetchone()
                account_row = conn.execute(
                    "SELECT value FROM settings WHERE key = 'steam_account_id'"
                ).fetchone()
                account = account_row[0] if account_row else None
                if row and row[0]:
                    pending = json.loads(row[0])
                    players = pending.get("players", [])
                    for player in players:
                        if account and str(player.get("accountId")) == str(account):
                            hero_id = int(player.get("heroId"))
                            return hero_id, self._heroes_map.get(hero_id, "Hero")
                    if players:
                        hero_id = int(players[0].get("heroId"))
                        return hero_id, self._heroes_map.get(hero_id, "Hero")
            except Exception:
                pass
        return None, "Unknown"

    def _build_id_for_hero(self, conn: sqlite3.Connection, hero_id: Optional[int]) -> Optional[int]:
        try:
            account_row = conn.execute(
                "SELECT value FROM settings WHERE key = 'steam_account_id'"
            ).fetchone()
            account = account_row[0] if account_row else None
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'hero_builds_pending'"
            ).fetchone()
            if not row or not row[0]:
                return None
            pending = json.loads(row[0])
            for player in pending.get("players", []):
                matches_account = account and str(player.get("accountId")) == str(account)
                if matches_account or player.get("heroId") == hero_id:
                    timeline = player.get("timeline", [])
                    if timeline and timeline[-1].get("buildId"):
                        return int(timeline[-1]["buildId"])
        except Exception:
            pass
        return None

    def _wpa_stats(self, conn: sqlite3.Connection, hero_id: Optional[int]) -> Dict[str, dict]:
        if hero_id is None or conn is None:
            return {}
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (f"builds_wpa_{hero_id}",)
            ).fetchone()
            if not row or not row[0]:
                return {}
            payload = json.loads(row[0])
            items = payload.get("body", {}).get("items", [])
            return {(entry.get("item") or "").lower(): entry for entry in items if entry.get("item")}
        except Exception:
            return {}

    def get_game_state(
        self,
        max_items: int = 5,
        *,
        region_override: Optional[dict] = None,
        allow_db_fallback: bool = False,
    ) -> GameState:
        """Return the current match and the live Statlocker recommendations."""
        started = time.time()
        snapshot = LogSnapshot()
        conn: Optional[sqlite3.Connection] = None
        try:
            # Discovery, catalog parsing and log tailing are all fallible; the
            # caller must always receive a state object, never an exception.
            has_catalog = self.load_catalog()
            snapshot = self._tracker.poll(self.log_dir)
            log_hero = snapshot.hero_id or detect_active_hero_from_logs(self.log_dir)
            conn = self.open_connection()
            hero_id, hero_name = self._resolve_hero(conn, log_hero)
            state = GameState(
                match_id=snapshot.match_id,
                hero_id=hero_id,
                hero_name=hero_name,
                clock_s=snapshot.clock_s,
                owned_items=snapshot.owned_classes,
                is_in_match=snapshot.match_id is not None,
                generated_at=started,
            )

            if not has_catalog:
                state.scan_status = "error"
                state.last_error = self._catalog_error or "Statlocker catalog unavailable"
                self._last_state = state
                return state

            # Counter items for the enemy team (same read path as the WPA rows).
            enemy_ids = list(self.manual_enemy_heroes or sorted(snapshot.enemy_hero_ids))

            # Live broadcast data (deadlock-api) beats inference: exact enemy
            # lineup, per-player souls and the fed enemy of the current match.
            live_threat_id: Optional[int] = None
            live_souls = 0
            match_id = self.manual_match_id or (int(snapshot.match_id) if snapshot.match_id else None)
            if match_id is None:
                try:
                    from match_code_reader import get_match_id as read_match_code

                    match_id = read_match_code()
                except Exception:
                    match_id = None
            if match_id and hero_id is not None:
                try:
                    from live_match import get_live_snapshot, strongest_enemy as live_fed

                    live = get_live_snapshot(match_id)
                    me = None
                    if live is not None:
                        me = live.player_for_hero(hero_id) or live.player_for_account(self.manual_account_id)
                    if live is not None and me is not None:
                        live_players = live.enemies(me.account_id, me.hero_id)
                        if live_players:
                            enemy_ids = [player.hero_id for player in live_players]
                            fed = live_fed(live, me.account_id, me.hero_id)
                            live_threat_id = fed.hero_id if fed else None
                            live_souls = me.souls
                except Exception:
                    live_threat_id = None

            state.counter_items, state.counter_source = self._counter_items(
                conn, hero_id, enemy_ids, owned=snapshot.owned_classes, threat_id=live_threat_id
            )
            state.enemy_heroes = [self._heroes_map.get(int(e), str(e)) for e in enemy_ids]
            state.net_worth = live_souls
            threat = self._last_threat or {}
            threat_id = threat.get("enemy_id")
            if threat_id is not None:
                state.strongest_enemy = self._heroes_map.get(int(threat_id), str(threat_id))
                rate = threat.get("win_rate")
                state.strongest_enemy_winrate = float(rate) if rate is not None else None

            # Explicit preview mode (F6) - clearly tagged, never silent.
            if self.manual_hero_id is not None and conn is not None:
                state.recommended_items = self._preview_items(conn, hero_id, max_items)
                state.source = "build_preview"
                state.scan_status = "preview"
                state.detected_slots = len(state.recommended_items)
                state.matched_slots = len(state.recommended_items)
                state.is_in_match = True
                self._last_state = state
                return state

            stats_map = self._wpa_stats(conn, hero_id)
            # Hard contract: only names Statlocker currently recommends may be
            # shown. OCR text is allowed to pick *which* of those cards it is,
            # never to invent a different item.
            allowed_names = list(stats_map.keys())
            read = read_live_wpa_screen(
                self._matchable_items,
                region_override=region_override,
                preferred_names=allowed_names or None,
                restrict_to=allowed_names or None,
            )
            state.scan_status = read.status
            state.detected_slots = read.detected
            state.last_error = read.error

            if read.status == "ok":
                items = [
                    item
                    for item in (self._item_from_card(card, stats_map) for card in read.cards)
                    if item is not None
                ][:max_items]
                state.recommended_items = items
                state.matched_slots = len(items)
                state.source = "live_screen"
                state.is_in_match = True
                if items and read.frame is not None:
                    self._archiver.save_if_changed(read.frame, [it.name for it in items])
            elif read.status.startswith("empty"):
                state.source = "live_screen"
                state.is_in_match = True
                state.scan_status = read.status
                state.recommended_items = []
                state.matched_slots = 0
            elif allow_db_fallback and snapshot.match_id and conn is not None:
                # Opt-in only; clearly marked so the UI can flag it.
                state.recommended_items = self._preview_items(conn, hero_id, max_items)
                state.source = "db_fallback"
                state.detected_slots = len(state.recommended_items)
                state.matched_slots = len(state.recommended_items)
                state.is_in_match = True

            self._last_state = state
            return state
        except Exception as err:
            failed = GameState(
                is_in_match=snapshot.match_id is not None,
                match_id=snapshot.match_id,
                clock_s=snapshot.clock_s,
                scan_status="error",
                last_error=f"{type(err).__name__}: {err}",
                generated_at=started,
            )
            self._last_state = failed
            return failed
        finally:
            if conn is not None:
                conn.close()

    def inspect_live_screen(self, region_override: Optional[dict] = None) -> ScreenReadResult:
        """Expose a single raw screen scan for diagnostics."""
        self.load_catalog()
        return read_live_wpa_screen(
            self._matchable_items,
            region_override=region_override,
        )

    def cycle_next_hero(self) -> None:
        """Advance the F6 preview to the next hero present in the database."""
        conn = self.open_connection()
        if not conn:
            return
        try:
            rows = conn.execute(
                "SELECT key FROM settings WHERE key LIKE 'builds_page_%' "
                "AND key NOT LIKE 'builds_page_pending%'"
            ).fetchall()
            hero_ids = sorted(
                {
                    int(parts[2])
                    for row in rows
                    for parts in [str(row[0]).split("_")]
                    if len(parts) >= 3 and parts[2].isdigit()
                }
            )
            if not hero_ids:
                return
            current = self.manual_hero_id or self._last_state.hero_id or hero_ids[0]
            index = hero_ids.index(current) if current in hero_ids else -1
            for step in range(1, len(hero_ids) + 1):
                candidate = hero_ids[(index + step) % len(hero_ids)]
                if self._hero_has_wpa(conn, candidate):
                    self.manual_hero_id = candidate
                    return
            self.manual_hero_id = hero_ids[(index + 1) % len(hero_ids)]
        finally:
            conn.close()

    @staticmethod
    def _hero_has_wpa(conn, hero_id) -> bool:
        try:
            row = conn.execute(
                'SELECT value FROM settings WHERE key = ?', ('builds_wpa_%d' % hero_id,)
            ).fetchone()
            if not row or not row[0]:
                return False
            items = json.loads(row[0]).get('body', {}).get('items', [])
            return bool(items)
        except Exception:
            return False

    def latest_log_path(self) -> Optional[Path]:
        """Path of the newest companion log (watchdog helper)."""
        return get_latest_log_path(self.log_dir)
