"""Data contracts for the Deadlock WPA overlay.

Everything in this module is plain data: no I/O, no Win32, no UI, so the
contracts can be imported by tests, the diagnostics CLI and the UI alike.

Design rule: unknown values are ``None``.  The overlay never invents an item
name, a WPA percentage or a "usually bought" timestamp.  If Statlocker does not
render a value, the field stays empty.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


def category_color_for(category: str) -> str:
    """Hex colour matching Deadlock's Vitality / Spirit / Weapon slots."""
    cat = (category or "").lower()
    if cat in ("vitality", "utility", "health", "armor", "defense"):
        return "#74a832"  # Vitality green
    if cat in ("spirit", "tech", "magic", "ability"):
        return "#9f62de"  # Spirit purple
    if cat in ("weapon", "damage", "gun"):
        return "#de8b00"  # Weapon amber
    return "#64748b"  # Slate fallback


@dataclass
class WpaItem:
    """A recommended Deadlock item as rendered by Statlocker Companion."""

    name: str
    category: str = "weapon"  # "vitality" | "weapon" | "spirit"
    cost: Optional[int] = None
    wpa_pct: Optional[float] = None  # +4.0 for +4.0 %; None when unknown
    usually_time: Optional[str] = None  # "33:25"; None when unknown
    image_url: Optional[str] = None
    icon_filename: Optional[str] = None
    can_buy: bool = True
    tier: Optional[int] = None
    class_name: Optional[str] = None
    confidence: float = 0.0  # OCR match confidence, 0.0 .. 1.0
    slot_index: int = 0  # left-to-right position in the live Statlocker row
    item_id: Optional[int] = None  # deadlock-api item id when known
    # Advisor evidence, always reported, never fabricated:
    win_rate: Optional[float] = None  # measured win rate, 0.0 .. 1.0
    samples: int = 0  # matches behind that win rate
    reason: str = ""  # short tags, e.g. "AHEAD / COUNTER HAZE"

    @property
    def display_name(self) -> str:
        """Upper-case, compact display name (max 18 chars)."""
        clean = self.name.upper()
        if len(clean) > 18:
            return clean[:16] + ".."
        return clean

    @property
    def wpa_text(self) -> str:
        """Formatted WPA string, e.g. ``+4.0%`` or ``--`` when unknown."""
        if self.wpa_pct is None:
            return "--"
        sign = "+" if self.wpa_pct >= 0 else ""
        return f"{sign}{self.wpa_pct:.1f}%"

    @property
    def usually_text(self) -> str:
        """Formatted timing string, e.g. ``33:25`` or ``--`` when unknown."""
        return self.usually_time or "--"

    @property
    def winrate_text(self) -> str:
        """Measured win rate, e.g. ``52.4%``; empty when there is no sample."""
        if self.win_rate is None or self.samples <= 0:
            return ""
        return f"{self.win_rate * 100:.1f}%"

    @property
    def category_color(self) -> str:
        """Hex colour matching Deadlock's Vitality / Spirit / Weapon slots."""
        return category_color_for(self.category)


@dataclass
class CounterItem:
    """A counter item for one of the enemy heroes in the current match.

    ``score`` is the counter signal from the source (win-probability added for
    the local Statlocker rows, win rate for the optional remote fallback) and
    ``samples`` is the number of matches behind it.  Both are always reported,
    never invented.
    """

    name: str
    category: str = "weapon"
    score: float = 0.0
    samples: int = 0
    enemy_id: Optional[int] = None
    enemy_name: str = ""
    image_url: Optional[str] = None
    class_name: Optional[str] = None
    # Advisor evidence: the item's own win rate and how much it gains when
    # filtered to this enemy lineup. Both measured, both optional.
    win_rate: Optional[float] = None
    gain: Optional[float] = None
    item_id: Optional[int] = None
    evidence: dict = field(default_factory=dict)

    @property
    def gain_text(self) -> str:
        """Matchup gain over the same item's general rate, e.g. ``+1.8 pts``."""
        if self.gain is None:
            return ""
        return f"{self.gain * 100:+.1f} pts"

    @property
    def category_color(self) -> str:
        return category_color_for(self.category)

    @property
    def samples_text(self) -> str:
        """Compact sample size: 980, 3.2k, 12k."""
        try:
            value = int(self.samples)
        except (TypeError, ValueError):
            return "--"
        if value >= 10_000:
            return f"{value // 1000}k"
        if value >= 1_000:
            return f"{value / 1000:.1f}k"
        return str(value)

    @property
    def display_name(self) -> str:
        """Upper-case label cut on a word boundary so it stays readable."""
        clean = (self.name or "?").upper()
        if len(clean) <= 10:
            return clean
        label = ""
        for word in clean.split():
            candidate = f"{label} {word}".strip()
            if len(candidate) > 10:
                break
            label = candidate
        return label or clean[:10]


@dataclass(frozen=True)
class ItemReplacement:
    """One affordable, evidence-backed change to a confirmed full inventory."""

    sell_id: int
    sell_name: str
    buy: WpaItem
    held_win_rate: float
    buy_win_rate: float
    supported_gap: float
    basis: str
    sell_matches: int
    buy_matches: int
    slots_used: int
    slot_limit: int
    held_upper: float
    buy_lower: float
    pool_baseline: float
    minimum_supported_gap: float


@dataclass
class GameState:
    """Snapshot of the match and the live Statlocker recommendation row."""

    is_in_match: bool = False
    match_id: Optional[str] = None
    hero_id: Optional[int] = None
    hero_name: str = "Unknown"
    clock_s: float = 0.0
    net_worth: int = 0  # live broadcast souls for our hero (0 = unknown)
    stage: str = ""  # "early" | "mid" | "late" when souls are known
    next_buy: Optional[WpaItem] = None  # single best next purchase
    # Top three purchases for this stage, already filtered for ownership and
    # budget. The first one is the single next-buy call.
    build_candidates: List[WpaItem] = field(default_factory=list)
    # A current-evidence expansion of the queue, never a guessed future build.
    build_plan: List[WpaItem] = field(default_factory=list)
    replacement: Optional[ItemReplacement] = None
    inventory_capacity: Optional[int] = None
    threat_summary: str = ""
    build_note: str = ""
    owned_items: Set[str] = field(default_factory=set)
    recommended_items: List[WpaItem] = field(default_factory=list)
    # Ranked counter items for the enemy team, plus who they counter.
    counter_items: List[CounterItem] = field(default_factory=list)
    enemy_heroes: List[str] = field(default_factory=list)
    # "remote" (deadlock-api.com) | "none"
    counter_source: str = "none"
    # The enemy this hero performs worst against (deadlock-api matchups).
    strongest_enemy: str = ""
    strongest_enemy_winrate: Optional[float] = None
    # Live match context (broadcast): team soul lead and the enemy with the
    # highest soul count / hero damage. All zero when the roster is unknown.
    stance: str = "unknown"  # "ahead" | "even" | "behind" | "unknown"
    soul_lead: int = 0
    team_souls: int = 0
    enemy_souls: int = 0
    buy_budget: Optional[int] = None  # unspent souls when the broadcast reports them
    known_owned_items: int = 0  # owned ids that resolved to a shop item
    # Provenance / diagnostics -------------------------------------------
    source: str = "none"  # "live_screen" | "build_preview" | "none"
    scan_status: str = "idle"  # "ok" | "empty" | "not_visible" | "error" | "idle"
    detected_slots: int = 0
    matched_slots: int = 0
    last_error: Optional[str] = None
    generated_at: float = 0.0
    valid_until: Optional[float] = None

    @property
    def is_complete(self) -> bool:
        """True when every detected card was resolved to a catalog item."""
        return self.detected_slots > 0 and self.matched_slots == self.detected_slots


@dataclass
class OverlayConfig:
    """User preferences and persisted window state."""

    x: int = 0  # 0 means "dock flush to the right edge"
    y: int = 120  # 120 is the "dock to the corner" sentinel
    corner: str = "top_right"
    # True once the user dragged the HUD somewhere exact: x/y are then used
    # verbatim (including x == 0, the left edge).  False keeps the corner dock.
    positioned: bool = False
    opacity: float = 0.80
    clickthrough: bool = True
    hover_controls: bool = True  # briefly hover to reveal drag/settings controls
    only_in_game: bool = False
    only_when_focused: bool = False
    layout: str = "horizontal"  # "horizontal" ribbon | "vertical" stack
    view_mode: str = "minimal"  # "minimal" queue | "full" current build plan
    refresh_seconds: float = 20.0  # background polling cadence
    queue_seconds: float = 150.0  # review one new suggestion every 2.5 minutes
    auto_refresh_seconds: float = 20.0  # legacy alias kept for old configs
    max_items: int = 5  # slots reserved in the HUD (no layout jumps)
    font_size: int = 8
    icon_size: int = 32
    hud_alpha: float = 0.80
    # User size multiplier on top of the Windows DPI scale: 0.75 .. 2.0.
    # Applied to the HUD cards, icons, gaps and every font in one place.
    hud_scale: float = 1.0
    tray_promote: bool = False
    tray_notify: bool = False
    allow_db_fallback: bool = False
    show_timer: bool = False
    standby_badge: bool = False
    # Which data source to use: "advisor" (deadlock-api only, no database),
    # "statlocker" (mirror the live WPA row) or "auto" (Statlocker if found).
    source: str = "advisor"
    hero_id: Optional[int] = None  # advisor: the hero to recommend for
    read_match_id: bool = False  # optional corner OCR, identity only
    account_id: Optional[int] = None
    match_id: Optional[int] = None  # explicit fallback when watch-list discovery misses
    enemy_hero_ids: List[int] = field(default_factory=list)  # advisor: enemy team
    icons_only: bool = False  # super-small strip: item icons, no text
    show_counters: bool = True  # COUNTER ITEMS panel under the WPA strip
    max_counters: int = 3  # counter chips rendered in that panel
    # Optional manual override for the WPA row, in Statlocker window pixels:
    # {"x": 1044, "y": 449, "w": 760, "h": 265}
    wpa_region: Optional[dict] = None


@dataclass(frozen=True)
class Candidate:
    """One shop item with its measured evidence."""

    item_id: int
    name: str
    category: str = "weapon"
    cost: Optional[int] = None
    tier: Optional[int] = None
    image_url: Optional[str] = None
    class_name: Optional[str] = None
    win_rate: Optional[float] = None
    matches: int = 0
    pick_rate: float = 0.0
    counter_gain: float = 0.0
    counter_enemy: str = ""
    replaces_ids: Tuple[int, ...] = ()
    evidence: dict = field(default_factory=dict)

    @property
    def win_pct(self) -> Optional[float]:
        return round(self.win_rate * 100.0, 1) if self.win_rate is not None else None


@dataclass(frozen=True)
class Scored:
    """A candidate plus the score breakdown that produced it."""

    candidate: Candidate
    score: float
    confidence: str
    tags: Tuple[str, ...] = ()
    affordable_now: Optional[bool] = None
    breakdown: Dict[str, float] = field(default_factory=dict)

    @property
    def item_id(self) -> int:
        return self.candidate.item_id

    @property
    def name(self) -> str:
        return self.candidate.name

    @property
    def category(self) -> str:
        return self.candidate.category

    @property
    def cost(self) -> Optional[int]:
        return self.candidate.cost

    @property
    def tier(self) -> Optional[int]:
        return self.candidate.tier

    @property
    def image_url(self) -> Optional[str]:
        return self.candidate.image_url

    @property
    def class_name(self) -> Optional[str]:
        return self.candidate.class_name

    @property
    def win_rate(self) -> Optional[float]:
        return self.candidate.win_rate

    @property
    def matches(self) -> int:
        return self.candidate.matches

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "category": self.category,
            "cost": self.cost,
            "tier": self.tier,
            "score": round(self.score, 3),
            "confidence": self.confidence,
            "win_rate_pct": self.candidate.win_pct,
            "matches": self.matches,
            "purchase_share": round(self.candidate.pick_rate, 3),
            "counter_gain_pts": round(self.candidate.counter_gain * 100.0, 2),
            "tags": list(self.tags),
            "evidence": self.candidate.evidence,
            "affordable_now": self.affordable_now,
            "breakdown": {key: round(value, 3) for key, value in self.breakdown.items()},
        }


@dataclass
class BuildAdvice:
    """Fresh scored evidence and its two views for one validated live snapshot."""

    ranked: List[Scored] = field(default_factory=list)
    plan: List[Scored] = field(default_factory=list)
    items: List[WpaItem] = field(default_factory=list)
    choices: List[WpaItem] = field(default_factory=list)
    next_buy: Optional[WpaItem] = None
    replacement: Optional[ItemReplacement] = None
    counters: List[CounterItem] = field(default_factory=list)


@dataclass
class RecommendationQueueState:
    """Only identity and order are retained; displayed evidence is always fresh."""

    owner: Optional[tuple] = None
    item_ids: List[int] = field(default_factory=list)
    reviewed_at: float = 0.0



@dataclass(frozen=True)
class MatchContext:
    """Everything the picker knows about the current game state."""

    known: bool = False
    souls: int = 0
    bank: Optional[int] = None
    level: int = 0
    stage: str = ""
    team: int = 0
    team_souls: int = 0
    enemy_souls: int = 0
    soul_lead: int = 0
    stance: str = "unknown"  # "ahead" | "even" | "behind" | "unknown"
    my_damage: int = 0
    team_damage: int = 0
    damage_share: Optional[float] = None
    enemy_ids: Tuple[int, ...] = ()
    enemy_top_souls: int = 0
    enemy_top_hero_id: Optional[int] = None
    enemy_damage: int = 0
    enemy_damage_hero_id: Optional[int] = None
    owned_item_ids: Tuple[int, ...] = ()
    ownership_known: bool = False
    inventory_capacity: Optional[int] = None
    target_cost: int = 0

    @property
    def buy_budget(self) -> Optional[int]:
        """Only unspent gold is spendable; earned net worth is not a bank."""
        return max(0, int(self.bank)) if self.bank is not None else None

    def to_dict(self) -> dict:
        """JSON-friendly view for ``main.py --explain`` and diagnostics."""
        return {
            "known": self.known,
            "souls": self.souls,
            "bank": self.bank,
            "level": self.level,
            "stage": self.stage,
            "stance": self.stance,
            "soul_lead": self.soul_lead,
            "team_souls": self.team_souls,
            "enemy_souls": self.enemy_souls,
            "damage_share": round(self.damage_share, 3) if self.damage_share is not None else None,
            "enemy_ids": list(self.enemy_ids),
            "enemy_top_souls": self.enemy_top_souls,
            "enemy_top_hero_id": self.enemy_top_hero_id,
            "enemy_damage": self.enemy_damage,
            "enemy_damage_hero_id": self.enemy_damage_hero_id,
            "owned_item_ids": list(self.owned_item_ids),
            "ownership_known": self.ownership_known,
            "inventory_capacity": self.inventory_capacity,
            "buy_budget": self.buy_budget,
            "target_cost": self.target_cost,
        }
