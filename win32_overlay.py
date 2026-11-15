"""Native Windows integration: DPI, overlay styles, screen bounds, processes.

Everything here is defensive: any Win32 call may fail on an exotic setup and the
overlay must keep running, so failures degrade to a safe default instead of
raising.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Dict, Optional, Tuple

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Explicit pointer widths are required on 64-bit Windows. ctypes otherwise
# truncates HANDLE/HWND return values to a signed 32-bit integer.
for _function, _arguments, _result in (
    (kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
    (kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
    (kernel32.QueryFullProcessImageNameW,
     [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
    (kernel32.CreateToolhelp32Snapshot, [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
    (kernel32.Process32FirstW, [wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
    (kernel32.Process32NextW, [wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
    (user32.GetForegroundWindow, [], wintypes.HWND),
    (user32.GetAncestor, [wintypes.HWND, wintypes.UINT], wintypes.HWND),
    (user32.GetWindowThreadProcessId, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
    (user32.GetWindowRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
    (user32.IsWindowVisible, [wintypes.HWND], wintypes.BOOL),
    (user32.IsIconic, [wintypes.HWND], wintypes.BOOL),
):
    _function.argtypes, _function.restype = _arguments, _result

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

SetWindowLongPtr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
SetWindowLongPtr.restype = ctypes.c_ssize_t

GetWindowLongPtr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongPtr.restype = ctypes.c_ssize_t

_DPI_AWARE = False
_DPI_CHECKED = False
_ATTACHED = threading.local()
_PROCESS_CACHE: Dict[str, Tuple[float, bool]] = {}
_PROCESS_LOCK = threading.Lock()


def enable_dpi_awareness() -> bool:
    """Declare system DPI awareness so pixel math matches real screen pixels.

    Must run before Tk creates a window.  Returns True when the process is
    DPI aware afterwards.
    """
    global _DPI_AWARE, _DPI_CHECKED
    if _DPI_CHECKED:
        return _DPI_AWARE
    _DPI_CHECKED = True
    try:
        shcore = ctypes.windll.shcore
        shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        _DPI_AWARE = True
    except Exception:
        try:
            _DPI_AWARE = bool(user32.SetProcessDPIAware())
        except Exception:
            _DPI_AWARE = False
    return _DPI_AWARE


def ui_scale() -> float:
    """Effective UI scale factor (1.0 at 96 DPI, 1.5 at 150 %)."""
    if not _DPI_AWARE:
        return 1.0
    try:
        dpi = int(user32.GetDpiForSystem())
        if 48 <= dpi <= 480:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def attach_to_default_desktop() -> bool:
    """Attach the calling thread to the interactive 'Default' desktop (once)."""
    if getattr(_ATTACHED, "done", False):
        return True
    try:
        flags = 0x01FF  # DESKTOP_ALL
        handle = user32.OpenDesktopW("Default", 0, False, flags)
        if handle:
            result = bool(user32.SetThreadDesktop(handle))
            _ATTACHED.done = True
            _ATTACHED.handle = handle  # keep alive for the thread's lifetime
            return result
    except Exception as err:
        print(f"[win32] Failed to attach to Default desktop: {err}")
    return False


def get_root_hwnd(hwnd: int) -> int:
    """Resolve a child window id (Tk) to its true top-level owner window."""
    root = user32.GetAncestor(hwnd, 3)  # GA_ROOTOWNER
    if root:
        return root
    parent = user32.GetParent(hwnd)
    return parent if parent else hwnd


def make_overlay(hwnd: int, clickthrough: bool = True) -> int:
    """Apply topmost/layered/toolwindow/noactivate styles (and clickthrough).

    Styles are applied to the true top-level window ONLY.  Tk's ``winfo_id``
    is an inner child window: giving the child its own layered/topmost styles
    strands its surface on the next resize (stale pixels, new regions black),
    so the child must never be touched here.
    """
    root_hwnd = get_root_hwnd(hwnd)
    style = GetWindowLongPtr(wintypes.HWND(root_hwnd), GWL_EXSTYLE)
    target = style | WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if clickthrough:
        target |= WS_EX_TRANSPARENT
    else:
        target &= ~WS_EX_TRANSPARENT
    SetWindowLongPtr(wintypes.HWND(root_hwnd), GWL_EXSTYLE, target)
    user32.SetWindowPos(
        wintypes.HWND(root_hwnd),
        HWND_TOPMOST,
        0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    return root_hwnd


def set_clickthrough(hwnd: int, enabled: bool) -> None:
    """Toggle WS_EX_TRANSPARENT (click-through) on the overlay window."""
    root_hwnd = get_root_hwnd(hwnd)
    style = GetWindowLongPtr(wintypes.HWND(root_hwnd), GWL_EXSTYLE)
    style = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
    SetWindowLongPtr(wintypes.HWND(root_hwnd), GWL_EXSTYLE, style)


def ensure_topmost(hwnd: int) -> bool:
    """Re-assert HWND_TOPMOST without moving, resizing or stealing focus."""
    root_hwnd = get_root_hwnd(hwnd)
    return bool(
        user32.SetWindowPos(
            wintypes.HWND(root_hwnd),
            HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
    )


def set_app_user_model_id(app_id: str) -> None:
    """Give the process a stable identity (tray grouping, taskbar, toasts)."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _scan_processes(exe_name: str) -> bool:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, -1, ctypes.c_void_p(-1).value):
        return False
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    target = exe_name.lower()
    found = False
    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() == target:
                    found = True
                    break
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def is_process_running(exe_name: str, max_age: float = 2.0) -> bool:
    """Cached process check (toolhelp snapshots are cheap but not free)."""
    now = time.monotonic()
    with _PROCESS_LOCK:
        cached = _PROCESS_CACHE.get(exe_name)
    if cached and (now - cached[0]) < max_age:
        return cached[1]
    result = _scan_processes(exe_name)
    with _PROCESS_LOCK:
        _PROCESS_CACHE[exe_name] = (now, result)
    return result


def clear_process_cache() -> None:
    """Drop cached process results (used by diagnostics)."""
    with _PROCESS_LOCK:
        _PROCESS_CACHE.clear()


def is_foreground_process(exe_name: str, self_hwnd: Optional[int] = None) -> bool:
    """True when the foreground window belongs to ``exe_name``."""
    fg_hwnd = user32.GetForegroundWindow()
    if not fg_hwnd:
        return False
    if self_hwnd and (fg_hwnd == self_hwnd or get_root_hwnd(self_hwnd) == fg_hwnd):
        return True

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))
    if not pid.value:
        return False

    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            path = buf.value.lower()
            return path.endswith("\\" + exe_name.lower()) or path.endswith("/" + exe_name.lower())
        return False
    finally:
        kernel32.CloseHandle(handle)


def get_screen_bounds() -> Tuple[int, int, int, int]:
    """Primary monitor working area (left, top, right, bottom) - excludes taskbar."""
    rect = wintypes.RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def get_monitor_bounds() -> Tuple[int, int, int, int]:
    """Full primary monitor rectangle, ignoring the taskbar (true screen edge)."""
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return (0, 0, width, height)


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def get_monitor_layouts() -> list:
    """All monitors as ``[(full_rect, work_rect), ...]`` (primary first).

    Falls back to the single primary monitor when enumeration fails, so
    single-monitor behaviour is unchanged.
    """
    try:
        monitors = []
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)
        def _cb(hmon, _hdc, _rect, _data):
            local = MONITORINFO()
            local.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(local)):
                m, w = local.rcMonitor, local.rcWork
                monitors.append(
                    ((m.left, m.top, m.right, m.bottom),
                     (w.left, w.top, w.right, w.bottom),
                     bool(local.dwFlags & 0x00000001)))
            return True

        user32.EnumDisplayMonitors(None, None, _cb, 0)
        if monitors:
            monitors.sort(key=lambda entry: not entry[2])
            return [(full, work) for full, work, _primary in monitors]
    except Exception:
        pass
    return [(get_monitor_bounds(), get_screen_bounds())]


def _overlap_area(rect: Tuple[int, int, int, int],
                  other: Tuple[int, int, int, int]) -> int:
    left = max(rect[0], other[0])
    top = max(rect[1], other[1])
    right = min(rect[2], other[2])
    bottom = min(rect[3], other[3])
    return max(0, right - left) * max(0, bottom - top)


def monitor_for_rect(rect: Tuple[int, int, int, int], layouts: list) -> int:
    """Index of the monitor with the largest overlap with ``rect``.

    Pure function (no Win32 calls) so multi-monitor docking math is unit
    testable.  Ties and zero overlap resolve to the first (primary) monitor.
    """
    if not layouts:
        return 0
    best, best_area = 0, -1
    for index, (full, _work) in enumerate(layouts):
        area = _overlap_area(rect, full)
        if area > best_area:
            best, best_area = index, area
    return best


def _exe_of_process(pid: int) -> str:
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def find_process_window_rect(exe_names: Tuple[str, ...]) -> Optional[Tuple[int, int, int, int]]:
    """Largest visible, non-minimized top-level window rect for ``exe_names``.

    Used to dock the overlay on the same monitor as the game.  Returns None
    when no matching window exists.
    """
    if not exe_names:
        return None
    wanted = tuple(name.lower() for name in exe_names)
    best_rect: Optional[Tuple[int, int, int, int]] = None
    best_area = 0
    hwnd_values: list = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _data):
        hwnd_values.append(hwnd)
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        return None
    for hwnd in hwnd_values:
        try:
            if not user32.IsWindowVisible(hwnd):
                continue
            if user32.IsIconic(hwnd):
                continue
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                continue
            path = _exe_of_process(pid.value)
            if not any(path.endswith("\\" + name) or path.endswith("/" + name)
                       for name in wanted):
                continue
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            if area > best_area:
                best_area = area
                best_rect = (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            continue
    return best_rect
