"""Build-bound counter picks for the Statlocker source.

These methods only read attributes owned by ``StatlockerDataSource`` (catalog,
remote counter cache and the hero build body), so they live in a mixin to keep
the state assembler below the file-size ceiling.
"""

import json
import sqlite3
from typing import List, Optional, Sequence

from build_counters import build_pool, rank_pool_items, strongest_enemy
from counter_remote import fetch_hero_matchups, fetch_item_stats, normalize_rows
from item_categories import normalize_category
from models import CounterItem


class CounterMixin:
    COUNTER_LIMIT = 3

    def _build_body(self, conn, hero_id) -> Optional[dict]:
        """Parsed ``builds_page_<hero>`` body (the hero's current build)."""
        if conn is None or hero_id is None:
            return None
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (f"builds_page_{int(hero_id)}",)
            ).fetchone()
            if not row or not row[0]:
                return None
            body = (json.loads(row[0]) or {}).get("body")
            return body if isinstance(body, dict) else None
        except Exception:
            return None

    def _counter_item(self, entry: dict) -> Optional[CounterItem]:
        """Resolve one ranked build item into a renderable counter."""
        catalog = self._catalog_items.get((entry.get("name") or "").lower(), {})
        item_id = entry.get("item_id")
        if not catalog and item_id is not None:
            try:
                catalog = self._catalog_items_by_id.get(int(item_id), {})
            except (TypeError, ValueError):
                catalog = {}
        name = entry.get("name") or catalog.get("name")
        if not name:
            return None
        enemy_id = entry.get("enemy_id")
        raw_slot = (
            catalog.get("item_slot_type")
            or catalog.get("slot_type")
            or catalog.get("slotType")
            or catalog.get("category")
            or entry.get("slot_type")
            or ""
        )
        return CounterItem(
            name=name,
            category=normalize_category(raw_slot),
            score=float(entry.get("win_rate") or 0.0),
            samples=int(entry.get("samples") or 0),
            enemy_id=int(enemy_id) if enemy_id is not None else None,
            enemy_name=self._heroes_map.get(int(enemy_id), "") if enemy_id is not None else "",
            image_url=catalog.get("image") or catalog.get("shop_image") or catalog.get("icon"),
            class_name=catalog.get("class_name") or entry.get("class_name"),
        )

    def _counter_items(
        self,
        conn: Optional[sqlite3.Connection],
        hero_id: Optional[int],
        enemy_ids: Sequence[int],
        owned: Sequence[str] = (),
        threat_id: Optional[int] = None,
    ):
        """Counter picks from the hero's build, aimed at the strongest enemy."""
        self._last_threat = None
        if hero_id is None:
            return [], "none"
        pool = build_pool(self._build_body(conn, hero_id) or {})
        if not pool or not enemy_ids:
            # A "counter" claim needs a concrete enemy team; never guess one.
            return [], "none"

        if threat_id is not None:
            # Live match data named the fed enemy; skip the historical matchup.
            threat = {"enemy_id": int(threat_id), "win_rate": None, "matches": 0}
        else:
            matchups = self._remote_counters.peek_matchups(hero_id)
            if matchups is None:
                self._remote_counters.prime_matchups(hero_id)
                matchups = self._remote_counters.peek_matchups(hero_id)
            if matchups is None:
                self._remote_counters.request_matchups(hero_id)
                return [], "none"
            threat = strongest_enemy(matchups, hero_id, enemy_ids)
            if threat is None:
                return [], "none"
        self._last_threat = threat

        ids = sorted({int(e) for e in enemy_ids})
        tag = "vs-" + "-".join(str(e) for e in ids) if ids else "all"
        rows = self._remote_counters.peek(hero_id, tag)
        if rows is None:
            self._remote_counters.prime(hero_id, tag)
            rows = self._remote_counters.peek(hero_id, tag)
        if rows is None:
            self._remote_counters.request(hero_id, [threat["enemy_id"]], tag)
            return [], "none"

        ranked = rank_pool_items(pool, rows, limit=self.COUNTER_LIMIT + 2, exclude=owned)
        items = []
        for entry in ranked:
            item = self._counter_item(dict(entry, enemy_id=threat["enemy_id"]))
            if item is not None:
                items.append(item)
        return items[: self.COUNTER_LIMIT], ("remote" if items else "none")

    def counter_report(self, hero_id: int, enemy_ids: Optional[List[int]] = None, limit: int = 3) -> dict:
        """Headless evidence: build pool, strongest enemy and counter picks."""
        self.load_catalog()
        conn = self.open_connection()
        if conn is None:
            return {"hero_id": hero_id, "status": "no_database", "items": []}
        try:
            chosen = [int(e) for e in (enemy_ids or [])]
            pool = build_pool(self._build_body(conn, hero_id) or {})
            matchups = fetch_hero_matchups(hero_id, chosen)
            threat = strongest_enemy(matchups, hero_id, chosen)
            if threat is None:
                return {"hero_id": hero_id, "status": "no_matchup_data", "items": []}
            payload = fetch_item_stats(hero_id, [threat["enemy_id"]])
            rows = normalize_rows(payload, [threat["enemy_id"]])
            picks = rank_pool_items(pool, rows, limit=limit + 2)
            items = [self._counter_item(dict(pick, enemy_id=threat["enemy_id"])) for pick in picks]
            items = [item for item in items if item is not None][:limit]
            return {
                "hero_id": hero_id,
                "hero_name": self._heroes_map.get(int(hero_id), ""),
                "status": "ok",
                "build_items": len(pool),
                "strongest_enemy": self._heroes_map.get(int(threat["enemy_id"]), str(threat["enemy_id"])),
                "strongest_enemy_winrate_pct": round(threat["win_rate"] * 100, 1),
                "source": "remote",
                "items": [
                    {
                        "name": item.name,
                        "win_rate_pct": round(item.score * 100, 1),
                        "samples": item.samples,
                        "enemy": item.enemy_name or item.enemy_id,
                    }
                    for item in items
                ],
            }
        except Exception as err:
            return {"hero_id": hero_id, "status": "api_error", "error": str(err)[:160], "items": []}
        finally:
            conn.close()
