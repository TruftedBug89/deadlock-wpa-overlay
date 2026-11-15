"""Unit tests for the Statlocker capture archiver."""

from pathlib import Path
from types import SimpleNamespace
import numpy as np

from capture_archiver import StatlockerCaptureArchiver, _slugify, get_captures_directory


def test_slugify():
    assert _slugify("Curse") == "curse"
    assert _slugify("Diviner's Kevlar") == "diviner_s_kevlar"
    assert _slugify("   ") == "item"
    assert _slugify("100% Winrate!") == "100_winrate"


def test_save_if_changed(tmp_path: Path):
    archiver = StatlockerCaptureArchiver(target_dir=tmp_path)
    rgb = np.zeros((100, 100, 3), dtype=np.uint8)
    frame = SimpleNamespace(rgb=rgb)

    # 1. First save succeeds
    saved1 = archiver.save_if_changed(frame, ["Curse", "Lucky Shot"])
    assert saved1 is not None
    assert saved1.exists()
    assert "curse-lucky_shot" in saved1.name
    assert archiver.last_captured_items == ("Curse", "Lucky Shot")

    # 2. Duplicate items do not save
    saved2 = archiver.save_if_changed(frame, ["Curse", "Lucky Shot"])
    assert saved2 is None

    # 3. Changed items trigger a new save
    saved3 = archiver.save_if_changed(frame, ["Curse", "Siphon Bullets"])
    assert saved3 is not None
    assert saved3.exists()
    assert "curse-siphon_bullets" in saved3.name
    assert archiver.last_captured_items == ("Curse", "Siphon Bullets")


def test_empty_or_invalid_frame(tmp_path: Path):
    archiver = StatlockerCaptureArchiver(target_dir=tmp_path)
    # Empty items
    assert archiver.save_if_changed(SimpleNamespace(rgb=np.zeros((10, 10, 3), dtype=np.uint8)), []) is None
    # None frame
    assert archiver.save_if_changed(None, ["Curse"]) is None
    # Frame missing rgb
    assert archiver.save_if_changed(SimpleNamespace(), ["Curse"]) is None
