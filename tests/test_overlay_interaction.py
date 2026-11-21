"""Hover, settings and dragging behavior in isolated Tk windows."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models import GameState, OverlayConfig, WpaItem
from ui.main_window import OverlayWindow


@pytest.fixture
def overlay():
    import tkinter as tk
    with patch("ui.main_window.save_config"), patch("ui.overlay_settings.save_config"), \
            patch("ui.drag_handler.save_config"), patch("ui.hover_controls.set_clickthrough"):
        try:
            window = OverlayWindow(OverlayConfig(), SimpleNamespace(), enable_worker=False,
                                   enable_hotkeys=False, enable_tray=False, enable_dpi=False)
        except tk.TclError as err:
            pytest.skip(str(err))
        window._apply_new_state(GameState(recommended_items=[WpaItem("Test item")], scan_status="ok"))
        yield window
        window.close()


def test_hover_requires_dwell_and_restores_clickthrough_preference(overlay):
    hover = overlay._hover_controls
    hover.update(True, 0)
    hover.update(True, .2)
    assert not hover.active
    hover.update(True, .4)
    assert hover.active and overlay._is_locked and overlay.config.clickthrough
    hover.update(False, .5)
    assert hover.active
    hover.update(False, .8)
    assert not hover.active
    assert overlay._is_locked and overlay.config.clickthrough


def test_crossing_hud_while_firing_does_not_enable_input(overlay):
    hover = overlay._hover_controls
    hover.update(True, 0, pressed=True)
    hover.update(True, 1, pressed=True)
    assert not hover.active
    hover.update(True, 2)
    assert not hover.active
    hover.update(True, 2.4)
    assert hover.active


def test_settings_reuses_panel_and_saves_display_preferences(overlay):
    overlay.open_settings()
    panel = overlay._settings
    overlay.open_settings()
    assert overlay._settings is panel
    with patch("ui.overlay_settings.save_config") as save:
        panel.apply("layout", "vertical")
        panel.apply("opacity", .65)
        panel.apply("max_items", 2)
        panel.apply("icons_only", True)
    assert save.call_count == 4
    assert overlay.config.layout == "vertical"
    assert overlay.config.opacity == overlay.config.hud_alpha == .65
    assert overlay.config.max_items == 2 and overlay.config.icons_only
    assert overlay._wake_event.is_set()
    panel.close()
    assert overlay._settings is None


def test_hover_drag_stays_locked_and_does_not_start_from_settings_button(overlay):
    hover = overlay._hover_controls
    hover.set_active(True)
    handler = overlay._drag_handler
    handler.on_start(SimpleNamespace(widget=hover.settings_button, x_root=50, y_root=50))
    assert not handler.active
    handler.on_start(SimpleNamespace(widget=hover.grip, x_root=50, y_root=50))
    assert handler.active and overlay._is_locked
    hover.update(False, 100)
    hover.update(False, 101)
    assert hover.active  # do not release input halfway through a drag
    handler.on_stop(SimpleNamespace())
    assert not handler.active and overlay._is_locked


def test_disabling_hover_and_hiding_settings_leaves_no_orphan_panel(overlay):
    hover = overlay._hover_controls
    hover.set_active(True)
    overlay.open_settings()
    overlay._settings.apply("hover_controls", False)
    assert not hover.active
    hover.update(True, 0)
    hover.update(True, 1)
    assert not hover.active
    overlay.hide_overlay()
    assert overlay._settings is None and overlay._parked


def test_drag_release_without_press_never_moves_or_saves(overlay):
    with patch("ui.drag_handler.save_config") as save:
        overlay._drag_handler.on_stop(SimpleNamespace())
        save.assert_not_called()


def test_retry_drops_advice_from_the_previous_poll(overlay):
    old = GameState(source="advisor", scan_status="ok", recommended_items=[WpaItem("Old match")])
    overlay._publish(old, overlay._connection_request)
    overlay.config.account_id = 1001
    overlay.config.match_id = 9001
    overlay.request_connection()
    first_request = overlay._connection_request
    overlay.request_connection()  # Retrying the same IDs is still a new request.
    overlay._publish(old, first_request)
    overlay._drain_queue()
    assert overlay._current_state.scan_status == "connecting"
    assert not overlay._current_state.recommended_items

    fresh = GameState(source="advisor", scan_status="ok", recommended_items=[WpaItem("New match")])
    source = overlay.data_source
    source.get_game_state = lambda **_: fresh
    seen = []
    source.reset_connection = lambda: seen.append((source.account_id, source.match_id))
    overlay.poll_once()
    overlay._drain_queue()
    assert seen == [(1001, 9001)]
    assert overlay._current_state is fresh


def test_edge_resize_scales_without_saving_each_mouse_move(overlay):
    handler = overlay._resize_handler
    width = overlay.root.winfo_width()
    handler.start(SimpleNamespace(x_root=100), "right")
    with patch("ui.main_window.save_config") as per_motion, patch("ui.resize_handler.save_config") as on_release:
        handler.motion(SimpleNamespace(x_root=100 + width // 3))
        assert 1.2 < overlay.config.hud_scale < 1.5
        per_motion.assert_not_called()
        handler.stop()
        on_release.assert_called_once()


def test_drag_does_not_delay_invalid_item_removal(overlay):
    overlay._drag_handler.active = True
    before = overlay.root.geometry()
    overlay._apply_new_state(GameState(source="advisor", scan_status="unknown"))
    assert overlay._view.item_names == []
    assert overlay._view._name_labels[0].cget("text") == ""
    assert overlay.root.geometry() == before
    overlay._drag_handler.active = False
    overlay._render_content()


def test_drag_keeps_claims_fresh_without_moving_window(overlay):
    overlay._drag_handler.active = True
    before = overlay.root.geometry()
    current = WpaItem("Test item", win_rate=.57, reason="SAVE 500", can_buy=False)
    overlay._apply_new_state(GameState(recommended_items=[current], scan_status="ok"))
    assert overlay._view.items[0].win_rate == .57
    assert overlay._view._time_labels[0].cget("text") == "SAVE 500"
    assert overlay.root.geometry() == before
    overlay._drag_handler.active = False


def test_drag_hides_counter_chips_that_lose_evidence(overlay):
    from models import CounterItem
    item = WpaItem("Test item")
    overlay._apply_new_state(GameState(recommended_items=[item], scan_status="ok",
                                       counter_items=[CounterItem("Counter", gain=.04)]))
    chip_view = overlay._counter_view
    assert chip_view is not None and chip_view.winfo_manager() == "pack"
    overlay._drag_handler.active = True
    overlay._apply_new_state(GameState(recommended_items=[item], scan_status="ok"))
    assert chip_view.winfo_manager() == ""
    overlay._drag_handler.active = False
    overlay._render_content()
    assert overlay._counter_view is None
