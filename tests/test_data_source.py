"""StatlockerDataSource tests: truth policy, categories and fallbacks.

The live screen is mocked, so these tests describe *contracts* rather than the
host's currently installed Statlocker build:

* items only ever come from the cards the screen reader resolved;
* the database is metadata plus an explicit opt-in fallback, never a silent
  replacement for a failed screen read;
* missing percentages/timings stay ``None``.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from card_detector import CardBox
from data_source import StatlockerDataSource
from live_screen_reader import CardRead, ScreenReadResult
from log_tracker import LogSnapshot
from models import WpaItem


class _DummyConnection:
    """Stands in for a sqlite3 connection without touching a real database."""

    def close(self) -> None:
        pass


def _card(name: str, index: int = 0, score: float = 0.94) -> CardRead:
    return CardRead(
        index=index,
        box=CardBox(x=index * 150, y=0, w=140, h=210),
        raw_text=f"{name} WPA +2.0% USUALLY 30:00",
        cleaned_text=name,
        item={"name": name},
        score=score,
    )


def _source(tmp_path: Path) -> StatlockerDataSource:
    return StatlockerDataSource(db_path=tmp_path / "missing.db", log_dir=tmp_path)


class TestItemConstruction(unittest.TestCase):
    """``_make_wpa_item`` must never invent a cost, WPA or timing."""

    def setUp(self):
        self.source = _source(Path("."))

    def test_unknown_fields_stay_none(self):
        item = self.source._make_wpa_item({"name": "Silencer", "item_slot_type": "weapon"})
        self.assertEqual(item.name, "Silencer")
        self.assertIsNone(item.wpa_pct)
        self.assertIsNone(item.usually_time)
        self.assertIsNone(item.cost)
        self.assertEqual(item.wpa_text, "--")
        self.assertEqual(item.usually_text, "--")

    def test_cost_and_category_are_mapped(self):
        item = self.source._make_wpa_item(
            {"name": "Fortitude", "item_slot_type": "vitality", "cost": "3000"}
        )
        self.assertEqual(item.cost, 3000)
        self.assertEqual(item.category, "vitality")
        self.assertEqual(item.category_color, "#74a832")

    def test_slot_type_aliases(self):
        cases = {"spirit": "spirit", "tech": "spirit", "gun": "weapon", "armor": "vitality"}
        for raw, expected in cases.items():
            item = self.source._make_wpa_item({"name": "X", "slot_type": raw})
            self.assertEqual(item.category, expected, raw)

    def test_live_values_are_preserved(self):
        item = self.source._make_wpa_item(
            {"name": "Silencer"},
            wpa_pct=2.4,
            usually_time="31:05",
            confidence=0.91,
            slot_index=2,
        )
        self.assertEqual(item.wpa_text, "+2.4%")
        self.assertEqual(item.usually_text, "31:05")
        self.assertEqual(item.confidence, 0.91)
        self.assertEqual(item.slot_index, 2)


class TestGetGameState(unittest.TestCase):
    """Screen reads drive the item list; the DB does not."""

    def _prepare(self, source):
        source._index_item({"name": "Silencer", "type": "upgrade", "item_slot_type": "weapon"})
        source._catalog_loaded = True

    def test_missing_catalog_is_an_error_without_items(self):
        source = _source(Path("."))
        with patch.object(source, "load_catalog", return_value=False), patch.object(
            source, "open_connection", return_value=None
        ), patch.object(
            source, "_tracker"
        ) as tracker, patch("data_source.detect_active_hero_from_logs", return_value=None):
            tracker.poll.return_value = LogSnapshot()
            state = source.get_game_state()
        self.assertEqual(state.scan_status, "error")
        self.assertEqual(state.recommended_items, [])
        self.assertIsNotNone(state.last_error)

    def test_live_cards_become_items_without_invented_stats(self):
        source = _source(Path("."))
        self._prepare(source)
        # Live OCR text carries the real WPA% and timing; DB stays empty.
        read = ScreenReadResult(status="ok", cards=[_card("Silencer")])
        conn = _DummyConnection()
        with patch.object(source, "load_catalog", return_value=True), patch.object(
            source, "open_connection", return_value=conn
        ), patch.object(source, "_tracker") as tracker, patch.object(
            source, "_resolve_hero", return_value=(27, "Haze")
        ), patch.object(
            source, "_wpa_stats", return_value={}
        ), patch(
            "data_source.detect_active_hero_from_logs", return_value=None
        ), patch(
            "data_source.read_live_wpa_screen", return_value=read
        ):
            tracker.poll.return_value = LogSnapshot(match_id="4242", clock_s=640.0)
            state = source.get_game_state(max_items=5)

        self.assertEqual([item.name for item in state.recommended_items], ["Silencer"])
        self.assertEqual(state.source, "live_screen")
        self.assertEqual(state.scan_status, "ok")
        self.assertEqual((state.detected_slots, state.matched_slots), (1, 1))
        self.assertTrue(state.is_in_match)
        # Live values come from OCR, not invented: raw is 'WPA +2.0% USUALLY 30:00'.
        self.assertEqual(state.recommended_items[0].wpa_pct, 2.0)
        self.assertEqual(state.recommended_items[0].usually_time, "30:00")

    def test_empty_screen_clears_items(self):
        source = _source(Path("."))
        self._prepare(source)
        conn = _DummyConnection()
        with patch.object(source, "load_catalog", return_value=True), patch.object(
            source, "open_connection", return_value=conn
        ), patch.object(source, "_tracker") as tracker, patch.object(
            source, "_resolve_hero", return_value=(27, "Haze")
        ), patch.object(
            source, "_wpa_stats", return_value={}
        ), patch(
            "data_source.detect_active_hero_from_logs", return_value=None
        ), patch(
            "data_source.read_live_wpa_screen", return_value=ScreenReadResult(status="empty")
        ):
            tracker.poll.return_value = LogSnapshot(match_id="4242")
            state = source.get_game_state()

        self.assertEqual(state.recommended_items, [])
        self.assertEqual(state.source, "live_screen")
        self.assertEqual(state.scan_status, "empty")
        self.assertTrue(state.is_in_match)

    def test_not_visible_does_not_fall_back_by_default(self):
        source = _source(Path("."))
        self._prepare(source)
        conn = _DummyConnection()
        with patch.object(source, "load_catalog", return_value=True), patch.object(
            source, "open_connection", return_value=conn
        ), patch.object(source, "_tracker") as tracker, patch.object(
            source, "_resolve_hero", return_value=(27, "Haze")
        ), patch.object(
            source, "_wpa_stats", return_value={}
        ), patch(
            "data_source.detect_active_hero_from_logs", return_value=None
        ), patch(
            "data_source.read_live_wpa_screen", return_value=ScreenReadResult(status="not_visible")
        ), patch.object(source, "_preview_items") as preview:
            tracker.poll.return_value = LogSnapshot(match_id="4242")
            state = source.get_game_state(allow_db_fallback=False)

        preview.assert_not_called()
        self.assertEqual(state.recommended_items, [])
        self.assertEqual(state.source, "none")

    def test_db_fallback_is_opt_in_and_labelled(self):
        source = _source(Path("."))
        self._prepare(source)
        conn = _DummyConnection()
        fake_items = [WpaItem(name="Silencer"), WpaItem(name="Fortitude")]
        with patch.object(source, "load_catalog", return_value=True), patch.object(
            source, "open_connection", return_value=conn
        ), patch.object(source, "_tracker") as tracker, patch.object(
            source, "_resolve_hero", return_value=(27, "Haze")
        ), patch.object(
            source, "_wpa_stats", return_value={}
        ), patch(
            "data_source.detect_active_hero_from_logs", return_value=None
        ), patch(
            "data_source.read_live_wpa_screen", return_value=ScreenReadResult(status="not_visible")
        ), patch.object(source, "_preview_items", return_value=fake_items):
            tracker.poll.return_value = LogSnapshot(match_id="4242")
            state = source.get_game_state(allow_db_fallback=True)

        self.assertEqual([item.name for item in state.recommended_items], ["Silencer", "Fortitude"])
        self.assertEqual(state.source, "db_fallback")

    def test_worker_exception_is_reported_not_raised(self):
        source = _source(Path("."))
        with patch.object(source, "load_catalog", side_effect=RuntimeError("boom")):
            state = source.get_game_state()
        self.assertEqual(state.scan_status, "error")
        self.assertIn("boom", state.last_error or "")


class TestInstalledCatalog(unittest.TestCase):
    """Optional checks that only run when Statlocker is installed locally."""

    def test_real_catalog_if_available(self):
        source = StatlockerDataSource()
        if not source.load_catalog():
            self.skipTest("Statlocker catalog not installed on this host")
        names = {item.get("name", "").lower() for item in source.catalog_items()}
        self.assertIn("diviner's kevlar", names)
        self.assertGreater(len(names), 100)


if __name__ == "__main__":
    unittest.main()
