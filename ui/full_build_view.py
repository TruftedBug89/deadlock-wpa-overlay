"""Full build board with stable item rows and a separate match view."""

import tkinter as tk

from icon_loader import get_item_photo
from ui import theme
from ui.counter_panel import counter_gain_text
from ui.hud_geometry import HudMetrics
from ui.hud_presentation import inventory_status


def full_build_metrics(scale, work):
    """Keep the board inside the monitor work area at any configured size."""
    left, top, right, bottom = work
    width = max(1, min(right - left - 16, round(472 * scale)))
    height = max(1, min(bottom - top - 16, round(494 * scale)))
    return HudMetrics("vertical", 1, scale, 24, 1, 6, 10, 0, width, height)


def item_key(item):
    return item.item_id if item.item_id is not None else item.name


def lead_text(state):
    if state.stance == "unknown" or state.team_souls <= 0 or state.enemy_souls <= 0:
        return "Team lead unknown"
    if not state.soul_lead:
        return "Teams tied on souls"
    side = "ahead" if state.soul_lead > 0 else "behind"
    return f"Team {theme.souls_text(abs(state.soul_lead))} {side}"


class BuildRow(tk.Frame):
    """A compact row that keeps its widget when evidence or wallet changes."""

    def __init__(self, view, parent):
        super().__init__(parent, bg=theme.SURFACE)
        self.rail = tk.Frame(self, width=view.px(3), bg=theme.ACCENT)
        self.rail.pack(side="left", fill="y")
        self._icon = tk.Label(self, bg=theme.SURFACE, bd=0, padx=0, pady=0)
        self._icon.bind("<MouseWheel>", view._scroll)
        self._icon_size = view.px(28)
        self._icon_margin = view.px(6)
        self._photo = None
        body = tk.Frame(self, bg=theme.SURFACE, padx=view.px(8), pady=view.px(5))
        self._body = body
        body.pack(side="left", fill="both", expand=True)
        header = tk.Frame(body, bg=theme.SURFACE)
        header.pack(fill="x")
        self.price = view.label(header, size=12, color=theme.MUTED)
        self.price.pack(side="right", padx=(view.px(6), 0))
        self.name = view.label(header, size=13, bold=True, wrap=view.metrics.width - view.px(159))
        self.name.pack(side="left", fill="x", expand=True)
        self.detail = view.label(body, size=11, color=theme.MUTED,
                                 wrap=view.metrics.width - view.px(99))
        self.detail.pack(fill="x")
        self._signature = None

    def update_item(self, item, next_buy):
        self._update_art(item.image_url)
        signature = (item.name, item.cost, item.win_rate, item.reason, item.category, next_buy)
        if signature == self._signature:
            return
        self._signature = signature
        self.rail.configure(bg=item.category_color)
        self.name.configure(text=f"{item.name}  •  Next buy" if next_buy else item.name,
                            fg=theme.ACCENT if next_buy else theme.TEXT)
        self.price.configure(text=f"{item.cost:,}" if item.cost is not None else "Unknown")
        evidence = f"{item.win_rate * 100:.1f}% WR" if item.win_rate is not None else ""
        self.detail.configure(text="  /  ".join(part for part in (evidence, item.reason) if part),
                              fg=theme.SAVING if item.reason.startswith("SAVE") else theme.MUTED)

    def _update_art(self, url):
        photo = get_item_photo(url, self._icon_size)
        if photo is self._photo:
            return
        self._photo = photo
        if photo is None:
            self._icon.configure(image="")
            self._icon.pack_forget()
        else:
            self._icon.configure(image=photo)
            self._icon.pack(side="left", before=self._body, padx=(self._icon_margin, 0))


class ReplacementPanel(tk.Frame):
    """A separate, conditional swap suggestion with a measured comparison."""

    def __init__(self, view, parent):
        super().__init__(parent, bg=theme.RAISED, highlightbackground=theme.BORDER,
                         highlightthickness=1, padx=view.px(10), pady=view.px(9))
        self.view = view
        self.heading = view.label(self, "Replacement option", size=12, bold=True, color=theme.ACCENT)
        self.heading.pack(fill="x")
        self.sell = view.label(self, size=12, color=theme.MUTED,
                               wrap=view.metrics.width - view.px(60))
        self.sell.pack(fill="x", pady=(view.px(6), view.px(5)))
        buy = tk.Frame(self, bg=theme.RAISED)
        buy.pack(fill="x")
        self.art = tk.Label(buy, bg=theme.RAISED, bd=0)
        self.art.bind("<MouseWheel>", view._scroll)
        self._photo = None
        self.buy = view.label(buy, size=14, bold=True, wrap=view.metrics.width - view.px(104))
        self.buy.pack(side="left", fill="x", expand=True)
        self.price = view.label(self, size=11, color=theme.ACCENT)
        self.price.pack(fill="x", pady=(view.px(4), 0))
        self.evidence = view.label(self, size=10, color=theme.MUTED,
                                   wrap=view.metrics.width - view.px(60))
        self.evidence.pack(fill="x", pady=(view.px(5), 0))

    def set_replacement(self, replacement):
        if replacement is None:
            self.sell.configure(text="")
            self.buy.configure(text="")
            self.price.configure(text="")
            self.evidence.configure(text="")
            self.art.configure(image="")
            self.art.pack_forget()
            self._photo = None
            self.pack_forget()
            return
        self.sell.configure(text=f"Sell {replacement.sell_name}")
        self.buy.configure(text=f"Buy {replacement.buy.name}")
        cost = replacement.buy.cost
        self.price.configure(text=f"Purchase price: {cost:,} souls" if cost is not None else "Price unknown")
        self.evidence.configure(text=(
            f"Historical WR {replacement.held_win_rate * 100:.1f}% / "
            f"{replacement.buy_win_rate * 100:.1f}%  •  "
            f"{replacement.slots_used}/{replacement.slot_limit} slots used"))
        photo = get_item_photo(replacement.buy.image_url, self.view.px(32))
        self._photo = photo
        if photo is None:
            self.art.configure(image="")
            self.art.pack_forget()
        else:
            self.art.configure(image=photo)
            self.art.pack(side="left", before=self.buy, padx=(0, self.view.px(8)))


class FullBuildView(tk.Frame):
    """Switch between the purchase plan and measured match context."""

    def __init__(self, parent, state, metrics, max_items=5, show_counters=True):
        super().__init__(parent, bg=theme.BG)
        self.metrics = metrics
        self.max_items = max_items
        self.show_counters = show_counters
        self.items = []
        self.rows = {}
        self._match_id = None
        self._active_page = "Plan"
        self._pages = {}
        self._buttons = {}
        self._orders = {}
        self._make_header()
        self._make_pages()
        self.set_state(state)

    def px(self, value):
        return max(1, round(value * min(self.metrics.scale, self.metrics.width / 380)))

    def label(self, parent, text="", *, size=12, color=theme.TEXT, bold=False, wrap=0):
        label = tk.Label(parent, text=text, anchor="w", justify="left", bg=parent.cget("bg"),
                         fg=color, bd=0, font=(theme.FONT, -self.px(size), "bold" if bold else "normal"),
                         wraplength=max(0, wrap))
        label.bind("<MouseWheel>", self._scroll)
        return label

    def _make_header(self):
        header = tk.Frame(self, bg=theme.RAISED, padx=self.px(13), pady=self.px(10))
        header.pack(fill="x")
        self.title = self.label(header, size=18, bold=True)
        self.title.pack(fill="x", padx=(0, self.px(120)))
        self.wallet = self.label(header, size=12, color=theme.ACCENT)
        self.wallet.pack(fill="x", pady=(self.px(3), 0))
        self.inventory = self.label(header, size=11, color=theme.MUTED)
        self.inventory.pack(fill="x", pady=(self.px(3), 0))
        tabs = tk.Frame(header, bg=theme.RAISED)
        tabs.pack(fill="x", pady=(self.px(9), 0))
        for name in ("Plan", "Match"):
            button = tk.Button(tabs, text=name, anchor="w", bd=0, cursor="hand2", relief="flat",
                               activebackground=theme.BORDER, activeforeground=theme.TEXT,
                               font=(theme.FONT, -self.px(12), "bold"), padx=self.px(12),
                               pady=self.px(4), command=lambda page=name: self.show_page(page))
            button.pack(side="left", padx=(0, self.px(4)))
            self._buttons[name] = button

    def _make_pages(self):
        self.canvas = tk.Canvas(self, bg=theme.BG, bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._fit_width)
        self.canvas.bind("<MouseWheel>", self._scroll)
        self.body = tk.Frame(self.canvas, bg=theme.BG, padx=self.px(10), pady=self.px(9))
        self.body.bind("<Configure>", self._fit_scroll)
        self._body_id = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        for name in ("Plan", "Match"):
            self._pages[name] = tk.Frame(self.body, bg=theme.BG)
        plan = self._pages["Plan"]
        self.replacement_panel = ReplacementPanel(self, plan)
        self.queue_heading = self._heading(plan, "Purchase queue")
        self.queue_rows = tk.Frame(plan, bg=theme.BG)
        self.queue_rows.pack(fill="x")
        self.extra_heading = self._heading(plan, "Build options")
        self.extra_rows = tk.Frame(plan, bg=theme.BG)
        self.extra_rows.pack(fill="x")
        self.note = self.label(plan, size=11, color=theme.MUTED, wrap=self.metrics.width - self.px(45))
        self.note.pack(fill="x", pady=(self.px(5), 0))
        match = self._pages["Match"]
        self.threats = self._match_section(match, "Enemy threats")
        self.owned = self._match_section(match, "Owned items")
        self.alternatives = self._match_section(match, "Matchup alternatives") if self.show_counters else None
        self.show_page("Plan")

    def _heading(self, parent, name):
        label = self.label(parent, name, size=12, bold=True, color=theme.ACCENT)
        label.pack(fill="x", pady=(self.px(3), self.px(6)))
        return label

    def _match_section(self, parent, name):
        panel = tk.Frame(parent, bg=theme.SURFACE, padx=self.px(10), pady=self.px(6))
        panel.pack(fill="x", pady=(0, self.px(8)))
        self._heading(panel, name)
        value = self.label(panel, color=theme.TEXT, wrap=self.metrics.width - self.px(60))
        value.pack(fill="x", pady=(0, self.px(4)))
        return value

    def show_page(self, name):
        for page, panel in self._pages.items():
            self._buttons[page].configure(bg=theme.BORDER if page == name else theme.RAISED,
                                          fg=theme.ACCENT if page == name else theme.MUTED)
            if page == name:
                panel.pack(fill="x")
            else:
                panel.pack_forget()
        self._active_page = name
        self.canvas.yview_moveto(0)

    def set_state(self, state):
        """Refresh facts in place, discarding withdrawn item rows immediately."""
        self.items = list(state.recommended_items[:self.max_items])
        plan = state.build_plan or self.items
        replacement = getattr(state, "replacement", None)
        blocked_inventory = inventory_status(state)
        self.item_names = [item.name for item in plan]
        self.title.configure(text=f"{state.hero_name} / Build" if plan or replacement or blocked_inventory else "Current build")
        if plan or replacement or blocked_inventory:
            bank = f"{state.buy_budget:,} souls available" if state.buy_budget is not None else "Spendable souls unknown"
            self.wallet.configure(text=f"{bank}  •  {lead_text(state)}" if state.is_in_match and state.match_id else bank)
        else:
            self.wallet.configure(text="Waiting for current purchase advice")
        capacity = getattr(state, "inventory_capacity", None)
        inventory = f"Inventory {state.known_owned_items}/{capacity}" if capacity is not None else ""
        if blocked_inventory:
            inventory = f"{inventory}  •  {blocked_inventory}" if inventory else blocked_inventory
        self.inventory.configure(text=inventory)
        self.replacement_panel.set_replacement(replacement)
        if replacement is not None:
            self.replacement_panel.pack(fill="x", before=self.queue_heading, pady=(0, self.px(10)))
        self.queue_heading.configure(text="Purchase queue" if self.items else "")
        queued = {item_key(item) for item in self.items}
        extra = [item for item in plan if item_key(item) not in queued]
        self.extra_heading.configure(text=f"Build options ({len(extra)})" if extra else "")
        self._update_rows(self.queue_rows, self.items, state.next_buy)
        self._update_rows(self.extra_rows, extra, None)
        note = state.build_note if plan or replacement else (state.last_error or "")
        if blocked_inventory and not plan and replacement is None:
            note = "No purchase or replacement meets the current checks. See Match for owned items."
        self.note.configure(text=note)
        self._update_match(state, queued | {item_key(item) for item in extra})
        if state.match_id != self._match_id:
            self._match_id = state.match_id
            self.show_page("Plan")

    def _update_rows(self, parent, items, next_buy):
        order = tuple(item_key(item) for item in items)
        old_order = self._orders.get(parent, ())
        for key in old_order:
            if key not in order:
                self.rows.pop((parent, key)).destroy()
        for item in items:
            key = item_key(item)
            row = self.rows.get((parent, key))
            if row is None:
                row = self.rows[(parent, key)] = BuildRow(self, parent)
            row.update_item(item, next_buy is not None and key == item_key(next_buy))
            if old_order != order:
                row.pack_forget()
                row.pack(fill="x", pady=(0, self.px(4)))
        self._orders[parent] = order

    def _update_match(self, state, shown):
        self.threats.configure(text=state.threat_summary.replace(" / ", "\n") or "Threat data unavailable")
        owned = "\n".join(sorted(state.owned_items))
        self.owned.configure(text=owned or ("No items owned" if state.match_id and state.scan_status == "ok"
                                             else "Inventory unavailable"))
        if self.alternatives is not None:
            lines = [f"{item.name}  {counter_gain_text(item)} vs {item.enemy_name}"
                     for item in state.counter_items if item_key(item) not in shown]
            self.alternatives.configure(text="\n".join(lines) or "No separate counter picks meet the evidence gates")

    def update_timer(self, _text):
        pass

    def _fit_width(self, event):
        self.canvas.itemconfigure(self._body_id, width=event.width)

    def _fit_scroll(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _scroll(self, event):
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"
