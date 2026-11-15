"""Statlocker window discovery, capture and "WPA ITEMS" header detection.

All capture happens on the polling thread, never on Tkinter's thread, and the
header search is cached: a cheap local re-check around the last known position
runs first, the expensive full-window FFT scan only when that fails.
"""

import ctypes
import ntpath
import sys
from ctypes import wintypes
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from template_match import TemplateHit, find_template

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

HBITMAP = getattr(wintypes, "HBITMAP", wintypes.HANDLE)
HGDIOBJ = getattr(wintypes, "HGDIOBJ", wintypes.HANDLE)

# --- ctypes prototypes (avoid 64-bit handle truncation) ---------------------
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, HGDIOBJ]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    TMPL_PATH = Path(sys._MEIPASS) / "assets" / "wpa_items_header.png"
else:
    TMPL_PATH = Path(__file__).resolve().parent / "assets" / "wpa_items_header.png"

_TMPL_ARR: Optional[np.ndarray] = None
_LAST_FOUND_POS: Optional[Tuple[int, int]] = (1044, 449)
_LAST_SCALE: float = 1.0
_LAST_HWND: Optional[int] = None

# Scales cover 100 %, 125 % and 150 % Windows scaling plus Statlocker zoom.
_SCALES = (1.0, 1.1, 1.25, 1.4, 0.9, 0.8, 1.6)

# Window titles Statlocker Companion is known to use.
_WINDOW_TITLES = ("statlocker companion", "statlocker-companion", "statlocker")

# A browser tab titled "statlocker.gg/..." is not the Companion app and can
# contain advertisement thumbnails of the WPA panel, which would otherwise be
# read as live recommendations.
_BROWSER_EXECUTABLES = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
        "opera_gx.exe",
        "vivaldi.exe",
        "librewolf.exe",
        "waterfox.exe",
    }
)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


@dataclass
class CapturedFrame:
    """A captured Statlocker window frame in window-relative coordinates."""

    hwnd: int
    rgb: np.ndarray  # uint8, shape (h, w, 3)
    rect: Tuple[int, int, int, int]  # screen (left, top, right, bottom)
    method: str = "printwindow"

    @cached_property
    def gray(self) -> np.ndarray:
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        return (self.rgb.astype(np.float32) @ weights).astype(np.float32)

    @property
    def size(self) -> Tuple[int, int]:
        return int(self.rgb.shape[1]), int(self.rgb.shape[0])


def _find_template_file() -> Optional[Path]:
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "wpa_items_header.png")
        candidates.append(Path(sys._MEIPASS) / "wpa_items_header.png")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "assets" / "wpa_items_header.png")
    candidates.append(Path(__file__).resolve().parent / "assets" / "wpa_items_header.png")
    candidates.append(Path.cwd() / "assets" / "wpa_items_header.png")
    for c in candidates:
        if c.exists():
            return c
    return None


def _ensure_template_loaded() -> bool:
    """Load the header template once; returns False when the asset is missing."""
    global _TMPL_ARR
    if _TMPL_ARR is not None:
        return True
    tmpl_file = _find_template_file()
    if not tmpl_file:
        print("[WpaDetector] Template file not found!")
        return False
    try:
        _TMPL_ARR = np.array(Image.open(tmpl_file).convert("L"), dtype=np.float32)
        print(f"[WpaDetector] Loaded template {tmpl_file}, shape={_TMPL_ARR.shape}")
        return _TMPL_ARR.size > 0
    except Exception as err:
        print(f"[WpaDetector] Failed to open {tmpl_file}: {err}")
        _TMPL_ARR = None
        return False


def template_shape() -> Optional[Tuple[int, int]]:
    """Return ``(height, width)`` of the header template, if available."""
    if not _ensure_template_loaded() or _TMPL_ARR is None:
        return None
    return int(_TMPL_ARR.shape[0]), int(_TMPL_ARR.shape[1])


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value


def _window_process_path(hwnd: int) -> str:
    """Full path of the process owning ``hwnd`` ("" when it cannot be read)."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _companion_priority(title: str, executable_path: str) -> int:
    """0 = Companion process, 1 = explicit Companion title, 2 = ignore."""
    lower_title = (title or "").lower()
    executable = ntpath.basename(executable_path or "").lower()

    if lower_title.startswith("com.statlocker"):
        return 2  # IPC single-instance message window, not UI
    if "statlocker" in executable:
        if "companion" in lower_title or "statlocker" in lower_title:
            return 0
        return 1
    if "statlocker" not in lower_title:
        return 2
    if executable in _BROWSER_EXECUTABLES:
        # Only an explicit "Statlocker Companion" tab, never statlocker.gg.
        return 1 if "companion" in lower_title else 2
    if "companion" in lower_title:
        return 1
    return 2


def _get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < 320 or height < 240:
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def _find_statlocker_hwnd() -> Optional[int]:
    """Return the visible Statlocker Companion window handle.

    The Companion process is preferred over everything else.  Browser windows
    are only accepted when their title explicitly says "Statlocker Companion",
    because a normal statlocker.gg tab contains ad thumbnails of the WPA panel.
    """
    try:
        from win32_overlay import attach_to_default_desktop
        attach_to_default_desktop()
    except Exception:
        pass
    global _LAST_HWND
    if _LAST_HWND and user32.IsWindow(_LAST_HWND) and user32.IsWindowVisible(_LAST_HWND):
        if not user32.IsIconic(_LAST_HWND) and _get_window_rect(_LAST_HWND) is not None:
            title = _window_title(_LAST_HWND)
            if _companion_priority(title, _window_process_path(_LAST_HWND)) <= 1:
                return _LAST_HWND
        _LAST_HWND = None

    best: Optional[int] = None
    best_priority = 2

    def enum_cb(hwnd, _lparam):
        nonlocal best, best_priority
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if not _get_window_rect(hwnd):
            return True
        title = _window_title(hwnd)
        lower = title.lower()
        proc_path = _window_process_path(hwnd)
        if "statlocker" not in lower and "statlocker" not in proc_path:
            return True
        priority = _companion_priority(lower, proc_path)
        if priority < best_priority:
            best = hwnd
            best_priority = priority
            if priority == 0:
                return False  # Companion wins; stop enumerating
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    _LAST_HWND = best
    return best


def is_statlocker_open() -> bool:
    """True when a Statlocker window is currently on screen."""
    return _find_statlocker_hwnd() is not None



def _bitmap_to_rgb(source_dc: int, bitmap: int, width: int, height: int) -> Optional[np.ndarray]:
    """Read a GDI bitmap into an RGB numpy array."""
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buffer = ctypes.create_string_buffer(width * height * 4)
    copied = gdi32.GetDIBits(source_dc, bitmap, 0, height, buffer, ctypes.byref(bmi), 0)
    if not copied:
        return None
    arr = np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4))
    # GDI 32-bit BI_RGB pixels are BGRA; the rest of the pipeline is RGB.
    return np.ascontiguousarray(arr[:, :, 2::-1])


def _capture_with(hwnd: int, width: int, height: int, mode: str) -> Optional[np.ndarray]:
    """Capture the window with PrintWindow or a plain BitBlt."""
    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    rgb: Optional[np.ndarray] = None
    try:
        if mode == "printwindow":
            ok = user32.PrintWindow(hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT
            if not ok:
                ok = user32.PrintWindow(hwnd, mem_dc, 0)
            if not ok:
                return None
        else:
            if not gdi32.BitBlt(mem_dc, 0, 0, width, height, window_dc, 0, 0, 0x00CC0020):
                return None
        rgb = _bitmap_to_rgb(mem_dc, bitmap, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, window_dc)
    return rgb


def _capture_from_screen(rect: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
    """Last-resort desktop capture of the window rectangle (window must be visible)."""
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    screen_dc = user32.GetDC(0)
    if not screen_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, left, top, 0x00CC0020):
            return None
        return _bitmap_to_rgb(mem_dc, bitmap, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)


def capture_statlocker_frame() -> Optional[CapturedFrame]:
    """Capture the Statlocker window, trying cheap and robust methods in order."""
    hwnd = _find_statlocker_hwnd()
    if not hwnd or user32.IsIconic(hwnd):
        return None
    rect = _get_window_rect(hwnd)
    if not rect:
        return None
    width, height = rect[2] - rect[0], rect[3] - rect[1]

    attempts = (
        ("printwindow", lambda: _capture_with(hwnd, width, height, "printwindow")),
        ("bitblt", lambda: _capture_with(hwnd, width, height, "bitblt")),
        ("screen", lambda: _capture_from_screen(rect)),
    )
    for method, capture in attempts:
        rgb = capture()
        if rgb is None or rgb.size == 0:
            continue
        # Reject black / uniform frames produced by some GPU composited apps.
        if float(np.std(rgb)) < 2.0:
            continue
        return CapturedFrame(hwnd=hwnd, rgb=rgb, rect=rect, method=method)
    return None


def locate_wpa_header(frame: "CapturedFrame") -> Optional[TemplateHit]:
    """Find the WPA ITEMS heading inside a captured frame."""
    global _LAST_FOUND_POS, _LAST_SCALE
    if not _ensure_template_loaded() or _TMPL_ARR is None:
        return None

    gray = frame.gray
    th, tw = _TMPL_ARR.shape

    # 1) Cheap local re-check around the previous position.
    if _LAST_FOUND_POS:
        lx, ly = _LAST_FOUND_POS
        pad = 28
        x0 = max(0, lx - pad)
        y0 = max(0, ly - pad)
        x1 = min(gray.shape[1], lx + tw + pad)
        y1 = min(gray.shape[0], ly + th + pad)
        if x1 - x0 > tw + 4 and y1 - y0 > th + 4:
            local = find_template(
                gray[y0:y1, x0:x1],
                _TMPL_ARR,
                scales=(_LAST_SCALE,),
                min_score=0.80,
                max_scan_dim=10_000,
            )
            if local:
                _LAST_FOUND_POS = (x0 + local.x, y0 + local.y)
                return TemplateHit(
                    x=x0 + local.x,
                    y=y0 + local.y,
                    score=local.score,
                    scale=_LAST_SCALE,
                    width=local.width,
                    height=local.height,
                )

    # 2) Full-window scan, preferring the last known scale.
    ordered = _ordered_scales(_LAST_SCALE)
    hit = find_template(gray, _TMPL_ARR, scales=ordered, min_score=0.72)
    if hit is None:
        return None
    _LAST_FOUND_POS = (hit.x, hit.y)
    _LAST_SCALE = hit.scale
    return hit


def _ordered_scales(preferred: float) -> tuple:
    rest = tuple(scale for scale in _SCALES if abs(scale - preferred) > 1e-3)
    return (preferred,) + rest


def is_wpa_items_visible_in_statlocker() -> bool:
    """True only when the WPA ITEMS heading is currently rendered."""
    frame = capture_statlocker_frame()
    if frame is None:
        return False
    return locate_wpa_header(frame) is not None


def reset_detection_cache() -> None:
    """Forget cached window/position/scale (used by diagnostics)."""
    global _LAST_FOUND_POS, _LAST_SCALE, _LAST_HWND
    _LAST_FOUND_POS = None
    _LAST_SCALE = 1.0
    _LAST_HWND = None
