"""Dynamic discovery of Statlocker Companion install and database paths on any Windows PC."""

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def find_statlocker_paths() -> Tuple[Path, Path]:
    """Dynamically discover Statlocker Companion database and log paths on any Windows PC.

    Checks:
    1. Running process path (statlocker-companion.exe / statlocker.exe)
    2. LocalAppData, AppData, UserProfile, and ProgramData directories
    3. Windows Uninstall Registry keys for custom install locations
    4. Fallback defaults
    """
    candidates: List[Path] = []

    # 1. Check running process (highest fidelity across custom install locations)
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            p_name = (p.info.get("name") or "").lower()
            if "statlocker" in p_name:
                exe_path = p.info.get("exe")
                if exe_path:
                    p_dir = Path(exe_path).parent
                    candidates.append(p_dir)
                    candidates.append(p_dir / "statlocker-companion")
    except Exception:
        pass

    # 2. Standard Windows environment locations
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.extend(
            [
                Path(local_app_data) / "statlocker-companion",
                Path(local_app_data) / "Statlocker",
                Path(local_app_data) / "Programs" / "statlocker-companion",
                Path(local_app_data) / "Programs" / "Statlocker",
            ]
        )

    app_data = os.environ.get("APPDATA")
    if app_data:
        candidates.extend(
            [
                Path(app_data) / "statlocker-companion",
                Path(app_data) / "Statlocker",
            ]
        )

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / "AppData" / "Local" / "statlocker-companion")
        candidates.append(Path(user_profile) / "AppData" / "Roaming" / "statlocker-companion")

    program_data = os.environ.get("ProgramData")
    if program_data:
        candidates.append(Path(program_data) / "statlocker-companion")
        candidates.append(Path(program_data) / "Statlocker")

    # 2b. Shallow scan of %LOCALAPPDATA%\*\app.db for renamed install folders.
    if local_app_data:
        try:
            for child in Path(local_app_data).iterdir():
                if child.is_dir() and "statlocker" in child.name.lower():
                    candidates.append(child)
        except OSError:
            pass

    # 3. Check Windows Registry (uninstall entries)
    try:
        import winreg
        for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            try:
                with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\Uninstall") as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                disp_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                                if "statlocker" in str(disp_name).lower():
                                    loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                    if loc:
                                        candidates.append(Path(loc))
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    # Find the first candidate that actually contains app.db
    for c in candidates:
        try:
            db_cand = c / "app.db"
            if db_cand.exists() and db_cand.stat().st_size > 0:
                log_cand = c / "logs"
                return db_cand, log_cand
        except Exception:
            pass

    # Find candidate with logs if app.db is in parent or sibling
    for c in candidates:
        try:
            if (c / "logs").exists():
                return c / "app.db", c / "logs"
        except Exception:
            pass

    # Default fallback
    base = Path(local_app_data) if local_app_data else Path(os.path.expanduser("~")) / "AppData" / "Local"
    return base / "statlocker-companion" / "app.db", base / "statlocker-companion" / "logs"
