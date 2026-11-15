"""Config loading, validation and persistence tests."""

import json

from config import _from_dict, load_config, save_config
from models import OverlayConfig


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.json")
    assert cfg.layout == "horizontal"
    assert cfg.refresh_seconds == 20.0
    assert cfg.show_timer is False
    assert cfg.allow_db_fallback is False


def test_invalid_values_are_clamped_or_defaulted():
    cfg = _from_dict(
        {
            "layout": "diagonal",
            "opacity": 9.0,
            "hud_alpha": 0.1,
            "refresh_seconds": 0.1,
            "max_items": 99,
            "font_size": 99,
            "icon_size": 0,
            "wpa_region": "not-a-dict",
        }
    )
    assert cfg.layout == "horizontal"
    assert cfg.opacity == cfg.hud_alpha == 0.30
    assert cfg.refresh_seconds == 5.0
    assert cfg.max_items == 5
    assert cfg.font_size == 14
    assert cfg.icon_size == 20
    assert cfg.wpa_region is None


def test_legacy_auto_refresh_alias_is_honoured():
    cfg = _from_dict({"auto_refresh_seconds": 45})
    assert cfg.refresh_seconds == 45.0


def test_corner_is_normalised_to_a_known_value():
    assert _from_dict({"corner": "Bottom_Left"}).corner == "bottom_left"
    assert _from_dict({"corner": "center"}).corner == "top_right"
    assert _from_dict({}).corner == "top_right"


def test_icons_only_survives_a_save_load_round_trip(tmp_path):
    target = tmp_path / "overlay_config.json"
    original = OverlayConfig(icons_only=True)
    assert save_config(original, target) == target
    assert load_config(target).icons_only is True
    assert load_config(tmp_path / "missing.json").icons_only is False


def test_standby_badge_survives_a_save_load_round_trip(tmp_path):
    target = tmp_path / "overlay_config.json"
    original = OverlayConfig(standby_badge=True, corner="bottom_left")
    assert save_config(original, target) == target
    reloaded = load_config(target)
    assert reloaded.standby_badge is True
    assert reloaded.corner == "bottom_left"


def test_positioned_survives_a_save_load_round_trip(tmp_path):
    target = tmp_path / "overlay_config.json"
    original = OverlayConfig(x=0, y=640, positioned=True)
    assert save_config(original, target) == target
    reloaded = load_config(target)
    assert reloaded.positioned is True
    assert (reloaded.x, reloaded.y) == (0, 640)


def test_legacy_config_with_free_x_counts_as_dragged():
    assert _from_dict({"x": 700, "y": 260}).positioned is True
    assert _from_dict({"x": 0, "y": 120}).positioned is False
    assert _from_dict({"x": 0, "positioned": True}).positioned is True


def test_round_trip_writes_valid_json(tmp_path):
    target = tmp_path / "overlay_config.json"
    original = OverlayConfig(
        layout="vertical",
        refresh_seconds=30.0,
        max_items=3,
        show_timer=True,
        wpa_region={"x": 10, "y": 20, "w": 300, "h": 200},
    )
    saved = save_config(original, target)
    assert saved == target
    assert target.exists()

    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["layout"] == "vertical"
    assert raw["refresh_seconds"] == 30.0
    assert raw["auto_refresh_seconds"] == 30.0
    assert raw["show_timer"] is True

    reloaded = load_config(target)
    assert reloaded.layout == "vertical"
    assert reloaded.max_items == 3
    assert reloaded.show_timer is True
    assert reloaded.wpa_region == {"x": 10, "y": 20, "w": 300, "h": 200}
