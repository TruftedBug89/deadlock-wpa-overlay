"""Read official shop artwork from the disk cache on Tk's thread.

Only the background poll worker downloads artwork, and the cache uses the
same URL the catalog supplied. An unavailable image leaves the item text.
"""

import hashlib
import io
import os
import time
import tkinter as tk
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlsplit

from advisor_api import CACHE_TTL_ASSETS

if TYPE_CHECKING:
    from PIL import ImageTk

LOCAL_CACHE_DIR = (
    Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"))
    / "DeadlockWPAOverlay" / "shop_art"
)
_SHOP_ASSET_HOST = "assets-bucket.deadlock-api.com"
_SHOP_ASSET_PREFIX = "/assets-api-res/images/"
_MAX_IMAGE_BYTES = 512_000
_MAX_IMAGE_DIMENSION = 1024
_PHOTO_CACHE: dict[tuple[Path, int, int], "ImageTk.PhotoImage"] = {}
_INVALID_ART: dict[Path, int] = {}
_RETRY_AT: dict[str, float] = {}


def clear_photo_cache() -> None:
    """Drop cached Tk photos when the interpreter is destroyed."""
    _PHOTO_CACHE.clear()


def _cache_path(url: Optional[str]) -> Optional[Path]:
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (parsed.scheme != "https" or parsed.netloc != _SHOP_ASSET_HOST
            or not parsed.path.startswith(_SHOP_ASSET_PREFIX)
            or not parsed.path.endswith(".png") or parsed.fragment):
        return None
    return LOCAL_CACHE_DIR / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.png"


def _cached_file(path: Path) -> Optional[int]:
    """Return the current file generation or None for unusable art."""
    try:
        stat = path.stat()
    except OSError:
        return None
    if (not 0 < stat.st_size <= _MAX_IMAGE_BYTES
            or time.time() - stat.st_mtime >= CACHE_TTL_ASSETS
            or _INVALID_ART.get(path) == stat.st_mtime_ns):
        return None
    return stat.st_mtime_ns


def _valid_image(image) -> bool:
    return image.format == "PNG" and max(image.size) <= _MAX_IMAGE_DIMENSION


def _download_icon(url: str, target: Path) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "DeadlockOverlay/2.0"})
        with urllib.request.urlopen(request, timeout=3.0) as response:
            if _cache_path(response.geturl()) != target:
                return False
            data = response.read(_MAX_IMAGE_BYTES + 1)
        if not 0 < len(data) <= _MAX_IMAGE_BYTES:
            return False
        from PIL import Image

        with Image.open(io.BytesIO(data)) as probe:
            if not _valid_image(probe):
                return False
            probe.verify()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".part")
        try:
            temp.write_bytes(data)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return True
    except Exception:
        # Failed art must never replace current advice with a poll error.
        return False


def can_prewarm(image_url: Optional[str]) -> bool:
    """Skip cached art and retry failed requests at most every five minutes."""
    path = _cache_path(image_url)
    return (path is not None and _cached_file(path) is None
            and time.monotonic() >= _RETRY_AT.get(image_url, 0))


def prewarm_icon(image_url: Optional[str]) -> bool:
    """Fetch one missing catalog image, returning True when newly cached."""
    if not can_prewarm(image_url):
        return False
    path = _cache_path(image_url)
    if _download_icon(image_url, path):
        _INVALID_ART.pop(path, None)
        _RETRY_AT.pop(image_url, None)
        return True
    _RETRY_AT[image_url] = time.monotonic() + 300
    return False


def get_item_photo(image_url: Optional[str], size: int) -> "Optional[ImageTk.PhotoImage]":
    """Return the catalog shop image without stretching it or doing network I/O."""
    path = _cache_path(image_url)
    stamp = _cached_file(path) if path is not None else None
    if stamp is None:
        return None
    cache_key = (path, stamp, size)
    cached = _PHOTO_CACHE.get(cache_key)
    if cached is not None:
        if getattr(cached, "tk", None) is getattr(tk._default_root, "tk", None):
            return cached
        _PHOTO_CACHE.pop(cache_key, None)

    from PIL import Image, ImageOps, ImageTk

    try:
        with Image.open(path) as image:
            if not _valid_image(image):
                raise ValueError("Invalid shop image")
            art = ImageOps.contain(image.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        _INVALID_ART[path] = stamp
        return None
    try:
        photo = ImageTk.PhotoImage(art)
    except (RuntimeError, tk.TclError):
        return None
    _PHOTO_CACHE[cache_key] = photo
    if len(_PHOTO_CACHE) > 160:
        _PHOTO_CACHE.pop(next(iter(_PHOTO_CACHE)))
    return photo
