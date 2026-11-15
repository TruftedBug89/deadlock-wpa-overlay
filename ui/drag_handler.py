"""Window drag-and-drop controller for the overlay window."""

from typing import TYPE_CHECKING
from config import save_config
from ui.hud_geometry import clamp_y
from win32_overlay import get_monitor_layouts, monitor_for_rect

if TYPE_CHECKING:
    from ui.main_window import OverlayWindow


class WindowDragHandler:
    """Manages root-delta mouse dragging and border-dock snapping."""

    def __init__(self, overlay: "OverlayWindow"):
        self.overlay = overlay
        self.start_x = 0
        self.start_y = 0
        self.win_x = 0
        self.win_y = 0
        self.active = False

    def on_start(self, event) -> None:
        hover = getattr(self.overlay, "_hover_controls", None)
        if self.overlay._is_locked and not (hover and hover.active):
            return
        if getattr(getattr(event, "widget", None), "winfo_class", lambda: "")() in ("Button", "Checkbutton", "Radiobutton", "Scale"):
            return
        self.active = True
        self.overlay.root.grab_set()
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.win_x = int(self.overlay.root.winfo_x())
        self.win_y = int(self.overlay.root.winfo_y())

    def on_motion(self, event) -> None:
        if not self.active:
            return
        dx = event.x_root - self.start_x
        dy = event.y_root - self.start_y
        self.overlay.root.geometry(f"+{self.win_x + dx}+{self.win_y + dy}")

    def on_stop(self, _event) -> None:
        if not self.active:
            return
        self.active = False
        self.overlay.root.grab_release()
        cur_x, cur_y = int(self.overlay.root.winfo_x()), int(self.overlay.root.winfo_y())
        layouts = get_monitor_layouts()
        _full, (wl, wt, wr, wb) = layouts[
            monitor_for_rect((cur_x, cur_y, cur_x + 1, cur_y + 1), layouts)
        ]
        _ml, _mt, mon_r, _mb = _full
        self.overlay._anchor_origin = (_full[0], _full[1])
        right = min(mon_r, wr)
        width = self.overlay._metrics.width
        edge_x = right - width
        left_x = wl
        if abs(cur_x - edge_x) <= 25 or cur_x >= edge_x:
            # Flush against the right edge snaps back into corner-dock mode.
            self.overlay.config.x = 0
            self.overlay.config.positioned = False
            self.overlay.config.corner = "top_right"
        elif abs(cur_x - left_x) <= 25 or cur_x <= left_x:
            # Left edge docks to the top-left corner instead of a pixel spot.
            self.overlay.config.x = 0
            self.overlay.config.positioned = False
            self.overlay.config.corner = "top_left"
        else:
            self.overlay.config.x = max(wl, min(cur_x, edge_x))
            self.overlay.config.positioned = True
        self.overlay.config.y = clamp_y(self.overlay._metrics, cur_y, wt, wb)
        save_config(self.overlay.config)
        self.overlay._position_window(self.overlay._metrics)
        self.overlay._render_content()
