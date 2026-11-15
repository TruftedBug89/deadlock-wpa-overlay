"""Tray promotion helpers (pure registry-key logic, no live tray needed)."""

from tray_manager import (
    _get_tray_icon_image,
    icon_belongs_to_app,
    new_icon_keys,
    promote_icon_keys,
    snapshot_notify_icons,
)


def test_new_keys_are_a_set_difference():
    assert new_icon_keys({"a", "b"}, {"a", "b", "c"}) == {"c"}
    assert new_icon_keys(set(), set()) == set()
    assert new_icon_keys({"a"}, set()) == set()


def test_frozen_app_path_is_recognised():
    assert icon_belongs_to_app(r"C:\Apps\DeadlockWPAOverlay\DeadlockWPAOverlay.exe")
    assert icon_belongs_to_app(r"C:\Python311\python.exe", "Deadlock WPA Overlay")


def test_unrelated_icons_are_left_alone():
    assert not icon_belongs_to_app(r"C:\Program Files\Discord\Discord.exe", "Discord")
    assert not icon_belongs_to_app("", "")


def test_icon_image_is_64px():
    image = _get_tray_icon_image()
    assert image.size == (64, 64)
    assert image.mode == "RGBA"


def test_snapshot_is_safe_on_any_host():
    # Returns a set even when the Windows 11 key is absent.
    assert isinstance(snapshot_notify_icons(), set)


def test_promote_invalid_key_is_noop():
    assert promote_icon_keys(["not-a-real-icon-key"]) == []
