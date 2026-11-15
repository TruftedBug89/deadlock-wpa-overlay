"""What the COUNTER ITEMS panel shows and how big it is (no Tk imports)."""

from typing import List, Optional, Tuple

from models import CounterItem, GameState
from ui.hud_geometry import CounterMetrics, HudMetrics, compute_counter_metrics


def visible_counters(state: GameState, config) -> List[CounterItem]:
    """Counter items the panel should render; empty means "no panel"."""
    if not bool(getattr(config, "show_counters", True)):
        return []
    limit = max(1, int(getattr(config, "max_counters", 3) or 3))
    return list(state.counter_items)[:limit]


def subtitle(state: GameState) -> str:
    """``VS HAZE 47% / NEXT: BURST 3200``: threat plus the next purchase."""
    if state.source == "advisor":
        targets = {item.enemy_name for item in state.counter_items if item.enemy_name}
        label = next(iter(targets)) if len(targets) == 1 else "LINEUP"
        return f"VS {label.upper()[:10]} / GAIN"
    label = ""
    if state.strongest_enemy:
        rate = state.strongest_enemy_winrate
        label = f"VS {state.strongest_enemy.upper()}"
        label += f" {rate * 100:.0f}%" if rate else ""
    else:
        names = [name for name in state.enemy_heroes if name]
        if names:
            label = "VS " + ", ".join(names[:2]).upper()
            if len(names) > 2:
                label += f" +{len(names) - 2}"
    if state.next_buy is not None:
        cost = f" {state.next_buy.cost}" if state.next_buy.cost else ""
        extra = f"NEXT: {state.next_buy.display_name}{cost}"
        label = f"{label} / {extra}" if label else extra
    return label


def panel_for(
    state: GameState,
    config,
    scale: float,
    base: HudMetrics,
) -> Tuple[Optional[CounterMetrics], List[CounterItem]]:
    """Panel metrics + counters for this state, or ``(None, [])`` to hide it."""
    counters = visible_counters(state, config)
    if not counters:
        return None, []
    return compute_counter_metrics(scale, len(counters), min_width=base.width), counters
