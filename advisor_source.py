"""Statlocker-free recommendations from deadlock-api.com.

No database or companion app. Optional OCR reads only the match ID:

* ``/v1/assets/items`` + ``/v1/assets/heroes`` give the catalog (cached 7 days);
* ``/v1/analytics/item-stats`` ranks the hero's items by win rate *in the
  net-worth bracket the player is actually in* (``bucket`` + merge);
* ``/v1/analytics/hero-counter-stats`` names the enemy this hero struggles
  against most, and ``item-stats`` filtered by the enemy lineup ranks counters;
* the live broadcast (``live_match.py``) supplies souls, unspent gold, team
  soul lead, hero damage and the owned item vector.

The hero comes from the live match, ``--hero`` / ``hero_id`` (F6 cycles it).
Everything is cached under ``%LOCALAPPDATA%\\DeadlockWPAOverlay\\advisor``.
"""

import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from advisor_api import (  # re-exported for callers and the lifecycle sim
    API,
    BUCKET_PARAM,
    CACHE_TTL_ASSETS,
    CACHE_TTL_STATS,
    cache_dir,
    fetch_assets,
    fetch_item_stats,
    fetch_matchups,
    read_cache,
    write_cache,
)
from advisor_live import AdvisorLiveMixin
from advisor_build import AdvisorBuildMixin, BUILD_NOTE, threat_summary
from item_inventory import component_graph, apply_inventory
from advisor_evidence import prepare_candidates, select_threat
from item_economy import stage_for_souls, stage_target_cost
from item_stats import (  # re-exported for tests and callers
    MIN_MATCHES,
    bucket_floor,
    merge_buckets,
    rank_items,
    smoothed_win_rate,
)
from match_context import MatchContext, build_context
from models import CounterItem, GameState, WpaItem
from recommendation_queue import RecommendationQueue

SLOT_MAP = {"weapon": "weapon", "vitality": "vitality", "spirit": "spirit", "tech": "spirit"}


class AdvisorDataSource(AdvisorLiveMixin, AdvisorBuildMixin):
    """Same ``get_game_state`` contract as StatlockerDataSource."""

    is_advisor = True
    supports_preview_clear = False

    def __init__(
        self,
        hero_id: Optional[int] = None,
        enemy_ids: Optional[Sequence[int]] = None,
        *,
        assets_fetcher: Optional[Callable] = None,
        stats_fetcher: Optional[Callable] = None,
        matchup_fetcher: Optional[Callable] = None,
        cache_path: Optional[Path] = None,
        match_id: Optional[int] = None,
        account_id: Optional[int] = None,
        require_match: bool = False,
        read_match_id: bool = False,
        live_fetcher: Optional[Callable] = None,
        preview_souls: Optional[int] = None,
    ):
        self.manual_hero_id = int(hero_id) if hero_id else None
        self.manual_enemy_heroes: List[int] = [int(e) for e in (enemy_ids or [])]
        self.preview_souls = int(preview_souls) if preview_souls else 0
        self.match_id = int(match_id) if match_id else None
        self.account_id = int(account_id) if account_id else None
        self.require_match = bool(require_match)
        self.read_match_id = bool(read_match_id)
        self._live_fetcher = live_fetcher
        # Last known ownership for the current match only. A tick without the
        # vector keeps this set; a new match id or an idle state wipes it.
        self._owned_match_id: Optional[int] = None
        self._owned_player: Optional[tuple] = None
        self._owned_ids: set = set()
        self._assets_fetcher = assets_fetcher or fetch_assets
        self._stats_fetcher = stats_fetcher or fetch_item_stats
        self._matchup_fetcher = matchup_fetcher or fetch_matchups
        self._cache = Path(cache_path) if cache_path else cache_dir()
        self._items: Dict[int, dict] = {}
        self._heroes: Dict[int, str] = {}
        self._assets_error: Optional[str] = None
        self._loaded = False
        self._assets_loaded_at = 0.0
        self._requests = []
        self._stats_errors = {}
        # Populated by every successful scan; ``--explain`` prints it verbatim.
        self.last_explanation: dict = {}
        self._item_queue = RecommendationQueue()
        self._counter_queue = RecommendationQueue()
        self._plan_queue = RecommendationQueue()

    # ---------------------------------------------------------------- assets
    def _ensure_assets(self) -> bool:
        if self._loaded and time.time() - self._assets_loaded_at < CACHE_TTL_ASSETS:
            return bool(self._items)
        self._items.clear()
        self._heroes.clear()
        self._loaded = False
        payload = read_cache(self._cache / "assets.json", CACHE_TTL_ASSETS)
        if (payload is not None and self._assets_fetcher is fetch_assets
                and any("component_items" not in i for i in payload.get("items", []))):
            payload = None
        if payload is None:
            try:
                payload = self._assets_fetcher()
                write_cache(self._cache / "assets.json", payload)
            except Exception as err:
                self._assets_error = f"assets unavailable: {type(err).__name__}"
                return False
        for item in payload.get("items") or ():
            try:
                item_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if item.get("type") != "upgrade" or item.get("disabled") or item.get("shopable") is False:
                continue
            self._items[item_id] = item
        for hero in payload.get("heroes") or ():
            self._heroes[int(hero["id"])] = str(hero["name"])
        self._loaded = True
        path = self._cache / "assets.json"
        self._assets_loaded_at = path.stat().st_mtime if path.exists() else time.time()
        return bool(self._items)

    def hero_name(self, hero_id: Optional[int]) -> str:
        return self._heroes.get(int(hero_id), "Unknown") if hero_id else "Unknown"

    def _meta(self, item_id: int) -> Optional[dict]:
        """Catalog metadata in the shape the picker expects."""
        item = self._items.get(int(item_id))
        if (not item or not item.get("name") or
                str(item.get("item_slot_type") or "").lower() not in SLOT_MAP):
            return None
        return {
            "id": int(item_id),
            "name": item["name"],
            "category": SLOT_MAP.get(str(item.get("item_slot_type") or "").lower(), ""),
            "cost": item.get("cost"),
            "item_tier": item.get("item_tier"),
            "image": item.get("image"),
            "class_name": item.get("class_name"),
        }

    def _owned_categories(self) -> Dict[int, str]:
        return {
            item_id: meta["category"]
            for item_id in self._items
            for meta in [self._meta(item_id)]
            if meta is not None
        }

    # ----------------------------------------------------------------- data
    def _stats(self, hero_id: int, enemy_ids: Sequence[int], bucket: bool = False) -> List[dict]:
        enemy_ids = sorted(set(enemy_ids))
        suffix = "b" if bucket else "vs" if enemy_ids else "all"
        key = "stats_%s_hero%d_vs%s.json" % (
            suffix,
            hero_id,
            "-".join(str(e) for e in enemy_ids) or "all",
        )
        key = "v3_" + key
        cached = read_cache(self._cache / key, CACHE_TTL_STATS)
        request = {"endpoint": "/v1/analytics/item-stats", "hero_id": hero_id,
                   "enemy_hero_ids": list(enemy_ids), "bucket": BUCKET_PARAM if bucket else None,
                   "min_matches": 1 if bucket else MIN_MATCHES, "cached": cached is not None}
        self._requests.append(request)
        if cached is not None:
            request["fetched_at"] = (self._cache / key).stat().st_mtime
            return cached
        if time.time() < self._stats_errors.get(key, 0):
            raise RuntimeError("Analytics unavailable during retry delay")
        try:
            try:
                rows = self._stats_fetcher(hero_id, list(enemy_ids), bucket)
            except TypeError:
                # Injected fetchers keep the two-argument contract.
                rows = self._stats_fetcher(hero_id, list(enemy_ids))
        except Exception:
            self._stats_errors[key] = time.time() + 60
            raise
        request["fetched_at"] = time.time()
        if isinstance(rows, list):
            write_cache(self._cache / key, rows)
        return rows if isinstance(rows, list) else []

    def _matchups(self, hero_id: int) -> List[dict]:
        cached = read_cache(self._cache / f"matchups_hero{hero_id}.json", CACHE_TTL_STATS)
        if cached is not None:
            return cached
        key = f"matchups_{hero_id}"
        if time.time() < self._stats_errors.get(key, 0):
            return []
        try:
            rows = self._matchup_fetcher(hero_id)
        except Exception:
            self._stats_errors[key] = time.time() + 60
            return []
        write_cache(self._cache / f"matchups_hero{hero_id}.json", rows)
        return rows if isinstance(rows, list) else []

    # ---------------------------------------------------------------- state
    def cycle_next_hero(self) -> None:
        if not self._ensure_assets() or not self._heroes:
            return
        ids = sorted(self._heroes)
        current = self.manual_hero_id
        self.manual_hero_id = ids[(ids.index(current) + 1) % len(ids)] if current in ids else ids[0]

    def latest_log_path(self):
        return None

    def get_game_state(self, max_items: int = 5, queue_seconds: float = 150, **_kwargs) -> GameState:
        state = self._get_game_state(max_items, queue_seconds)
        if state.scan_status != "ok":
            self._item_queue.clear()
            self._counter_queue.clear()
            self._plan_queue.clear()
        return state

    def _get_game_state(self, max_items: int, queue_seconds: float) -> GameState:
        started = time.time()
        self._requests = []
        self.last_explanation = {"status": "unknown"}
        live = self._live_state()
        if live is None and self.require_match:
            status = getattr(self, "_live_status", "idle")
            reason = getattr(self, "_live_reason", "no confirmed live match")
            self.last_explanation = {"status": status, "reason": reason}
            return GameState(scan_status=status, source="advisor", is_in_match=False,
                             last_error=reason, generated_at=started)
        if not self._ensure_assets():
            reason = self._assets_error or "catalog unavailable"
            self.last_explanation = {"status": "error", "reason": reason}
            return GameState(scan_status="error", source="advisor", last_error=reason,
                             generated_at=started)
        context = live["context"] if live else MatchContext()
        hero_id = (live or {}).get("hero_id") or self.manual_hero_id
        if hero_id is None:
            return GameState(scan_status="needs_hero", source="advisor", generated_at=started)
        hero_name = self.hero_name(hero_id)
        enemies = list(context.enemy_ids if live else self.manual_enemy_heroes)
        souls = int(context.souls if live else self.preview_souls or 0)
        target_cost = context.target_cost or stage_target_cost(souls)
        owned_ids = sorted(
            self._known_owned(context, (live or {}).get("match_id"), (live or {}).get("owner"))
        )

        if live and (context.bank is None or not context.ownership_known or souls <= 0
                     or any(self._meta(i) is None for i in owned_ids)):
            self.last_explanation = {"status": "unknown", "reason": "live budget, inventory, catalog ownership or souls unknown",
                                     "context": context.to_dict()}
            return GameState(hero_id=hero_id, hero_name=hero_name, is_in_match=True,
                             source="advisor", scan_status="unknown", generated_at=started)
        targets, strongest, strongest_rate = select_threat(self, hero_id, enemies, context) if enemies else ([], "", None)
        try:
            candidates, audit, basis = prepare_candidates(self, hero_id, targets, souls)
            candidates = apply_inventory(candidates, owned_ids, component_graph(self._items))
        except Exception as err:
            self.last_explanation = {"status": "error", "reason": type(err).__name__}
            return GameState(hero_id=hero_id, hero_name=hero_name, scan_status="error",
                             source="advisor", last_error=type(err).__name__, generated_at=started)
        baseline = candidates[0].evidence["general_pool_baseline"] if candidates and basis != "mixed" else None
        advice = self._make_advice(candidates, context, live, hero_id, souls, target_cost,
                                   baseline, owned_ids, max_items, queue_seconds)
        items, counters = advice.items, advice.counters
        if live and time.time() >= live["valid_until"]:
            self.last_explanation = {"status": "unknown", "reason": "snapshot expired during analytics refresh"}
            return GameState(source="advisor", scan_status="unknown", generated_at=started)
        self.last_explanation = {
            "status": "ok",
            "source": "deadlock-api.com",
            "assets_fetched_at": self._assets_loaded_at,
            "live_tick": live["tick"] if live else None,
            "valid_until": live["valid_until"] if live else None,
            "hero": {"id": hero_id, "name": hero_name},
            "basis": basis,
            "baseline_win_rate": baseline,
            "context": context.to_dict(),
            "items": [scored.to_dict() for scored in advice.ranked],
            "build_plan": [scored.to_dict() for scored in advice.plan],
            "plan_queue": self._plan_queue.explanation if live else {"action": "preview"},
            "build_note": BUILD_NOTE,
            "threat_summary": threat_summary(context, self.hero_name),
            "connection_source": (live or {}).get("connection_source", "unknown"),
            "candidate_evidence": audit,
            "queue": self._item_queue.explanation if live else {"action": "preview"},
            "counter_queue": self._counter_queue.explanation if live else {"action": "preview"},
            "requests": self._requests,
            "preview": not bool(live),
            "target_enemy_ids": targets,
            "counters": [entry.__dict__ for entry in counters],
            "generated_at": started,
        }
        return GameState(
            match_id=str(live["match_id"]) if live else None,
            hero_id=hero_id,
            hero_name=hero_name,
            recommended_items=items,
            build_plan=[self._to_wpa(entry) for entry in advice.plan],
            threat_summary=threat_summary(context, self.hero_name),
            build_note=BUILD_NOTE,
            detected_slots=len(items),
            matched_slots=len(items),
            counter_items=counters,
            counter_source="remote" if counters else "none",
            enemy_heroes=[self.hero_name(e) for e in enemies],
            strongest_enemy=strongest,
            strongest_enemy_winrate=strongest_rate,
            net_worth=souls,
            stage=stage_for_souls(souls),
            stance=context.stance,
            soul_lead=context.soul_lead,
            team_souls=context.team_souls,
            enemy_souls=context.enemy_souls,
            buy_budget=context.buy_budget,
            valid_until=live["valid_until"] if live else None,
            known_owned_items=len([i for i in owned_ids if i in self._items]),
            owned_items={
                str(self._items[item_id].get("name"))
                for item_id in owned_ids
                if item_id in self._items and self._items[item_id].get("name")
            },
            next_buy=advice.next_buy,
            build_candidates=advice.choices,
            is_in_match=bool(live) if self.require_match else True,
            source="advisor",
            scan_status="ok",
            generated_at=started,
        )
