"""One-shot diagnostic report for the live Statlocker read pipeline.

Run ``python main.py --diagnose``.  It works whether or not Deadlock is running;
when Statlocker Companion is open it reports exactly what the overlay would see
(heading position, card boxes, OCR text, catalog matches) and writes annotated
debug images so a misdetection is obvious instead of mysterious.
"""

import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from PIL import Image, ImageDraw

import config as config_module
from data_source import StatlockerDataSource
from live_screen_reader import read_live_wpa_screen
from statlocker_discovery import find_statlocker_paths
from ui.hud_geometry import compute_metrics, dock_x
from win32_overlay import (
    clear_process_cache,
    enable_dpi_awareness,
    get_monitor_bounds,
    get_screen_bounds,
    is_process_running,
    ui_scale,
)
from wpa_detector import (
    capture_statlocker_frame,
    locate_wpa_header,
    reset_detection_cache,
    template_shape,
)


def _artifact_dir() -> Path:
    base = (
        Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
        / "DeadlockWPAOverlay"
        / "diagnostics"
    )
    path = base / time.strftime("%Y%m%d-%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _annotate(frame_rgb, region, boxes, output: Path) -> None:
    """Draw the detected row and card boxes onto a copy of the frame."""
    if frame_rgb is None:
        return
    image = Image.fromarray(frame_rgb, mode="RGB")
    draw = ImageDraw.Draw(image)
    if region:
        x, y, w, h = region
        draw.rectangle([x, y, x + w, y + h], outline=(56, 189, 248), width=2)
    for index, box in enumerate(boxes, start=1):
        x0 = (region[0] if region else 0) + box.x
        y0 = (region[1] if region else 0) + box.y
        draw.rectangle([x0, y0, x0 + box.w, y0 + box.h], outline=(222, 139, 0), width=2)
        draw.text((x0 + 3, y0 + 2), f"#{index}", fill=(255, 255, 255))
    image.save(output)


def _geometry_report(config) -> Dict:
    scale = ui_scale()
    _left, _top, right, _bottom = get_monitor_bounds()
    rows = {}
    for slots in range(1, 6):
        metrics = compute_metrics(
            config.layout,
            slots,
            scale,
            show_timer=bool(getattr(config, "show_timer", False)),
        )
        rows[str(slots)] = {
            "width": metrics.width,
            "height": metrics.height,
            "x": dock_x(metrics, right),
            "right_gap": right - (dock_x(metrics, right) + metrics.width),
        }
    return {"layout": config.layout, "scale": scale, "right_edge": right, "by_card_count": rows}


def run_diagnostics(region_override: Optional[dict] = None, write_artifacts: bool = True) -> Dict:
    """Collect everything needed to explain what the overlay currently sees."""
    enable_dpi_awareness()
    clear_process_cache()
    reset_detection_cache()
    artifacts = _artifact_dir() if write_artifacts else None
    config = config_module.load_config()

    report: Dict = {
        "version": "2.0.0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "monitor": get_monitor_bounds(),
        "work_area": get_screen_bounds(),
        "processes": {
            "deadlock": is_process_running("deadlock.exe", max_age=0),
            "project8": is_process_running("project8.exe", max_age=0),
        },
        "config": {
            "path": str(config_module.config_path() or ""),
            "refresh_seconds": config.refresh_seconds,
            "layout": config.layout,
            "max_items": config.max_items,
            "wpa_region": config.wpa_region,
        },
        "template": template_shape(),
        "hud_geometry": _geometry_report(config),
    }

    discovered_db, discovered_log = find_statlocker_paths()
    report["statlocker"] = {
        "db_path": str(discovered_db),
        "db_exists": discovered_db.exists(),
        "log_dir": str(discovered_log),
        "log_dir_exists": discovered_log.exists(),
    }

    data_source = StatlockerDataSource()
    has_catalog = data_source.load_catalog()
    report["catalog"] = {
        "ok": has_catalog,
        "items": len(data_source.catalog_items()),
        "error": data_source.catalog_error,
    }

    frame = capture_statlocker_frame()
    if frame is None:
        report["screen"] = {"status": "not_visible", "reason": "Statlocker window not capturable"}
        report["artifacts"] = str(artifacts) if artifacts else ""
        return report

    header = locate_wpa_header(frame)
    report["screen"] = {
        "status": "ok",
        "method": frame.method,
        "window_rect": frame.rect,
        "window_size": frame.size,
        "header": None
        if header is None
        else {
            "x": header.x,
            "y": header.y,
            "width": header.width,
            "height": header.height,
            "score": round(header.score, 4),
            "scale": header.scale,
        },
    }
    if artifacts:
        Image.fromarray(frame.rgb, mode="RGB").save(artifacts / "frame.png")

    if header is None:
        report["screen"]["status"] = "header_not_found"
        report["artifacts"] = str(artifacts) if artifacts else ""
        return report

    read = read_live_wpa_screen(
        data_source.catalog_items(),
        region_override=region_override,
    )
    report["scan"] = {
        "status": read.status,
        "error": read.error,
        "region": read.region,
        "detected_cards": read.detected,
        "resolved_cards": read.resolved,
        "cards": [
            {
                "slot": card.index,
                "box": {"x": card.box.x, "y": card.box.y, "w": card.box.w, "h": card.box.h},
                "ocr": card.raw_text,
                "cleaned": card.cleaned_text,
                "matched": card.name,
                "score": round(card.score, 4),
                "ambiguous": card.ambiguous,
            }
            for card in read.cards
        ],
    }

    state = data_source.get_game_state(max_items=5, region_override=region_override)
    report["state"] = {
        "is_in_match": state.is_in_match,
        "hero": f"{state.hero_name} ({state.hero_id})",
        "source": state.source,
        "scan_status": state.scan_status,
        "items": [item.name for item in state.recommended_items],
        "error": state.last_error,
    }

    if artifacts:
        if read.region:
            x, y, w, h = read.region
            Image.fromarray(frame.rgb[y : y + h, x : x + w], mode="RGB").save(artifacts / "row.png")
        _annotate(frame.rgb, read.region, [card.box for card in read.cards], artifacts / "cards_annotated.png")
        report["artifacts"] = str(artifacts)
        (artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    return report


def main(argv: Optional[list] = None) -> int:
    """CLI entry: print the report as JSON and return an exit code."""
    import argparse

    parser = argparse.ArgumentParser(description="Deadlock WPA overlay diagnostics")
    parser.add_argument("--json", action="store_true", help="machine-readable output only")
    parser.add_argument("--no-artifacts", action="store_true", help="skip debug images")
    args = parser.parse_args(argv)

    report = run_diagnostics(write_artifacts=not args.no_artifacts)
    print(json.dumps(report, indent=2))
    if not args.json:
        print("\nDiagnostics complete.")
    # Exit 0 only when a recommendation row was actually read.  A missing
    # window, a missing heading or unresolved cards are diagnostic failures.
    return 0 if report.get("scan", {}).get("status") in ("ok", "empty") else 2


if __name__ == "__main__":
    raise SystemExit(main())
