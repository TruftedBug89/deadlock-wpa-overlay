"""Small, live settings panel reachable from the HUD or tray."""

import tkinter as tk

from config import save_config
from local_account import normalize_account_id
from ui import theme
from win32_overlay import get_monitor_layouts, monitor_for_rect


class SettingsPanel:
    def __init__(self, overlay):
        self.overlay = overlay
        self.window = tk.Toplevel(overlay.root)
        self.window.title("Overlay settings")
        self.window.configure(bg=theme.BG)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.attributes("-toolwindow", True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.close())
        self.canvas = tk.Canvas(self.window, bg=theme.BG, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.window, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=theme.BG, padx=18, pady=16)
        self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.window.bind("<MouseWheel>", self._scroll)
        self.variables = {}
        self._build()
        self.window.update_idletasks()
        self._place()
        self.window.focus_force()

    def _text(self, parent, text, muted=False, size=9):
        label = tk.Label(parent, text=text, font=(theme.FONT, size), bg=theme.BG,
                         fg=theme.MUTED if muted else theme.TEXT, anchor="w")
        label.configure(wraplength=370)
        label.pack(anchor="w")
        return label

    def _build(self):
        self.content = self.body
        self._text(self.body, "Overlay settings", size=16)
        tabs = tk.Frame(self.body, bg=theme.BG)
        tabs.pack(fill="x", pady=(14, 4))
        self.tab_buttons = {}
        choices = ["Display", "Match", "Behavior"] if getattr(
            self.overlay.data_source, "is_advisor", False) else ["Display", "Behavior"]
        for label in choices:
            button = tk.Button(tabs, text=label, command=lambda name=label: self.select_tab(name),
                               bg=theme.SURFACE, fg=theme.MUTED, relief="flat", bd=0,
                               font=(theme.FONT, 10), padx=18, pady=8)
            button.pack(side="left", padx=(0, 4))
            self.tab_buttons[label] = button
        self.body = tk.Frame(self.content, bg=theme.BG)
        self.body.pack(fill="both", expand=True)
        self.select_tab("Display", place=False)
        footer = tk.Frame(self.content, bg=theme.BG)
        footer.pack(fill="x", pady=(16, 0))
        for label, action in [("Dock left", lambda: self.dock("top_left")),
                              ("Dock right", lambda: self.dock("top_right")), ("Done", self.close)]:
            tk.Button(footer, text=label, command=action, bg=theme.RAISED,
                      fg=theme.ACCENT, activebackground=theme.BORDER, relief="flat", bd=0,
                      padx=16, pady=7, font=(theme.FONT, 9)).pack(side="left", padx=(0, 8))

    def select_tab(self, name, place=True):
        for child in self.body.winfo_children():
            child.destroy()
        self.variables.clear()
        self.connection_status = None
        for label, button in self.tab_buttons.items():
            button.configure(bg=theme.RAISED if name == label else theme.SURFACE,
                             fg=theme.ACCENT if name == label else theme.MUTED)
        if name == "Match":
            self._connection()
        elif name == "Behavior":
            self._behavior()
        else:
            self._display()
        self.canvas.yview_moveto(0)
        if place:
            self.window.update_idletasks()
            self._place()

    def _display(self):
        if getattr(self.overlay.data_source, "is_advisor", False):
            self._section("View")
            self._choices("view_mode", [("Minimal queue", "minimal"), ("Full build", "full")])
            self._text(self.body, "Full build shows item names, reasons, owned items and threats.", muted=True, size=8)
        self._section("Queue cards / 1 to 5")
        self._choices("max_items", [(str(i), i) for i in range(1, 6)])
        self._section("Minimal queue layout")
        self._choices("layout", [("Row", "horizontal"), ("Stack", "vertical")])
        self._toggle("icons_only", "Minimal view: compact icons only")
        self._section("Size")
        self._choices("hud_scale", [("S", .8), ("M", 1.), ("L", 1.25), ("XL", 1.5)])
        self._section("Opacity")
        self._choices("opacity", [("50%", .5), ("65%", .65), ("80%", .8), ("100%", 1.)])
        self._toggle("show_counters", "Show matchup alternatives")
        self._toggle("show_timer", "Minimal view: show freshness timer")

    def _behavior(self):
        if getattr(self.overlay.data_source, "is_advisor", False):
            self._section("Queue review")
            self._choices("queue_seconds", [("2 min", 120.), ("2.5 min", 150.), ("3 min", 180.)])
            self._text(self.body, "Bought or invalid items leave on the next live update.", muted=True, size=8)
        self._section("Interaction")
        self._toggle("hover_controls", "Reveal controls on hover")
        self._toggle("clickthrough", "Pass clicks through when idle")
        self._toggle("only_when_focused", "Show only while playing")
        self._toggle("standby_badge", "Keep connection status visible")
        self._text(self.body, "Hover to drag or scroll. F9 also unlocks movement.", muted=True, size=8)
        self._text(self.body, "Settings are always available in the tray.", muted=True, size=8)

    def _section(self, title):
        row = tk.Frame(self.body, bg=theme.BG)
        row.pack(fill="x", pady=(14, 5))
        self._text(row, title, muted=True, size=8)

    def _connection(self):
        self._section("Match connection")
        self._toggle("read_match_id", "Read match ID from game corner")
        self.connection_fields = {}
        row = tk.Frame(self.body, bg=theme.BG)
        row.pack(fill="x")
        for field, label in (("account_id", "Account ID or SteamID64"), ("match_id", "Match ID / blank for auto")):
            column = tk.Frame(row, bg=theme.BG)
            column.pack(side="left", padx=(0, 8))
            self._text(column, label, muted=True, size=8)
            entry = tk.Entry(column, width=20, bg=theme.SURFACE, fg=theme.TEXT,
                             insertbackground=theme.ACCENT, relief="flat", font=(theme.FONT, 9))
            entry.insert(0, str(getattr(self.overlay.config, field) or ""))
            entry.pack(ipady=5)
            self.connection_fields[field] = entry
        self.connection_status = self._text(self.body, "", muted=True, size=8)
        self.update_connection_status(self.overlay._current_state)
        tk.Button(self.body, text="Connect / retry", command=self.connect,
                  bg=theme.RAISED, fg=theme.ACCENT, relief="flat", bd=0,
                  padx=10, pady=4, font=(theme.FONT, 9)).pack(anchor="w")

    def update_connection_status(self, state):
        if getattr(self, "connection_status", None) is None:
            return
        if state.is_in_match and state.scan_status == "ok":
            detail = f"Connected: {state.hero_name} / match {state.match_id}"
        else:
            from ui.hud_presentation import get_status_info
            detail = state.last_error or get_status_info(state)[0]
        self.connection_status.configure(text=detail)

    def connect(self):
        values = {}
        for field, entry in self.connection_fields.items():
            text = entry.get().strip()
            if text and (not text.isascii() or not text.isdecimal() or len(text) > 20 or int(text) <= 0):
                self.connection_status.config(text="Use a numeric ID, or leave match ID blank.")
                return
            number = int(text) if text else None
            values[field] = normalize_account_id(number) if field == "account_id" else number
            if text and (values[field] is None or values[field] >= 2**64):
                self.connection_status.config(text="Check the account or match ID and try again.")
                return
        for field, value in values.items():
            setattr(self.overlay.config, field, value)
        save_config(self.overlay.config)
        self.overlay.request_connection()
        self.connection_status.config(text="Checking connection in the background...")

    def _choices(self, field, options):
        value = getattr(self.overlay.config, field)
        variable = tk.StringVar(self.window, value=str(value))
        self.variables[field] = variable
        row = tk.Frame(self.body, bg=theme.BG)
        row.pack(fill="x")
        for label, option in options:
            tk.Radiobutton(
                row, text=label, value=str(option), variable=variable, indicatoron=False,
                command=lambda f=field, v=option: self.apply(f, v), font=(theme.FONT, 9),
                bg=theme.SURFACE, fg=theme.MUTED, selectcolor=theme.RAISED,
                activebackground=theme.BORDER, activeforeground=theme.ACCENT,
                bd=0, highlightthickness=0, padx=12, pady=7, cursor="hand2",
            ).pack(side="left", padx=(0, 3))

    def _toggle(self, field, label):
        variable = tk.BooleanVar(self.window, value=getattr(self.overlay.config, field))
        self.variables[field] = variable
        tk.Checkbutton(
            self.body, text=label, variable=variable,
            command=lambda: self.apply(field, variable.get()),
            bg=theme.BG, fg=theme.TEXT, activebackground=theme.BG,
            activeforeground=theme.ACCENT, selectcolor=theme.SURFACE,
            font=(theme.FONT, 9), bd=0, highlightthickness=0, pady=3, cursor="hand2",
        ).pack(anchor="w")

    def apply(self, field, value):
        overlay = self.overlay
        if field == "hud_scale":
            overlay.set_scale(value)
            self._place()
            return
        setattr(overlay.config, field, value)
        if field == "read_match_id":
            save_config(overlay.config)
            overlay.request_connection()
            return
        if field == "opacity":
            overlay.config.hud_alpha = value
            overlay.root.attributes("-alpha", value)
        elif field == "clickthrough":
            overlay._is_locked = value
            overlay._hover_controls.sync_clickthrough()
        elif field == "hover_controls" and not value:
            overlay._hover_controls.set_active(False)
        save_config(overlay.config)
        overlay._content_kind = None
        overlay._render_content()
        overlay._wake_event.set()

    def dock(self, corner: str = "top_right"):
        self.overlay.set_position(corner)
        self._place()

    def _place(self):
        root = self.overlay.root
        x, y = root.winfo_x(), root.winfo_y()
        layouts = get_monitor_layouts()
        index = monitor_for_rect((x, y, x + 1, y + 1), layouts)
        _, (left, top, right, bottom) = layouts[index]
        body_width, body_height = self.content.winfo_reqwidth(), self.content.winfo_reqheight()
        viewport = min(body_height, max(220, bottom - top - 90))
        self.canvas.configure(width=body_width, height=viewport,
                              scrollregion=(0, 0, body_width, body_height))
        if viewport < body_height:
            self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()
        self.window.update_idletasks()
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x = max(left, min(x - width - 10, right - width))
        y = max(top + 30, min(y, bottom - height - 40))
        self.window.geometry(f"+{x}+{y}")

    def _scroll(self, event):
        if self.scrollbar.winfo_ismapped():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def close(self):
        self.overlay._settings = None
        self.window.destroy()
        self.overlay._update_visibility()
