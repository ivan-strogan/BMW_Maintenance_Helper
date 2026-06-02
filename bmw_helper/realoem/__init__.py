"""RealOEM.com catalog scraper.

Uses curl-cffi to impersonate a real browser TLS fingerprint and bypass
Cloudflare. All responses are cached with a 7-day TTL via diskcache.

URL structure:
  VIN lookup : /bmw/enUS/select?vin={vin}
  Main groups: /bmw/enUS/showparts?id={catalog_id}
  Sub-groups : /bmw/enUS/showparts?id={catalog_id}&hg={hg}
  Diagram    : /bmw/enUS/showparts?id={catalog_id}&mospid={mospid}&hg={hg}&fg={fg}
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

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
    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        impersonate: str = "chrome120",
    ) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: diskcache.Cache = diskcache.Cache(str(cache_dir))
        self._session = _make_session()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get(self, url: str, *, bust: bool = False) -> str:
        """GET url, returning HTML. Caches response; bust=True forces refetch."""
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

    @staticmethod
    def _abs(href: str) -> str:
        if href.startswith("http"):
            return href
        return urljoin(BASE, href)

    # ── VIN → catalog ID ──────────────────────────────────────────────────────

    def resolve_catalog_id(self, vin: str) -> str:
        """Resolve a VIN to a RealOEM catalog ID string (e.g. 'WB_36_06_0615').

        Raises ValueError if no catalog is found for the VIN.
        """
        url = f"{BASE}/select?vin={vin}"
        html = self._get(url)
        soup = self._soup(html)

        # RealOEM embeds catalog IDs in showparts links — grab the first one
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"showparts\?id=([^&\s]+)", href)
            if m:
                return m.group(1)

        # Some VIN lookups return a selection table — try parsing that too
        for inp in soup.find_all("input", {"name": "id"}):
            val = inp.get("value", "").strip()
            if val:
                return val

        raise ValueError(
            f"Could not resolve catalog ID for VIN {vin}. "
            "The page structure may have changed or the VIN is not in the RealOEM database."
        )

    # ── Group browsing ─────────────────────────────────────────────────────────

    def get_groups(self, catalog_id: str) -> list[dict]:
        """Return top-level groups for a catalog.

        Each dict: {hg, name, url}
        """
        url = f"{BASE}/showparts?id={catalog_id}"
        html = self._get(url)
        return self._parse_groups(html, catalog_id, level="top")

    def get_subgroups(self, catalog_id: str, hg: str) -> list[dict]:
        """Return sub-groups (diagrams) for a main group hg code.

        Each dict: {mospid, hg, fg, name, url}
        """
        url = f"{BASE}/showparts?id={catalog_id}&hg={hg}"
        html = self._get(url)
        return self._parse_groups(html, catalog_id, level="sub")

    @staticmethod
    def _parse_groups(html: str, catalog_id: str, level: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()

        for a in soup.find_all("a", href=re.compile(r"showparts")):
            href = a.get("href", "")
            params = parse_qs(urlparse(href).query)
            name = a.get_text(" ", strip=True)

            if not name or len(name) < 2:
                continue

            if level == "top":
                # Top-level: has hg= but not mospid= or fg=
                if "hg" in params and "mospid" not in params and "fg" not in params:
                    hg = params["hg"][0]
                    if hg in seen:
                        continue
                    seen.add(hg)
                    results.append({"hg": hg, "name": name, "url": href})
            else:
                # Sub-level: has fg= or mospid=
                if "mospid" in params or "fg" in params:
                    key = href
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append({
                        "mospid": params.get("mospid", [""])[0],
                        "hg": params.get("hg", [""])[0],
                        "fg": params.get("fg", [""])[0],
                        "name": name,
                        "url": href,
                    })

        return results

    # ── Parts fetching ─────────────────────────────────────────────────────────

    def get_parts(
        self,
        catalog_id: str,
        mospid: str,
        hg: str,
        fg: str,
    ) -> list[CatalogPart]:
        """Fetch the parts list for a specific diagram."""
        params = urlencode({"id": catalog_id, "mospid": mospid, "hg": hg, "fg": fg})
        url = f"{BASE}/showparts?{params}"
        html = self._get(url)
        return self._parse_parts(html, catalog_path=[hg, fg])

    @staticmethod
    def _parse_parts(html: str, catalog_path: list[str]) -> list[CatalogPart]:
        """Parse the parts table from a RealOEM diagram page."""
        soup = BeautifulSoup(html, "html.parser")
        parts: list[CatalogPart] = []

        # RealOEM parts table has class "partsList" or sits inside div#partsList
        table = (
            soup.find("table", class_="partsList")
            or soup.find("div", id="partsList")
            or soup.find("table", id="partsList")
        )
        if not table:
            return parts

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            # Typical columns: Ref | Part Number | Description | Qty | Price
            ref_text = cells[0].get_text(strip=True)
            pn_cell = cells[1]
            desc_text = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""
            qty_text = cells[3].get_text(strip=True) if len(cells) > 3 else "1"
            price_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            # Part number — may be a link
            pn_link = pn_cell.find("a")
            pn = (pn_link.get_text(strip=True) if pn_link else pn_cell.get_text(strip=True))
            pn = re.sub(r"\s+", "", pn)  # strip whitespace within PN

            if not pn or not re.match(r"^\d{11}$", pn):
                continue  # skip header rows, non-PN rows

            # Supersession notice sometimes appears as strikethrough with a new PN
            superseded_by: Optional[str] = None
            strike = pn_cell.find("s")
            if strike:
                superseded_by = pn
                new_pn = pn_cell.get_text(strip=True).replace(pn, "").strip()
                new_pn = re.sub(r"\s+", "", new_pn)
                if re.match(r"^\d{11}$", new_pn):
                    pn = new_pn

            try:
                qty = int(re.sub(r"\D", "", qty_text) or "1")
            except ValueError:
                qty = 1

            price: Optional[float] = None
            price_m = re.search(r"[\d,]+\.\d{2}", price_text)
            if price_m:
                try:
                    price = float(price_m.group().replace(",", ""))
                except ValueError:
                    pass

            parts.append(CatalogPart(
                oem_pn=pn,
                description=desc_text,
                qty_required=qty,
                realoem_price=price,
                superseded_by=superseded_by,
                diagram_ref=ref_text or None,
                catalog_path=catalog_path,
            ))

        return parts

    # ── Hint-based navigation ──────────────────────────────────────────────────

    def find_by_hint(
        self,
        catalog_id: str,
        hint: str,
    ) -> list[dict]:
        """Navigate catalog groups by a hint string like 'Engine > Oil Filter'.

        Returns matching sub-group dicts. Call get_parts() on the result to
        fetch the actual parts list.
        """
        parts = [p.strip().lower() for p in hint.split(">")]
        if not parts:
            return []

        # Match top-level group
        groups = self.get_groups(catalog_id)
        matched_group = _best_match(parts[0], groups, key="name")
        if not matched_group:
            return []

        subgroups = self.get_subgroups(catalog_id, matched_group["hg"])

        if len(parts) == 1:
            return subgroups

        # Match sub-group
        needle = " ".join(parts[1:])
        matched_sub = _best_match(needle, subgroups, key="name")
        return [matched_sub] if matched_sub else subgroups


def _best_match(needle: str, items: list[dict], *, key: str) -> Optional[dict]:
    """Return the item whose key best matches needle (case-insensitive substring)."""
    needle = needle.lower()
    # Exact match first
    for item in items:
        if item[key].lower() == needle:
            return item
    # Substring match
    for item in items:
        if needle in item[key].lower():
            return item
    # Word-overlap match
    needle_words = set(needle.split())
    best, best_score = None, 0
    for item in items:
        words = set(item[key].lower().split())
        score = len(needle_words & words)
        if score > best_score:
            best, best_score = item, score
    return best if best_score > 0 else None


# ── Module-level convenience ───────────────────────────────────────────────────

def get_client() -> RealOEMClient:
    """Return a module-level RealOEMClient (lazy singleton)."""
    global _client
    if _client is None:
        _client = RealOEMClient()
    return _client


_client: Optional[RealOEMClient] = None
