"""Windows notification-area (system tray) integration.

The icon is created when the overlay starts.  Windows 11 hides new tray icons in
the overflow flyout by default, so after the icon registers itself this module
watches ``HKCU\\Control Panel\\NotifyIconSettings`` for the *new* entry and sets
``IsPromoted = 1`` (the same switch as dragging the icon onto the taskbar).
Only entries created by this process - or entries whose name/path clearly belong
to this app - are touched, never other applications' icons.
"""

import sys
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import Menu, MenuItem

from win32_overlay import attach_to_default_desktop, set_app_user_model_id

_NOTIFY_KEY = r"Control Panel\NotifyIconSettings"
_APP_ID = "Deadlock.WPA.Overlay"
_ICON_HINTS = ("deadlockwpaoverlay", "deadlock wpa", "deadlock-wpa", "deadlock")


def _get_tray_icon_image() -> Image.Image:
    """Bundled tray artwork, or a generated 64x64 fallback."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        icon_path = Path(sys._MEIPASS) / "assets" / "tray_icon.png"
    else:
        icon_path = Path(__file__).resolve().parent / "assets" / "tray_icon.png"

    if icon_path.exists():
        try:
            image = Image.open(icon_path).convert("RGBA")
            return image.resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            pass

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [2, 2, size - 3, size - 3], radius=14, fill=(12, 15, 19, 255), outline=(222, 139, 0, 255), width=3
    )
    try:
        font = ImageFont.truetype("segoeuib.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "W", font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - text_w) / 2, (size - text_h) / 2 - bbox[1] - 2),
        "W",
        fill=(255, 255, 255, 255),
        font=font,
    )
    draw.rectangle([20, size - 12, size - 20, size - 9], fill=(222, 139, 0, 255))
    return image


# --------------------------------------------------------------------- registry
def snapshot_notify_icons() -> Set[str]:
    """Subkey names currently present under NotifyIconSettings."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _NOTIFY_KEY, 0, winreg.KEY_READ) as key:
            count = winreg.QueryInfoKey(key)[0]
            names = set()
            for index in range(count):
                try:
                    names.add(winreg.EnumKey(key, index))
                except OSError:
                    break
            return names
    except Exception:
        return set()


def new_icon_keys(before: Set[str], after: Set[str]) -> Set[str]:
    """Pure helper: registry entries that appeared after the snapshot."""
    return set(after) - set(before)


def icon_belongs_to_app(executable_path: str, icon_name: str = "") -> bool:
    """True when a tray registry entry looks like ours."""
    haystack = f"{executable_path or ''} {icon_name or ''}".lower()
    return any(hint in haystack for hint in _ICON_HINTS)


def promote_icon_keys(keys: Iterable[str]) -> List[str]:
    """Set IsPromoted=1 on the given NotifyIconSettings entries."""
    promoted: List[str] = []
    try:
        import winreg
    except Exception:
        return promoted

    for key_name in keys:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, rf"{_NOTIFY_KEY}\{key_name}", 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, "IsPromoted", 0, winreg.REG_DWORD, 1)
            promoted.append(key_name)
        except Exception:
            continue
    return promoted


# ----------------------------------------------------------------------- tray
class TrayManager:
    """Owns the pystray icon and keeps it pinned to the taskbar corner."""

    def __init__(self, overlay_window, config=None):
        self.overlay = overlay_window
        self.config = config if config is not None else getattr(overlay_window, "config", None)
        self._icon: Optional[pystray.Icon] = None
        self._running = False
        self._lock = threading.Lock()
        self._before_keys = snapshot_notify_icons()
        self._promoted: Set[str] = set()
        self._setup_icon()

    # ------------------------------------------------------------------ build
    def _setup_icon(self) -> None:
        image = _get_tray_icon_image()

        def on_thread(action):
            def _run(icon=None, item=None):
                try:
                    self.overlay.root.after(0, action)
                except Exception:
                    pass

            return _run

        def set_corner(corner):
            return on_thread(lambda: self.overlay.set_position(corner))

        menu = Menu(
            MenuItem("Show / Hide Overlay  (F10)", on_thread(self.overlay.toggle_visibility), default=True),
            MenuItem("Move Overlay  (F9)", on_thread(self.overlay.begin_move)),
            MenuItem("Overlay Settings", on_thread(lambda: self.overlay.open_settings())),
            MenuItem(
                "Position",
                Menu(
                    MenuItem("Top Right", set_corner("top_right")),
                    MenuItem("Top Left", set_corner("top_left")),
                    MenuItem("Bottom Right", set_corner("bottom_right")),
                    MenuItem("Bottom Left", set_corner("bottom_left")),
                    Menu.SEPARATOR,
                    MenuItem("Snap to Right Edge", on_thread(self.overlay.reposition_to_edge)),
                ),
            ),
            MenuItem("Toggle Layout  (F8)", on_thread(self.overlay.toggle_layout)),
            MenuItem(
                "Size",
                Menu(
                    MenuItem("Small  80%", on_thread(lambda: self.overlay.set_scale(.8))),
                    MenuItem("Normal  100%", on_thread(lambda: self.overlay.set_scale(1.0))),
                    MenuItem("Large  125%", on_thread(lambda: self.overlay.set_scale(1.25))),
                    MenuItem("Extra large  150%", on_thread(lambda: self.overlay.set_scale(1.5))),
                ),
            ),
            Menu.SEPARATOR,
            MenuItem("Pin Tray Icon", lambda icon, item: self.promote_now()),
            Menu.SEPARATOR,
            MenuItem("Exit", on_thread(self.overlay.close)),
        )

        self._icon = pystray.Icon(
            name="DeadlockWPAOverlay",
            icon=image,
            title="Deadlock WPA Overlay",
            menu=menu,
        )

    # ------------------------------------------------------------- promotions
    def _promote_once(self) -> None:
        """Find our registry entry and mark it promoted."""
        current = snapshot_notify_icons()
        new_keys = new_icon_keys(self._before_keys, current)

        candidates: Set[str] = set()
        for key_name in current:
            if key_name in self._promoted:
                continue
            info = self._read_icon_values(key_name)
            exe = info.get("ExecutablePath", "")
            name = info.get("InitialTooltip") or info.get("Tooltip") or info.get("Name") or ""
            if icon_belongs_to_app(exe, name):
                candidates.add(key_name)
            elif key_name in new_keys and (not exe or not name):
                # When Windows 11 creates a fresh entry, attributes may arrive incrementally
                candidates.add(key_name)

        if not candidates:
            return
        promoted = promote_icon_keys(candidates)
        self._promoted.update(promoted)

    @staticmethod
    def _read_icon_values(key_name: str) -> dict:
        values: dict = {}
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{_NOTIFY_KEY}\{key_name}", 0, winreg.KEY_READ) as key:
                for value_name in (
                    "ExecutablePath",
                    "InitialTooltip",
                    "Tooltip",
                    "Name",
                    "UID",
                    "IsPromoted",
                    "IconGuid",
                ):
                    try:
                        values[value_name], _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
        except Exception:
            pass
        return values

    def _promotion_worker(self) -> None:
        for delay in (0.3, 0.8, 1.5, 3.0, 6.0, 12.0, 20.0):
            time.sleep(delay)
            if not self._running:
                return
            try:
                self._promote_once()
            except Exception:
                pass

    def promote_now(self) -> None:
        """Manual "Pin Tray Icon" action from the menu."""
        threading.Thread(target=self._promote_once, daemon=True).start()

    # ------------------------------------------------------------------- state
    def _on_setup(self, icon: pystray.Icon) -> None:
        attach_to_default_desktop()
        set_app_user_model_id(_APP_ID)
        try:
            icon.visible = True
        except Exception:
            return

        if self.config is not None and getattr(self.config, "tray_promote", True):
            threading.Thread(target=self._promotion_worker, daemon=True).start()

        if self.config is not None and getattr(self.config, "tray_notify", False):
            try:
                icon.notify("Overlay active - right-click the tray icon to pin it.", "Deadlock WPA Overlay")
            except Exception:
                pass

    def set_status(self, text: str) -> None:
        """Update the tooltip without touching the menu."""
        icon = self._icon
        if icon is None:
            return
        try:
            if icon.title != text:
                icon.title = text
        except Exception:
            pass

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        with self._lock:
            if self._running or self._icon is None:
                return
            self._running = True
            try:
                orig_run = self._icon._run

                def _run_with_desktop():
                    attach_to_default_desktop()
                    set_app_user_model_id(_APP_ID)
                    return orig_run()

                self._icon._run = _run_with_desktop
                self._icon.run_detached(setup=self._on_setup)
            except Exception as err:
                self._running = False
                print(f"[Tray] Failed to start tray icon: {err}")

    def stop(self) -> None:
        with self._lock:
            if not self._running or self._icon is None:
                return
            self._running = False
            try:
                self._icon.stop()
            except Exception as err:
                print(f"[Tray] Failed to stop tray icon: {err}")
