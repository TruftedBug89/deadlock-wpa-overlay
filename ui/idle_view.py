"""Compact status pill used between matches, while scanning or for feedback."""

import tkinter as tk
from typing import Optional

from ui import theme

BG = theme.BG
TITLE_FG = theme.TEXT
SUB_FG = theme.MUTED


class StatusBadgeView(tk.Frame):
    """One-line status badge: coloured dot, short title, muted detail."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str = "BETWEEN GAMES",
        subtitle: str = "",
        dot_color: str = "#22c55e",
        scale: float = 1.0,
        **kwargs,
    ):
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0, **kwargs)
        self._scale = max(0.75, min(2.0, float(scale or 1.0)))
        self._dot_lbl: Optional[tk.Label] = None
        self._title_lbl: Optional[tk.Label] = None
        self._sub_lbl: Optional[tk.Label] = None
        self._build_ui(title, subtitle, dot_color)

    def _px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, int(round(value * self._scale)))

    def _build_ui(self, title: str, subtitle: str, dot_color: str) -> None:
        row = tk.Frame(self, bg=BG)
        row.place(relx=0.5, rely=0.5, anchor="center")

        self._dot_lbl = tk.Label(
            row, text="●", fg=dot_color, bg=BG, font=(theme.FONT, self._px(7, 5)),
            bd=0, padx=0, pady=0
        )
        self._dot_lbl.pack(side="left", padx=(0, self._px(5)))

        self._title_lbl = tk.Label(
            row, text=title, fg=TITLE_FG, bg=BG,
            font=(theme.FONT, self._px(8, 6), "bold"), bd=0, padx=0, pady=0
        )
        self._title_lbl.pack(side="left")

        self._sub_lbl = tk.Label(
            row, text=subtitle, fg=SUB_FG, bg=BG, font=(theme.FONT, self._px(7, 5)),
            bd=0, padx=0, pady=0
        )
        if subtitle:
            self._sub_lbl.pack(side="left", padx=(self._px(5), 0))

    def set_status(self, title: str, subtitle: str = "", dot_color: str = "#22c55e") -> None:
        """Update text/colour in place (no geometry change)."""
        if self._dot_lbl and self._dot_lbl.winfo_exists():
            self._dot_lbl.config(fg=dot_color)
        if self._title_lbl and self._title_lbl.winfo_exists():
            self._title_lbl.config(text=title)
        if self._sub_lbl and self._sub_lbl.winfo_exists():
            self._sub_lbl.config(text=subtitle)
            if subtitle:
                self._sub_lbl.pack(side="left", padx=(self._px(5), 0))
            else:
                self._sub_lbl.pack_forget()


IdleBadgeView = StatusBadgeView
