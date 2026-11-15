"""Icon caching, downloading, and resizing for Tkinter overlay."""

import os
import re
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Dict, Optional
import tkinter as tk

if getattr(sys, "frozen", False):
    BUNDLE_ICONS_DIR = Path(getattr(sys, "_MEIPASS", "")) / "assets" / "icons"
    USER_ICONS_DIR = Path(sys.executable).parent / "assets" / "icons"
else:
    BUNDLE_ICONS_DIR = Path(__file__).parent / "assets" / "icons"
    USER_ICONS_DIR = BUNDLE_ICONS_DIR


def sanitize_filename(name: str) -> str:
    """Sanitize item name for safe filename on Windows."""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
    return f"{clean}.png"


class IconManager:
    """Manages downloading, caching, and PhotoImage generation."""

    def __init__(self, icons_dir: Path = USER_ICONS_DIR, bundle_dir: Path = BUNDLE_ICONS_DIR):
        self.icons_dir = icons_dir
        self.bundle_dir = bundle_dir
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        self._image_cache: Dict[str, tk.PhotoImage] = {}
        self._download_lock = threading.Lock()
        self._downloading = set()

    def get_image(
        self,
        name: str,
        image_url: Optional[str] = None,
        target_size: int = 48,
        on_download_complete: Optional[callable] = None,
    ) -> Optional[tk.PhotoImage]:
        """Return a PhotoImage for the item or trigger background download."""
        cache_key = f"{name}_{target_size}"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        filename = sanitize_filename(name)
        # Check bundled assets first, then user writable cache
        file_path = self.bundle_dir / filename
        if not file_path.exists():
            file_path = self.icons_dir / filename

        # If cached on disk, load and resize
        if file_path.exists():
            try:
                img = tk.PhotoImage(file=str(file_path))
                orig_w = img.width()
                if orig_w > target_size and orig_w > 0:
                    scale = max(1, orig_w // target_size)
                    img = img.subsample(scale, scale)
                self._image_cache[cache_key] = img
                return img
            except Exception as err:
                print(f"[IconManager] Failed reading {file_path}: {err}")

        # If URL provided and not yet downloaded, queue background download
        if image_url and name not in self._downloading:
            self._downloading.add(name)
            dest_save = self.icons_dir / filename
            threading.Thread(
                target=self._async_download,
                args=(name, image_url, dest_save, on_download_complete),
                daemon=True,
            ).start()

        return None

    def _async_download(
        self,
        name: str,
        url: str,
        dest_path: Path,
        callback: Optional[callable] = None,
    ) -> None:
        """Download icon image in background thread."""
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                with open(dest_path, "wb") as f:
                    f.write(data)
            if callback:
                callback()
        except Exception as err:
            print(f"[IconManager] Background download failed for {name}: {err}")
        finally:
            with self._download_lock:
                self._downloading.discard(name)
