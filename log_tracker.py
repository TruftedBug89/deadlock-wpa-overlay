"""Incremental Statlocker companion log parsing.

The companion log can grow to tens of megabytes during a long session.  Reading
it in full every poll is pure disk churn, so this tracker remembers the byte
offset and only parses newly appended lines.
"""

import datetime
import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from win32_overlay import is_process_running

_LOG_GLOB = "companion-*.log"
_CLOCK_RE = re.compile(r"clock=(\d+)")
_MATCH_START_RE = re.compile(r"entry match=(\d+)")
_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z?)")
_ITEM_RE = re.compile(r'item=Some\("([^"]+)"\)')
_TEAM_RE = re.compile(r"actor=slot\d+/t(\d+)/")
_LEAD_RE = re.compile(r"team=Some\((\d+)\)")
_HERO_RE = re.compile(r"hero(\d+)/self")
# Feed actors look like `actor=slot2/t2/hero63/enemy` (or `/ally`).
_ACTOR_HERO_RE = re.compile(r"actor=slot\d+/t\d+/hero(\d+)/(enemy|ally)")
_HERO_BUILD_RE = re.compile(r"build_id=\d+\s+hero_id=(\d+)")
_FEED_PREFIX = "ingame_feed: entry match="

_MATCH_END_MARKERS = (
    "kind=match_end",
    "match_ended",
    "game state -> PostGame",
    "game state -> End",
    "game state -> Abandoned",
    "left GameInProgress",
    "phase=PostGame",
    "phase=End",
    "phase=Abandoned",
    "match frame-rate summary stored",
    "match details: gameplay ended",
)

# If no feed event has arrived for this long and Deadlock is closed, match is over.
_INACTIVITY_LIMIT_S = 1800.0


@dataclass
class LogSnapshot:
    """Parsed match state from the companion log."""

    match_id: Optional[str] = None
    owned_classes: Set[str] = field(default_factory=set)
    all_bought: Set[str] = field(default_factory=set)
    clock_s: float = 0.0
    is_behind: bool = False
    hero_id: Optional[int] = None
    enemy_hero_ids: Set[int] = field(default_factory=set)
    last_event: Optional[datetime.datetime] = None

    @property
    def is_in_match(self) -> bool:
        return self.match_id is not None


def latest_log_path(log_dir: Path) -> Optional[Path]:
    """Newest ``companion-*.log`` in ``log_dir`` (or ``None``)."""
    if not log_dir or not log_dir.exists():
        return None
    try:
        candidates = glob.glob(str(log_dir / _LOG_GLOB))
    except OSError:
        return None
    if not candidates:
        return None
    try:
        return Path(max(candidates, key=os.path.getmtime))
    except OSError:
        return None


def get_latest_log_path(log_dir: Path) -> Optional[Path]:
    """Backwards-compatible alias used by the data source."""
    return latest_log_path(log_dir)


class MatchLogTracker:
    """Stateful, offset-based tailer for the newest companion log."""

    def __init__(self) -> None:
        self._path: Optional[Path] = None
        self._offset: int = 0
        self._match_id: Optional[str] = None
        self._clock_s: float = 0.0
        self._bought: Set[str] = set()
        self._sold: Set[str] = set()
        self._kills: int = 0
        self._deaths: int = 0
        self._friendly_team: Optional[int] = None
        self._enemy_lead: bool = False
        self._last_event: Optional[datetime.datetime] = None
        self._hero_id: Optional[int] = None
        self._enemy_heroes: Set[int] = set()
        self._ally_heroes: Set[int] = set()

    def reset(self) -> None:
        """Forget all parsed state (new log file or new process)."""
        self.__init__()

    def _reset_match(self) -> None:
        self._match_id = None
        self._clock_s = 0.0
        self._bought.clear()
        self._sold.clear()
        self._kills = 0
        self._deaths = 0
        self._enemy_lead = False
        self._enemy_heroes.clear()
        self._ally_heroes.clear()

    def poll(self, log_dir: Path) -> LogSnapshot:
        """Read new log lines and return the current match snapshot."""
        path = latest_log_path(log_dir)
        if path is None:
            self.reset()
            return LogSnapshot()

        if path != self._path:
            self.reset()
            self._path = path

        try:
            size = path.stat().st_size
        except OSError:
            return self._snapshot()
        if size < self._offset:
            self._offset = 0
            self._reset_match()

        if size > self._offset:
            try:
                with open(path, "rb") as handle:
                    handle.seek(self._offset)
                    chunk = handle.read()
                self._offset += len(chunk)
                self._consume(chunk.decode("utf-8", errors="ignore"))
            except OSError:
                pass

        return self._snapshot()

    def _consume(self, text: str) -> None:
        for line in text.splitlines():
            self._parse_line(line)

    @staticmethod
    def _parse_timestamp(line: str) -> Optional[datetime.datetime]:
        match = _TIMESTAMP_RE.match(line)
        if not match:
            return None
        try:
            value = datetime.datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value

    def _parse_line(self, line: str) -> None:
        if _FEED_PREFIX in line:
            timestamp = self._parse_timestamp(line)
            if timestamp is not None:
                self._last_event = timestamp

        if "kind=match_start" in line:
            match = _MATCH_START_RE.search(line)
            if match:
                self._reset_match()
                self._match_id = match.group(1)
                return

        if any(marker in line for marker in _MATCH_END_MARKERS):
            self._reset_match()
            return

        entry_match = _MATCH_START_RE.search(line)
        if entry_match:
            curr_match = entry_match.group(1)
            if self._match_id != curr_match:
                if self._match_id is not None:
                    self._reset_match()
                self._match_id = curr_match

        clock = _CLOCK_RE.search(line)
        if clock:
            self._clock_s = float(clock.group(1))

        # Enemy/ally hero picks arrive on feed lines that never mention /self,
        # so this has to run before the actor filter below.
        for actor in _ACTOR_HERO_RE.finditer(line):
            hero = int(actor.group(1))
            if actor.group(2) == "enemy":
                self._enemy_heroes.add(hero)
            else:
                self._ally_heroes.add(hero)

        if "/self" not in line:
            return

        team = _TEAM_RE.search(line)
        if team:
            self._friendly_team = int(team.group(1))

        if "kind=item_bought" in line:
            item = _ITEM_RE.search(line)
            if item:
                self._bought.add(item.group(1).lower())
        elif "kind=item_sold" in line:
            item = _ITEM_RE.search(line)
            if item:
                self._sold.add(item.group(1).lower())
        elif "kind=kill" in line:
            for token in line.split():
                if token.startswith("actor=") and "/self" in token:
                    self._kills += 1
                elif token.startswith("target=") and "/self" in token:
                    self._deaths += 1

        hero = _HERO_RE.search(line)
        if hero:
            self._hero_id = int(hero.group(1))
        else:
            build = _HERO_BUILD_RE.search(line)
            if build:
                self._hero_id = int(build.group(1))

        lead = _LEAD_RE.search(line)
        if lead and self._friendly_team is not None:
            self._enemy_lead = int(lead.group(1)) != self._friendly_team

    def _snapshot(self) -> LogSnapshot:
        match_id = self._match_id
        if match_id and not is_process_running("deadlock.exe"):
            self._reset_match()
            match_id = None
        if match_id and self._last_event is not None:
            now = datetime.datetime.now(datetime.timezone.utc)
            if (now - self._last_event).total_seconds() > _INACTIVITY_LIMIT_S:
                self._reset_match()
                match_id = None

        if match_id is None:
            return LogSnapshot(hero_id=self._hero_id)

        return LogSnapshot(
            match_id=match_id,
            owned_classes=set(self._bought - self._sold),
            all_bought=set(self._bought),
            clock_s=self._clock_s,
            is_behind=(self._deaths > self._kills) or self._enemy_lead,
            hero_id=self._hero_id,
            enemy_hero_ids=set(self._enemy_heroes),
            last_event=self._last_event,
        )


_TRACKERS: Dict[str, MatchLogTracker] = {}


def parse_match_logs(log_dir: Path) -> Tuple[Optional[str], Set[str], Set[str], float, bool]:
    """Backwards-compatible one-shot API backed by a per-directory tracker."""
    key = str(log_dir)
    tracker = _TRACKERS.get(key)
    if tracker is None:
        tracker = MatchLogTracker()
        _TRACKERS[key] = tracker
    snapshot = tracker.poll(log_dir)
    return (
        snapshot.match_id,
        snapshot.owned_classes,
        snapshot.all_bought,
        snapshot.clock_s,
        snapshot.is_behind,
    )


def detect_active_hero_from_logs(log_dir: Path) -> Optional[int]:
    """Best-effort hero detection from the newest log's tail."""
    path = latest_log_path(log_dir)
    if path is None:
        return None
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - 64_000))
            tail = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        hero = _HERO_RE.search(line)
        if hero:
            return int(hero.group(1))
        build = _HERO_BUILD_RE.search(line)
        if build:
            return int(build.group(1))
    return None
