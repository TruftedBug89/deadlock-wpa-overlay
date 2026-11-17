"""Scrollable full-name build board using only the current validated state."""

import tkinter as tk

from ui import theme
from ui.hud_geometry import HudMetrics


def full_build_metrics(scale, work):
    """Bound the board to the current monitor; content scrolls inside it."""
    left, top, right, bottom = work
    width = min(max(240, right - left - 24), round(540 * scale))
    height = min(max(200, bottom - top - 24), round(660 * scale))
    return HudMetrics("vertical", 1, scale, 24, 1, 6, 10, 0, width, height)


class FullBuildView(tk.Frame):
    """A current-game plan, queued purchases and measured threat context."""

    def __init__(self, parent, state, metrics, max_items=5, show_counters=True):
        super().__init__(parent, bg=theme.BG, highlightthickness=0)
        self.metrics, self.max_items = metrics, max_items
        self.show_counters = show_counters
        self.items = []
        self._signature = None
        self._row_labels = []
        self.canvas = tk.Canvas(self, bg=theme.BG, bd=0, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=theme.BG, padx=self.px(12), pady=self.px(12))
        self._body_id = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._fit_width)
        self.body.bind("<Configure>", self._fit_scroll)
        self.bind("<MouseWheel>", self._scroll)
        self.set_state(state)

    def px(self, value):
        return max(1, round(value * min(self.metrics.scale, self.metrics.width / 420)))

    def _label(self, parent, text, *, color=theme.TEXT, size=10, bold=False, wrap=True):
        label = tk.Label(parent, text=text, anchor="w", justify="left", bg=parent.cget("bg"),
                         fg=color, font=(theme.FONT, -self.px(size), "bold" if bold else "normal"),
                         wraplength=max(160, self.metrics.width - self.px(74)) if wrap else 0)
        label.bind("<MouseWheel>", self._scroll)
        label.pack(anchor="w", fill="x")
        return label

    def _heading(self, title):
        row = tk.Frame(self.body, bg=theme.BG, pady=self.px(8))
        row.pack(fill="x")
        self._label(row, title, color=theme.ACCENT, size=10, bold=True)

    def _item(self, item, prefix):
        row = tk.Frame(self.body, bg=theme.SURFACE, padx=self.px(10), pady=self.px(7))
        row.pack(fill="x", pady=(0, self.px(4)))
        line = f"{prefix}  {item.name}"
        self._row_labels.append(self._label(row, line, size=12, bold=True))
        price = f"{item.cost:,} souls" if item.cost is not None else "Price unknown"
        evidence = f"WR {item.win_rate * 100:.1f}%" if item.win_rate is not None else "WR unknown"
        self._label(row, f"{price}  /  {evidence}", color=theme.MUTED)
        if item.reason:
            self._label(row, item.reason, color=theme.SAVING if item.reason.startswith("SAVE") else theme.ACCENT)

    def set_state(self, state):
        """Replace displayed claims immediately while preserving scroll position."""
        self.items = list(state.recommended_items[:self.max_items])
        plan = list(getattr(state, "build_plan", []))
        self.item_names = [item.name for item in plan]
        signature = (repr(state), self.max_items, self.show_counters)
        if signature == self._signature:
            return
        self._signature = signature
        position = self.canvas.yview()[0]
        for child in self.body.winfo_children():
            child.destroy()
        self._row_labels = []
        self._label(self.body, f"{state.hero_name.upper()} / YOUR BUILD", color=theme.ACCENT, size=16, bold=True)
        bank = f"{state.buy_budget:,} souls to spend" if state.buy_budget is not None else "Spendable souls unknown"
        self._label(self.body, bank, color=theme.MUTED)
        if getattr(state, "threat_summary", ""):
            self._label(self.body, state.threat_summary, color=theme.SAVING)
        self._heading("NEXT IN QUEUE")
        for index, item in enumerate(self.items):
            self._item(item, "NEXT" if index == 0 and item.can_buy else f"{index + 1:02}")
        if not self.items:
            self._label(self.body, "Waiting for validated purchase advice.", color=theme.MUTED)
        queued = {item.item_id for item in self.items}
        remaining = [item for item in plan if item.item_id not in queued]
        if remaining:
            self._heading("BUILD OPTIONS / CURRENT GAME")
            for index, item in enumerate(remaining, len(self.items) + 1):
                self._item(item, f"{index:02}")
        self._counter_rows(state, {item.item_id for item in plan} | queued)
        self._heading("OWNED ITEMS")
        self._label(self.body, ", ".join(sorted(state.owned_items)) or (
            "None" if state.is_in_match and state.scan_status == "ok" else "Unknown"), color=theme.MUTED)
        if getattr(state, "build_note", ""):
            self._heading("HOW TO USE THIS PLAN")
            self._label(self.body, state.build_note, color=theme.MUTED)
        self.body.update_idletasks()
        self._fit_scroll()
        self.canvas.yview_moveto(position)

    def _counter_rows(self, state, shown):
        counters = [item for item in state.counter_items if item.item_id not in shown]
        if not self.show_counters or not counters:
            return
        self._heading("MATCHUP ALTERNATIVES")
        for item in counters:
            self._label(self.body, f"{item.name} / {item.gain_text} / VS {item.enemy_name}", color=theme.ACCENT)

    def update_timer(self, _text):
        pass

    def _fit_width(self, event):
        self.canvas.itemconfigure(self._body_id, width=event.width)

    def _fit_scroll(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _scroll(self, event):
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"
