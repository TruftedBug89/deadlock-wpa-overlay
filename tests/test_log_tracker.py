"""Incremental log-tailer tests.

The tracker is the only path that decides "are we in a match"; these tests pin
the offset behaviour and the end-of-match rules without needing Deadlock or
Statlocker to be running.
"""

import datetime
import os
from pathlib import Path

import pytest

import log_tracker
from log_tracker import MatchLogTracker, detect_active_hero_from_logs, latest_log_path


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(log_dir: Path, name: str = "companion-1.log") -> Path:
    path = log_dir / name
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path


def _append(path: Path, *lines: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


@pytest.fixture(autouse=True)
def _game_running(monkeypatch):
    """Pretend Deadlock is running so the snapshot does not self-reset."""
    monkeypatch.setattr(log_tracker, "is_process_running", lambda *_args, **_kwargs: True)


def test_missing_directory_returns_empty_snapshot(tmp_path):
    tracker = MatchLogTracker()
    snapshot = tracker.poll(tmp_path / "does-not-exist")
    assert snapshot.match_id is None
    assert snapshot.owned_classes == set()


def test_match_start_clock_items_and_hero(tmp_path):
    path = _write(tmp_path)
    stamp = _now()
    _append(
        path,
        f"{stamp} ingame_feed: entry match=777 clock=0",
        f"{stamp} kind=match_start entry match=777",
        f'{stamp} ingame_feed: entry match=777 clock=120 kind=item_bought '
        'actor=slot3/t2/self hero19/self item=Some("Silencer")',
        f'{stamp} ingame_feed: entry match=777 clock=121 kind=item_bought '
        'actor=slot1/t2/self item=Some("Fortitude")',
    )

    snapshot = MatchLogTracker().poll(tmp_path)

    assert snapshot.match_id == "777"
    assert snapshot.clock_s == 121
    assert snapshot.owned_classes == {"silencer", "fortitude"}
    assert snapshot.hero_id == 19
    assert snapshot.is_in_match


def test_poll_is_incremental(tmp_path):
    path = _write(tmp_path)
    stamp = _now()
    _append(
        path,
        f"{stamp} ingame_feed: entry match=888 clock=10",
        f"{stamp} kind=match_start entry match=888",
    )

    tracker = MatchLogTracker()
    first = tracker.poll(tmp_path)
    second = tracker.poll(tmp_path)  # nothing new on disk
    assert first.match_id == second.match_id == "888"
    assert tracker._offset == path.stat().st_size

    _append(
        path,
        f'{stamp} ingame_feed: entry match=888 clock=60 kind=item_bought '
        'actor=slot2/t3/self item=Some("Refresher")',
    )
    third = tracker.poll(tmp_path)
    assert third.owned_classes == {"refresher"}
    assert third.clock_s == 60


def test_sold_item_is_removed_but_remembered_as_bought(tmp_path):
    path = _write(tmp_path)
    stamp = _now()
    _append(
        path,
        f"{stamp} ingame_feed: entry match=999 clock=0",
        f"{stamp} kind=match_start entry match=999",
        f'{stamp} ingame_feed: entry match=999 clock=30 kind=item_bought '
        'actor=slot1/t2/self item=Some("Silencer")',
        f'{stamp} ingame_feed: entry match=999 clock=90 kind=item_sold '
        'actor=slot1/t2/self item=Some("Silencer")',
    )

    snapshot = MatchLogTracker().poll(tmp_path)
    assert snapshot.owned_classes == set()
    assert snapshot.all_bought == {"silencer"}


def test_match_end_resets_state(tmp_path):
    path = _write(tmp_path)
    stamp = _now()
    _append(
        path,
        f"{stamp} ingame_feed: entry match=1234 clock=0",
        f"{stamp} kind=match_start entry match=1234",
        f"{stamp} kind=match_end",
    )

    snapshot = MatchLogTracker().poll(tmp_path)
    assert snapshot.match_id is None


def test_stale_feed_is_treated_as_match_over(tmp_path):
    path = _write(tmp_path)
    old = "2020-01-01T00:00:00Z"
    _append(
        path,
        f"{old} ingame_feed: entry match=555 clock=0",
        f"{old} kind=match_start entry match=555",
    )

    snapshot = MatchLogTracker().poll(tmp_path)
    assert snapshot.match_id is None


def test_latest_log_path_picks_newest_file(tmp_path):
    first = tmp_path / "companion-old.log"
    second = tmp_path / "companion-new.log"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    os.utime(first, (1_600_000_000, 1_600_000_000))
    os.utime(second, (1_700_000_000, 1_700_000_000))

    assert latest_log_path(tmp_path) == second
    assert latest_log_path(tmp_path / "missing") is None


def test_hero_detection_reads_log_tail(tmp_path):
    path = _write(tmp_path)
    _append(
        path,
        "2026-01-01T00:00:00Z ingame_feed: entry match=1 clock=5 "
        "actor=slot0/t1/self hero42/self",
    )
    assert detect_active_hero_from_logs(tmp_path) == 42
    assert detect_active_hero_from_logs(tmp_path / "missing") is None
