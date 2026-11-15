"""Unit test for visual WPA detector."""

import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from PIL import Image
from wpa_detector import _ensure_template_loaded, is_wpa_items_visible_in_statlocker


class TestWpaDetector(unittest.TestCase):
    """Test template loading and visual detection."""

    def test_template_loaded(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.png"
            Image.new("RGB", (40, 20), "white").save(path)
            with patch("wpa_detector._TMPL_ARR", None), patch(
                "wpa_detector._find_template_file", return_value=path
            ):
                self.assertTrue(_ensure_template_loaded())

    def test_detection_runs(self):
        # Should execute cleanly without throwing exceptions
        with patch("wpa_detector.capture_statlocker_frame", return_value=None):
            res = is_wpa_items_visible_in_statlocker()
        self.assertIsInstance(res, bool)

    def test_companion_priority_ignores_ipc_siw_windows(self):
        from wpa_detector import _companion_priority
        # Electron / Tauri single-instance windows must be ignored (prio 2)
        prio = _companion_priority("com.statlocker.companion-siw", "statlocker-companion.exe")
        self.assertEqual(prio, 2)

    def test_companion_priority_accepts_main_companion_window(self):
        from wpa_detector import _companion_priority
        prio = _companion_priority("Statlocker Companion", "statlocker-companion.exe")
        self.assertEqual(prio, 0)
        prio_short = _companion_priority("Statlocker", "statlocker.exe")
        self.assertEqual(prio_short, 0)

    def test_companion_priority_browser_rules(self):
        from wpa_detector import _companion_priority
        # Normal website tab in Chrome is ignored (thumbnails only)
        self.assertEqual(_companion_priority("statlocker.gg - Builds", "chrome.exe"), 2)
        # Explicit Companion title in browser is priority 1
        self.assertEqual(_companion_priority("Statlocker Companion - Live", "chrome.exe"), 1)


if __name__ == "__main__":
    unittest.main()
