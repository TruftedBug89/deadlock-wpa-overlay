"""Single source of truth for HUD pixel geometry.

The window is sized from these numbers, not from Tk's requested size.  That is
what stops the overlay from resizing, reflowing or clipping when Statlocker
shows one card instead of five.
"""

from dataclasses import dataclass, replace

BASE_ICON = 32
BASE_BORDER = 1
BASE_GAP = 6
BASE_PAD = 6
BASE_TIMER_HEIGHT = 10
BASE_CARD_W = 124
BASE_CARD_H = 116
MAX_SLOTS = 5


@dataclass(frozen=True)
class HudMetrics:
    """Frozen pixel metrics for one layout at one DPI scale."""

    layout: str
    slots: int
    scale: float
    icon: int
    border: int
    gap: int
    pad: int
    timer_h: int
    width: int
    height: int
    card_w: int = 104
    card_h: int = 92

    @property
    def slot(self) -> int:
        """Outer size of a single icon slot, including its hairline border."""
        return self.icon + self.border * 2

    @property
    def content_width(self) -> int:
        return self.width - self.pad * 2

    @property
    def content_height(self) -> int:
        return self.height - self.pad * 2

    def px(self, value: float, minimum: int = 1) -> int:
        """Scale one design pixel by this HUD's combined DPI and size scale."""
        return max(minimum, int(round(value * self.scale)))


def _px(value: float, scale: float, minimum: int = 1) -> int:
    return max(minimum, int(round(value * scale)))


def compute_metrics(
    layout: str = "horizontal",
    slots: int = MAX_SLOTS,
    scale: float = 1.0,
    show_timer: bool = True,
) -> HudMetrics:
    """Return exact window dimensions for the requested layout."""
    layout = "vertical" if str(layout).lower() == "vertical" else "horizontal"
    slots = max(1, min(MAX_SLOTS, int(slots)))
    scale = max(0.75, min(3.0, float(scale)))

    icon = _px(BASE_ICON, scale, 16)
    border = _px(BASE_BORDER, scale, 1)
    gap = _px(BASE_GAP, scale, 2)
    pad = _px(BASE_PAD, scale, 2)
    timer_h = _px(BASE_TIMER_HEIGHT, scale, 6) if show_timer else 0
    card_w = _px(BASE_CARD_W, scale, 64)
    card_h = _px(BASE_CARD_H, scale, 64)

    if layout == "horizontal":
        width = pad * 2 + card_w * slots + gap * (slots - 1)
        height = pad * 2 + card_h + timer_h
    else:
        width = pad * 2 + card_w
        height = pad * 2 + card_h * slots + gap * (slots - 1) + timer_h

    return HudMetrics(
        layout=layout,
        slots=slots,
        scale=scale,
        icon=icon,
        border=border,
        gap=gap,
        pad=pad,
        timer_h=timer_h,
        width=width,
        height=height,
        card_w=card_w,
        card_h=card_h,
    )


def compute_icon_metrics(
    layout: str = "horizontal",
    slots: int = MAX_SLOTS,
    scale: float = 1.0,
) -> HudMetrics:
    """Exact window dimensions for the super-small icons-only strip.

    One bordered icon per slot, no text at all.  At scale 1.0 a 5-slot
    horizontal strip is ~172x34 px.
    """
    layout = "vertical" if str(layout).lower() == "vertical" else "horizontal"
    slots = max(1, min(MAX_SLOTS, int(slots)))
    scale = max(0.75, min(3.0, float(scale)))

    icon = _px(BASE_ICON_ONLY, scale, 16)
    border = _px(BASE_BORDER, scale, 1)
    gap = _px(BASE_ICON_ONLY_GAP, scale, 2)
    pad = _px(BASE_ICON_ONLY_PAD, scale, 2)
    card_w = icon + border * 2
    card_h = icon + border * 2

    if layout == "horizontal":
        width = pad * 2 + card_w * slots + gap * (slots - 1)
        height = pad * 2 + card_h
    else:
        width = pad * 2 + card_w
        height = pad * 2 + card_h * slots + gap * (slots - 1)

    return HudMetrics(
        layout=layout,
        slots=slots,
        scale=scale,
        icon=icon,
        border=border,
        gap=gap,
        pad=pad,
        timer_h=0,
        width=width,
        height=height,
        card_w=card_w,
        card_h=card_h,
    )


BASE_COUNTER_ICON = 22
BASE_COUNTER_CHIP_W = 104
BASE_COUNTER_GAP = 4
BASE_COUNTER_PAD = 3
BASE_COUNTER_HEADER = 11
BASE_COUNTER_NAME = 12
BASE_COUNTER_SAMPLES = 11


@dataclass(frozen=True)
class CounterMetrics:
    """Pixel geometry of the COUNTER ITEMS panel under the WPA strip."""

    count: int
    scale: float
    icon: int
    chip_w: int
    chip_h: int
    gap: int
    pad: int
    header_h: int
    width: int
    height: int

    def px(self, value: float, minimum: int = 1) -> int:
        """Scale one design pixel by this panel's combined scale."""
        return max(minimum, int(round(value * self.scale)))


def compute_counter_metrics(
    scale: float = 1.0,
    count: int = 3,
    min_width: int = 0,
) -> CounterMetrics:
    """Exact size of the counter panel for ``count`` ranked items."""
    scale = max(0.75, min(3.0, float(scale)))
    count = max(1, min(MAX_SLOTS, int(count)))

    icon = _px(BASE_COUNTER_ICON, scale, 14)
    chip_w = _px(BASE_COUNTER_CHIP_W, scale, 30)
    gap = _px(BASE_COUNTER_GAP, scale, 1)
    pad = _px(BASE_COUNTER_PAD, scale, 1)
    header_h = _px(BASE_COUNTER_HEADER, scale, 8)
    name_h = _px(BASE_COUNTER_NAME, scale, 7)
    samples_h = _px(BASE_COUNTER_SAMPLES, scale, 6)
    chip_h = max(icon, name_h + samples_h) + _px(10, scale, 4)

    width = pad * 2 + chip_w * count + gap * (count - 1)
    height = pad * 2 + header_h + _px(2, scale, 1) + chip_h
    return CounterMetrics(
        count=count,
        scale=scale,
        icon=icon,
        chip_w=chip_w,
        chip_h=chip_h,
        gap=gap,
        pad=pad,
        header_h=header_h,
        width=max(int(min_width), width),
        height=height,
    )


def stack_metrics(base: HudMetrics, panel: CounterMetrics) -> HudMetrics:
    """Window metrics for a WPA strip with a counter panel underneath it."""
    return replace(
        base,
        width=max(base.width, panel.width),
        height=base.height + panel.height,
    )


def dock_x(metrics: HudMetrics, screen_right: int) -> int:
    """X coordinate that puts the window flush against the right screen edge."""
    return int(screen_right - metrics.width)


def clamp_y(metrics: HudMetrics, requested_y: int, work_top: int, work_bottom: int) -> int:
    """Keep the whole window on screen vertically."""
    highest = work_top
    lowest = max(work_top, work_bottom - metrics.height)
    return int(max(highest, min(requested_y, lowest)))


BASE_ICON_ONLY = 28
BASE_ICON_ONLY_PAD = 3
BASE_ICON_ONLY_GAP = 4

BASE_BADGE_CHAR = 7
BASE_BADGE_DOT = 14


def compute_badge_metrics(
    scale: float = 1.0,
    text: str = "",
    show_timer: bool = False,
) -> HudMetrics:
    """Geometry for the transient one-line hotkey feedback pill.

    The badge is sized from its text so a word like ``PREVIEW`` is never clipped
    by the one-slot item geometry.
    """
    scale = max(0.75, min(3.0, float(scale)))
    icon = _px(BASE_ICON, scale, 16)
    border = _px(BASE_BORDER, scale, 1)
    gap = _px(BASE_GAP, scale, 2)
    pad = _px(BASE_PAD, scale, 2)
    timer_h = _px(BASE_TIMER_HEIGHT, scale, 6) if show_timer else 0
    card_w = _px(BASE_CARD_W, scale, 64)
    card_h = _px(BASE_CARD_H, scale, 64)
    chars = max(3, len(text or ""))
    text_width = _px(BASE_BADGE_CHAR * chars + BASE_BADGE_DOT, scale, 24)
    icon_width = icon + border * 2 + gap
    width = pad * 2 + max(icon_width, text_width)
    height = pad * 2 + icon + border * 2 + timer_h
    return HudMetrics(
        layout="horizontal",
        slots=1,
        scale=scale,
        icon=icon,
        border=border,
        gap=gap,
        pad=pad,
        timer_h=timer_h,
        width=width,
        height=height,
        card_w=card_w,
        card_h=card_h,
    )
