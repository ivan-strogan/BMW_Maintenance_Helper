"""RockAuto aftermarket parts integration.

search_by_oem: direct curl-cffi scraper of /en/partsearch/ — works for any
  OEM part number and returns CAD prices regardless of vehicle.

search_by_category / search_by_hint: uses rockauto-api library which scrapes
  the vehicle+category catalog. Results are cached with diskcache.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import diskcache
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
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


def _parse_partsearch_results(html: str) -> list[RockAutoAlternative]:
    """Parse the HTML response from RockAuto's /en/partsearch/ form POST."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[RockAutoAlternative] = []

    for mfr_span in soup.find_all("span", class_="listing-final-manufacturer"):
        brand = mfr_span.get_text(strip=True)
        pn_span = mfr_span.find_next("span", class_="listing-final-partnumber")
        if not pn_span:
            continue
        pn = pn_span.get_text(strip=True)
        if not pn or pn == "Unknown":
            continue

        # Description is the next text span after the part number
        desc_span = pn_span.find_next("span", class_="span-link-underline-remover")
        notes = desc_span.get_text(strip=True) if desc_span else None

        # Price span and availability are in the same row
        row = mfr_span.find_parent("tr") or mfr_span.find_parent(
            "div", class_=re.compile(r"listing")
        )
        price: Optional[float] = None
        availability = "in_stock"
        url = ""
        if row:
            price_span = row.find("span", class_=re.compile(r"price|listing-price"))
            if price_span:
                oos = price_span.find("span", class_="oos-price-text")
                map_price = price_span.find("span", class_="map-price-text")
                if oos:
                    availability = "out_of_stock"
                elif map_price:
                    availability = "map_price"  # price hidden — add to cart to see
                else:
                    price = _parse_price(price_span.get_text(strip=True))
            link = row.find("a", href=re.compile(r"(rockauto|moreinfo|partslist)"))
            if link:
                href = link["href"]
                url = href if href.startswith("http") else f"https://www.rockauto.com{href}"

        results.append(RockAutoAlternative(
            brand=brand,
            part_number=pn,
            oem_interchange=[],
            price=price or 0.0,
            currency="CAD",
            availability=availability,
            url=url,
            notes=notes,
        ))

    return results


def savings_vs_oem(oem_price: Optional[float], ra_price: float) -> Optional[float]:
    """Return savings (positive = cheaper on RA, negative = more expensive).

    Returns None when either price is unavailable or RA price is zero
    (indicating OOS or MAP-priced item where no real comparison is possible).
    """
    if oem_price is None or ra_price <= 0:
        return None
    return round(oem_price - ra_price, 2)


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
            vehicle = await client.get_vehicle(v.make, v.year, v.model)
            result = await client.get_parts_by_category(v.make, v.year, v.model, vehicle.carcode, category)

        parts = [
            alt for part in result.parts
            if (alt := _part_to_alternative(part)) is not None
        ]
        self._cache.set(cache_key, parts, expire=CACHE_TTL)
        return parts

    def search_by_oem(self, oem_pn: str) -> list[RockAutoAlternative]:
        """Find aftermarket parts that cross-reference to a given OEM part number.

        Uses direct HTML scraping of RockAuto's part-number search form.
        Returns CAD prices (the currency RockAuto shows to Canadian visitors).
        """
        cache_key = f"ra:oem:{oem_pn}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update({
            "Accept-Language": "en-CA,en;q=0.9",
            "Referer": "https://www.rockauto.com/",
        })

        # Fetch the search page to get the _nck security token
        r1 = session.get("https://www.rockauto.com/en/partsearch/", timeout=20)
        nck_inp = BeautifulSoup(r1.text, "html.parser").find("input", {"name": "_nck"})
        if not nck_inp:
            return []

        r2 = session.post("https://www.rockauto.com/en/partsearch/", data={
            "_nck": nck_inp["value"],
            "dopartsearch": "1",
            "partsearch[partnum][partsearch_007]": oem_pn,
            "partsearch[manufacturer][partsearch_007]": "",
            "partsearch[partgroup][partsearch_007]": "",
            "partsearch[parttype][partsearch_007]": "",
            "partsearch[partname][partsearch_007]": "",
            "partsearch[do][partsearch_007]": "Search",
        }, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.rockauto.com/en/partsearch/",
        }, timeout=20)

        parts = _parse_partsearch_results(r2.text)
        self._cache.set(cache_key, parts, expire=CACHE_TTL)
        return parts
