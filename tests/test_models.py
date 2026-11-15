"""Unit tests for the data contracts in :mod:`models`.

These tests pin the "never invent a value" rule: unknown percentages and
timings must surface as ``--`` instead of a plausible-looking default.
"""

import unittest

from models import GameState, OverlayConfig, WpaItem


class TestWpaItemFormatting(unittest.TestCase):
    """Display helpers used by the HUD and the diagnostics report."""

    def test_short_names_are_not_truncated(self):
        item = WpaItem(name="Diviner's Kevlar", category="vitality")
        self.assertEqual(item.display_name, "DIVINER'S KEVLAR")

    def test_long_names_are_truncated_to_eighteen_chars(self):
        item = WpaItem(name="Mystic Regeneration", category="vitality")
        self.assertEqual(item.display_name, "MYSTIC REGENERAT..")
        self.assertEqual(len(item.display_name), 18)

    def test_known_wpa_is_signed(self):
        self.assertEqual(WpaItem(name="X", wpa_pct=4.0).wpa_text, "+4.0%")
        self.assertEqual(WpaItem(name="X", wpa_pct=-1.2).wpa_text, "-1.2%")

    def test_unknown_wpa_is_a_dash(self):
        self.assertEqual(WpaItem(name="X").wpa_text, "--")

    def test_unknown_timing_is_a_dash(self):
        self.assertEqual(WpaItem(name="X").usually_text, "--")
        self.assertEqual(WpaItem(name="X", usually_time="33:25").usually_text, "33:25")


class TestCategoryColours(unittest.TestCase):
    """Category mapping drives the 1 px slot accent in the HUD."""

    def test_vitality(self):
        self.assertEqual(WpaItem(name="X", category="vitality").category_color, "#74a832")
        self.assertEqual(WpaItem(name="X", category="utility").category_color, "#74a832")

    def test_spirit(self):
        self.assertEqual(WpaItem(name="X", category="spirit").category_color, "#9f62de")

    def test_weapon(self):
        self.assertEqual(WpaItem(name="X", category="weapon").category_color, "#de8b00")

    def test_unknown_category_uses_slate(self):
        self.assertEqual(WpaItem(name="X", category="other").category_color, "#64748b")


class TestGameState(unittest.TestCase):
    """Completeness is derived, never stored."""

    def test_incomplete_when_a_card_is_unresolved(self):
        state = GameState(detected_slots=3, matched_slots=2)
        self.assertFalse(state.is_complete)

    def test_complete_when_every_card_resolved(self):
        state = GameState(detected_slots=3, matched_slots=3)
        self.assertTrue(state.is_complete)

    def test_empty_state_is_not_complete(self):
        self.assertFalse(GameState().is_complete)


class TestOverlayConfigDefaults(unittest.TestCase):
    """Defaults chosen for the ultra-minimal, silent HUD."""

    def test_defaults(self):
        cfg = OverlayConfig()
        self.assertEqual(cfg.max_items, 5)
        self.assertEqual(cfg.layout, "horizontal")
        self.assertFalse(cfg.only_in_game)
        self.assertTrue(cfg.clickthrough)
        self.assertEqual(cfg.refresh_seconds, 20.0)
        self.assertFalse(cfg.show_timer)
        self.assertFalse(cfg.allow_db_fallback)
        self.assertAlmostEqual(cfg.opacity, 0.80)


if __name__ == "__main__":
    unittest.main()
