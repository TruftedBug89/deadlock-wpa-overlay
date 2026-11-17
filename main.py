"""Entry point for the Deadlock WPA overlay."""

import argparse
import ctypes
import os
import sys
from pathlib import Path

from version import VERSION

def _install_safe_streams() -> None:
    if getattr(sys, "frozen", False):
        from app_logging import SafeLogStream
        sys.stdout = sys.stderr = SafeLogStream()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Deadlock WPA overlay")
    parser.add_argument("--view", choices=["minimal", "full"], default=None,
                        help="five-item queue or complete current-game build board")
    parser.add_argument("--layout", choices=["vertical", "horizontal"], default=None)
    parser.add_argument("--corner", choices=["top_left", "top_right", "bottom_left", "bottom_right"], default=None)
    parser.add_argument("--opacity", type=float, default=None, help="0.3 .. 1.0")
    parser.add_argument("--size", type=float, default=None,
                        help="HUD size multiplier 0.75 .. 2.0 (tray and settings do the same)")
    parser.add_argument("--items", type=int, default=None, help="max cards to display (1..5)")
    parser.add_argument("--y", type=int, default=None, help="vertical offset in pixels")
    parser.add_argument("--queue-seconds", type=float, default=None,
                        help="seconds between new queued suggestions (default 150)")
    parser.add_argument("--refresh-seconds", type=float, default=None, help="poll cadence (default 20)")
    parser.add_argument("--force-show", action="store_true", help="ignore the in-game auto-hide rule")
    parser.add_argument("--unlocked", action="store_true", help="start in move mode (not click-through)")
    parser.add_argument("--preview-hero", type=int, default=None, help="show a build preview for this hero id")
    parser.add_argument(
        "--preview-souls", type=int, default=None, metavar="SOULS",
        help="assume earned souls for previews (bracket and tempo, not spendable gold)",
    )
    parser.add_argument("--no-counters", action="store_true", help="hide the COUNTER ITEMS panel")
    parser.add_argument(
        "--source", choices=("auto", "statlocker", "advisor"), default="advisor",
        help="data source: deadlock-api only (default), mirror Statlocker, or auto",
    )
    parser.add_argument("--hero", type=int, default=None, metavar="HERO_ID",
                        help="hero id to recommend for in advisor mode")
    parser.add_argument("--match-id", type=int, default=None,
                        help="live match id (deadlock-api live broadcast)")
    parser.add_argument("--read-match-id", action="store_true",
                        help="read only the match ID from the game corner")
    parser.add_argument("--account", type=int, default=None,
                        help="Steam account id for live match identity (auto-detected)")
    parser.add_argument("--live-report", type=int, default=None, metavar="MATCH_ID",
                        help="print the live match roster/souls from deadlock-api and exit")
    parser.add_argument(
        "--enemy-heroes", default=None, metavar="ID,ID",
        help="override the enemy hero ids used for counter items (preview/testing)",
    )
    parser.add_argument(
        "--counters-report", type=int, default=None, metavar="HERO_ID",
        help="print the strongest enemy and build-bound counter items, then exit",
    )
    parser.add_argument("--diagnose", action="store_true", help="print a live screen-read report and exit")
    parser.add_argument("--explain", action="store_true",
                        help="print the picker evidence (context, scores, win rates) as JSON and exit")
    parser.add_argument("--no-artifacts", action="store_true", help="diagnostics: skip debug images")
    parser.add_argument("--no-tray", action="store_true", help="do not create the tray icon")
    parser.add_argument("--no-dpi", action="store_true", help="skip DPI awareness (debug only)")
    parser.add_argument("--version", action="version", version=f"Deadlock WPA Overlay {VERSION}")
    return parser.parse_args(argv)


def _parse_hero_ids(raw):
    """Comma separated hero ids -> list[int], ignoring junk."""
    ids = []
    for token in str(raw or "").replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids


def _acquire_single_instance():
    """Return a mutex handle, or None when another instance is already running."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, "Local\\DeadlockWpaOverlay")
        if handle and ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            return None
        return handle
    except Exception:
        return 0


def main(argv=None) -> int:
    _install_safe_streams()
    from app_logging import setup_logging

    setup_logging()
    args = parse_args(argv)

    if args.live_report is not None:
        import json

        from live_match import fetch_live_snapshot

        snapshot = fetch_live_snapshot(args.live_report)
        if snapshot is None:
            print(json.dumps({"match_id": args.live_report, "status": "unavailable"}, indent=2))
            return 1
        teams: dict = {}
        for player in snapshot.players:
            teams.setdefault(str(player.team), []).append(
                {
                    "account_id": player.account_id,
                    "hero_id": player.hero_id,
                    "souls": player.souls,
                    "level": player.level,
                    "kills": player.kills,
                    "deaths": player.deaths,
                }
            )
        for players in teams.values():
            players.sort(key=lambda entry: entry["souls"], reverse=True)
        print(json.dumps(
            {"match_id": snapshot.match_id, "tick": snapshot.tick, "teams": teams},
            indent=2,
        ))
        return 0

    if args.counters_report is not None:
        import json

        from data_source import StatlockerDataSource

        report = StatlockerDataSource().counter_report(
            args.counters_report, _parse_hero_ids(args.enemy_heroes) or None
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("status") == "ok" else 1

    if args.diagnose:
        from diagnostics import run_diagnostics
        import json

        report = run_diagnostics(write_artifacts=not args.no_artifacts)
        print(json.dumps(report, indent=2))
        screen_status = report.get("screen", {}).get("status") or report.get("scan", {}).get("status")
        return 0 if screen_status in ("ok", "empty") else 2

    if args.explain:
        import json

        from advisor_source import AdvisorDataSource

        source = AdvisorDataSource(
            hero_id=args.hero or args.preview_hero,
            enemy_ids=_parse_hero_ids(args.enemy_heroes),
            match_id=args.match_id,
            account_id=args.account,
            read_match_id=args.read_match_id,
            require_match=args.preview_hero is None,
            preview_souls=args.preview_souls,
        )
        state = source.get_game_state(max_items=args.items or 5)
        payload = {
            "state": {
                "scan_status": state.scan_status,
                "hero": state.hero_name,
                "match_id": state.match_id,
                "souls": state.net_worth,
                "buy_budget": state.buy_budget,
                "stage": state.stage,
                "stance": state.stance,
                "soul_lead": state.soul_lead,
                "items": [
                    {
                        "name": item.name,
                        "cost": item.cost,
                        "win_rate": item.winrate_text,
                        "samples": item.samples,
                        "reason": item.reason,
                    }
                    for item in state.recommended_items
                ],
            },
            "explanation": source.last_explanation,
        }
        print(json.dumps(payload, indent=2))
        return 0 if state.scan_status == "ok" else 2

    if args.no_dpi:
        os.environ["DEADLOCK_OVERLAY_NO_DPI"] = "1"

    from config import load_config, save_config
    from ui.main_window import OverlayWindow
    from win32_overlay import attach_to_default_desktop, get_monitor_bounds, get_screen_bounds

    mutex = _acquire_single_instance()
    if mutex is None:
        print("Deadlock WPA Overlay is already running.")
        return 0

    attach_to_default_desktop()
    config = load_config()

    if args.view:
        config.view_mode = args.view
    if args.layout:
        config.layout = args.layout
    if args.force_show:
        config.only_in_game = False
    if args.unlocked:
        config.clickthrough = False
    if args.opacity is not None:
        config.hud_alpha = max(0.3, min(1.0, args.opacity))
        config.opacity = config.hud_alpha
    if args.items is not None:
        config.max_items = max(1, min(5, args.items))
    if args.no_counters:
        config.show_counters = False
    if args.source:
        config.source = args.source
    if args.hero is not None:
        config.hero_id = args.hero
    if args.read_match_id:
        config.read_match_id = True
    if args.account is not None:
        config.account_id = args.account
    if args.match_id is not None:
        config.match_id = args.match_id
    if args.queue_seconds is not None:
        config.queue_seconds = max(60.0, min(600.0, args.queue_seconds))
    if args.refresh_seconds is not None:
        config.refresh_seconds = max(5.0, args.refresh_seconds)
    if args.size is not None:
        config.hud_scale = max(0.75, min(2.0, float(args.size)))
    if args.y is not None:
        config.y = args.y
    elif args.corner and args.corner.startswith("bottom"):
        _left, _top, _right, bottom = get_screen_bounds()
        config.y = max(0, bottom - 140)
    save_config(config)

    enemy_override = _parse_hero_ids(args.enemy_heroes)
    if enemy_override:
        config.enemy_hero_ids = enemy_override

    mode = args.source or config.source
    use_advisor = mode == "advisor"
    if mode == "auto":
        from statlocker_discovery import find_statlocker_paths

        db_path, _log_dir = find_statlocker_paths()
        use_advisor = not (db_path and db_path.exists())

    if use_advisor:
        from advisor_source import AdvisorDataSource

        data_source = AdvisorDataSource(
            hero_id=args.hero or args.preview_hero or config.hero_id,
            enemy_ids=config.enemy_hero_ids,
            match_id=args.match_id or config.match_id,
            account_id=args.account or config.account_id,
            read_match_id=config.read_match_id,
            # An explicit --preview-hero is a deliberate preview outside a match.
            require_match=args.preview_hero is None,
            preview_souls=args.preview_souls,
        )
    else:
        from data_source import StatlockerDataSource

        data_source = StatlockerDataSource()
        data_source.manual_match_id = args.match_id
        if args.preview_hero is not None:
            data_source.manual_hero_id = args.preview_hero
        elif args.hero is not None:
            data_source.manual_hero_id = args.hero
        if config.enemy_hero_ids:
            data_source.manual_enemy_heroes = list(config.enemy_hero_ids)

    overlay = OverlayWindow(
        config=config,
        data_source=data_source,
        enable_tray=not args.no_tray,
        enable_dpi=not args.no_dpi,
    )

    _left, _top, right, _bottom = get_monitor_bounds()
    print(f"Deadlock WPA Overlay {VERSION}")
    print(f"  layout={config.layout} items={config.max_items} refresh={config.refresh_seconds:g}s")
    print(f"  right edge at x={right} (width computed per card count)")
    print("  F6 preview hero | F7 auto-hide | F8 layout | F9 lock/move | F10 show/hide")
    print(f"  source: {'advisor (deadlock-api)' if use_advisor else 'statlocker (live WPA row)'}")
    print(f"  counters: {'on' if config.show_counters else 'off'} (build counter items vs strongest enemy)")
    print("  tray: right-click for Move Overlay and Position (4 corners)")
    overlay.start()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        try:
            log_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "DeadlockWPAOverlay"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise
