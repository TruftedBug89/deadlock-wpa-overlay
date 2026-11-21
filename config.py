"""Configuration loading, validation, migration and atomic persistence."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import OverlayConfig
from local_account import normalize_account_id

_ACTIVE_PATH: Optional[Path] = None

# Legacy keys that older builds wrote and that still map onto today's fields.
_LEGACY_ALIASES = {
    "refresh_seconds": ("refresh_seconds", "auto_refresh_seconds"),
    "auto_refresh_seconds": ("auto_refresh_seconds", "refresh_seconds"),
    "hud_alpha": ("hud_alpha", "opacity"),
}


def get_config_search_paths() -> List[Path]:
    """Return config locations in priority order (portable first)."""
    paths: List[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).resolve().parent
    paths.append(exe_dir / "overlay_config.json")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        paths.append(Path(local_app_data) / "DeadlockWPAOverlay" / "overlay_config.json")
    else:
        paths.append(Path.home() / "AppData" / "Local" / "DeadlockWPAOverlay" / "overlay_config.json")
    return paths


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _first(data: Dict[str, Any], field: str, default: Any) -> Any:
    """Read a field, honouring legacy aliases, without raising on bad input."""
    for key in _LEGACY_ALIASES.get(field, (field,)):
        if key in data and data[key] is not None:
            return data[key]
    return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _from_dict(data: Dict[str, Any]) -> OverlayConfig:
    """Build a validated config from a raw JSON dictionary."""
    region = data.get("wpa_region")
    if not isinstance(region, dict):
        region = None

    layout = str(_first(data, "layout", "horizontal")).lower()
    if layout not in ("horizontal", "vertical"):
        layout = "horizontal"

    corner = str(data.get("corner", "top_right")).lower()
    if corner not in ("top_right", "top_left", "bottom_right", "bottom_left"):
        corner = "top_right"

    icons_only = _to_bool(data.get("icons_only"), False)

    source = str(data.get("source") or "auto").lower()
    if source not in ("auto", "statlocker", "advisor"):
        source = "auto"
    hero_id = _to_int(data.get("hero_id"), 0) or None
    enemy_hero_ids = []
    for raw in data.get("enemy_hero_ids") or []:
        value = _to_int(raw, 0)
        if value > 0:
            enemy_hero_ids.append(value)

    # Older configs encoded "dragged somewhere" purely as x != 0; keep that
    # meaning so an existing position survives the upgrade.
    x_value = _to_int(_first(data, "x", 0), 0)
    refresh = _to_float(_first(data, "refresh_seconds", 20.0), 20.0)
    cfg = OverlayConfig(
        x=x_value,
        y=_to_int(_first(data, "y", 120), 120),
        corner=corner,
        positioned=_to_bool(data.get("positioned"), x_value != 0),
        opacity=_clamp(_to_float(data.get("opacity"), 0.80), 0.30, 1.0),
        clickthrough=_to_bool(data.get("clickthrough"), True),
        hover_controls=_to_bool(data.get("hover_controls"), True),
        only_in_game=_to_bool(data.get("only_in_game"), False),
        only_when_focused=_to_bool(data.get("only_when_focused"), False),
        layout=layout,
        view_mode="full" if data.get("view_mode") == "full" else "minimal",
        refresh_seconds=_clamp(refresh, 5.0, 300.0),
        queue_seconds=_clamp(_to_float(data.get("queue_seconds"), 150.0), 60.0, 600.0),
        auto_refresh_seconds=_clamp(refresh, 5.0, 300.0),
        max_items=int(_clamp(_to_int(_first(data, "max_items", 5), 5), 1, 5)),
        font_size=int(_clamp(_to_int(data.get("font_size"), 8), 6, 14)),
        icon_size=int(_clamp(_to_int(data.get("icon_size"), 32), 20, 64)),
        hud_alpha=_clamp(_to_float(_first(data, "hud_alpha", 0.80), 0.80), 0.30, 1.0),
        hud_scale=_clamp(_to_float(data.get("hud_scale"), 1.0), 0.75, 2.0),
        tray_promote=_to_bool(data.get("tray_promote"), False),
        tray_notify=_to_bool(data.get("tray_notify"), False),
        allow_db_fallback=_to_bool(data.get("allow_db_fallback"), False),
        show_timer=_to_bool(data.get("show_timer"), False),
        standby_badge=_to_bool(data.get("standby_badge"), False),
        source=source,
        hero_id=hero_id,
        read_match_id=_to_bool(data.get("read_match_id"), False),
        account_id=normalize_account_id(data.get("account_id")),
        match_id=_to_int(data.get("match_id"), 0) or None,
        enemy_hero_ids=enemy_hero_ids,
        icons_only=icons_only,
        show_counters=_to_bool(data.get("show_counters"), True),
        max_counters=int(_clamp(_to_int(data.get("max_counters"), 3), 1, 5)),
        wpa_region=region,
    )
    cfg.opacity = cfg.hud_alpha
    return cfg


def load_config(path: Optional[Path] = None) -> OverlayConfig:
    """Load the first readable config, falling back to defaults."""
    global _ACTIVE_PATH
    search_paths = [path] if path is not None else get_config_search_paths()

    for candidate in search_paths:
        if not candidate or not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError("config root is not an object")
            _ACTIVE_PATH = candidate
            return _from_dict(raw)
        except Exception as err:  # pragma: no cover - depends on host state
            print(f"[Config] Ignoring unreadable config {candidate}: {err}")

    _ACTIVE_PATH = None
    return OverlayConfig()


def _to_dict(config: OverlayConfig) -> Dict[str, Any]:
    return {
        "x": int(config.x),
        "y": int(config.y),
        "corner": config.corner,
        "positioned": bool(config.positioned),
        "opacity": round(float(config.opacity), 3),
        "clickthrough": bool(config.clickthrough),
        "hover_controls": bool(config.hover_controls),
        "only_in_game": bool(config.only_in_game),
        "only_when_focused": bool(config.only_when_focused),
        "layout": config.layout,
        "view_mode": config.view_mode,
        "refresh_seconds": round(float(config.refresh_seconds), 2),
        "queue_seconds": round(float(config.queue_seconds), 2),
        "auto_refresh_seconds": round(float(config.refresh_seconds), 2),
        "max_items": int(config.max_items),
        "font_size": int(config.font_size),
        "icon_size": int(config.icon_size),
        "hud_alpha": round(float(config.hud_alpha), 3),
        "hud_scale": round(float(config.hud_scale), 3),
        "tray_promote": bool(config.tray_promote),
        "tray_notify": bool(config.tray_notify),
        "allow_db_fallback": bool(config.allow_db_fallback),
        "show_timer": bool(config.show_timer),
        "standby_badge": bool(config.standby_badge),
        "source": str(config.source),
        "hero_id": config.hero_id,
        "read_match_id": config.read_match_id,
        "account_id": config.account_id,
        "match_id": config.match_id,
        "enemy_hero_ids": [int(e) for e in config.enemy_hero_ids],
        "icons_only": bool(config.icons_only),
        "show_counters": bool(config.show_counters),
        "max_counters": int(config.max_counters),
        "wpa_region": config.wpa_region,
    }


def config_path() -> Optional[Path]:
    """Path of the config file currently in use (if any)."""
    return _ACTIVE_PATH


def save_config(config: OverlayConfig, path: Optional[Path] = None) -> Optional[Path]:
    """Atomically persist config, preferring the file that was loaded."""
    global _ACTIVE_PATH
    config.refresh_seconds = _clamp(float(config.refresh_seconds), 5.0, 300.0)
    config.auto_refresh_seconds = config.refresh_seconds
    config.hud_alpha = _clamp(float(config.hud_alpha), 0.30, 1.0)
    config.opacity = config.hud_alpha
    config.hud_scale = _clamp(float(getattr(config, "hud_scale", 1.0) or 1.0), 0.75, 2.0)

    if path is not None:
        targets = [path]
    elif _ACTIVE_PATH is not None:
        targets = [_ACTIVE_PATH]
    else:
        targets = get_config_search_paths()

    payload = json.dumps(_to_dict(config), indent=2)
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
            _ACTIVE_PATH = target
            return target
        except Exception:
            continue
    return None
