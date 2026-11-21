"""HUD presentation formatting: status badges, timers, and tray status."""

import time
from typing import Optional, Tuple
from models import GameState, OverlayConfig


def inventory_status(state: GameState) -> str:
    """Describe blocked capacity only for a current, confirmed inventory."""
    if not state.is_in_match or not state.match_id or state.scan_status != "ok":
        return ""
    capacity = getattr(state, "inventory_capacity", None)
    if capacity is not None and capacity > 0 and state.known_owned_items >= capacity:
        return "Inventory full"
    if capacity is None and state.known_owned_items >= 9:
        return "Available slots unknown"
    return ""


def get_status_info(
    state: GameState,
    feedback: Optional[Tuple[str, str]] = None,
) -> Tuple[str, str]:
    """Return (title, dot_color) for the standby badge or feedback flash."""
    if feedback:
        return feedback[0], feedback[1]
    if state.scan_status == "needs_match":
        return "FINDING MATCH AUTOMATICALLY", "#e6bf83"
    if state.scan_status == "connecting":
        title = "WAITING FOR LIVE DATA" if state.last_error else "CONNECTING TO MATCH"
        return title, "#91a5aa"
    if state.scan_status == "broadcast_unavailable":
        return "BROADCAST UNAVAILABLE / AUTO RETRY", "#e6bf83"
    if state.scan_status == "needs_account":
        return "CHECK ACCOUNT ID", "#e6bf83"
    if state.scan_status == "unknown":
        return "LIVE DATA UNAVAILABLE", "#91a5aa"
    if state.scan_status == "error":
        return "SCAN ERROR", "#ef4444"
    if state.scan_status == "empty_pick_build":
        return "SELECT BUILD", "#f59e0b"
    if state.scan_status in ("empty", "empty_no_items"):
        return "NO ITEMS STAND OUT", "#f59e0b"
    if state.scan_status == "needs_hero":
        return "PICK HERO (F6)", "#f59e0b"
    if getattr(state, "replacement", None) is not None and not state.recommended_items:
        return "SWAP OPTION / OPEN FULL BUILD", "#88d5ba"
    if not state.recommended_items and inventory_status(state):
        return inventory_status(state).upper(), "#91a5aa"
    if state.scan_status == "ok" and state.is_in_match and not state.recommended_items:
        return "NO VALID PURCHASES", "#91a5aa"
    if state.scan_status in ("scanning", "unresolved") or state.is_in_match:
        return "SCANNING...", "#38bdf8"
    return "WAITING FOR MATCH", "#22c55e"


def format_timer_text(
    state: GameState,
    last_poll_time: float,
    show_timer: bool = False,
) -> str:
    """Format the transient refresh age timer string."""
    if not show_timer:
        return ""
    if state.source == "build_preview":
        return "PREVIEW"
    if not state.recommended_items:
        return ""
    age = max(0, int(time.time() - last_poll_time))
    text = "NOW" if age < 3 else f"{age}s"
    if state.detected_slots and state.matched_slots < state.detected_slots:
        text += f" {state.matched_slots}/{state.detected_slots}"
    return text


def get_desired_content(
    state: GameState,
    config: OverlayConfig,
    is_ingame: bool,
    feedback: Optional[Tuple[str, str]] = None,
    force_visible: bool = False,
) -> Tuple[str, int]:
    """Determine what view type ('items', 'status', 'feedback', 'hidden') to render.

    ``force_visible`` means the user explicitly asked to see the overlay (F10,
    tray → Show, Move), so an empty scan still renders a status badge instead
    of parking the window offscreen and looking broken.
    """
    if feedback:
        return ("feedback", 1)
    items = state.recommended_items[: config.max_items]
    if items:
        return ("items", max(1, len(items)))
    if getattr(state, "replacement", None) is not None:
        return ("items", 1) if config.view_mode == "full" else ("status", 1)
    if inventory_status(state):
        return ("items", 1) if config.view_mode == "full" else ("status", 1)
    if state.scan_status in ("needs_match", "connecting", "needs_account", "broadcast_unavailable"):
        return ("status", 1)
    if state.source == "advisor" and is_ingame and state.scan_status in ("unknown", "error", "ok"):
        return ("status", 1)
    if force_visible:
        return ("status", 1)
    if getattr(config, "standby_badge", True):
        if config.only_in_game and not is_ingame:
            return ("hidden", 0)
        return ("status", 1)
    return ("hidden", 0)


def format_tray_text(state: GameState) -> str:
    """Format tooltip text for the system tray icon."""
    if state.recommended_items:
        names = ", ".join(item.name for item in state.recommended_items[:3])
        return f"Deadlock WPA - {len(state.recommended_items)} items: {names}"
    return "Deadlock WPA - scan error" if state.scan_status == "error" else "Deadlock WPA - idle"
