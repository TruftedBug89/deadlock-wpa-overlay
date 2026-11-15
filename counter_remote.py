"""Counter data from deadlock-api.com (no database involved).

* ``hero-counter-stats`` names the enemy this hero struggles against most;
* ``item-stats`` ranks build items by win rate in that matchup.

MIT licensed, community-run, not endorsed by Valve.  No API key is sent; the
unauthenticated limit is 200 requests/minute and this module fires at most one
request per hero/matchup, from a single daemon thread, never from the UI.

Responses are cached under ``%LOCALAPPDATA%\\DeadlockWPAOverlay\\counters``.
A 503/504 with ``Retry-After`` sets a cooldown and retries later.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

API_URL = "https://api.deadlock-api.com/v1/analytics/item-stats"
MATCHUP_URL = "https://api.deadlock-api.com/v1/analytics/hero-counter-stats"
API_MIN_MATCHES = 50
MATCHUP_MIN_MATCHES = 200
MATCHUP_TTL_S = 6 * 3600
CACHE_TTL_S = 24 * 3600
RETRY_AFTER_FALLBACK_S = 60
REQUEST_TIMEOUT_S = 6.0
_USER_AGENT = "DeadlockWPAOverlay/2.0 (local overlay; counter fallback)"


class RateLimited(Exception):
    """503/504 from the API; ``wait_s`` comes from the Retry-After header."""

    def __init__(self, wait_s: float):
        super().__init__(f"rate limited for {wait_s:.0f}s")
        self.wait_s = max(1.0, float(wait_s))


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "DeadlockWPAOverlay" / "counters"


def _cache_path(hero_id: int, tag: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(tag or "unknown"))
    return cache_dir() / f"hero{int(hero_id)}_{safe}.json"


def load_cache(hero_id: int, tag: str, max_age_s: float = CACHE_TTL_S) -> Optional[List[dict]]:
    """Rows cached for this hero + patch tag, or ``None`` when unusable."""
    path = _cache_path(hero_id, tag)
    try:
        if not path.exists():
            return None
        if max_age_s and (time.time() - path.stat().st_mtime) > max_age_s:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    rows = payload.get("rows") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else None


def save_cache(hero_id: int, tag: str, rows: Sequence[dict]) -> None:
    path = _cache_path(hero_id, tag)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".part")
        temp.write_text(
            json.dumps({"tag": str(tag), "fetched_at": int(time.time()), "rows": list(rows)}),
            encoding="utf-8",
        )
        os.replace(temp, path)
    except Exception:
        pass


def _retry_after(headers) -> float:
    try:
        value = float((headers or {}).get("Retry-After") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else RETRY_AFTER_FALLBACK_S


def fetch_item_stats(hero_id: int, enemy_ids: Sequence[int]) -> List[dict]:
    """Raw API rows for one hero against the given enemies.

    The response is filtered to the hero's build locally; the API's own
    ``include_item_ids`` filter silently returns nothing for long lists.
    Raises :class:`RateLimited` on 503/504 so the caller can back off quietly.
    """
    params = urllib.parse.urlencode(
        {
            "hero_id": int(hero_id),
            "enemy_hero_ids": ",".join(str(int(e)) for e in enemy_ids),
            "min_matches": API_MIN_MATCHES,
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}", headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as err:
        if err.code in (503, 504):
            raise RateLimited(_retry_after(getattr(err, "headers", None)))
        raise
    return payload if isinstance(payload, list) else []


def normalize_rows(payload: Sequence[dict], enemy_ids: Sequence[int]) -> List[dict]:
    """API rows -> the ``vs``/``n`` shape the local ranker already speaks."""
    enemies = [str(int(e)) for e in enemy_ids]
    rows: List[dict] = []
    for entry in payload or ():
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        try:
            matches = int(entry.get("matches") or 0)
            wins = int(entry.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if item_id is None or matches < API_MIN_MATCHES:
            continue
        score = wins / matches if matches else 0.0
        rows.append(
            {
                "item": "",
                "item_id": item_id,
                "vs": {enemy: score for enemy in enemies},
                "n": {enemy: matches for enemy in enemies},
            }
        )
    return rows


def _matchup_cache_path(hero_id: int) -> Path:
    return cache_dir() / f"matchups_hero{int(hero_id)}.json"


def load_matchup_cache(hero_id: int, max_age_s: float = MATCHUP_TTL_S) -> Optional[List[dict]]:
    path = _matchup_cache_path(hero_id)
    try:
        if not path.exists():
            return None
        if max_age_s and (time.time() - path.stat().st_mtime) > max_age_s:
            return None
        rows = json.loads(path.read_text(encoding="utf-8")).get("rows")
    except Exception:
        return None
    return rows if isinstance(rows, list) else None


def save_matchup_cache(hero_id: int, rows: Sequence[dict]) -> None:
    try:
        path = _matchup_cache_path(hero_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".part")
        temp.write_text(json.dumps({"rows": list(rows)}), encoding="utf-8")
        os.replace(temp, path)
    except Exception:
        pass


def fetch_hero_matchups(
    hero_id: int,
    enemy_ids: Sequence[int] = (),
    min_matches: int = MATCHUP_MIN_MATCHES,
) -> List[dict]:
    """Our hero's win rate vs each enemy hero (who actually counters us)."""
    params = urllib.parse.urlencode({"min_matches": int(min_matches)})
    request = urllib.request.Request(
        f"{MATCHUP_URL}?{params}",
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as err:
        if err.code in (503, 504):
            raise RateLimited(_retry_after(getattr(err, "headers", None)))
        raise
    wanted = {int(e) for e in enemy_ids}
    rows: List[dict] = []
    for entry in payload if isinstance(payload, list) else ():
        try:
            if int(entry.get("hero_id")) != int(hero_id):
                continue
            enemy_id = int(entry.get("enemy_hero_id"))
            matches = int(entry.get("matches_played") or 0)
            wins = int(entry.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if wanted and enemy_id not in wanted:
            continue
        if matches < min_matches:
            continue
        rows.append(
            {
                "hero_id": int(hero_id),
                "enemy_hero_id": enemy_id,
                "matches": matches,
                "win_rate": wins / matches if matches else 0.0,
            }
        )
    return rows


class RemoteCounters:
    """Single-flight, cached, never-blocking access to the free API."""

    def __init__(
        self,
        fetcher: Optional[Callable] = None,
        matchup_fetcher: Optional[Callable] = None,
    ):
        self._fetcher = fetcher or fetch_item_stats
        self._matchup_fetcher = matchup_fetcher or fetch_hero_matchups
        self._lock = threading.Lock()
        self._rows: Dict[int, List[dict]] = {}
        self._matchups: Dict[int, List[dict]] = {}
        self._inflight: set = set()
        self._attempted: set = set()
        self._cooldown_until = 0.0

    # ------------------------------------------------------------- read side
    def peek(self, hero_id: int, tag: str = "live") -> Optional[List[dict]]:
        """Rows already fetched/primed for this hero + matchup tag."""
        with self._lock:
            return self._rows.get((int(hero_id), str(tag)))

    def prime(self, hero_id: int, tag: str) -> bool:
        """Load this hero's tag-scoped cache without any network call."""
        cached = load_cache(int(hero_id), tag)
        if cached is None:
            return False
        with self._lock:
            self._rows[(int(hero_id), str(tag))] = cached
        return True

    # ------------------------------------------------------------ fetch side
    def peek_matchups(self, hero_id: int) -> Optional[List[dict]]:
        """Hero matchup rows already fetched/primed (never triggers I/O)."""
        with self._lock:
            return self._matchups.get(int(hero_id))

    def prime_matchups(self, hero_id: int) -> bool:
        cached = load_matchup_cache(int(hero_id))
        if cached is None:
            return False
        with self._lock:
            self._matchups[int(hero_id)] = cached
        return True

    def request_matchups(self, hero_id: int) -> bool:
        """Queue one background matchup fetch for this hero."""
        hero_id = int(hero_id)
        key = (hero_id, "matchups")
        with self._lock:
            if hero_id in self._matchups or key in self._inflight:
                return False
            if key in self._attempted or time.time() < self._cooldown_until:
                return False
            self._attempted.add(key)
            self._inflight.add(key)
        threading.Thread(
            target=self._run_matchups, args=(hero_id,), name="CounterMatchupFetch", daemon=True
        ).start()
        return True

    def _run_matchups(self, hero_id: int) -> None:
        rows: List[dict] = []
        try:
            rows = list(self._matchup_fetcher(hero_id) or [])
        except RateLimited as err:
            with self._lock:
                self._cooldown_until = time.time() + err.wait_s
        except Exception:
            rows = []
        finally:
            with self._lock:
                self._inflight.discard((hero_id, "matchups"))
                if rows:
                    self._matchups[hero_id] = rows
                else:
                    self._attempted.discard((hero_id, "matchups"))
                    self._cooldown_until = max(self._cooldown_until, time.time() + RETRY_AFTER_FALLBACK_S)
        if rows:
            save_matchup_cache(hero_id, rows)

    def request(self, hero_id: int, enemy_ids: Sequence[int], tag: str) -> bool:
        """Queue one background fetch; returns True when a thread was started."""
        hero_id = int(hero_id)
        key = (hero_id, str(tag))
        with self._lock:
            if key in self._rows or key in self._inflight:
                return False
            if key in self._attempted or time.time() < self._cooldown_until:
                return False
            self._attempted.add(key)
            self._inflight.add(key)
        threading.Thread(
            target=self._run,
            args=(hero_id, [int(e) for e in enemy_ids], str(tag)),
            name="CounterApiFetch",
            daemon=True,
        ).start()
        return True

    def _run(self, hero_id: int, enemy_ids: List[int], tag: str) -> None:
        rows: List[dict] = []
        try:
            payload = self._fetcher(hero_id, enemy_ids) or []
            rows = normalize_rows(payload, enemy_ids)
        except RateLimited as err:
            with self._lock:
                self._cooldown_until = time.time() + err.wait_s
        except Exception:
            rows = []
        finally:
            key = (hero_id, str(tag))
            with self._lock:
                self._inflight.discard(key)
                if rows:
                    self._rows[key] = rows
                else:
                    self._attempted.discard(key)
                    self._cooldown_until = max(self._cooldown_until, time.time() + RETRY_AFTER_FALLBACK_S)
        if rows:
            save_cache(hero_id, tag, rows)
