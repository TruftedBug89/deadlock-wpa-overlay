"""Icons-only strip: the super-small HUD. One bordered icon per slot, no text.

Mirrors the MinimalItemView interface (items, set_items, update_timer,
item_names) so the overlay window can swap it in without render-path changes.
"""

import tkinter as tk
from typing import List, Sequence

from icon_loader import get_item_photo
from models import WpaItem
from ui.hud_geometry import HudMetrics

from ui import theme

BG = theme.BG
CARD_BG = theme.SURFACE


class IconStripView(tk.Frame):
    """A row/column of bare item icons with category-colour hairline borders."""

    def __init__(self, parent, items, metrics, **kwargs):
        super().__init__(
            parent,
            bg=BG,
            highlightthickness=0,
            bd=0,
            padx=metrics.pad,
            pady=metrics.pad,
            **kwargs,
        )
        self.metrics = metrics
        self.items: List[WpaItem] = list(items)
        self._photos = []
        self._slot_frames: List[tk.Frame] = []
        self._icon_labels: List[tk.Label] = []
        for index in range(metrics.slots):
            outer = tk.Frame(
                self,
                width=metrics.card_w,
                height=metrics.card_h,
                bg=BG,
                bd=0,
                highlightthickness=0,
            )
            outer.pack_propagate(False)
            if metrics.layout == "horizontal":
                padx = (0, metrics.gap if index < metrics.slots - 1 else 0)
                outer.pack(side="left", padx=padx)
            else:
                pady = (0, metrics.gap if index < metrics.slots - 1 else 0)
                outer.pack(side="top", pady=pady)
            icon = tk.Label(outer, bg=CARD_BG, bd=0, highlightthickness=0)
            icon.pack(fill="both", expand=True, padx=1, pady=1)
            self._slot_frames.append(outer)
            self._icon_labels.append(icon)
        self.set_items(self.items)

    def set_items(self, items: Sequence[WpaItem]) -> None:
        """Swap icons in place (no rebuild, no flicker)."""
        self.items = list(items)
        self._photos.clear()
        for index in range(len(self._slot_frames)):
            outer = self._slot_frames[index]
            icon_lbl = self._icon_labels[index]
            if index >= len(self.items):
                outer.config(bg=BG)
                icon_lbl.config(image="", text="", bg=BG)
                continue
            item = self.items[index]
            photo = get_item_photo(
                item.name,
                image_url=item.image_url,
                size=self.metrics.icon,
                class_name=item.class_name,
                category=item.category,
                allow_download=False,
            )
            if photo is not None:
                self._photos.append(photo)
            outer.config(bg=item.category_color)
            try:
                if photo is not None:
                    icon_lbl.config(image=photo, text="", bg=CARD_BG)
                else:
                    icon_lbl.config(image="", text="?", bg=CARD_BG)
            except tk.TclError:
                if photo is not None and self._photos and self._photos[-1] is photo:
                    self._photos.pop()
                outer.config(bg=BG)

    def update_timer(self, _text: str = "") -> None:
        """No timer line in icons-only mode (interface compatibility)."""

    @property
    def item_names(self) -> List[str]:
        return [item.name for item in self.items]
