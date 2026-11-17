"""Full build presentation stays current and within monitor bounds."""
import tkinter as tk
import pytest
from models import GameState, WpaItem
from ui.full_build_view import FullBuildView, full_build_metrics


def test_full_build_updates_and_removes_invalid_plan():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(str(error))
    root.withdraw()
    try:
        item = WpaItem(name="A complete item name", item_id=1, cost=500, win_rate=.55, can_buy=True)
        state = GameState(hero_name="Test Hero", recommended_items=[item], build_plan=[item],
                          owned_items={"Owned item"}, threat_summary="Enemy leads souls: 12,000")
        view = FullBuildView(root, state, full_build_metrics(1, (0, 0, 1024, 768)))
        assert view.item_names == [item.name]
        view.set_state(GameState(scan_status="unknown"))
        assert not view.item_names and not view.items
    finally:
        root.destroy()


def test_full_mode_config_and_small_monitor_bounds():
    from config import _from_dict, _to_dict
    assert _to_dict(_from_dict({"view_mode":"full"}))["view_mode"] == "full"
    assert _from_dict({"view_mode":"invalid"}).view_mode == "minimal"
    metrics = full_build_metrics(2, (0, 0, 800, 600))
    assert metrics.width <= 800 and metrics.height <= 600
