"""Placement math: dock corners, exact dragged spots and clamping."""

from models import OverlayConfig
from ui.hud_geometry import compute_icon_metrics
from ui.positioning import AUTO_Y, is_docked, resolve_origin

MONITOR = (0, 0, 1920, 1080)
WORK = (0, 0, 1920, 1040)
METRICS = compute_icon_metrics("horizontal", 5)


def test_default_config_docks_top_right():
    x, y = resolve_origin(METRICS, OverlayConfig(), MONITOR, WORK)
    assert (x + METRICS.width, y) == (1920, 0)


def test_every_corner_resolves_flush():
    expected = {
        "top_right": (1920 - METRICS.width, 0),
        "top_left": (0, 0),
        "bottom_right": (1920 - METRICS.width, 1040 - METRICS.height),
        "bottom_left": (0, 1040 - METRICS.height),
    }
    for corner, origin in expected.items():
        cfg = OverlayConfig(corner=corner)
        assert resolve_origin(METRICS, cfg, MONITOR, WORK) == origin, corner


def test_dragged_position_is_used_verbatim():
    cfg = OverlayConfig(x=400, y=320, positioned=True)
    assert resolve_origin(METRICS, cfg, MONITOR, WORK) == (400, 320)


def test_dragged_left_edge_is_not_mistaken_for_dock_mode():
    cfg = OverlayConfig(x=0, y=600, positioned=True)
    assert is_docked(cfg) is False
    assert resolve_origin(METRICS, cfg, MONITOR, WORK) == (0, 600)
    # The same numbers without ``positioned`` mean "dock to the right".
    assert resolve_origin(METRICS, OverlayConfig(x=0, y=600), MONITOR, WORK) == (
        1920 - METRICS.width,
        600,
    )


def test_dragged_position_is_clamped_inside_the_work_area():
    cfg = OverlayConfig(x=5000, y=5000, positioned=True)
    x, y = resolve_origin(METRICS, cfg, MONITOR, WORK)
    assert x == 1920 - METRICS.width
    assert y == 1040 - METRICS.height


def test_legacy_free_x_still_counts_as_a_dragged_spot():
    cfg = OverlayConfig(x=300, y=200)
    assert is_docked(cfg) is False
    assert resolve_origin(METRICS, cfg, MONITOR, WORK) == (300, 200)


def test_auto_y_sentinel_follows_the_corner():
    for corner, y in (("top_right", 0), ("bottom_right", 1040 - METRICS.height)):
        cfg = OverlayConfig(corner=corner, y=AUTO_Y)
        assert resolve_origin(METRICS, cfg, MONITOR, WORK)[1] == y


def test_second_monitor_offsets_the_origin():
    cfg = OverlayConfig()
    x, y = resolve_origin(METRICS, cfg, (1920, 0, 3840, 1080), (1920, 0, 3840, 1040))
    assert (x + METRICS.width, y) == (3840, 0)
