"""Unit tests for HUD presentation, timer formatting, and tray tooltip logic."""

import time
from models import GameState, OverlayConfig, WpaItem
from ui.hud_presentation import (
    format_timer_text,
    format_tray_text,
    get_desired_content,
    get_status_info,
)


def test_get_status_info():
    # Feedback override
    assert get_status_info(GameState(), feedback=("TEST", "#fff")) == ("TEST", "#fff")

    # Error
    assert get_status_info(GameState(scan_status="error")) == ("SCAN ERROR", "#ef4444")

    # Empty pick build
    assert get_status_info(GameState(scan_status="empty_pick_build")) == ("SELECT BUILD", "#f59e0b")

    # Empty / no items
    assert get_status_info(GameState(scan_status="empty")) == ("NO ITEMS STAND OUT", "#f59e0b")
    assert get_status_info(GameState(scan_status="empty_no_items")) == ("NO ITEMS STAND OUT", "#f59e0b")

    # Scanning / match
    assert get_status_info(GameState(scan_status="scanning")) == ("SCANNING...", "#38bdf8")
    assert get_status_info(GameState(is_in_match=True)) == ("SCANNING...", "#38bdf8")

    # Waiting for match
    assert get_status_info(GameState()) == ("WAITING FOR MATCH", "#22c55e")


def test_format_timer_text():
    # show_timer disabled
    assert format_timer_text(GameState(), time.time(), show_timer=False) == ""

    # Preview source
    assert format_timer_text(GameState(source="build_preview"), time.time(), show_timer=True) == "PREVIEW"

    # No items
    assert format_timer_text(GameState(), time.time(), show_timer=True) == ""

    # With items
    items = [WpaItem(name="Silencer")]
    now = time.time()
    assert format_timer_text(GameState(recommended_items=items), now, show_timer=True) == "NOW"
    assert format_timer_text(GameState(recommended_items=items), now - 10, show_timer=True) == "10s"

    # With partial match slots
    state = GameState(recommended_items=items, detected_slots=4, matched_slots=1)
    assert format_timer_text(state, now, show_timer=True) == "NOW 1/4"


def test_get_desired_content():
    cfg = OverlayConfig(max_items=3, standby_badge=True, only_in_game=False)

    # Feedback has highest priority
    assert get_desired_content(GameState(), cfg, is_ingame=False, feedback=("TEST", "#fff")) == ("feedback", 1)

    # Items
    items = [WpaItem(name="Silencer"), WpaItem(name="Fortitude")]
    assert get_desired_content(GameState(recommended_items=items), cfg, is_ingame=False) == ("items", 2)

    # Standby badge
    assert get_desired_content(GameState(), cfg, is_ingame=False) == ("status", 1)

    # Standby badge with only_in_game=True
    cfg_ingame = OverlayConfig(max_items=3, standby_badge=True, only_in_game=True)
    assert get_desired_content(GameState(), cfg_ingame, is_ingame=False) == ("hidden", 0)
    assert get_desired_content(GameState(), cfg_ingame, is_ingame=True) == ("status", 1)

    # Disabled standby badge
    cfg_no_standby = OverlayConfig(max_items=3, standby_badge=False)
    assert get_desired_content(GameState(), cfg_no_standby, is_ingame=False) == ("hidden", 0)


def test_force_visible_always_renders_something():
    """An explicit Show must never leave the user staring at nothing."""
    cfg = OverlayConfig(max_items=3, standby_badge=False, only_in_game=True)
    assert get_desired_content(GameState(), cfg, is_ingame=False) == ("hidden", 0)
    assert get_desired_content(GameState(), cfg, is_ingame=False, force_visible=True) == (
        "status",
        1,
    )
    # Items still win over the forced badge.
    items = [WpaItem(name="Silencer")]
    assert get_desired_content(
        GameState(recommended_items=items), cfg, is_ingame=False, force_visible=True
    ) == ("items", 1)


def test_format_tray_text():
    # Idle
    assert format_tray_text(GameState()) == "Deadlock WPA - idle"

    # Error
    assert format_tray_text(GameState(scan_status="error")) == "Deadlock WPA - scan error"

    # With items
    items = [WpaItem(name="Silencer"), WpaItem(name="Fortitude")]
    assert "Silencer, Fortitude" in format_tray_text(GameState(recommended_items=items))
