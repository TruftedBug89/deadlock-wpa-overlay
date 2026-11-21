"""The opt-in report contains only coarse state, including when a game closes."""

import json

from models import GameState, WpaItem
from playtest_health import PlaytestHealth


def test_report_omits_ids_names_and_stale_reasons(tmp_path):
    path = tmp_path / "health.json"
    health = PlaytestHealth(path)
    explanation = {"connection_source": "corner", "reason": "corner match ID unreadable 123456789",
                   "account": 999999999}
    state = GameState(is_in_match=True, scan_status="ok", match_id="123456789",
                      recommended_items=[WpaItem("Private item")])
    health.record(state, "items", explanation)
    raw = path.read_text(encoding="utf-8")
    assert json.loads(raw)["shown_scans"] == 1
    assert all(value not in raw for value in ("123456789", "999999999", "Private item"))
    health.record(GameState(scan_status="idle"), "status", explanation)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["connection"] is None
    assert report["reasons"] == []
    assert report["shown_scans"] == 1
