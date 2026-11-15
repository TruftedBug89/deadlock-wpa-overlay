"""Archive Statlocker companion window screenshots when recommendations change."""

import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image


def get_captures_directory() -> Path:
    """Resolve the directory for storing Statlocker diagnostic captures."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.lower() == "dist":
            base = exe_dir.parent
        else:
            base = exe_dir
    else:
        base = Path(__file__).resolve().parent

    target = base / "captures"
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except Exception:
        local_app = os.environ.get("LOCALAPPDATA")
        fallback = (
            Path(local_app or Path.home() / "AppData" / "Local")
            / "DeadlockWPAOverlay"
            / "captures"
        )
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return cleaned or "item"


class StatlockerCaptureArchiver:
    """Records full Statlocker window screenshots whenever recommended items change."""

    def __init__(self, target_dir: Optional[Path] = None):
        self._target_dir = target_dir
        self._last_items: Optional[Tuple[str, ...]] = None

    @property
    def target_dir(self) -> Path:
        if self._target_dir is not None:
            self._target_dir.mkdir(parents=True, exist_ok=True)
            return self._target_dir
        return get_captures_directory()

    @property
    def last_captured_items(self) -> Optional[Tuple[str, ...]]:
        return self._last_items

    def save_if_changed(
        self,
        frame: object,
        item_names: Sequence[str],
    ) -> Optional[Path]:
        """Save a capture if item_names differs from the last saved capture."""
        clean_names = tuple(name.strip() for name in item_names if name and name.strip())
        if not clean_names:
            return None
        if clean_names == self._last_items:
            return None

        rgb = getattr(frame, "rgb", None)
        if rgb is None:
            return None

        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            slug_summary = "-".join(_slugify(n) for n in clean_names[:5])
            filename = f"statlocker_{ts}_{slug_summary}.png"
            dest = self.target_dir / filename
            img = Image.fromarray(rgb)
            img.save(dest)
            self._last_items = clean_names
            return dest
        except Exception as err:
            print(f"[CaptureArchiver] Failed to save screenshot: {err}")
            return None
