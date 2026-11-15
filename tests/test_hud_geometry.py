"""HUD geometry tests: flush-right docking, stable height, no clipping."""

import pytest

from ui.hud_geometry import MAX_SLOTS, clamp_y, compute_badge_metrics, compute_icon_metrics, compute_metrics, dock_x


@pytest.mark.parametrize("layout", ["horizontal", "vertical"])
@pytest.mark.parametrize("slots", [1, 2, 3, 4, 5])
def test_right_edge_is_flush(layout, slots):
    metrics = compute_metrics(layout, slots, scale=1.0)
    right_edge = 2560
    x = dock_x(metrics, right_edge)
    assert x + metrics.width == right_edge
    assert x > 0


def test_horizontal_height_is_independent_of_card_count():
    heights = {compute_metrics("horizontal", slots, 1.0).height for slots in range(1, 6)}
    assert len(heights) == 1, heights


def test_vertical_width_is_independent_of_card_count():
    widths = {compute_metrics("vertical", slots, 1.0).width for slots in range(1, 6)}
    assert len(widths) == 1, widths


def test_width_grows_with_cards():
    widths = [compute_metrics("horizontal", slots, 1.0).width for slots in range(1, 6)]
    assert widths == sorted(widths)
    assert len(set(widths)) == MAX_SLOTS


def test_icons_only_strip_is_super_small():
    horizontal = compute_icon_metrics("horizontal", 5, 1.0)
    assert (horizontal.width, horizontal.height) == (172, 36)
    vertical = compute_icon_metrics("vertical", 5, 1.0)
    assert (vertical.width, vertical.height) == (36, 172)
    assert horizontal.width < 200 and horizontal.height < 50


def test_scale_affects_pixels_proportionally():
    small = compute_metrics("horizontal", 5, 1.0)
    large = compute_metrics("horizontal", 5, 1.5)
    assert large.icon > small.icon
    assert large.width > small.width
    assert large.height > small.height


def test_clamp_keeps_window_on_screen():
    metrics = compute_metrics("horizontal", 5, 1.0)
    assert clamp_y(metrics, -500, 0, 1080) == 0
    assert clamp_y(metrics, 5000, 0, 1080) == 1080 - metrics.height


def test_slots_are_clamped_to_five():
    assert compute_metrics("horizontal", 99, 1.0).slots == MAX_SLOTS
    assert compute_metrics("horizontal", 0, 1.0).slots == 1


def test_badge_fits_its_text():
    short = compute_badge_metrics(1.0, "LOCK")
    long = compute_badge_metrics(1.0, "PREVIEW")
    assert long.width > short.width
    assert short.width >= 48
    # Badge is a compact pill; full WPA cards are taller by design.
    assert short.height <= compute_metrics("horizontal", 1, 1.0, show_timer=False).height


def test_badge_scales_with_dpi():
    small = compute_badge_metrics(1.0, "PREVIEW")
    large = compute_badge_metrics(1.5, "PREVIEW")
    assert large.width > small.width
    assert large.height > small.height
    assert large.icon == 48
