"""Find the local Deadlock account id from the game folder file name.

Deadlock writes ``account_<id>.stats`` next to its config.  Only the file name
is read; the contents are never touched.  This id is the ``m_unEconAccountID``
the live broadcast reports, so it identifies the local player in a match.
"""

import os
import threading
import time
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_CACHE: dict = {"id": None, "at": None}
DISCOVERY_TTL_S = 60.0
STEAM64_BASE = 76561197960265728


def normalize_account_id(value) -> Optional[int]:
    """Accept a Steam account ID or the equivalent individual SteamID64."""
    digits = str(value).strip()
    if not digits.isascii() or not digits.isdecimal() or len(digits) > 20:
        return None
    number = int(digits)
    if number >= STEAM64_BASE:
        number -= STEAM64_BASE
    return number if 0 < number < 2**32 else None


def _running_game_directory() -> Optional[Path]:
    """Use the game process path to support Steam libraries on other drives."""
    try:
        import ctypes
        from ctypes import wintypes
        from win32_overlay import _exe_of_process, user32

        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, "Deadlock")
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = Path(_exe_of_process(pid.value))
        if path.name.lower() not in ("deadlock.exe", "project8.exe"):
            return None
        return path.parents[2] / "citadel"
    except (AttributeError, IndexError, OSError):
        return None


def _candidate_dirs() -> list:
    dirs = []
    override = os.environ.get("DEADLOCK_DIR")
    if override:
        dirs.append(Path(override))
    running = _running_game_directory()
    if running is not None:
        dirs.append(running)
    program_files = os.environ.get("PROGRAMFILES(X86)") or r"C:\Program Files (x86)"
    dirs.append(Path(program_files) / "Steam" / "steamapps" / "common" / "Deadlock" / "game" / "citadel")
    return dirs


def find_account_id() -> Optional[int]:
    """Find exactly one account by filename; ambiguity and misses are unknown."""
    with _LOCK:
        now = time.monotonic()
        if _CACHE["at"] is not None and now - _CACHE["at"] < DISCOVERY_TTL_S:
            return _CACHE["id"]
        found = set()
        for directory in _candidate_dirs():
            try:
                for path in directory.glob("account_*.stats"):
                    digits = path.stem.split("_", 1)[-1]
                    if digits.isdigit() and len(digits) >= 5:
                        found.add(int(digits))
            except OSError:
                continue
        account = next(iter(found)) if len(found) == 1 else None
        _CACHE["id"], _CACHE["at"] = account, now
        return account
