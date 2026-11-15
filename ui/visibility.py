"""Show/hide policy for the overlay window.

The window is *never* withdrawn: withdrawing an ``overrideredirect`` window
permanently breaks its repaint.  "Hidden" means parked at the offscreen
coordinates below, which keeps the layered surface intact across show/hide.
"""

from ui.positioning import GAME_EXECUTABLES
from win32_overlay import ensure_topmost, is_foreground_process, is_process_running

_PARK_X, _PARK_Y = -32000, -32000
_STYLE_DELAY_MS = 800


def is_ingame() -> bool:
    """True when Deadlock is running."""
    return any(is_process_running(name) for name in GAME_EXECUTABLES)


def should_park(overlay) -> bool:
    """True when the window must stay parked offscreen right now.

    An explicit Show (``_forced_visible``) outranks the "only in game" /
    "only when focused" rules: the user asked to see it, so it shows.
    """
    if overlay._user_hidden:
        return True
    if overlay._forced_visible:
        return False
    if overlay._content_kind == "hidden":
        return True
    if getattr(overlay, "_settings", None) is not None:
        return False
    if overlay.config.only_when_focused and not any(
        is_foreground_process(name, self_hwnd=overlay._hwnd) for name in GAME_EXECUTABLES
    ):
        return True
    if overlay.config.only_in_game and not is_ingame():
        return True
    return False


def update(overlay) -> None:
    """Apply the visibility rules to the current content and config."""
    if should_park(overlay):
        withdraw(overlay)
        return
    if overlay._parked:
        overlay._position_window(overlay._metrics)
        if overlay._hwnd:
            try:
                ensure_topmost(overlay._hwnd)
            except Exception:
                pass
        if not overlay._styles_applied:
            # Delay past several compositor frames so the first onscreen paint
            # lands before the layered styles redirect the surface.
            overlay.root.after(_STYLE_DELAY_MS, overlay._apply_win32_styles)


def withdraw(overlay) -> None:
    """Park the window offscreen (much safer than withdrawing it)."""
    try:
        overlay.root.geometry(
            f"{overlay._metrics.width}x{overlay._metrics.height}+{_PARK_X}+{_PARK_Y}"
        )
        overlay.root.update_idletasks()
    except Exception:
        pass
    overlay._parked = True


def hide(overlay) -> None:
    """User-requested hide (F10 / tray)."""
    overlay._user_hidden = True
    overlay._forced_visible = False
    if getattr(overlay, "_settings", None) is not None:
        overlay._settings.close()
    update(overlay)


def show(overlay) -> None:
    """User-requested show: always renders something to grab.

    With ``standby_badge`` off and Statlocker showing no recommendations the
    content would normally be "hidden", which made show feel broken.  A
    force-shown badge gives the user a visible anchor to find and drag.
    """
    overlay._user_hidden = False
    overlay._forced_visible = True
    overlay._content_kind = None
    overlay._render_content()


def toggle(overlay) -> None:
    """F10 / tray "Show / Hide".

    Decides from what is actually on screen, not from the flag: an idle
    overlay is parked without being user-hidden, and pressing the key there
    must bring it back rather than appear to do nothing.
    """
    if overlay._parked or overlay._user_hidden:
        show(overlay)
    else:
        hide(overlay)
