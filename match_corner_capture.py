"""Capture only Deadlock's match-stamp pixels, without saving images."""

import ctypes
from ctypes import wintypes as w

import numpy as np


def capture_corner():
    """Return a small RGB corner array, or None for an unavailable window."""
    from win32_overlay import _exe_of_process

    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    signatures = (
        (user.FindWindowW, [w.LPCWSTR, w.LPCWSTR], w.HWND),
        (user.GetWindowDC, [w.HWND], w.HDC),
        (user.ReleaseDC, [w.HWND, w.HDC], ctypes.c_int),
        (user.PrintWindow, [w.HWND, w.HDC, w.UINT], w.BOOL),
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
    hwnd = user.FindWindowW(None, "Deadlock")
    if not hwnd or user.IsIconic(hwnd):
        return None
    pid = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if _exe_of_process(pid.value).lower().rsplit("\\", 1)[-1] not in ("deadlock.exe", "project8.exe"):
        return None
    rect = w.RECT()
    if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 640 or height < 480:
        return None
    return _capture(user, gdi, hwnd, width, height)


def _capture(user, gdi, hwnd, width, height):
    from match_code_reader import _to_rgb

    crop_w, crop_h = max(150, int(width * .09)), max(46, int(height * .05))
    src = user.GetWindowDC(hwnd)
    full_dc, crop_dc = gdi.CreateCompatibleDC(src), gdi.CreateCompatibleDC(src)
    full = gdi.CreateCompatibleBitmap(src, width, height)
    crop = gdi.CreateCompatibleBitmap(src, crop_w, crop_h)
    old_full, old_crop = gdi.SelectObject(full_dc, full), gdi.SelectObject(crop_dc, crop)
    try:
        if not user.PrintWindow(hwnd, full_dc, 2):
            return None
        if not gdi.BitBlt(crop_dc, 0, 0, crop_w, crop_h, full_dc,
                          width - crop_w, height - crop_h, 0x00CC0020):
            return None
        gdi.SelectObject(crop_dc, old_crop)
        return _to_rgb(crop_dc, crop, crop_w, crop_h)
    finally:
        gdi.SelectObject(full_dc, old_full)
        gdi.SelectObject(crop_dc, old_crop)
        for bitmap in (full, crop):
            gdi.DeleteObject(bitmap)
        for dc in (full_dc, crop_dc):
            gdi.DeleteDC(dc)
        user.ReleaseDC(hwnd, src)
