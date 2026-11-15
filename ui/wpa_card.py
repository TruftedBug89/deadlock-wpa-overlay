"""UI component for a single WPA recommended item card."""

import tkinter as tk
from typing import Optional
from models import WpaItem
from icon_manager import IconManager


class WpaCard(tk.Frame):
    """Visual card for an individual WPA item matching Statlocker design."""

    def __init__(
        self,
        parent: tk.Widget,
        item: WpaItem,
        icon_mgr: IconManager,
        on_refresh: Optional[callable] = None,
        **kwargs,
    ):
        super().__init__(
            parent,
            bg="#14171a",
            highlightthickness=1,
            highlightbackground="#24282e",
            padx=4,
            pady=6,
            **kwargs,
        )
        self.item = item
        self.icon_mgr = icon_mgr
        self.on_refresh = on_refresh
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct card widgets: accent line, icon, badge, name, stats."""
        cat_color = self.item.category_color

        # Top Category Accent Line
        top_accent = tk.Frame(self, bg=cat_color, height=2)
        top_accent.pack(fill="x", pady=(0, 4))

        # Icon Frame with colored category border
        icon_frame = tk.Frame(
            self,
            bg="#0d0f11",
            highlightthickness=2,
            highlightbackground=cat_color,
            width=54,
            height=54,
        )
        icon_frame.pack_propagate(False)
        icon_frame.pack(pady=(0, 2))

        # PhotoImage or Fallback Canvas
        photo = self.icon_mgr.get_image(
            name=self.item.name,
            image_url=self.item.image_url,
            target_size=46,
            on_download_complete=self.on_refresh,
        )

        if photo:
            icon_lbl = tk.Label(icon_frame, image=photo, bg="#0d0f11")
            icon_lbl.image = photo  # Keep reference to prevent GC
            icon_lbl.pack(expand=True)
        else:
            # Initials canvas fallback
            initials = "".join([w[0] for w in self.item.name.split()[:2]]).upper()
            fallback_lbl = tk.Label(
                icon_frame,
                text=initials,
                font=("Segoe UI", 12, "bold"),
                fg=cat_color,
                bg="#0d0f11",
            )
            fallback_lbl.pack(expand=True)

        # "CAN BUY" badge
        badge_frame = tk.Frame(self, bg="#2ecc71", padx=4, pady=1)
        badge_frame.pack(pady=(0, 4))
        badge_lbl = tk.Label(
            badge_frame,
            text="CAN BUY",
            font=("Segoe UI", 7, "bold"),
            fg="#0b100d",
            bg="#2ecc71",
        )
        badge_lbl.pack()

        # Item Name
        name_lbl = tk.Label(
            self,
            text=self.item.display_name,
            font=("Segoe UI", 8, "bold"),
            fg="#f3f4f6",
            bg="#14171a",
        )
        name_lbl.pack(pady=(0, 5))

        # WPA Stat Box
        wpa_box = tk.Frame(self, bg="#0c0e10", padx=4, pady=2)
        wpa_box.pack(fill="x", pady=(0, 2))

        wpa_prefix = tk.Label(
            wpa_box,
            text="WPA ",
            font=("Segoe UI", 7),
            fg="#9ca3af",
            bg="#0c0e10",
        )
        wpa_prefix.pack(side="left")

        wpa_val = tk.Label(
            wpa_box,
            text=f"+{self.item.wpa_pct:.1f}%",
            font=("Segoe UI", 7, "bold"),
            fg="#22c55e",
            bg="#0c0e10",
        )
        wpa_val.pack(side="left")

        # USUALLY Timing Box
        time_box = tk.Frame(self, bg="#0c0e10", padx=4, pady=2)
        time_box.pack(fill="x")

        time_prefix = tk.Label(
            time_box,
            text="USUALLY ",
            font=("Segoe UI", 7),
            fg="#9ca3af",
            bg="#0c0e10",
        )
        time_prefix.pack(side="left")

        time_val = tk.Label(
            time_box,
            text=self.item.usually_time,
            font=("Segoe UI", 7, "bold"),
            fg="#f3f4f6",
            bg="#0c0e10",
        )
        time_val.pack(side="left")
