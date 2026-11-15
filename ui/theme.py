"""Shared visual language for the HUD, its controls and settings."""

BG = "#0e1419"
SURFACE = "#172127"
RAISED = "#1e2c33"
BORDER = "#29383f"
TEXT = "#e6eeed"
MUTED = "#91a5aa"
QUIET = "#61777e"
ACCENT = "#88d5ba"
SAVING = "#e6bf83"
FONT = "Segoe UI"


def souls_text(value):
    if value is None:
        return ""
    return f"{value / 1000:g}k" if value >= 1000 else str(value)
