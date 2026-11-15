"""Dwell-to-reveal controls that restore the user's click-through preference."""

import time
import tkinter as tk

from ui import theme
from win32_overlay import set_clickthrough, user32


class HoverControls:
    """Poll pointer position because a click-through window gets no Enter events."""

    def __init__(self, overlay):
        self.overlay = overlay
        self.active = False
        self.entered_at = None
        self.left_at = None
        self.job = None
        self.closed = False
        self.bar = tk.Frame(overlay.root, bg=theme.RAISED, bd=0,
                            highlightthickness=1, highlightbackground=theme.BORDER)
        self.grip = tk.Label(self.bar, text="\u283f", font=("Segoe UI Symbol", 12),
                             bg=theme.RAISED, fg=theme.MUTED, cursor="fleur", padx=8)
        self.grip.pack(side="left")
        self.settings_button = tk.Button(
            self.bar, text="\u2699", font=("Segoe UI Symbol", 11), bg=theme.RAISED,
            fg=theme.ACCENT, activebackground=theme.BORDER, activeforeground=theme.TEXT,
            bd=0, highlightthickness=0, padx=7, pady=0, cursor="hand2",
            command=overlay.open_settings, takefocus=True)
        self.settings_button.pack(side="left")
        self.edges = []
        for side in ("left", "right"):
            edge = tk.Frame(overlay.root, bg=theme.BORDER, cursor="sb_h_double_arrow")
            edge.bind("<ButtonPress-1>", lambda e, s=side: overlay._resize_handler.start(e, s))
            edge.bind("<B1-Motion>", overlay._resize_handler.motion)
            edge.bind("<ButtonRelease-1>", overlay._resize_handler.stop)
            self.edges.append(edge)
        self.job = overlay.root.after(80, self.poll)

    def poll(self):
        if self.closed or self.overlay._stop_event.is_set():
            return
        root = self.overlay.root
        try:
            px, py = root.winfo_pointerxy()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            inside = x <= px < x + root.winfo_width() and y <= py < y + root.winfo_height()
            pressed = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (1, 2, 4))
            self.update(inside, time.monotonic(), pressed)
        except tk.TclError:
            return
        self.job = root.after(800 if self.overlay._parked else 100 if self.active else 180, self.poll)

    def update(self, inside, now, pressed=False):
        overlay = self.overlay
        if overlay._parked or overlay._user_hidden:
            self.set_active(False)
            self.entered_at = None
            return
        if overlay._drag_handler.active or overlay._resize_handler.active:
            return
        if not overlay.config.hover_controls:
            self.set_active(False)
            self.entered_at = None
            return
        if inside:
            self.left_at = None
            if pressed and not self.active:
                self.entered_at = None
                return
            if self.entered_at is None:
                self.entered_at = now
            if now - self.entered_at >= .35:
                self.set_active(True)
        else:
            self.entered_at = None
            if self.left_at is None:
                self.left_at = now
            if now - self.left_at >= .2:
                self.set_active(False)

    def set_active(self, active):
        changed = self.active != active
        self.active = active
        if active:
            self.bar.place(relx=1, x=-3, y=3, anchor="ne")
            self.bar.lift()
            for index, edge in enumerate(self.edges):
                edge.place(relx=index, x=0 if index == 0 else -4, rely=.35, relheight=.5, width=4)
                edge.lift()
        else:
            self.bar.place_forget()
            for edge in self.edges:
                edge.place_forget()
        if changed:
            self.sync_clickthrough()

    def sync_clickthrough(self):
        if self.overlay._hwnd:
            set_clickthrough(self.overlay._hwnd, self.overlay._is_locked and not self.active)

    def close(self):
        self.closed = True
        if self.job:
            self.overlay.root.after_cancel(self.job)
            self.job = None
        self.set_active(False)
