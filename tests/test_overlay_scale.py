"""User size scaling: config round-trip, metrics, settings and edge docking."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config import _from_dict, _to_dict
from models import GameState, OverlayConfig, WpaItem
from ui.hud_geometry import compute_metrics


@pytest.fixture
def overlay():
    import tkinter as tk

    with patch("ui.main_window.save_config"), patch("ui.overlay_settings.save_config"), \
            patch("ui.drag_handler.save_config"), patch("ui.hover_controls.set_clickthrough"):
        try:
            window = __import__("ui.main_window", fromlist=["OverlayWindow"]).OverlayWindow(
                OverlayConfig(), SimpleNamespace(), enable_worker=False,
                enable_hotkeys=False, enable_tray=False, enable_dpi=False,
            )
        except tk.TclError as err:
            pytest.skip(str(err))
        window._apply_new_state(
            GameState(recommended_items=[WpaItem("Test item")], scan_status="ok")
        )
        yield window
        window.close()


def test_hud_scale_is_clamped_and_round_trips():
    assert _from_dict({"hud_scale": 9}).hud_scale == 2.0
    assert _from_dict({"hud_scale": 0.1}).hud_scale == 0.75
    assert _to_dict(_from_dict({"hud_scale": 1.25}))["hud_scale"] == 1.25


def test_metrics_and_fonts_grow_with_scale():
    small = compute_metrics("horizontal", 5, 1.0)
    large = compute_metrics("horizontal", 5, 1.5)
    assert large.width > small.width and large.height > small.height
    assert small.px(8) == 8 and large.px(8) == 12


def test_set_scale_resizes_the_hud_and_saves(overlay):
    before = overlay._base_metrics_for(5).width
    with patch("ui.main_window.save_config") as save:
        overlay.set_scale(1.5)
    assert overlay.config.hud_scale == 1.5
    assert overlay._base_metrics_for(5).width > before
    save.assert_called_once()


def test_set_scale_rejects_out_of_range_values(overlay):
    overlay.set_scale(99)
    assert overlay.config.hud_scale == 2.0
    overlay.set_scale("nope")
    assert overlay.config.hud_scale == 1.0


def test_settings_size_choice_delegates_to_overlay(overlay):
    overlay.open_settings()
    panel = overlay._settings
    with patch.object(overlay, "set_scale") as set_scale:
        panel.apply("hud_scale", 1.25)
    set_scale.assert_called_once_with(1.25)
    panel.close()


def test_drag_release_near_left_edge_docks_top_left(overlay):
    layouts = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
    overlay.root.geometry("+4+300")
    overlay.root.update_idletasks()
    overlay._drag_handler.active = True
    with patch("ui.drag_handler.get_monitor_layouts", return_value=layouts), \
            patch("ui.drag_handler.monitor_for_rect", return_value=0):
        overlay._drag_handler.on_stop(SimpleNamespace())
    assert overlay.config.corner == "top_left"
    assert not overlay.config.positioned
    assert overlay.config.x == 0
