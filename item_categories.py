"""Map catalog slot names onto the three HUD categories."""

CATEGORY_MAP = {
    "vitality": "vitality",
    "utility": "vitality",
    "health": "vitality",
    "armor": "vitality",
    "defense": "vitality",
    "spirit": "spirit",
    "tech": "spirit",
    "magic": "spirit",
    "ability": "spirit",
    "weapon": "weapon",
    "damage": "weapon",
    "gun": "weapon",
}


def normalize_category(raw: str, default: str = "weapon") -> str:
    return CATEGORY_MAP.get(str(raw or "").lower(), default)
