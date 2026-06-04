"""RealOEM.com catalog scraper.

Uses curl-cffi to impersonate a real browser TLS fingerprint and bypass
Cloudflare. All responses are cached with a 7-day TTL via diskcache.

Actual URL structure (verified by inspection):
  VIN lookup  : /bmw/enUS/select?vin={vin}
                -> links with partgrp?id={catalog_id}&mg=XX
  Main groups : /bmw/enUS/partgrp?id={catalog_id}
                -> links with partgrp?id={catalog_id}&mg=XX
  Sub-groups  : /bmw/enUS/partgrp?id={catalog_id}&mg={mg}
                -> links with showparts?id={catalog_id}&diagId=XX_XXXX
  Diagram     : /bmw/enUS/showparts?id={catalog_id}&diagId={diag_id}
                -> table#partsList with ref, description, qty, part number, price
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import diskcache
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from ..models import CatalogPart

BASE = "https://www.realoem.com/bmw/enUS"
CACHE_DIR = Path(__file__).parent.parent / ".cache" / "realoem"
CACHE_TTL = 7 * 24 * 3600  # 7 days


# ── Session + cache ────────────────────────────────────────────────────────────

def _make_session() -> cffi_requests.Session:
    s = cffi_requests.Session(impersonate="chrome120")
    s.headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.realoem.com/",
    })
    return s


class RealOEMClient:
    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: diskcache.Cache = diskcache.Cache(str(cache_dir))
        self._session = _make_session()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get(self, url: str, *, bust: bool = False) -> str:
        if not bust and url in self._cache:
            return self._cache[url]
        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()
        html = resp.text
        self._cache.set(url, html, expire=CACHE_TTL)
        return html

    @staticmethod
    def _soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    # ── VIN → catalog ID ──────────────────────────────────────────────────────

    def resolve_catalog_id(self, vin: str) -> str:
        """Resolve a VIN to a RealOEM catalog ID (e.g. 'WL73-USA-04-2007-E93-BMW-335i').

        RealOEM only needs the last 7 characters of the VIN.
        Raises ValueError if no catalog is found.
        """
        short_vin = vin[-7:] if len(vin) > 7 else vin
        url = f"{BASE}/select?vin={short_vin}"
        html = self._get(url)
        soup = self._soup(html)

        # Primary: hidden input name="id" inside a partgrp form
        for inp in soup.find_all("input", {"name": "id"}):
            val = inp.get("value", "").strip()
            if val:
                return val

        # Fallback: partgrp links
        for a in soup.find_all("a", href=True):
            m = re.search(r"partgrp\?id=([^&\s]+)", a["href"])
            if m:
                return m.group(1)

        # Fallback: showparts links
        for a in soup.find_all("a", href=True):
            m = re.search(r"showparts\?id=([^&\s]+)", a["href"])
            if m:
                return m.group(1)

        raise ValueError(
            f"Could not resolve catalog ID for VIN {vin}. "
            "The VIN may not be in the RealOEM database."
        )

    # ── Group browsing ─────────────────────────────────────────────────────────

    def get_groups(self, catalog_id: str) -> list[dict]:
        """Return top-level groups for a catalog.

        Each dict: {mg, name}
        """
        url = f"{BASE}/partgrp?id={catalog_id}"
        html = self._get(url)
        soup = self._soup(html)

        results = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=re.compile(r"partgrp")):
            params = parse_qs(urlparse(a["href"]).query)
            if "mg" not in params:
                continue
            mg = params["mg"][0]
            if mg in seen:
                continue
            name = a.get_text(" ", strip=True)
            if not name or len(name) < 2:
                continue
            seen.add(mg)
            img_url = f"https://www.realoem.com/bmw/images/group_{mg}-00-P.jpg"
            results.append({"mg": mg, "name": name, "img_url": img_url})

        return results

    def get_subgroups(self, catalog_id: str, mg: str) -> list[dict]:
        """Return diagrams (sub-groups) for a main group.

        Each dict: {diag_id, name, thumb_url}
        """
        url = f"{BASE}/partgrp?id={catalog_id}&mg={mg}"
        html = self._get(url)
        soup = self._soup(html)

        results = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=re.compile(r"showparts")):
            params = parse_qs(urlparse(a["href"]).query)
            if "diagId" not in params:
                continue
            diag_id = params["diagId"][0]
            if diag_id in seen:
                continue
            name = a.get_text(" ", strip=True)
            if not name or len(name) < 2:
                continue
            seen.add(diag_id)

            # Thumbnail is the <img> inside the link's parent container
            thumb_url: str | None = None
            for ancestor in [a.parent, a.parent.parent if a.parent else None]:
                if ancestor:
                    img = ancestor.find("img", src=re.compile(r"/bmw/images/thumb_"))
                    if img:
                        src = img["src"]
                        thumb_url = f"https://www.realoem.com{src}" if not src.startswith("http") else src
                        break

            results.append({"diag_id": diag_id, "name": name, "thumb_url": thumb_url})

        return results

    # ── Parts fetching ─────────────────────────────────────────────────────────

    def get_parts(self, catalog_id: str, diag_id: str) -> tuple[list[CatalogPart], str | None]:
        """Fetch parts for a specific diagram (e.g. diag_id='11_3971').

        Returns (parts, diagram_image_url).
        diagram_image_url is an absolute URL or None if not found.
        """
        url = f"{BASE}/showparts?id={catalog_id}&diagId={diag_id}"
        html = self._get(url)
        parts = self._parse_parts(html, catalog_path=[diag_id])
        diagram_url = self._parse_diagram_url(html)
        if diagram_url:
            for p in parts:
                p.diagram_url = diagram_url
        return parts, diagram_url

    @staticmethod
    def _parse_diagram_url(html: str) -> str | None:
        """Extract the main diagram image URL from a showparts page."""
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img", src=True):
            src = img["src"]
            # Diagram images are at /bmw/images/diag_*.jpg
            if "/bmw/images/diag_" in src:
                if src.startswith("http"):
                    return src
                return f"https://www.realoem.com{src}"
        return None

    @staticmethod
    def _strip_affiliate(text: str) -> str:
        """Remove affiliate/shop link text injected into RealOEM cells."""
        return re.sub(r"\s*Shop at \S[^\n]*", "", text, flags=re.IGNORECASE).strip()

    @staticmethod
    def _parse_parts(html: str, catalog_path: list[str]) -> list[CatalogPart]:
        soup = BeautifulSoup(html, "html.parser")
        parts: list[CatalogPart] = []

        table = (
            soup.find("table", id="partsList")
            or soup.find("table", class_="partsList")
        )
        if not table:
            return parts

        current_fitment: Optional[str] = None

        for row in table.find_all("tr"):
            cells = row.find_all("td")

            # Fitment context row: italic/bold row with no part number, spans description
            # e.g. "For vehicles with M Sports suspension" or "For vehicles without sport suspension"
            if len(cells) >= 1:
                row_text = row.get_text(" ", strip=True)
                if re.search(r"For vehicles?\s+with|without|from|up to", row_text, re.I):
                    if not any(re.match(r"^\d{11}$", re.sub(r"\s+", "", c.get_text(strip=True))) for c in cells):
                        current_fitment = RealOEMClient._strip_affiliate(row_text)
                        continue

            if len(cells) < 3:
                continue

            # Columns: Ref | Description | Supp. | Qty | From | Up To | Part Number | Price | Notes
            ref_text  = cells[0].get_text(strip=True)
            raw_desc  = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
            desc_text = RealOEMClient._strip_affiliate(raw_desc)

            pn = ""
            price: Optional[float] = None
            qty = 1
            from_date: Optional[str] = None
            to_date: Optional[str] = None
            part_notes: Optional[str] = None

            for i, cell in enumerate(cells):
                text = cell.get_text(strip=True)
                # Part number: exactly 11 digits
                if re.match(r"^\d{11}$", re.sub(r"\s+", "", text)):
                    pn = re.sub(r"\s+", "", text)
                # Price: $XX.XX
                if not price:
                    pm = re.search(r"\$?([\d,]+\.\d{2})", text)
                    if pm and i > 3:
                        try:
                            price = float(pm.group(1).replace(",", ""))
                        except ValueError:
                            pass
                # Qty: small integer in column 3
                if i == 3 and re.match(r"^\d{1,3}$", text):
                    try:
                        qty = int(text)
                    except ValueError:
                        pass
                # From date (column 4): MM/YYYY pattern
                if i == 4 and re.match(r"^\d{2}/\d{4}$", text):
                    from_date = text
                # To date (column 5): MM/YYYY pattern
                if i == 5 and re.match(r"^\d{2}/\d{4}$", text):
                    to_date = text
                # Notes (last column): non-empty text that isn't a price or PN
                if i == len(cells) - 1 and text and not re.match(r"^\$?[\d,]+\.\d{2}$", text) and not re.match(r"^\d{11}$", text):
                    cleaned = RealOEMClient._strip_affiliate(text)
                    if cleaned and cleaned not in (ref_text, desc_text):
                        part_notes = cleaned

            if not pn:
                continue

            parts.append(CatalogPart(
                oem_pn=pn,
                description=desc_text,
                qty_required=qty,
                realoem_price=price,
                diagram_ref=ref_text or None,
                catalog_path=catalog_path,
                fitment_note=current_fitment,
                part_notes=part_notes,
                from_date=from_date,
                to_date=to_date,
            ))

        return parts

    # ── Hint-based navigation ──────────────────────────────────────────────────

    def find_by_hint(self, catalog_id: str, hint: str) -> list[dict]:
        """Navigate groups by a hint string like 'Engine > Oil Filter'.

        Returns matching sub-group dicts with {diag_id, name}.
        """
        segments = [p.strip().lower() for p in hint.split(">")]
        if not segments:
            return []

        groups = self.get_groups(catalog_id)
        matched = _best_match(segments[0], groups, key="name")
        if not matched:
            return []

        subgroups = self.get_subgroups(catalog_id, matched["mg"])

        if len(segments) == 1:
            return subgroups

        needle = " ".join(segments[1:])
        matched_sub = _best_match(needle, subgroups, key="name")
        return [matched_sub] if matched_sub else subgroups


def _best_match(needle: str, items: list[dict], *, key: str) -> Optional[dict]:
    """Return the item whose key best matches needle (case-insensitive).

    Scoring order:
      1. Exact match
      2. Full needle is a substring of item name
      3. Item name is a substring of full needle
      4. Proportional word overlap: needle words that partially match item words,
         divided by item word count — so "brake" matching all of "BRAKES" (1/1=1.0)
         beats "front" matching half of "FRONT AXLE" (1/2=0.5).
    """
    needle = needle.lower()
    needle_words = needle.split()

    for item in items:
        if item[key].lower() == needle:
            return item
    for item in items:
        if needle in item[key].lower():
            return item
    for item in items:
        if item[key].lower() in needle:
            return item

    best, best_score = None, 0.0
    for item in items:
        item_words = item[key].lower().split()
        if not item_words:
            continue
        matched = set()
        for nw in needle_words:
            for i, iw in enumerate(item_words):
                if nw == iw or nw in iw or iw in nw:
                    matched.add(i)
        score = len(matched) / len(item_words)
        if score > best_score:
            best, best_score = item, score
    return best if best_score > 0 else None


# ── Module-level convenience ───────────────────────────────────────────────────

_client: Optional[RealOEMClient] = None


def get_client() -> RealOEMClient:
    global _client
    if _client is None:
        _client = RealOEMClient()
    return _client
