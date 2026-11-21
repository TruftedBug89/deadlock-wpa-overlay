"""Read only a verified foreground game's client-corner pixels, never disk."""

import ctypes
from ctypes import wintypes as w

_STATUS = "Focus Deadlock to read its corner match ID, or enter it in settings."
_GAME_NAMES = ("deadlock.exe", "project8.exe")


def capture_status():
    return _STATUS


def _configure(user, gdi):
    signatures = (
        (user.GetForegroundWindow, [], w.HWND),
        (user.GetWindowThreadProcessId, [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
        (user.GetClientRect, [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
        (user.ClientToScreen, [w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
        (user.WindowFromPoint, [w.POINT], w.HWND),
        (user.GetAncestor, [w.HWND, w.UINT], w.HWND),
        (user.IsIconic, [w.HWND], w.BOOL),
        (user.GetDC, [w.HWND], w.HDC),
        (user.ReleaseDC, [w.HWND, w.HDC], ctypes.c_int),
        (gdi.CreateCompatibleDC, [w.HDC], w.HDC),
        (gdi.CreateCompatibleBitmap, [w.HDC, ctypes.c_int, ctypes.c_int], w.HBITMAP),
        (gdi.SelectObject, [w.HDC, w.HANDLE], w.HANDLE),
        (gdi.DeleteObject, [w.HANDLE], w.BOOL),
        (gdi.DeleteDC, [w.HDC], w.BOOL),
        (gdi.BitBlt, [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD], w.BOOL),
        (gdi.GetDIBits, [w.HDC, w.HBITMAP, w.UINT, w.UINT,
                        ctypes.c_void_p, ctypes.c_void_p, w.UINT], ctypes.c_int),
    )
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result


def game_window(user, process_path):
    """Use process identity, not a localized or changing window title."""
    hwnd = user.GetForegroundWindow()
    if not hwnd or user.IsIconic(hwnd):
        return None
    pid = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = process_path(pid.value).lower().replace("/", "\\").rsplit("\\", 1)[-1]
    if name not in _GAME_NAMES:
        return None
    rect = w.RECT()
    if not user.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    return (hwnd, width, height) if width >= 640 and height >= 480 else None


def capture_corner():
    """Copy only the corner of the verified foreground game in memory."""
    global _STATUS
    from win32_overlay import _exe_of_process
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    _configure(user, gdi)
    window = game_window(user, _exe_of_process)
    if window is None:
        _STATUS = "Focus Deadlock to read its corner match ID, or enter it in settings."
        return None
    hwnd, width, height = window
    crop_w = max(200, min(520, int(width * .12)))
    crop_h = max(54, min(140, int(height * .06)))
    x, y = width - crop_w, height - crop_h
    frame = _copy_crop(user, gdi, hwnd, x, y, crop_w, crop_h)
    if frame is None or not frame.any():
        frame = _visible_corner(user, gdi, hwnd, x, y, crop_w, crop_h)
    if frame is None or not frame.any():
        _STATUS = "Game corner capture unavailable; enter the match ID in settings."
        return None
    _STATUS = "Game corner captured; reading the match ID."
    return frame


def _visible_corner(user, gdi, hwnd, x, y, width, height):
    """Read the displayed game crop when DirectX has no window DC pixels."""
    if user.GetForegroundWindow() != hwnd:
        return None
    point = w.POINT(x, y)
    if not user.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    left, top = point.x, point.y
    right, bottom = left + width - 1, top + height - 1
    samples = ((left, top), (right, top), (left, bottom), (right, bottom),
               ((left + right) // 2, (top + bottom) // 2))
    for sx, sy in samples:
        hit = user.WindowFromPoint(w.POINT(sx, sy))
        if not hit or (hit != hwnd and user.GetAncestor(hit, 2) != hwnd):
            return None
    frame = _copy_crop(user, gdi, None, left, top, width, height)
    return frame if user.GetForegroundWindow() == hwnd else None


def _copy_crop(user, gdi, hwnd, x, y, width, height):
    """Avoid PrintWindow or full-frame render calls that can stall the worker."""
    from match_code_reader import _to_rgb
    src = user.GetDC(hwnd)
    if not src:
        return None
    crop_dc = gdi.CreateCompatibleDC(src)
    crop = gdi.CreateCompatibleBitmap(src, width, height)
    if not crop_dc or not crop:
        if crop:
            gdi.DeleteObject(crop)
        if crop_dc:
            gdi.DeleteDC(crop_dc)
        user.ReleaseDC(hwnd, src)
        return None
    old_crop = gdi.SelectObject(crop_dc, crop)
    try:
        if not gdi.BitBlt(crop_dc, 0, 0, width, height, src, x, y, 0x00CC0020):
            return None
        gdi.SelectObject(crop_dc, old_crop)
        return _to_rgb(crop_dc, crop, width, height)
    finally:
        gdi.SelectObject(crop_dc, old_crop)
        gdi.DeleteObject(crop)
        gdi.DeleteDC(crop_dc)
        user.ReleaseDC(hwnd, src)
