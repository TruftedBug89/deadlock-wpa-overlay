"""Ultra-minimal horizontal corner bar for zero-distraction gaming."""

import tkinter as tk
from typing import List, Optional
from models import WpaItem
from icon_manager import IconManager


class CompactBar(tk.Frame):
    """Sleek minimalist bar displaying 4 tiny icons with WPA tags."""

    def __init__(
        self,
        parent: tk.Widget,
        items: List[WpaItem],
        icon_mgr: IconManager,
        on_toggle_expand: Optional[callable] = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            bg="#111417",
            highlightthickness=1,
            highlightbackground="#24282e",
            padx=6,
            pady=3,
            **kwargs,
        )
        self.items = items
        self.icon_mgr = icon_mgr
        self.on_toggle_expand = on_toggle_expand
        self._build_ui()

    def _build_ui(self) -> None:
        """Render compact horizontal strip."""
        title_lbl = tk.Label(
            self,
            text="WPA",
            font=("Segoe UI", 7, "bold"),
            fg="#22c55e",
            bg="#111417",
            cursor="hand2",
        )
        title_lbl.pack(side="left", padx=(0, 6))
        if self.on_toggle_expand:
            title_lbl.bind("<Button-1>", lambda e: self.on_toggle_expand())

        for it in self.items:
            cat_color = it.category_color
            chip = tk.Frame(self, bg="#181c20", padx=3, pady=2, highlightthickness=1, highlightbackground=cat_color)
            chip.pack(side="left", padx=3)

            photo = self.icon_mgr.get_image(name=it.name, image_url=it.image_url, target_size=20)
            if photo:
                lbl_icon = tk.Label(chip, image=photo, bg="#181c20")
                lbl_icon.image = photo
                lbl_icon.pack(side="left")

            lbl_stat = tk.Label(
                chip,
                text=f"+{it.wpa_pct:.1f}%",
                font=("Segoe UI", 7, "bold"),
                fg="#22c55e",
                bg="#181c20",
            )
            lbl_stat.pack(side="left", padx=(2, 0))

            if self.on_toggle_expand:
                chip.bind("<Button-1>", lambda e: self.on_toggle_expand())
                lbl_stat.bind("<Button-1>", lambda e: self.on_toggle_expand())
