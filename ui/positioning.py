"""Window placement: monitor selection, dock origin and exact placement.

Pure geometry lives in :func:`resolve_origin`; the rest only touches the
overlay through this small contract:

    overlay.config          OverlayConfig (position + corner live here)
    overlay.root            tk.Tk
    overlay._metrics        HudMetrics of the current view
    overlay._anchor_origin  (left, top) of the monitor the HUD is pinned to
    overlay._parked         True while the window sits parked offscreen
"""

from typing import Optional, Tuple

from ui.hud_geometry import HudMetrics, clamp_y
from win32_overlay import find_process_window_rect, get_monitor_layouts, monitor_for_rect

GAME_EXECUTABLES = ("deadlock.exe", "project8.exe")
CORNERS = ("top_right", "top_left", "bottom_right", "bottom_left")

# config.y sentinel: "dock to the corner instead of using an exact y".
AUTO_Y = 120

Rect = Tuple[int, int, int, int]


def dock_bounds(overlay) -> Tuple[Rect, Rect]:
    """((monitor left,top,right,bottom), (work area)) of the anchor monitor.

    Sticks to the monitor the window is already on; when parked offscreen (or
    on first show) follows the game window's monitor; falls back to the
    primary monitor.  Single-monitor setups always resolve to primary.
    """
    layouts = get_monitor_layouts()
    if len(layouts) == 1:
        return layouts[0]
    if overlay._anchor_origin is not None:
        for full, work in layouts:
            if (full[0], full[1]) == overlay._anchor_origin:
                return full, work
    try:
        wx, wy = int(overlay.root.winfo_x()), int(overlay.root.winfo_y())
        if wx > -10000:
            return layouts[monitor_for_rect((wx, wy, wx + 1, wy + 1), layouts)]
    except Exception:
        pass
    try:
        game_rect = find_process_window_rect(GAME_EXECUTABLES)
    except Exception:
        game_rect = None
    if game_rect is not None:
        return layouts[monitor_for_rect(game_rect, layouts)]
    return layouts[0]


def is_docked(config) -> bool:
    """True when the HUD follows its corner instead of an exact dragged spot."""
    return not bool(getattr(config, "positioned", False)) and int(
        getattr(config, "x", 0) or 0
    ) == 0


def resolve_origin(
    metrics: HudMetrics,
    config,
    monitor: Rect,
    work: Rect,
) -> Tuple[int, int]:
    """Exact top-left pixel of the window for this config, monitor and size.

    Dock mode (default) is flush inside the corner named by ``config.corner``.
    A dragged window keeps its pixel position verbatim, including x == 0 (the
    left edge), which dock mode also uses as its sentinel.
    """
    mon_left, mon_top, monitor_right, _mon_bottom = monitor
    work_left, work_top, work_right, work_bottom = work
    right = min(monitor_right, work_right)
    corner = str(getattr(config, "corner", "top_right")).lower()
    if corner not in CORNERS:
        corner = "top_right"

    max_x = max(work_left, right - metrics.width)
    if is_docked(config):
        x = work_left if corner.endswith("left") else max_x
    else:
        x = max(work_left, min(int(getattr(config, "x", 0) or 0), max_x))

    requested_y = int(getattr(config, "y", AUTO_Y))
    if bool(getattr(config, "positioned", False)):
        y = clamp_y(metrics, requested_y, work_top, work_bottom)
    elif requested_y == AUTO_Y:
        if corner.startswith("bottom"):
            y = max(work_top, work_bottom - metrics.height)
        else:
            y = work_top
    else:
        y = clamp_y(metrics, requested_y, work_top, work_bottom)

    del mon_left, mon_top  # kept for readability of the unpack above
    return int(x), int(y)


def position_window(overlay, metrics: Optional[HudMetrics] = None) -> None:
    """Move the window to its resolved origin and mark it on screen."""
    if metrics is not None:
        overlay._metrics = metrics
    monitor, work = dock_bounds(overlay)
    overlay._anchor_origin = (monitor[0], monitor[1])
    x, y = resolve_origin(overlay._metrics, overlay.config, monitor, work)
    overlay.root.geometry(f"{overlay._metrics.width}x{overlay._metrics.height}+{x}+{y}")
    overlay.root.update_idletasks()
    overlay._parked = False


def set_corner(overlay, corner: str) -> str:
    """Switch to a docked corner preset; returns the corner actually applied."""
    corner = str(corner or "").lower()
    if corner not in CORNERS:
        corner = "top_right"
    overlay.config.corner = corner
    overlay.config.positioned = False
    overlay.config.x = 0
    overlay.config.y = AUTO_Y
    return corner


def snap_to_edge(overlay) -> None:
    """Re-dock flush against the anchor monitor's right edge."""
    overlay.config.x = 0
    overlay.config.positioned = False
    overlay.config.corner = "top_right"
