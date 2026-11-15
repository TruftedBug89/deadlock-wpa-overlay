"""Resize the HUD from either revealed edge; persist only on release."""

from config import save_config


class WindowResizeHandler:
    def __init__(self, overlay):
        self.overlay = overlay
        self.active = False

    def start(self, event, side):
        self.active = True
        self.side = side
        self.start_x = event.x_root
        self.start_width = max(1, self.overlay.root.winfo_width())
        self.start_scale = self.overlay.config.hud_scale
        self.origin = (self.overlay.root.winfo_x(), self.overlay.root.winfo_y())
        self.overlay.root.grab_set()
        return "break"

    def motion(self, event):
        if not self.active:
            return "break"
        delta = (event.x_root - self.start_x) * (-1 if self.side == "left" else 1)
        value = max(.75, min(2., self.start_scale * (self.start_width + delta) / self.start_width))
        if abs(value - self.overlay.config.hud_scale) < .015:
            return "break"
        width = round(self.start_width * value / self.start_scale)
        self.overlay.config.positioned = True
        self.overlay.config.x = self.origin[0] + (self.start_width - width if self.side == "left" else 0)
        self.overlay.config.y = self.origin[1]
        self.overlay.set_scale(value, persist=False, feedback=False)
        return "break"

    def stop(self, event=None):
        if self.active:
            self.active = False
            self.overlay.root.grab_release()
            save_config(self.overlay.config)
        return "break"
