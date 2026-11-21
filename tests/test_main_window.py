"""Overlay window tests: silent-when-idle HUD and flush-right geometry.

These need a real Tk display, so they skip themselves on a headless host.  The
worker thread is fed by a fake data source; nothing captures the screen.
"""

import tkinter as tk
import unittest
from unittest.mock import patch

from models import GameState, OverlayConfig, WpaItem
from ui.hud_geometry import compute_metrics
from ui.main_window import OverlayWindow


class _FakeSource:
    """Minimal stand-in for StatlockerDataSource."""

    def __init__(self, state: GameState):
        self.state = state
        self.manual_hero_id = None
        self.cycled = 0

    def get_game_state(self, **_kwargs) -> GameState:
        return self.state

    def cycle_next_hero(self) -> None:
        self.cycled += 1


def _items(count: int):
    names = ["Silencer", "Fortitude", "Refresher", "Inhibitor", "Mercurial Magnum"]
    return [WpaItem(name=name, category="weapon") for name in names[:count]]


class TestOverlayWindow(unittest.TestCase):
    def setUp(self):
        self._save_patcher = patch("ui.main_window.save_config", return_value=None)
        self._save_patcher.start()
        try:
            self.overlay = OverlayWindow(
                config=OverlayConfig(layout="horizontal", max_items=5, standby_badge=False),
                data_source=_FakeSource(GameState()),
                enable_tray=False,
                enable_dpi=False,
                enable_hotkeys=False,
                enable_worker=False,  # many Tk windows in one pytest process crash on thread start
            )
        except tk.TclError as err:  # pragma: no cover - headless host
            self._save_patcher.stop()
            self.skipTest(f"Tk unavailable: {err}")

    def tearDown(self):
        try:
            self.overlay.close()
        except Exception:
            pass
        self._save_patcher.stop()

    def test_starts_silent_when_idle(self):
        self.assertEqual(self.overlay._content_kind, "hidden")
        # Hidden means parked offscreen (the window is never withdrawn).
        self.assertTrue(self.overlay._parked)
        self.assertLessEqual(self.overlay.root.winfo_x(), -10000)

    def test_items_replace_the_hidden_state(self):
        state = GameState(recommended_items=_items(3), source="live_screen", scan_status="ok")
        self.overlay._apply_new_state(state)

        self.assertEqual(self.overlay._content_kind, "items")
        self.assertEqual(self.overlay._content_slots, 3)
        self.assertIsNotNone(self.overlay._view)
        self.assertFalse(self.overlay._parked)

    def test_width_matches_geometry_contract(self):
        state = GameState(recommended_items=_items(2), source="live_screen", scan_status="ok")
        self.overlay._apply_new_state(state)

        expected = compute_metrics(
            "horizontal", 2, self.overlay._scale, show_timer=self.overlay.config.show_timer
        )
        actual = self.overlay._metrics
        self.assertEqual((actual.width, actual.height), (expected.width, expected.height))

    def test_switching_card_count_does_not_rebuild_for_same_kind(self):
        self.overlay._apply_new_state(
            GameState(recommended_items=_items(2), source="live_screen", scan_status="ok")
        )
        view = self.overlay._view
        self.overlay._apply_new_state(
            GameState(recommended_items=_items(2), source="live_screen", scan_status="ok")
        )
        self.assertIs(self.overlay._view, view)

    def test_becoming_empty_hides_the_window(self):
        self.overlay._apply_new_state(
            GameState(recommended_items=_items(4), source="live_screen", scan_status="ok")
        )
        self.overlay._apply_new_state(
            GameState(scan_status="empty", source="live_screen", is_in_match=True)
        )
        self.assertEqual(self.overlay._content_kind, "hidden")
        self.assertTrue(self.overlay._parked)
        self.assertLessEqual(self.overlay.root.winfo_x(), -10000)

    def test_icons_only_renders_icon_strip(self):
        from ui.icon_view import IconStripView

        self.overlay.config.icons_only = True
        self.overlay._content_kind = None
        state = GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        self.overlay._apply_new_state(state)
        self.assertIsInstance(self.overlay._view, IconStripView)
        self.assertEqual(len(self.overlay._view.items), 5)
        self.assertFalse(self.overlay._parked)
        geom = self.overlay.root.geometry()
        parts = geom.replace("+", "x").split("x")
        self.assertEqual((int(parts[0]), int(parts[1])), (172, 36))

    def test_never_renders_more_than_max_items(self):
        self.overlay.config.max_items = 3
        self.overlay._apply_new_state(
            GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        )
        self.assertEqual(len(self.overlay._view.items), 3)
        self.assertEqual(self.overlay._content_slots, 3)

    def test_feedback_is_a_short_centred_badge(self):
        self.overlay.show_feedback("PREVIEW", "#f59e0b", duration_ms=10)
        self.assertEqual(self.overlay._content_kind, "feedback")
        self.assertIsNotNone(self.overlay._view)
        self.assertGreaterEqual(self.overlay._metrics.width, len("PREVIEW") * 6)

    def test_worker_thread_is_optional(self):
        # Unit tests run many Tk windows in one process; starting a Python
        # thread during that pattern crashes CPython 3.11 on Windows. The
        # production default still starts it (see OverlayWindow.__init__).
        self.assertIsNone(self.overlay._worker)
        self.assertFalse(self.overlay._stop_event.is_set())
        self.overlay.close()
        self.assertTrue(self.overlay._stop_event.is_set())

    def test_same_items_refresh_live_reason_winrate_and_counter_gain(self):
        from models import CounterItem
        from dataclasses import replace

        item = WpaItem(name="Same Item", cost=500, win_rate=.52, samples=1000, reason="AHEAD")
        counter = CounterItem(name="Counter", samples=500, gain=.02)
        state = GameState(recommended_items=[item], counter_items=[counter],
                          source="advisor", scan_status="ok", is_in_match=True)
        self.overlay._apply_new_state(state)
        view = self.overlay._view
        self.overlay._apply_new_state(replace(state,
            recommended_items=[replace(item, reason="SAVE 500", win_rate=.54, can_buy=False)],
            counter_items=[replace(counter, gain=.041)]))
        assert self.overlay._view is view
        assert view._time_labels[0].cget("text") == "SAVE 500"
        assert view._wpa_labels[0].cget("text") == "WR 54.0%"
        assert self.overlay._counter_view._sample_labels[0].cget("text") == "+4.1 pts"
        assert self.overlay._counter_view._subtitle.cget("text") == "VS LINEUP / GAIN"

    def test_expired_advisor_cards_clear_even_without_new_worker_result(self):
        import time
        self.overlay._apply_new_state(GameState(
            recommended_items=_items(2), source="advisor", scan_status="ok",
            valid_until=time.time() + 60))
        self.overlay._current_state.valid_until = time.time() - 1
        with patch.object(self.overlay, "_is_ingame", return_value=True):
            self.overlay._drain_queue()
        assert self.overlay._content_kind == "status"
        assert self.overlay._current_state.scan_status == "unknown"
        assert self.overlay._current_state.recommended_items == []

    def test_position_window_flush_right_zero_gap(self):
        state = GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        self.overlay._apply_new_state(state)
        self.overlay._position_window()
        self.overlay.root.update_idletasks()
        geom = self.overlay.root.geometry()
        parts = geom.replace("+", "x").split("x")
        w, x = int(parts[0]), int(parts[2])

        from win32_overlay import get_monitor_bounds, get_screen_bounds

        _l, _t, mon_r, _b = get_monitor_bounds()
        wl, _wt, wr, _wb = get_screen_bounds()
        right = min(mon_r, wr)
        self.assertEqual(x, max(wl, right - w))

    def test_position_window_custom_x(self):
        state = GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        self.overlay._apply_new_state(state)
        self.overlay.config.x = 500
        with patch("ui.positioning.get_monitor_layouts", return_value=[((0, 0, 1920, 1080), (0, 0, 1920, 1040))]):
            self.overlay._position_window()
        self.overlay.root.update_idletasks()
        geom = self.overlay.root.geometry()
        parts = geom.replace("+", "x").split("x")
        x = int(parts[2])
        self.assertEqual(x, 500)

    def test_status_info_empty_states(self):
        self.overlay._current_state = GameState(scan_status="empty_pick_build")
        text, color = self.overlay._status_info()
        self.assertEqual(text, "SELECT BUILD")
        self.assertEqual(color, "#f59e0b")

        self.overlay._current_state = GameState(scan_status="empty_no_items")
        text, color = self.overlay._status_info()
        self.assertEqual(text, "NO ITEMS STAND OUT")
        self.assertEqual(color, "#f59e0b")

    def test_standby_badge_renders_when_enabled(self):
        self.overlay.config.standby_badge = True
        self.overlay._content_kind = None
        self.overlay._render_content()
        self.assertEqual(self.overlay._content_kind, "status")
        self.assertIsNotNone(self.overlay._view)
        self.assertFalse(self.overlay._parked)

    def test_auto_y_docks_to_the_true_corner(self):
        state = GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        fake = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
        with patch("ui.positioning.get_monitor_layouts", return_value=fake):
            for corner, expected_y in (
                ("top_right", 0),
                ("top_left", 0),
                ("bottom_right", 1040 - self.overlay._metrics.height),
                ("bottom_left", 1040 - self.overlay._metrics.height),
            ):
                self.overlay.config.corner = corner
                self.overlay.config.x = 0
                self.overlay.config.y = 120
                self.overlay._anchor_origin = None
                self.overlay._content_kind = None
                self.overlay._apply_new_state(state)
                geom = self.overlay.root.geometry()
                parts = geom.replace("+", "x").split("x")
                y = int(parts[3])
                self.assertEqual(y, expected_y, f"corner={corner}")

    def test_custom_y_is_honoured_verbatim(self):
        state = GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        fake = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
        with patch("ui.positioning.get_monitor_layouts", return_value=fake):
            self.overlay.config.corner = "top_right"
            self.overlay.config.x = 0
            self.overlay.config.y = 200
            self.overlay._anchor_origin = None
            self.overlay._apply_new_state(state)
            geom = self.overlay.root.geometry()
            parts = geom.replace("+", "x").split("x")
            self.assertEqual(int(parts[3]), 200)

    def test_secondary_game_monitor_is_used_for_docking(self):
        state = GameState(recommended_items=_items(5), source="live_screen", scan_status="ok")
        fake = [
            ((0, 0, 1920, 1080), (0, 0, 1920, 1040)),
            ((1920, 0, 3840, 1080), (1920, 0, 3840, 1040)),
        ]
        game_rect = (1920, 0, 3840, 1080)
        with patch("ui.positioning.get_monitor_layouts", return_value=fake), patch(
            "ui.positioning.find_process_window_rect", return_value=game_rect
        ):
            self.overlay.config.corner = "top_right"
            self.overlay.config.x = 0
            self.overlay.config.y = 120
            self.overlay._anchor_origin = None
            self.overlay._apply_new_state(state)
            geom = self.overlay.root.geometry()
            parts = geom.replace("+", "x").split("x")
            w, x, y = int(parts[0]), int(parts[2]), int(parts[3])
            self.assertEqual((x + w, y), (3840, 0))
            self.assertEqual(self.overlay._anchor_origin, (1920, 0))

    def test_docked_x_stable_across_different_card_counts(self):
        self.overlay.config.x = 0
        right_edges = []
        for count in (5, 3, 1):
            state = GameState(recommended_items=_items(count), source="live_screen", scan_status="ok")
            self.overlay._apply_new_state(state)
            self.overlay.root.update_idletasks()
            geom = self.overlay.root.geometry()
            parts = geom.replace("+", "x").split("x")
            w, x = int(parts[0]), int(parts[2])
            right_edges.append(x + w)

        # Right edge must remain completely flush and stable across card counts
        self.assertEqual(len(set(right_edges)), 1, f"Right edge drifted: {right_edges}")


    def test_show_renders_a_badge_even_when_idle(self):
        """F10 / tray Show must never leave the user staring at nothing."""
        self.assertEqual(self.overlay._content_kind, "hidden")
        self.overlay.toggle_visibility()
        self.assertEqual(self.overlay._content_kind, "status")
        self.assertIsNotNone(self.overlay._view)
        self.assertFalse(self.overlay._parked)
        self.assertFalse(self.overlay._user_hidden)

    def test_hiding_again_parks_offscreen(self):
        self.overlay.toggle_visibility()
        self.overlay.toggle_visibility()
        self.assertTrue(self.overlay._parked)
        self.assertLessEqual(self.overlay.root.winfo_x(), -10000)

    def test_forced_show_outranks_the_in_game_rule(self):
        self.overlay.config.only_in_game = True
        self.overlay.config.only_in_game = True
        self.overlay._content_kind = None
        self.overlay._render_content()
        self.assertTrue(self.overlay._parked)
        self.overlay.toggle_visibility()
        self.assertFalse(self.overlay._parked)

    def test_begin_move_unlocks_and_puts_something_on_screen(self):
        self.assertTrue(self.overlay._is_locked)
        self.overlay.begin_move()
        self.assertFalse(self.overlay._is_locked)
        self.assertFalse(self.overlay._parked)
        self.assertFalse(self.overlay._user_hidden)
        self.assertIn(self.overlay._content_kind, ("status", "feedback"))

    def test_set_position_docks_the_named_corner(self):
        fake = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
        with patch("ui.positioning.get_monitor_layouts", return_value=fake):
            self.overlay.set_position("bottom_left")
            self.overlay.root.update_idletasks()
            parts = self.overlay.root.geometry().replace("+", "x").split("x")
            self.assertEqual(int(parts[2]), 0)
            self.assertEqual(int(parts[3]), 1040 - self.overlay._metrics.height)

        cfg = self.overlay.config
        self.assertEqual(cfg.corner, "bottom_left")
        self.assertFalse(cfg.positioned)
        self.assertEqual((cfg.x, cfg.y), (0, 120))

    def test_set_position_rejects_unknown_corners(self):
        self.overlay.set_position("somewhere_else")
        self.assertEqual(self.overlay.config.corner, "top_right")

    def test_dragged_position_survives_a_restart(self):
        self.overlay.config.positioned = True
        self.overlay.config.x = 0
        self.overlay.config.y = 500
        fake = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
        with patch("ui.positioning.get_monitor_layouts", return_value=fake):
            self.overlay._content_kind = None
            self.overlay.show_feedback("READY", duration_ms=10)
            parts = self.overlay.root.geometry().replace("+", "x").split("x")
        self.assertEqual((int(parts[2]), int(parts[3])), (0, 500))

if __name__ == "__main__":
    unittest.main()
