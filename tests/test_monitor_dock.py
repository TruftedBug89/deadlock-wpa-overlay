"""Multi-monitor docking math: pure selection plus layout structure."""

from win32_overlay import get_monitor_layouts, monitor_for_rect

LAYOUTS = [
    ((0, 0, 1920, 1080), (0, 0, 1920, 1040)),  # primary
    ((1920, 0, 3840, 1080), (1920, 0, 3840, 1040)),  # secondary right
]


def test_rect_fully_inside_secondary_selects_it():
    assert monitor_for_rect((2000, 100, 2500, 500), LAYOUTS) == 1


def test_rect_straddling_both_selects_larger_overlap():
    assert monitor_for_rect((1700, 100, 2100, 500), LAYOUTS) == 0
    assert monitor_for_rect((1800, 100, 2500, 500), LAYOUTS) == 1


def test_zero_overlap_falls_back_to_primary():
    assert monitor_for_rect((-32000, -32000, -31000, -31900), LAYOUTS) == 0


def test_empty_layouts_resolve_to_zero():
    assert monitor_for_rect((100, 100, 200, 200), []) == 0


def test_layout_enumeration_returns_usable_rects():
    layouts = get_monitor_layouts()
    assert len(layouts) >= 1
    for full, work in layouts:
        assert len(full) == 4 and len(work) == 4
        assert full[2] > full[0] and full[3] > full[1]
        assert work[2] > work[0] and work[3] > work[1]
