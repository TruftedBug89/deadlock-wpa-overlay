"""Compact icon strip with affordability markers for purchase advice.

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
        self._markers: List[tk.Label] = []
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
            icon = tk.Label(outer, bg=CARD_BG, bd=0, highlightthickness=0,
                            fg=theme.TEXT, font=(theme.FONT, -metrics.px(7, 6), "bold"),
                            wraplength=max(1, metrics.card_w - 4), padx=0, pady=0)
            icon.pack(fill="both", expand=True, padx=1, pady=1)
            marker = tk.Label(outer, bg=BG, fg=theme.SAVING, bd=0, padx=1,
                              font=(theme.FONT, -metrics.px(8, 7), "bold"))
            self._slot_frames.append(outer)
            self._icon_labels.append(icon)
            self._markers.append(marker)
        self.set_items(self.items)

    def set_items(self, items: Sequence[WpaItem]) -> None:
        """Swap icons in place (no rebuild, no flicker)."""
        self.items = list(items)
        self._photos.clear()
        for index in range(len(self._slot_frames)):
            outer = self._slot_frames[index]
            icon_lbl = self._icon_labels[index]
            marker = self._markers[index]
            marker.place_forget()
            if index >= len(self.items):
                outer.config(bg=BG)
                icon_lbl.config(image="", text="", bg=BG)
                continue
            item = self.items[index]
            photo = get_item_photo(item.image_url, self.metrics.icon)
            if photo is not None:
                self._photos.append(photo)
            outer.config(bg=item.category_color)
            if item.reason.startswith(("SAVE", "BUDGET UNKNOWN")):
                marker.configure(text="SAVE" if item.reason.startswith("SAVE") else "?")
                marker.place(relx=.5, rely=1, y=-1, anchor="s")
            try:
                if photo is not None:
                    icon_lbl.config(image=photo, text="", bg=CARD_BG)
                else:
                    icon_lbl.config(image="", text=item.name, bg=CARD_BG)
            except tk.TclError:
                if photo is not None and self._photos and self._photos[-1] is photo:
                    self._photos.pop()
                outer.config(bg=BG)

    def update_timer(self, _text: str = "") -> None:
        """No timer line in icons-only mode (interface compatibility)."""

    @property
    def item_names(self) -> List[str]:
        return [item.name for item in self.items]
