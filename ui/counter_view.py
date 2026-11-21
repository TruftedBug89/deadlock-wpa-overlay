"""COUNTER ITEMS panel: a compact row of named counter chips.

Sits directly under the WPA strip inside the same window.  Each chip is a fixed
size so the panel never reflows: item icon, a short name, and the match sample
size behind the ranking.  An empty list means the panel is not created at all ,
the caller hides it rather than showing an empty box.
"""

import tkinter as tk
from typing import List, Sequence

from icon_loader import get_item_photo
from models import CounterItem
from ui.counter_panel import counter_gain_text
from ui.hud_geometry import CounterMetrics
from ui import theme

BG = theme.BG
CHIP_BG = theme.SURFACE
TITLE_FG = theme.QUIET
SUBTLE_FG = theme.MUTED
NAME_FG = theme.TEXT


class CounterView(tk.Frame):
    """Header + up to N counter chips for the current enemy team."""

    def __init__(
        self,
        parent: tk.Widget,
        counters: Sequence[CounterItem],
        metrics: CounterMetrics,
        subtitle: str = "",
        **kwargs,
    ):
        super().__init__(
            parent,
            bg=BG,
            bd=0,
            highlightthickness=0,
            padx=metrics.pad,
            pady=metrics.pad,
            **kwargs,
        )
        self.metrics = metrics
        self.counters: List[CounterItem] = list(counters)
        self._photos = []
        self._chips: List[tk.Frame] = []
        self._icon_labels: List[tk.Label] = []
        self._name_labels: List[tk.Label] = []
        self._sample_labels: List[tk.Label] = []

        header = tk.Frame(self, bg=BG, height=metrics.header_h)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="MATCHUP", bg=BG, fg=TITLE_FG,
            font=(theme.FONT, metrics.px(6, 5), "bold"), bd=0, padx=0, pady=0,
        ).pack(side="left")
        self._subtitle = tk.Label(
            header, text=subtitle, bg=BG, fg=SUBTLE_FG,
            font=(theme.FONT, metrics.px(6, 5)), bd=0, padx=0, pady=0,
        )
        self._subtitle.pack(side="right")

        row = tk.Frame(self, bg=BG)
        row.pack(side="top", fill="x", pady=(metrics.px(2), 0))
        for index in range(len(self.counters)):
            # Outer frame is the 1 px category hairline, inner frame the chip.
            chip = tk.Frame(
                row,
                width=metrics.chip_w,
                height=metrics.chip_h,
                bg=CHIP_BG,
                bd=0,
                highlightthickness=0,
            )
            chip.pack_propagate(False)
            padx = (0, metrics.gap if index < len(self.counters) - 1 else 0)
            chip.pack(side="left", padx=padx)

            inner = tk.Frame(chip, bg=CHIP_BG, bd=0, highlightthickness=0)
            inner.pack(fill="both", expand=True, padx=1, pady=1)

            icon = tk.Label(inner, bg=CHIP_BG, bd=0, highlightthickness=0)
            icon.pack(side="left", padx=(metrics.px(5), metrics.px(4)),
                      pady=metrics.px(4))
            detail = tk.Frame(inner, bg=CHIP_BG)
            detail.pack(side="left", fill="both", expand=True, pady=metrics.px(3))
            name = tk.Label(
                detail, bg=CHIP_BG, fg=NAME_FG,
                font=(theme.FONT, metrics.px(6, 5), "bold"), bd=0, padx=0, pady=0,
            )
            name.pack(side="top", anchor="w")
            samples = tk.Label(
                detail, bg=CHIP_BG, fg=theme.ACCENT,
                font=(theme.FONT, metrics.px(6, 5)), bd=0, padx=0, pady=0,
            )
            samples.pack(side="top", anchor="w")

            self._chips.append(chip)
            self._icon_labels.append(icon)
            self._name_labels.append(name)
            self._sample_labels.append(samples)

        self._fill()

    def _fill(self) -> None:
        for index, counter in enumerate(self.counters[: len(self._chips)]):
            photo = get_item_photo(counter.image_url, self.metrics.icon)
            if photo is not None:
                self._photos.append(photo)
            try:
                self._chips[index].config(bg=theme.BORDER)
                icon = self._icon_labels[index]
                if photo is not None:
                    icon.config(image=photo, bg=CHIP_BG)
                    icon.pack_configure(padx=(self.metrics.px(5), self.metrics.px(4)))
                else:
                    icon.config(image="", bg=CHIP_BG)
                    icon.pack_configure(padx=(self.metrics.px(4), 0))
                self._name_labels[index].config(text=counter.display_name, bg=CHIP_BG)
                self._sample_labels[index].config(text=counter_gain_text(counter) or counter.samples_text, bg=CHIP_BG)
            except tk.TclError:
                continue

    # ------------------------------------------------------------------ update
    def set_counters(self, counters: Sequence[CounterItem], subtitle: str = "") -> None:
        """Swap chip content in place (same chip count, no rebuild)."""
        new_items = list(counters)
        if len(new_items) != len(self.counters) or len(new_items) > len(self._chips):
            return
        self.counters = new_items
        self._photos.clear()
        if self._subtitle.winfo_exists() and self._subtitle.cget("text") != subtitle:
            self._subtitle.config(text=subtitle)
        self._fill()

    @property
    def item_names(self) -> List[str]:
        return [counter.name for counter in self.counters]
