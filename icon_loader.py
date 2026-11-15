"""Item icon resolution with a disk cache and a clear placeholder.

Network access is deliberately confined to :func:`prewarm_icon`, which the
background polling thread calls.  Tkinter's thread only ever reads local files,
so a missing icon can never freeze the overlay or the game.
"""

import os
import io
import re
import sys
import tkinter as tk
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # Pillow loads on first icon use, not on overlay startup
    from PIL import Image, ImageDraw, ImageFont, ImageTk

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLED_ICONS_DIR = Path(sys._MEIPASS) / "assets" / "icons"
else:
    BUNDLED_ICONS_DIR = Path(__file__).resolve().parent / "assets" / "icons"

LOCAL_CACHE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "DeadlockWPAOverlay" / "icons"
)
try:
    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

_PHOTO_CACHE: Dict[Tuple[str, int, str], "ImageTk.PhotoImage"] = {}
_PREWARMED: set = set()


def clear_photo_cache() -> None:
    """Drop cached Tk photo images (call when the Tk root is destroyed)."""
    _PHOTO_CACHE.clear()


def normalize_item_name(name: str) -> str:
    """Filesystem-safe key, e.g. ``Diviner's Kevlar`` -> ``diviners_kevlar``."""
    clean = (name or "").lower().replace("'", "").strip()
    return re.sub(r"[^a-z0-9]+", "_", clean).strip("_")


def _search_dirs() -> List[Path]:
    dirs: List[Path] = []
    if BUNDLED_ICONS_DIR.exists():
        dirs.append(BUNDLED_ICONS_DIR)
    if LOCAL_CACHE_DIR.exists():
        dirs.append(LOCAL_CACHE_DIR)
    if getattr(sys, "frozen", False):
        exe_assets = Path(sys.executable).parent / "assets" / "icons"
        if exe_assets.exists():
            dirs.append(exe_assets)
    return dirs


def _candidate_filenames(name: str, class_name: Optional[str], image_url: Optional[str]) -> List[str]:
    key = normalize_item_name(name)
    spaced = (name or "").lower().replace(" ", "_")
    candidates = [
        f"{key}.png",
        f"{spaced}.png",
        f"{spaced.replace(chr(39), '_')}.png",
        f"{spaced.replace(chr(39), '')}.png",
    ]
    if class_name:
        clean_class = class_name.lower().strip()
        candidates.append(f"{clean_class}.png")
        if clean_class.startswith("upgrade_"):
            candidates.append(f"{clean_class[8:]}.png")
    if image_url:
        file_name = Path(image_url).name
        if file_name:
            candidates.append(file_name)
    return candidates


def find_local_icon(
    name: str,
    class_name: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Optional[Path]:
    """Locate an icon PNG on disk for an item."""
    candidates = _candidate_filenames(name, class_name, image_url)
    for directory in _search_dirs():
        for filename in candidates:
            path = directory / filename
            try:
                if path.exists() and path.stat().st_size > 0:
                    return path
            except OSError:
                continue
    return None


def download_icon(url: str, target_path: Path, timeout: float = 3.0) -> bool:
    """Download an icon, validate it, and store it atomically."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "DeadlockOverlay/2.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(512_000)
        if not data:
            return False
        from PIL import Image

        probe = Image.open(io.BytesIO(data))
        probe.verify()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp = target_path.with_suffix(".part")
        temp.write_bytes(data)
        os.replace(temp, target_path)
        return True
    except Exception:
        return False


def prewarm_icon(
    name: str,
    image_url: Optional[str] = None,
    class_name: Optional[str] = None,
) -> bool:
    """Ensure an icon exists on disk (worker thread only)."""
    key = normalize_item_name(name)
    if key in _PREWARMED:
        return True
    if find_local_icon(name, class_name=class_name, image_url=image_url):
        _PREWARMED.add(key)
        return True
    if not image_url:
        return False
    target = LOCAL_CACHE_DIR / f"{key}.png"
    if download_icon(image_url, target):
        _PREWARMED.add(key)
        return True
    return False


def _category_color(category: str) -> Tuple[int, int, int]:
    if category == "vitality":
        return (116, 168, 50)
    if category == "spirit":
        return (159, 98, 222)
    return (222, 139, 0)


def _generate_fallback_icon(name: str, size: int = 32, category: str = "weapon") -> "Image.Image":
    """Draw an obviously synthetic placeholder (dashed border + initials)."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA", (size, size), (12, 14, 17, 255))
    draw = ImageDraw.Draw(image)
    colour = _category_color(category)

    # Dashed 1 px border signals "icon missing" instead of faking artwork.
    dash, gap = 3, 3
    for x in range(1, size - 1, dash + gap):
        draw.line([(x, 1), (min(x + dash, size - 2), 1)], fill=colour + (200,))
        draw.line([(x, size - 2), (min(x + dash, size - 2), size - 2)], fill=colour + (120,))
    for y in range(1, size - 1, dash + gap):
        draw.line([(1, y), (1, min(y + dash, size - 2))], fill=colour + (200,))
        draw.line([(size - 2, y), (size - 2, min(y + dash, size - 2))], fill=colour + (120,))

    words = [word for word in re.split(r"[\s\-_]+", name or "") if word]
    initials = "".join(word[0].upper() for word in words[:2]) or "?"
    try:
        font = ImageFont.truetype("segoeuib.ttf", max(9, size // 3))
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), initials, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - text_w) / 2, (size - text_h) / 2 - bbox[1]),
        initials,
        fill=(148, 163, 184, 255),
        font=font,
    )
    return image


def get_item_photo(
    name: str,
    image_url: Optional[str] = None,
    size: int = 32,
    class_name: Optional[str] = None,
    category: str = "weapon",
    allow_download: bool = False,
) -> "Optional[ImageTk.PhotoImage]":
    """Return a Tk photo image for an item (placeholder when missing)."""
    from PIL import Image, ImageTk

    cache_key = (name.lower(), int(size), category)
    cached = _PHOTO_CACHE.get(cache_key)
    if cached is not None:
        try:
            # A PhotoImage is bound to the Tk interpreter that created it.  If
            # the overlay window was recreated, the cached image is dead and
            # using it raises `image "pyimageN" doesn't exist`.
            if getattr(cached, "tk", None) is not getattr(tk._default_root, "tk", None):
                raise RuntimeError("stale Tk interpreter")
            cached.width()
            return cached
        except Exception:
            _PHOTO_CACHE.pop(cache_key, None)

    local_path = find_local_icon(name, class_name=class_name, image_url=image_url)
    if local_path is None and allow_download and image_url:
        target = LOCAL_CACHE_DIR / f"{normalize_item_name(name)}.png"
        if download_icon(image_url, target):
            local_path = target

    if local_path is not None:
        try:
            image = Image.open(local_path).convert("RGBA")
            if image.size != (size, size):
                image = image.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            image = _generate_fallback_icon(name, size, category)
    else:
        image = _generate_fallback_icon(name, size, category)

    try:
        photo = ImageTk.PhotoImage(image)
    except Exception:
        return None
    _PHOTO_CACHE[cache_key] = photo
    return photo
