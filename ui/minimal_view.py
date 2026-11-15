"""WPA HUD cards: fixed-size slots with icon, name, WPA% and timing.

Slots are real widgets with a fixed pixel size, so nothing reflows or clips
when Statlocker shows 1 card instead of 5. ``set_items`` swaps content in
place when the card count stays the same.
"""

import tkinter as tk
from typing import List, Optional, Sequence

from icon_loader import get_item_photo
from models import WpaItem
from ui.hud_geometry import HudMetrics
from ui import theme

BG = theme.BG
CARD_BG = theme.SURFACE
NAME_FG = theme.TEXT
MUTED_FG = theme.MUTED
WPA_FG = theme.ACCENT
TIMER_FG = theme.QUIET
REASON_FG = theme.MUTED


class MinimalItemView(tk.Frame):
    """A row/column of WPA cards matching Statlocker's live row."""

    def __init__(
        self,
        parent: tk.Widget,
        items: Sequence[WpaItem],
        metrics: HudMetrics,
        timer_text: str = "",
        **kwargs,
    ):
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
        self._name_labels: List[tk.Label] = []
        self._wpa_labels: List[tk.Label] = []
        self._time_labels: List[tk.Label] = []
        self._timer_label: Optional[tk.Label] = None
        self._rank_labels = []
        self._price_labels = []
        self._category_lines = []
        self._build_slots()
        self.set_items(self.items)
        self.update_timer(timer_text)

    def _build_slots(self) -> None:
        metrics = self.metrics
        self._timer_frame = None
        if metrics.timer_h:
            self._timer_frame = tk.Frame(self, bg=BG, height=metrics.timer_h)
            self._timer_frame.pack(side="bottom", fill="x")
            self._timer_frame.pack_propagate(False)
            self._timer_label = tk.Label(
                self._timer_frame,
                text="",
                font=(theme.FONT, metrics.px(6, 5)),
                fg=TIMER_FG,
                bg=BG,
                bd=0,
                padx=0,
                pady=0,
            )
            self._timer_label.pack(side="right", anchor="e")

        self._icon_area = tk.Frame(self, bg=BG)
        self._icon_area.pack(fill="both", expand=True)

        card_w = getattr(metrics, "card_w", metrics.slot)
        card_h = getattr(metrics, "card_h", metrics.slot)
        for index in range(metrics.slots):
            outer = tk.Frame(
                self._icon_area,
                width=card_w,
                height=card_h,
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

            inner = tk.Frame(outer, bg=CARD_BG, bd=0, highlightthickness=0)
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            line = tk.Frame(inner, height=metrics.px(2), bg=theme.BORDER)
            line.pack(fill="x")
            header = tk.Frame(inner, bg=CARD_BG)
            header.pack(fill="x", padx=metrics.px(7, 2), pady=(metrics.px(4), 0))
            rank_label = tk.Label(header, bg=CARD_BG, fg=theme.QUIET,
                                  font=(theme.FONT, metrics.px(6, 5), "bold"), bd=0)
            rank_label.pack(side="left")
            price = tk.Label(header, bg=CARD_BG, fg=theme.QUIET,
                             font=(theme.FONT, metrics.px(6, 5)), bd=0)
            price.pack(side="right")
            self._rank_labels.append(rank_label)
            self._price_labels.append(price)
            self._category_lines.append(line)

            icon = tk.Label(inner, bg=CARD_BG, bd=0, highlightthickness=0)
            icon.pack(pady=(metrics.px(3), 0))

            name = tk.Label(
                inner, bg=CARD_BG, fg=NAME_FG,
                font=(theme.FONT, metrics.px(8, 6), "bold"), bd=0, padx=2,
            )
            name.pack(pady=(metrics.px(2), 0))

            wpa = tk.Label(
                inner, bg=CARD_BG, fg=WPA_FG,
                font=(theme.FONT, metrics.px(7, 5), "bold"), bd=0,
            )
            wpa.pack()

            usual = tk.Label(
                inner, bg=CARD_BG, fg=MUTED_FG,
                font=(theme.FONT, metrics.px(7, 5)), bd=0,
            )
            usual.pack(pady=(0, metrics.px(4)))

            self._slot_frames.append(outer)
            self._icon_labels.append(icon)
            self._name_labels.append(name)
            self._wpa_labels.append(wpa)
            self._time_labels.append(usual)

    def set_items(self, items: Sequence[WpaItem]) -> None:
        """Update cards in place (no rebuild, no flicker)."""
        self.items = list(items)
        self._photos.clear()
        for index in range(len(self._slot_frames)):
            outer = self._slot_frames[index]
            icon_lbl = self._icon_labels[index]
            name_lbl = self._name_labels[index]
            wpa_lbl = self._wpa_labels[index]
            time_lbl = self._time_labels[index]
            if index >= len(self.items):
                outer.config(bg=BG)
                for lbl in (icon_lbl, name_lbl, wpa_lbl, time_lbl):
                    lbl.config(image="", text="", bg=BG)
                self._rank_labels[index].config(text="")
                self._price_labels[index].config(text="")
                self._category_lines[index].config(bg=BG)
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
            outer.config(bg=theme.BORDER)
            self._category_lines[index].config(bg=item.category_color)
            self._rank_labels[index].config(text="NEXT" if index == 0 and item.can_buy else f"{index + 1:02}",
                                             fg=theme.ACCENT if index == 0 else theme.QUIET)
            self._price_labels[index].config(text=theme.souls_text(item.cost))
            try:
                if photo is not None:
                    icon_lbl.config(image=photo, bg=CARD_BG)
                else:
                    icon_lbl.config(image="", text="?", bg=CARD_BG)
                name_lbl.config(text=item.display_name, bg=CARD_BG)
                winrate = item.winrate_text
                if winrate:
                    wpa_lbl.config(text=f"WR {winrate}", fg=WPA_FG, bg=CARD_BG)
                else:
                    wpa_lbl.config(
                        text=f"WPA {item.wpa_text}",
                        fg=WPA_FG if item.wpa_pct is not None else MUTED_FG,
                        bg=CARD_BG,
                    )
                if item.reason:
                    time_lbl.config(text=item.reason, fg=theme.SAVING if item.reason.startswith("SAVE") else REASON_FG, bg=CARD_BG)
                else:
                    time_lbl.config(
                        text=f"USUALLY {item.usually_text}",
                        fg=MUTED_FG,
                        bg=CARD_BG,
                    )
            except tk.TclError:
                if photo is not None and self._photos and self._photos[-1] is photo:
                    self._photos.pop()
                outer.config(bg=BG)

    def update_timer(self, text: str) -> None:
        if self._timer_label is not None and self._timer_label.winfo_exists():
            if self._timer_label.cget("text") != text:
                self._timer_label.config(text=text)

    @property
    def item_names(self) -> List[str]:
        return [item.name for item in self.items]
