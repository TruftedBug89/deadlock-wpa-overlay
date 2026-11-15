"""Read the live match id from Deadlock's bottom-right HUD stamp.

The game prints ``MATCH: 136997713`` (server CPU readout above it) in the
bottom-right corner of the window.  The glyphs are about 6 px wide at 1080p,
so the strip is captured at native size, upscaled 5x and binarized before
Windows OCR.  A multi-scale vote rejects the common "13" -> "B" misread.
"""

import ctypes
import re
import threading
import time
from ctypes import wintypes
from typing import List, Optional
from collections import Counter

import numpy as np
from PIL import Image, ImageOps

from ocr_engine import _get_ocr_engine, run_ocr

_MATCH_RE = re.compile(r"MATCH\s*[:\;]\s*([0-9OQ]{8,12})", re.IGNORECASE)
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {"code": None, "at": 0.0}
CACHE_TTL_S = 5.0


class _BMIH(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPels", wintypes.LONG),
        ("biYPels", wintypes.LONG),
        ("biClr", wintypes.DWORD),
        ("biImp", wintypes.DWORD),
    ]


def _to_rgb(dc, bmp, width: int, height: int) -> Optional[np.ndarray]:
    gdi32 = ctypes.windll.gdi32
    bmi = _BMIH()
    bmi.biSize = ctypes.sizeof(_BMIH)
    bmi.biWidth = width
    bmi.biHeight = -height
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    if not gdi32.GetDIBits(dc, bmp, 0, height, buffer, ctypes.byref(bmi), 0):
        return None
    arr = np.frombuffer(buffer, dtype=np.uint8).reshape((height, width, 4))
    return np.ascontiguousarray(arr[:, :, 2::-1])


def capture_game_frame() -> Optional[np.ndarray]:
    """Only the match-stamp corner leaves the native capture buffer."""
    from match_corner_capture import capture_corner
    return capture_corner()


def _strip(frame: np.ndarray) -> Image.Image:
    """Bottom-right stamp, scaled with the window (verified at 1920x1080)."""
    height, width = frame.shape[:2]
    if width < 640 and height < 150:
        return Image.fromarray(frame)
    strip_width = max(150, int(width * 0.09))
    strip_height = max(46, int(height * 0.05))
    left = max(0, width - strip_width)
    top = max(0, height - strip_height)
    return Image.fromarray(frame).crop((left, top, width, height))


def parse_match_code(frame: np.ndarray) -> Optional[int]:
    """OCR the corner strip; return the numeric match id or None."""
    strip = ImageOps.autocontrast(ImageOps.grayscale(_strip(frame)))
    votes: List[str] = []
    engine = _get_ocr_engine()
    if engine is None:
        return None
    for scale in (4, 5, 6):
        big = strip.resize((strip.width * scale, strip.height * scale), Image.LANCZOS)
        for threshold in (140, 160, 180):
            binary = big.point(lambda value, limit=threshold: 255 if value > limit else 0)
            result = run_ocr(binary, engine)
            if result is None:
                continue
            text = " ".join(line.text for line in result.lines if line.text)
            found = _MATCH_RE.search(text)
            if found:
                votes.append(found.group(1).upper().replace("O", "0").replace("Q", "0"))
    if not votes:
        return None
    ranked = Counter(votes).most_common()
    best, count = ranked[0]
    if count < 2 or (len(ranked) > 1 and ranked[1][1] == count):
        return None
    try:
        value = int(best)
    except ValueError:
        return None
    return value if 1_000_000 <= value <= 99_999_999_999 else None


def _now() -> float:
    """Clock hook so the cache window is testable without sleeping."""
    return time.time()


def get_match_id(max_age_s: float = CACHE_TTL_S) -> Optional[int]:
    """Cached match id from the screen; never raises."""
    now = _now()
    with _CACHE_LOCK:
        if (_CACHE["code"] is not None or _CACHE["at"]) and now - _CACHE["at"] <= max_age_s:
            return int(_CACHE["code"]) if _CACHE["code"] is not None else None
    try:
        frame = capture_game_frame()
        code = parse_match_code(frame) if frame is not None else None
    except Exception:
        code = None
    with _CACHE_LOCK:
        _CACHE["code"], _CACHE["at"] = code, _now()
    return code
