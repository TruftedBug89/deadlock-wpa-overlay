"""Low-duty polling policy for a background overlay."""

LIVE_FRESHNESS_S = 45.0


def game_running():
    from win32_overlay import is_process_running
    return any(is_process_running(name) for name in ("deadlock.exe", "project8.exe"))


def poll_interval(config, state, advisor=True, running=True):
    if not advisor:
        return max(5.0, float(config.refresh_seconds))
    if not running:
        return 60.0
    if not state.is_in_match:
        return 30.0
    return max(10.0, min(30.0, float(config.refresh_seconds)))
