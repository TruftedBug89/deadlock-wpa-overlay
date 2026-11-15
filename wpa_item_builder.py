"""Turn OCR cards and Statlocker WPA rows into ``WpaItem`` values.

Pure formatting rules: live OCR values win, database metadata only fills gaps,
and unknown values stay ``None``.  The mixin reads the catalog maps owned by
``StatlockerDataSource``.
"""

import re
from typing import Dict, List, Optional

from item_categories import normalize_category
from models import WpaItem


class WpaItemMixin:
    _WPA_PCT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")
    _USUALLY_RE = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")

    @classmethod
    def _wpa_from_text(cls, raw: str) -> Optional[float]:
        """Parse live WPA % from OCR text (e.g. 'WPA +1.4%')."""
        if not raw:
            return None
        match = cls._WPA_PCT_RE.search(raw.upper())
        if not match:
            return None
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            return None
        # Sanity: WPA recommendations are single-digit percentages.
        if abs(value) > 30.0:
            return None
        return value

    @classmethod
    def _time_from_text(cls, raw: str) -> Optional[str]:
        """Parse live 'usually' timing from OCR text (e.g. 'USUALLY 13:49')."""
        if not raw:
            return None
        match = cls._USUALLY_RE.search(raw)
        if not match:
            return None
        return match.group(1)

    def _make_wpa_item(
        self,
        catalog_match: Optional[dict],
        *,
        name: str = "",
        wpa_pct: Optional[float] = None,
        usually_time: Optional[str] = None,
        fallback_category: str = "",
        confidence: float = 0.0,
        slot_index: int = 0,
    ) -> WpaItem:
        """Build a WpaItem without inventing any missing value."""
        catalog_match = catalog_match or {}
        item_name = catalog_match.get("name") or name
        raw_category = (
            catalog_match.get("item_slot_type")
            or catalog_match.get("slot_type")
            or catalog_match.get("slotType")
            or catalog_match.get("category")
            or fallback_category
            or ""
        )
        category = normalize_category(raw_category)

        cost = catalog_match.get("cost")
        tier = catalog_match.get("item_tier") or catalog_match.get("tier")
        try:
            cost_value = int(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_value = None
        try:
            tier_value = int(tier) if tier is not None else None
        except (TypeError, ValueError):
            tier_value = None

        return WpaItem(
            name=item_name,
            category=category,
            cost=cost_value,
            wpa_pct=wpa_pct,
            usually_time=usually_time,
            image_url=(
                catalog_match.get("image")
                or catalog_match.get("shop_image")
                or catalog_match.get("icon")
            ),
            tier=tier_value,
            class_name=catalog_match.get("class_name") or catalog_match.get("className"),
            confidence=confidence,
            slot_index=slot_index,
        )

    def _timing_from_stats(self, stats: dict) -> Optional[str]:
        mean_minutes = stats.get("mean_purchase_time_min")
        if mean_minutes is None:
            return None
        try:
            minutes = float(mean_minutes)
        except (TypeError, ValueError):
            return None
        whole = int(minutes)
        seconds = int(round((minutes - whole) * 60))
        if seconds >= 60:
            whole += 1
            seconds -= 60
        return f"{whole:02d}:{seconds:02d}"

    def _item_from_card(self, card, stats_map: Dict[str, dict]) -> Optional[WpaItem]:
        if not card.name:
            return None
        catalog_match = self._catalog_items.get(card.name.lower(), {})
        stats = stats_map.get(card.name.lower(), {})
        raw = getattr(card, "raw_text", "") or ""
        # Live OCR values first; DB stats only fill gaps.
        wpa_pct = self._wpa_from_text(raw)
        if wpa_pct is None:
            wpa_value = stats.get("wpaValue")
            try:
                wpa_pct = float(wpa_value) if wpa_value is not None else None
                if wpa_pct is not None:
                    wpa_pct *= 100.0
            except (TypeError, ValueError):
                wpa_pct = None
        usually = self._time_from_text(raw) or self._timing_from_stats(stats)
        return self._make_wpa_item(
            catalog_match,
            name=card.name,
            wpa_pct=wpa_pct,
            usually_time=usually,
            confidence=card.score,
            slot_index=card.index,
        )

    def _preview_items(
        self, conn, hero_id: Optional[int], limit: int
    ) -> List[WpaItem]:
        stats_map = self._wpa_stats(conn, hero_id)
        candidates = []
        for name, stats in stats_map.items():
            catalog_match = self._catalog_items.get(name, {})
            if catalog_match and (
                catalog_match.get("disabled") or catalog_match.get("shopable") is False
            ):
                continue
            wpa = float(stats.get("wpaValue") or 0.0)
            relative = float(stats.get("costRelativeWpa") or wpa)
            candidates.append(((wpa, relative), stats, catalog_match))
        candidates.sort(key=lambda entry: entry[0], reverse=True)

        items: List[WpaItem] = []
        for _, stats, catalog_match in candidates[:limit]:
            name = stats.get("item", "")
            items.append(
                self._make_wpa_item(
                    catalog_match,
                    name=name,
                    wpa_pct=float(stats.get("wpaValue") or 0.0) * 100.0,
                    usually_time=self._timing_from_stats(stats),
                    confidence=1.0,
                    slot_index=len(items),
                )
            )
        return items
