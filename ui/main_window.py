"""The overlay window: right-docked HUD, background polling, tray and hotkeys."""

import queue
import threading
import time
import tkinter as tk
from typing import TYPE_CHECKING, Optional, Tuple

from config import save_config
from models import GameState, OverlayConfig

if TYPE_CHECKING:  # advisor startup must not drag in the Statlocker stack
    from data_source import StatlockerDataSource
    from hotkey_manager import GlobalHotkeyManager
    from tray_manager import TrayManager
from ui import counter_panel, theme, visibility
from ui.drag_handler import WindowDragHandler
from ui.resize_handler import WindowResizeHandler
from ui.hud_geometry import (
    compute_badge_metrics, compute_icon_metrics, compute_metrics, stack_metrics,
)
from ui.hud_presentation import format_tray_text, get_status_info
from ui.minimal_view import BG
from ui.positioning import (
    GAME_EXECUTABLES,  # re-exported: callers/tests import it from here
    position_window,
    set_corner,
    snap_to_edge,
)
from ui.overlay_render import RenderMixin
from ui.state_updates import StateUpdatesMixin
from win32_overlay import (
    attach_to_default_desktop, enable_dpi_awareness,
    make_overlay, set_app_user_model_id, set_clickthrough, ui_scale,
)

VK_F6, VK_F7, VK_F8, VK_F9, VK_F10 = 0x75, 0x76, 0x77, 0x78, 0x79  # preview, autohide, layout, lock, hide


class OverlayWindow(RenderMixin, StateUpdatesMixin):
    """Right-docked, click-through WPA HUD."""

    def __init__(
        self,
        config: OverlayConfig,
        data_source: "StatlockerDataSource",
        enable_tray: bool = True,
        enable_dpi: bool = True,
        enable_hotkeys: bool = True,
        enable_worker: bool = True,
    ):
        self.config = config
        self.data_source = data_source

        if enable_dpi:
            enable_dpi_awareness()
        set_app_user_model_id("Deadlock.WPA.Overlay")
        attach_to_default_desktop()
        self._scale = ui_scale() * max(
            0.75, min(2.0, float(getattr(config, "hud_scale", 1.0) or 1.0))
        )

        self._status_slots = 1
        self._metrics = compute_metrics(
            config.layout,
            self._status_slots,
            self._scale,
            show_timer=bool(getattr(config, "show_timer", False)),
        )
        self._content_kind: Optional[str] = None
        self._content_slots = 0
        self._view = None
        self._counter_view = None
        self._feedback: Optional[Tuple[str, str]] = None
        self._feedback_token = 0
        self._hwnd: Optional[int] = None
        self._user_hidden = False
        self._forced_visible = False
        self._parked = True
        self._styles_applied = False
        self._anchor_origin: Optional[Tuple[int, int]] = None
        self._is_locked = bool(config.clickthrough)
        self._drag_handler = WindowDragHandler(self)
        self._resize_handler = WindowResizeHandler(self)
        self._current_state = GameState()
        self._last_poll_time = time.time()
        self._tick = 0
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._preview_event = threading.Event()
        self._preview_clear_event = threading.Event()
        self._preview_token = 0
        self._queue = queue.Queue(maxsize=4)
        self._connection_request = None
        self._worker_connection = None
        self._icon_refresh = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._settings = None
        self._hover_controls = None

        self.root = tk.Tk()
        self.root.title("Deadlock WPA Overlay")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-alpha", float(self.config.opacity))
        self.root.configure(bg=BG)

        self.container = tk.Frame(self.root, bg=BG, highlightthickness=0 if self._is_locked else 1, highlightbackground="#f59e0b", bd=0)
        self.container.pack(fill="both", expand=True)

        if enable_hotkeys:
            from hotkey_manager import GlobalHotkeyManager

            self.hotkey_mgr: Optional["GlobalHotkeyManager"] = GlobalHotkeyManager()
        else:
            self.hotkey_mgr = None
        if enable_tray:
            from tray_manager import TrayManager

            self.tray_manager: Optional["TrayManager"] = TrayManager(self)
        else:
            self.tray_manager = None

        self._render_content()
        self._setup_bindings()
        from ui.hover_controls import HoverControls
        self._hover_controls = HoverControls(self)
        if self.hotkey_mgr is not None:
            self._setup_hotkeys()

        self.root.after(120, self._apply_win32_styles)
        self.root.after(100, self._drain_queue)
        self.root.after(1000, self._ui_tick)

        self._worker = None
        if enable_worker:
            self._worker = threading.Thread(target=self._worker_loop, name="WpaPollWorker", daemon=True)
            self._worker.start()

    # ------------------------------------------------------------------ setup
    def _setup_bindings(self) -> None:
        for seq, fn in [("<ButtonPress-1>", self._on_drag_start), ("<B1-Motion>", self._on_drag_motion),
                        ("<ButtonRelease-1>", self._on_drag_stop)]:
            self.root.bind(seq, fn)
        self.root.bind("<Button-3>", lambda _e: self.open_settings())
        self.root.bind("<Control-l>", lambda _e: self.toggle_lock())
        self.root.bind("<Escape>", lambda _e: self.hide_overlay())

    def _setup_hotkeys(self) -> None:
        for idx, vk, fn in [(4, VK_F6, self.cycle_hero), (0, VK_F7, self.toggle_auto_hide),
                            (1, VK_F8, self.toggle_layout), (2, VK_F9, self.toggle_lock),
                            (3, VK_F10, self.toggle_visibility)]:
            self.hotkey_mgr.register(idx, vk, lambda f=fn: self.root.after(0, f))
        self.hotkey_mgr.start()

    def _apply_win32_styles(self) -> None:
        try:
            if self._stop_event.is_set():
                return
            if self._parked:
                # Not onscreen (or hidden again): wait for the next show.
                if not self._styles_applied:
                    self.root.after(500, self._apply_win32_styles)
                return
            if not self._styles_applied:
                # The first styles application must come AFTER the first
                # onscreen frame is painted and composed: applying the layered
                # styles to a never-painted window leaves its surface blank
                # forever. Pump a full update first so paint is guaranteed.
                self.root.update()
                self.root.update_idletasks()
            self._hwnd = make_overlay(self.root.winfo_id(), clickthrough=self._is_locked)
            self._styles_applied = True
            if self._hover_controls:
                self._hover_controls.sync_clickthrough()
        except Exception as err:
            print(f"[Overlay] win32 style error: {err}")

    # --------------------------------------------------------------- geometry
    def _base_metrics_for(self, slots: int):
        if bool(getattr(self.config, "icons_only", False)):
            return compute_icon_metrics(self.config.layout, slots, self._scale)
        return compute_metrics(
            self.config.layout,
            slots,
            self._scale,
            show_timer=bool(getattr(self.config, "show_timer", False)),
        )

    def _metrics_for(self, slots: int):
        """Window metrics: WPA strip plus the counter panel when it is shown."""
        base = self._base_metrics_for(slots)
        panel, _counters = counter_panel.panel_for(
            self._current_state, self.config, self._scale, base
        )
        return stack_metrics(base, panel) if panel is not None else base

    def _status_info(self) -> Tuple[str, str]:
        return get_status_info(self._current_state, self._feedback)

    def _badge_metrics(self, title: str = ""):
        if not title:
            title, _ = self._status_info()
        return compute_badge_metrics(
            self._scale,
            title,
            show_timer=bool(getattr(self.config, "show_timer", False)),
        )

    def _position_window(self, metrics: Optional[object] = None) -> None:
        """Dock to the corner, or restore the exact spot the user dragged it to."""
        position_window(self, metrics)

    def _apply_metrics(self, metrics) -> None:
        self._position_window(metrics)

    def _apply_geometry(self, slots: int) -> None:
        self._position_window(self._metrics_for(slots))

    def reposition_to_edge(self) -> None:
        """Re-dock flush right (tray menu / monitor changes)."""
        snap_to_edge(self)
        save_config(self.config)
        self._forced_visible = True
        self._user_hidden = False
        if self._content_kind != "hidden":
            self._position_window(self._metrics)
            self._update_visibility()

    def set_position(self, corner: str) -> None:
        """Tray: dock to a named corner of the current monitor."""
        applied = set_corner(self, corner)
        save_config(self.config)
        self._forced_visible = True
        self._user_hidden = False
        self._content_kind = None
        self._render_content()
        self.show_feedback(applied.replace("_", " ").upper(), "#38bdf8", 1400)

    def begin_move(self) -> None:
        """Tray / F9: unlock and make sure there is something on screen to grab."""
        if self._is_locked:
            self.toggle_lock()
        self._forced_visible = True
        self._user_hidden = False
        if self._content_kind == "hidden":
            self._content_kind = None
        self._render_content()
        self._update_visibility()
        self.show_feedback("MOVE", "#f59e0b")

    # ------------------------------------------------------------- visibility
    def _is_ingame(self) -> bool:
        return visibility.is_ingame()

    def _update_visibility(self) -> None:
        visibility.update(self)

    def _withdraw(self) -> None:
        visibility.withdraw(self)

    def hide_overlay(self) -> None:
        visibility.hide(self)

    def show_overlay(self) -> None:
        visibility.show(self)

    def toggle_visibility(self) -> None:
        visibility.toggle(self)

    def toggle_auto_hide(self) -> None:
        self.config.only_in_game = not self.config.only_in_game
        save_config(self.config)
        self._update_visibility()
        self.show_feedback("HIDE" if self.config.only_in_game else "SHOW", "#38bdf8")

    # ------------------------------------------------------------------ modes
    def toggle_lock(self) -> None:
        self._is_locked = not self._is_locked
        self.config.clickthrough = self._is_locked
        save_config(self.config)
        self.container.config(
            highlightthickness=0 if self._is_locked else 1,
            highlightbackground="#f59e0b",
        )
        if self._hover_controls:
            self._hover_controls.sync_clickthrough()
        self.show_feedback("MOVE" if not self._is_locked else "LOCK", "#f59e0b" if not self._is_locked else "#22c55e")

    def toggle_layout(self) -> None:
        self.config.layout = "horizontal" if self.config.layout == "vertical" else "vertical"
        save_config(self.config)
        self._content_kind = None
        self._render_content()

    def set_scale(self, value: float, persist=True, feedback=True) -> None:
        """Resize the whole HUD: cards, icons, gaps and every font."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 1.0
        value = max(0.75, min(2.0, value))
        self.config.hud_scale = value
        self._scale = ui_scale() * value
        if persist:
            save_config(self.config)
        self._content_kind = None
        self._render_content()
        if feedback:
            self.show_feedback(f"SIZE {int(round(value * 100))}%", theme.ACCENT)

    def toggle_view(self) -> None:
        if not getattr(self.data_source, "is_advisor", False):
            return
        self.config.view_mode = "minimal" if self.config.view_mode == "full" else "full"
        save_config(self.config)
        self._content_kind = None
        self._render_content()

    def open_settings(self) -> None:
        if self._settings is not None:
            self._settings.window.lift()
            self._settings.window.focus_force()
            return
        from ui.overlay_settings import SettingsPanel
        self._settings = SettingsPanel(self)
        if self._current_state.scan_status in (
            "needs_match", "needs_account", "connecting", "unknown", "broadcast_unavailable"
        ):
            if "Match" in self._settings.tab_buttons:
                self._settings.select_tab("Match")

    def cycle_hero(self) -> None:
        # SQLite stays on the worker thread; the UI only asks for the change.
        self._preview_event.set()
        self._wake_event.set()
        self.show_feedback(
            "NEXT HERO" if getattr(self.data_source, "is_advisor", False) else "PREVIEW",
            "#f59e0b",
        )
        # A preview must never mask the live Statlocker row for long: it is a
        # temporary look at another hero, then the overlay snaps back to live.
        if not getattr(self.data_source, "supports_preview_clear", True):
            # Advisor mode: F6 picks the hero to recommend for, so it persists.
            return
        self._preview_token += 1
        token = self._preview_token

        def _end_preview():
            if token != self._preview_token:
                return
            self._preview_clear_event.set()
            self._wake_event.set()
            self.show_feedback("LIVE", "#22c55e")

        self.root.after(12000, _end_preview)

    # ------------------------------------------------------------------- drag
    def _on_drag_start(self, event) -> None:
        self._drag_handler.on_start(event)

    def _on_drag_motion(self, event) -> None:
        self._drag_handler.on_motion(event)

    def _on_drag_stop(self, event) -> None:
        self._drag_handler.on_stop(event)

    # ----------------------------------------------------------------- render
    # ------------------------------------------------------------------- loop
    # --------------------------------------------------------------- lifecycle
    def close(self) -> None:
        self._stop_event.set()
        if self._hover_controls:
            self._hover_controls.close()
        if self._settings:
            self._settings.close()
        self._wake_event.set()
        for res, stopper in ((self._worker, lambda: self._worker.join(timeout=0.5) if self._worker.is_alive() else None),
                             (self.tray_manager, lambda: self.tray_manager.stop()),
                             (self.hotkey_mgr, lambda: self.hotkey_mgr.stop())):
            if res is not None:
                try: stopper()
                except Exception: pass
        try:
            self.root.destroy()
        except Exception:
            pass
        finally:
            from icon_loader import clear_photo_cache

            clear_photo_cache()

    def start(self) -> None:
        if self.tray_manager is not None:
            self.tray_manager.start()
        # Startup proof-of-life: an idle overlay parks itself, so flash how to
        # bring it back instead of leaving a silent launch.
        try:
            self.root.after(300, lambda: self.show_feedback("F10 SHOW", "#22c55e", 3500))
        except Exception:
            pass
        self.root.mainloop()
