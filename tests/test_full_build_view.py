"""Full build presentation stays current and within monitor bounds."""
import tkinter as tk
from dataclasses import replace
import pytest
from models import GameState, WpaItem
from ui.full_build_view import FullBuildView, full_build_metrics
from tests.test_overlay_interaction import overlay


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
        row = view.rows[(view.queue_rows, 1)]
        view.show_page("Match")
        view.set_state(replace(state, buy_budget=700, next_buy=item))
        assert view.rows[(view.queue_rows, 1)] is row
        assert "Next buy" in row.name.cget("text")
        assert "700" in view.wallet.cget("text")
        assert view._active_page == "Match"
        view.set_state(GameState(scan_status="unknown"))
        assert not view.item_names and not view.items and not view.rows
    finally:
        root.destroy()


def test_full_mode_config_and_small_monitor_bounds():
    from config import _from_dict, _to_dict
    assert _to_dict(_from_dict({"view_mode":"full"}))["view_mode"] == "full"
    assert _from_dict({"view_mode":"invalid"}).view_mode == "minimal"
    metrics = full_build_metrics(2, (0, 0, 800, 600))
    assert metrics.width <= 800 and metrics.height <= 600


def test_full_build_keeps_the_same_row_when_shop_art_arrives(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(str(error))
    root.withdraw()
    try:
        item = WpaItem(name="Shop item", item_id=1, image_url="shop.png")
        state = GameState(recommended_items=[item], build_plan=[item])
        view = FullBuildView(root, state, full_build_metrics(1, (0, 0, 1024, 768)))
        row = view.rows[(view.queue_rows, 1)]
        assert not row._icon.cget("image")

        art = tk.PhotoImage(master=root, width=12, height=8)
        monkeypatch.setattr("ui.full_build_view.get_item_photo", lambda url, size: art)
        view.set_state(state)
        assert view.rows[(view.queue_rows, 1)] is row
        assert row._icon.cget("image") == str(art)
    finally:
        root.destroy()


def replacement_state():
    from models import ItemReplacement
    buy = WpaItem(name="Stronger current item", item_id=7, cost=3200, win_rate=.56,
                  image_url="https://assets.example/shop.png", samples=1500)
    swap = ItemReplacement(sell_name="Held item", sell_id=4, buy=buy,
                           held_win_rate=.49, buy_win_rate=.56, supported_gap=.03,
                           basis="bracket", sell_matches=1600, buy_matches=1500,
                           slots_used=12, slot_limit=12, held_upper=.51, buy_lower=.54,
                           pool_baseline=.5, minimum_supported_gap=.01)
    state = GameState(hero_name="Test Hero", match_id="9001", is_in_match=True,
                      scan_status="ok", buy_budget=4000, known_owned_items=12,
                      replacement=swap, inventory_capacity=12)
    return state


def test_full_board_shows_and_withdraws_replacement_without_queue(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(str(error))
    root.withdraw()
    try:
        art = tk.PhotoImage(master=root, width=12, height=8)
        calls = []
        monkeypatch.setattr("ui.full_build_view.get_item_photo",
                            lambda url, size: calls.append(url) or art)
        state = replacement_state()
        view = FullBuildView(root, state, full_build_metrics(1, (0, 0, 1024, 768)))
        panel = view.replacement_panel
        assert panel.winfo_manager() == "pack"
        assert panel.sell.cget("text") == "Sell Held item"
        assert panel.buy.cget("text") == "Buy Stronger current item"
        assert "3,200" in panel.price.cget("text")
        assert "Historical WR 49.0% / 56.0%" in panel.evidence.cget("text")
        assert "12/12" in view.inventory.cget("text")
        assert panel.art.cget("image") == str(art)
        assert calls == [state.replacement.buy.image_url]
        view.set_state(GameState(scan_status="unknown"))
        assert panel.winfo_manager() == ""
        assert panel.buy.cget("text") == panel.sell.cget("text") == ""
        assert panel.art.cget("image") == ""
    finally:
        root.destroy()


def test_swap_only_uses_full_board_or_minimal_status():
    from models import OverlayConfig
    from ui.hud_presentation import get_desired_content, get_status_info
    state = replacement_state()
    assert get_desired_content(state, OverlayConfig(view_mode="full"), True) == ("items", 1)
    assert get_desired_content(state, OverlayConfig(view_mode="minimal"), True) == ("status", 1)
    assert get_status_info(state)[0] == "SWAP OPTION / OPEN FULL BUILD"
    assert "SWAP" not in get_status_info(GameState())[0]


def test_full_rows_preserve_overall_evidence_marker():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(str(error))
    root.withdraw()
    try:
        item = WpaItem("Item", item_id=1, samples=1000, win_rate=.54, reason="Overall / POPULAR")
        view = FullBuildView(root, GameState(recommended_items=[item], build_plan=[item]),
                             full_build_metrics(1, (0, 0, 1024, 768)))
        assert "Overall" in view.rows[(view.queue_rows, 1)].detail.cget("text")
        assert view.replacement_panel.winfo_manager() == ""
    finally:
        root.destroy()


def test_replacement_layout_wraps_inside_a_narrow_board():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(str(error))
    root.withdraw()
    try:
        metrics = full_build_metrics(2, (0, 0, 360, 500))
        state = replacement_state()
        view = FullBuildView(root, state, metrics)
        view.pack(fill="both", expand=True)
        root.geometry(f"{metrics.width}x{metrics.height}")
        root.update_idletasks()
        assert metrics.width <= 360 and metrics.height <= 500
        assert view.replacement_panel.buy.winfo_reqwidth() < metrics.width
        assert view.replacement_panel.evidence.winfo_reqwidth() < metrics.width
        assert view.replacement_panel.winfo_reqwidth() <= metrics.width
    finally:
        root.destroy()


def test_overlay_swap_only_refreshes_and_clears_while_dragging(overlay):
    overlay.config.view_mode = "full"
    state = replacement_state()
    overlay._apply_new_state(state)
    assert overlay._content_kind == "full_build"
    view = overlay._view
    panel = view.replacement_panel
    fresh_buy = replace(state.replacement.buy, name="Updated item", cost=3500)
    fresh = replace(state, replacement=replace(state.replacement, buy=fresh_buy))
    overlay._apply_new_state(fresh)
    assert overlay._view is view
    assert panel.buy.cget("text") == "Buy Updated item"
    overlay._drag_handler.active = True
    geometry = overlay.root.geometry()
    overlay._apply_new_state(GameState(source="advisor", scan_status="unknown"))
    assert panel.winfo_manager() == ""
    assert panel.buy.cget("text") == ""
    assert overlay.root.geometry() == geometry
    overlay._drag_handler.active = False
    overlay._render_content()


def test_replacement_art_keeps_existing_download_budget(overlay, monkeypatch):
    overlay.config.view_mode = "full"
    state = replacement_state()
    state.build_plan = [WpaItem("One", image_url="one"), WpaItem("Two", image_url="two")]
    attempts = []
    monkeypatch.setattr("icon_loader.can_prewarm", lambda _: True)
    monkeypatch.setattr("icon_loader.prewarm_icon", lambda url: attempts.append(url) or True)
    overlay._prewarm_icons(state)
    assert attempts == [state.replacement.buy.image_url, "one"]


@pytest.mark.parametrize("capacity,count,label", [(12, 12, "Inventory full"),
                                                   (None, 9, "Available slots unknown")])
def test_full_inventory_without_safe_buy_keeps_match_board(overlay, capacity, count, label):
    from models import OverlayConfig
    from ui.hud_presentation import get_desired_content, get_status_info
    overlay.config.view_mode = "full"
    state = GameState(source="advisor", scan_status="ok", is_in_match=True,
                      hero_name="Current Hero", match_id="9001", buy_budget=4600,
                      known_owned_items=count, inventory_capacity=capacity, owned_items={"Held item"})
    overlay._apply_new_state(state)
    assert overlay._content_kind == "full_build"
    view = overlay._view
    assert "Current Hero" in view.title.cget("text")
    assert "4,600" in view.wallet.cget("text")
    assert label in view.inventory.cget("text")
    assert view.replacement_panel.winfo_manager() == ""
    view.show_page("Match")
    assert "Held item" in view.owned.cget("text")
    overlay._drag_handler.active = True
    overlay._apply_new_state(replace(state, buy_budget=4700))
    assert overlay._content_kind == "full_build"
    assert "4,700" in view.wallet.cget("text")
    assert view._active_page == "Match"
    overlay._drag_handler.active = False
    assert get_desired_content(state, OverlayConfig(view_mode="minimal"), True) == ("status", 1)
    assert get_status_info(state)[0] == label.upper()
    invalid = replace(state, scan_status="unknown")
    assert get_desired_content(invalid, OverlayConfig(view_mode="full"), True) == ("status", 1)
