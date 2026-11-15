"""HTTP boundary for deadlock-api: URLs, JSON, and the disk cache.

No overlay state lives here.  Every function is safe to call from the worker
thread; nothing touches Tk or the game window.

Endpoints (all public, no API key, community-run):

* ``/v1/assets/items``   shop catalog, trimmed to the fields the picker needs
* ``/v1/assets/heroes``  hero id -> name
* ``/v1/analytics/item-stats``  item win rates, optionally per net-worth bucket
* ``/v1/analytics/hero-counter-stats``  which enemy beats this hero most
"""

import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional, Sequence

API = "https://api.deadlock-api.com"
USER_AGENT = "DeadlockWPAOverlay/2.0 (advisor)"
CACHE_TTL_ASSETS = 7 * 24 * 3600
CACHE_TTL_STATS = 6 * 3600
BUCKET_PARAM = "net_worth_by_5000"
ASSETS_TIMEOUT = 60.0
STATS_TIMEOUT = 30.0
_RETRY_UNTIL = {}


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "DeadlockWPAOverlay" / "advisor"


def http_json(url: str, timeout: float = 20.0):
    if time.time() < _RETRY_UNTIL.get(url, 0):
        raise RuntimeError("API retry delay active")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        if err.code in (429, 503, 504):
            try:
                delay = max(1, int(err.headers.get("Retry-After", "60")))
            except ValueError:
                delay = 60
            _RETRY_UNTIL[url] = time.time() + delay
        raise


def read_cache(path: Path, ttl: float):
    """Cached JSON, or ``None`` when missing, stale or unreadable."""
    try:
        if not path.exists() or (ttl and time.time() - path.stat().st_mtime > ttl):
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(path: Path, payload) -> None:
    """Atomic cache write; a cache failure must never break a scan."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".part")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, path)
    except Exception:
        pass


def fetch_assets() -> dict:
    """Trimmed catalog: shop upgrades plus the hero roster."""
    items = http_json(f"{API}/v1/assets/items?only_shopable_items=true", timeout=ASSETS_TIMEOUT)
    heroes = http_json(f"{API}/v1/assets/heroes", timeout=ASSETS_TIMEOUT)
    trimmed = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "class_name": item.get("class_name"),
            "type": item.get("type"),
            "item_slot_type": item.get("item_slot_type"),
            "item_tier": item.get("item_tier"),
            "cost": item.get("cost"),
            "image": item.get("shop_image") or item.get("image"),
            "shopable": item.get("shopable"),
            "disabled": item.get("disabled"),
            "component_items": item.get("component_items") or [],
        }
        for item in items
        if isinstance(item, dict)
    ]
    roster = [
        {"id": hero.get("id"), "name": hero.get("name")}
        for hero in heroes
        if isinstance(hero, dict) and hero.get("id") and hero.get("name")
    ]
    return {"items": trimmed, "heroes": roster}


def fetch_item_stats(
    hero_id: int,
    enemy_ids: Sequence[int] = (),
    bucket: bool = False,
    min_matches: int = 100,
) -> List[dict]:
    """Item win rates for a hero, optionally per net-worth bucket."""
    params = {"hero_id": int(hero_id), "min_matches": 1 if bucket else int(min_matches)}
    if enemy_ids:
        params["enemy_hero_ids"] = ",".join(str(e) for e in sorted({int(e) for e in enemy_ids}))
    if bucket:
        params["bucket"] = BUCKET_PARAM
    url = f"{API}/v1/analytics/item-stats?{urllib.parse.urlencode(params)}"
    rows = http_json(url, timeout=STATS_TIMEOUT)
    return rows if isinstance(rows, list) else []


def fetch_matchups(hero_id: int, min_matches: int = 200) -> List[dict]:
    """Matchup rows for one hero, reduced to enemy id, matches and win rate."""
    rows = http_json(
        f"{API}/v1/analytics/hero-counter-stats?min_matches={int(min_matches)}",
        timeout=STATS_TIMEOUT,
    )
    out: List[dict] = []
    for row in rows if isinstance(rows, list) else ():
        try:
            if int(row.get("hero_id")) != int(hero_id):
                continue
            matches = int(row.get("matches_played") or 0)
            wins = int(row.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if not matches:
            continue
        out.append(
            {
                "enemy_hero_id": int(row["enemy_hero_id"]),
                "matches": matches,
                "win_rate": wins / matches,
            }
        )
    return out


def describe_sources() -> dict:
    """Provenance block used by ``--explain`` and the API guide."""
    return {
        "api": API,
        "assets_ttl_s": CACHE_TTL_ASSETS,
        "stats_ttl_s": CACHE_TTL_STATS,
        "bucket": BUCKET_PARAM,
        "auth": "none",
        "cache": str(cache_dir()),
    }


_ACTIVE_CACHE = {}


def find_active_match(account_id: Optional[int]) -> Optional[int]:
    """Public watch-list discovery; absence is unknown, never an OCR fallback."""
    if account_id is None:
        return None
    now = time.time()
    cached = _ACTIVE_CACHE.get(int(account_id))
    if cached and now - cached[0] < 30:
        return cached[1]
    rows = http_json(f"{API}/v1/matches/active?account_ids={int(account_id)}", timeout=8)
    matches = {int(row["match_id"]) for row in rows if isinstance(row, dict) and row.get("match_id")}
    match_id = next(iter(matches)) if len(matches) == 1 else None
    _ACTIVE_CACHE[int(account_id)] = (now, match_id)
    return match_id
