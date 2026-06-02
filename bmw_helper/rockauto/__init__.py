"""RockAuto aftermarket parts integration.

Wraps the rockauto-api library (github.com/rsp2k/rockauto-api) which handles
the internal catalogapi.php HTTP protocol. Results are cached with diskcache.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import diskcache
from rockauto_api import RockAutoClient as _RAClient

from ..models import RockAutoAlternative, VehicleConfig

CACHE_DIR = Path(__file__).parent.parent.parent / ".cache" / "rockauto"
CACHE_TTL = 24 * 3600  # 1 day — prices change, but not minute-to-minute

# Map the first segment of our catalog_hint to a RockAuto category group name.
HINT_TO_CATEGORY: dict[str, str] = {
    "engine": "Engine",
    "brakes": "Brake & Wheel Hub",
    "brake": "Brake & Wheel Hub",
    "clutch": "Transmission-Manual & Clutch",
    "transmission": "Transmission-Manual & Clutch",
    "gearbox": "Transmission-Manual & Clutch",
    "differential": "Axle & Drivetrain",
    "steering": "Steering",
    "suspension": "Suspension",
    "heating": "Heat & Air Conditioning",
    "heating / air conditioning": "Heat & Air Conditioning",
    "electrical": "Electrical",
    "battery": "Electrical",
    "fuel": "Fuel & Emission",
    "exhaust": "Exhaust & Emission",
    "ignition": "Ignition",
}


def hint_to_category(hint: str) -> Optional[str]:
    """Map a schedule catalog_hint to a RockAuto category group name.

    Uses the first path segment (before '>'), matched case-insensitively.
    Returns None when no mapping exists.
    """
    first = hint.split(">")[0].strip().lower()
    if not first:
        return None
    if first in HINT_TO_CATEGORY:
        return HINT_TO_CATEGORY[first]
    for key, val in HINT_TO_CATEGORY.items():
        if first.startswith(key) or key.startswith(first):
            return val
    return None


def _parse_price(price_str: Optional[str]) -> Optional[float]:
    """Convert a price string like '$49.99' to a float, or return None."""
    if not price_str:
        return None
    m = re.search(r"[\d,]+\.\d{2}", price_str)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _part_to_alternative(part) -> Optional[RockAutoAlternative]:
    """Convert a rockauto-api PartInfo object to a RockAutoAlternative."""
    brand = getattr(part, "brand", None) or ""
    pn = getattr(part, "part_number", None) or ""
    name = getattr(part, "name", None) or ""
    url = getattr(part, "url", None) or ""

    if not pn or pn == "Unknown":
        return None

    raw_price = getattr(part, "get_current_price", lambda: None)()
    price = _parse_price(raw_price)

    # Extract any 11-digit OEM part numbers from compatibility notes
    oem_nums: list[str] = []
    compat = getattr(part, "compatibility_notes", None) or ""
    for m in re.finditer(r"\b\d{11}\b", compat):
        oem_nums.append(m.group())

    return RockAutoAlternative(
        brand=brand,
        part_number=pn,
        oem_interchange=oem_nums,
        price=price or 0.0,
        currency="USD",
        availability=getattr(part, "availability", "") or "",
        url=url,
        notes=name if name != pn else None,
    )


class RockAutoClient:
    """Async client for RockAuto parts lookups."""

    def __init__(self, vehicle: VehicleConfig, cache_dir: Path = CACHE_DIR) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._vehicle = vehicle
        self._cache: diskcache.Cache = diskcache.Cache(str(cache_dir))

    async def search_by_hint(self, hint: str) -> list[RockAutoAlternative]:
        """Find aftermarket parts using a schedule catalog_hint string."""
        category = hint_to_category(hint)
        if not category:
            return []
        return await self.search_by_category(category)

    async def search_by_category(self, category: str) -> list[RockAutoAlternative]:
        """Find aftermarket parts in a RockAuto category for the configured vehicle."""
        v = self._vehicle
        cache_key = f"ra:cat:{v.make}:{v.year}:{v.model}:{category}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        async with _RAClient() as client:
            vehicle = await client.get_vehicle(v.make, v.year, v.model.upper())
            result = await vehicle.get_parts_by_category(category)

        parts = [
            alt for part in result.parts
            if (alt := _part_to_alternative(part)) is not None
        ]
        self._cache.set(cache_key, parts, expire=CACHE_TTL)
        return parts

    async def search_by_oem(self, oem_pn: str) -> list[RockAutoAlternative]:
        """Find aftermarket parts that cross-reference to a given OEM part number."""
        cache_key = f"ra:oem:{oem_pn}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        async with _RAClient() as client:
            result = await client.search_parts_by_number(oem_pn)

        parts = [
            alt for part in result.parts
            if (alt := _part_to_alternative(part)) is not None
        ]
        self._cache.set(cache_key, parts, expire=CACHE_TTL)
        return parts
