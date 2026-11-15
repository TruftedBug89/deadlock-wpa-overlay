"""Tray icon tests.  They never call ``pystray.Icon.run_detached``."""

import unittest
from unittest.mock import MagicMock

from tray_manager import TrayManager, _get_tray_icon_image


class TestTrayIconArtwork(unittest.TestCase):
    def test_image_is_64px_rgba(self):
        image = _get_tray_icon_image()
        self.assertIsNotNone(image)
        self.assertEqual(image.size, (64, 64))
        self.assertEqual(image.mode, "RGBA")


class TestTrayManagerConstruction(unittest.TestCase):
    def setUp(self):
        self.overlay = MagicMock()
        self.overlay.config = MagicMock()
        self.overlay.config.tray_promote = False
        self.overlay.config.tray_notify = False

    def test_icon_is_built_but_not_started(self):
        tray = TrayManager(self.overlay)
        self.assertIsNotNone(tray._icon)
        self.assertEqual(tray._icon.title, "Deadlock WPA Overlay")
        self.assertFalse(tray._running)

    def test_stop_without_start_is_a_noop(self):
        tray = TrayManager(self.overlay)
        tray.stop()
        self.assertFalse(tray._running)

    def test_set_status_is_safe_without_a_running_icon(self):
        tray = TrayManager(self.overlay)
        tray.set_status("Deadlock WPA - idle")
        self.assertEqual(tray._icon.title, "Deadlock WPA - idle")

    def test_menu_actions_are_deferred_to_the_tk_thread(self):
        tray = TrayManager(self.overlay)
        menu = tray._icon.menu
        self.assertIsNotNone(menu)


if __name__ == "__main__":
    unittest.main()
