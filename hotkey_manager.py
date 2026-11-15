"""Global Windows hotkeys via RegisterHotKey + a dedicated message pump."""

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Dict, List, Optional, Tuple

from win32_overlay import attach_to_default_desktop

user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000


class GlobalHotkeyManager:
    """Registers F-key hotkeys that fire even while Deadlock has focus."""

    def __init__(self) -> None:
        self._callbacks: Dict[int, Callable[[], None]] = {}
        self._key_defs: List[Tuple[int, int, int]] = []
        self._thread: Optional[threading.Thread] = None
        self._thread_id: int = 0
        self._running = False
        self._ready = threading.Event()
        self._registered: List[int] = []

    def register(
        self,
        hotkey_id: int,
        vk_code: int,
        callback: Callable[[], None],
        modifiers: int = MOD_NOREPEAT,
    ) -> None:
        """Queue a hotkey; registration happens when :meth:`start` runs."""
        if any(entry[0] == hotkey_id for entry in self._key_defs):
            self._key_defs = [entry for entry in self._key_defs if entry[0] != hotkey_id]
        self._callbacks[hotkey_id] = callback
        self._key_defs.append((hotkey_id, vk_code, modifiers))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._message_loop, name="HotkeyPump", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _message_loop(self) -> None:
        attach_to_default_desktop()
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        for hotkey_id, vk_code, modifiers in self._key_defs:
            if user32.RegisterHotKey(None, hotkey_id, modifiers, vk_code):
                self._registered.append(hotkey_id)
            else:
                print(f"[Hotkeys] RegisterHotKey failed for id={hotkey_id} vk=0x{vk_code:02X}")
        self._ready.set()

        message = wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if ret <= 0 or message.message == WM_QUIT:
                break
            if message.message == WM_HOTKEY:
                callback = self._callbacks.get(int(message.wParam))
                if callback:
                    try:
                        callback()
                    except Exception as err:
                        print(f"[Hotkeys] Callback error: {err}")

        for hotkey_id in self._registered:
            user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()

    def stop(self) -> None:
        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
