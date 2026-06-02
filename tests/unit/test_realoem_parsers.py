"""Unit tests for RealOEM HTML parsing functions.

All tests use fixture HTML files — no network access required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "realoem"
CATALOG_ID = "WB_81_06_1234"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _html(name: str) -> str:
    return (FIXTURES / name).read_text()


# ── resolve_catalog_id (HTML parsing only) ────────────────────────────────────

class TestResolveCatalogId:
    def test_extracts_first_catalog_id(self):
        from bmw_helper.realoem import RealOEMClient
        html = _html("vin_select.html")
        soup = RealOEMClient._soup(html)
        import re
        for a in soup.find_all("a", href=True):
            m = re.search(r"showparts\?id=([^&\s]+)", a["href"])
            if m:
                result = m.group(1)
                break
        assert result == CATALOG_ID

    def test_returns_first_match_when_multiple_options(self):
        from bmw_helper.realoem import RealOEMClient
        import re
        html = _html("vin_select.html")
        soup = RealOEMClient._soup(html)
        ids = []
        for a in soup.find_all("a", href=True):
            m = re.search(r"showparts\?id=([^&\s]+)", a["href"])
            if m:
                ids.append(m.group(1))
        assert len(ids) == 2
        assert ids[0] == CATALOG_ID


# ── _parse_groups ─────────────────────────────────────────────────────────────

class TestParseGroups:
    def test_top_level_returns_all_groups(self):
        from bmw_helper.realoem import RealOEMClient
        html = _html("groups.html")
        groups = RealOEMClient._parse_groups(html, CATALOG_ID, level="top")
        assert len(groups) == 11

    def test_top_level_group_has_required_keys(self):
        from bmw_helper.realoem import RealOEMClient
        groups = RealOEMClient._parse_groups(_html("groups.html"), CATALOG_ID, level="top")
        for g in groups:
            assert "hg" in g
            assert "name" in g
            assert "url" in g

    def test_engine_group_has_correct_hg(self):
        from bmw_helper.realoem import RealOEMClient
        groups = RealOEMClient._parse_groups(_html("groups.html"), CATALOG_ID, level="top")
        engine = next((g for g in groups if "Engine" in g["name"] and "Electrical" not in g["name"]), None)
        assert engine is not None
        assert engine["hg"] == "11"

    def test_brakes_group_present(self):
        from bmw_helper.realoem import RealOEMClient
        groups = RealOEMClient._parse_groups(_html("groups.html"), CATALOG_ID, level="top")
        names = [g["name"] for g in groups]
        assert any("Brakes" in n for n in names)

    def test_no_duplicates(self):
        from bmw_helper.realoem import RealOEMClient
        groups = RealOEMClient._parse_groups(_html("groups.html"), CATALOG_ID, level="top")
        hgs = [g["hg"] for g in groups]
        assert len(hgs) == len(set(hgs))

    def test_subgroups_have_mospid_and_fg(self):
        from bmw_helper.realoem import RealOEMClient
        subs = RealOEMClient._parse_groups(_html("subgroups.html"), CATALOG_ID, level="sub")
        assert len(subs) > 0
        for s in subs:
            assert "mospid" in s
            assert "fg" in s
            assert "name" in s

    def test_subgroups_oil_filter_present(self):
        from bmw_helper.realoem import RealOEMClient
        subs = RealOEMClient._parse_groups(_html("subgroups.html"), CATALOG_ID, level="sub")
        names = [s["name"] for s in subs]
        assert any("Oil Filter" in n for n in names)


# ── _parse_parts ──────────────────────────────────────────────────────────────

class TestParseParts:
    def _parts(self):
        from bmw_helper.realoem import RealOEMClient
        return RealOEMClient._parse_parts(_html("parts.html"), catalog_path=["11", "11_0430"])

    def test_returns_four_parts(self):
        assert len(self._parts()) == 4

    def test_part_has_required_fields(self):
        for p in self._parts():
            assert p.oem_pn
            assert p.description
            assert p.qty_required >= 1

    def test_part_numbers_are_11_digits(self):
        for p in self._parts():
            assert len(p.oem_pn) == 11, f"bad PN: {p.oem_pn}"
            assert p.oem_pn.isdigit()

    def test_prices_parsed(self):
        parts = self._parts()
        prices = [p.realoem_price for p in parts if p.realoem_price is not None]
        assert len(prices) == 4

    def test_oil_filter_element_price(self):
        parts = self._parts()
        oil_filter = next(p for p in parts if "Filter Element" in p.description)
        assert oil_filter.oem_pn == "11427541827"
        assert oil_filter.realoem_price == pytest.approx(14.95)

    def test_catalog_path_set(self):
        for p in self._parts():
            assert p.catalog_path == ["11", "11_0430"]

    def test_diagram_ref_set(self):
        parts = self._parts()
        refs = [p.diagram_ref for p in parts if p.diagram_ref]
        assert len(refs) == 4
        assert refs[0] == "1"

    def test_empty_table_returns_empty_list(self):
        from bmw_helper.realoem import RealOEMClient
        result = RealOEMClient._parse_parts("<html><body></body></html>", catalog_path=[])
        assert result == []


# ── _best_match ───────────────────────────────────────────────────────────────

class TestBestMatch:
    def _items(self):
        return [
            {"hg": "11", "name": "Engine"},
            {"hg": "34", "name": "Brakes"},
            {"hg": "64", "name": "Heating / Air Conditioning"},
            {"hg": "13", "name": "Fuel Preparation System"},
        ]

    def test_exact_match(self):
        from bmw_helper.realoem import _best_match
        result = _best_match("Engine", self._items(), key="name")
        assert result["hg"] == "11"

    def test_case_insensitive(self):
        from bmw_helper.realoem import _best_match
        result = _best_match("engine", self._items(), key="name")
        assert result["hg"] == "11"

    def test_substring_match(self):
        from bmw_helper.realoem import _best_match
        result = _best_match("Air Conditioning", self._items(), key="name")
        assert result["hg"] == "64"

    def test_word_overlap_match(self):
        from bmw_helper.realoem import _best_match
        result = _best_match("Fuel", self._items(), key="name")
        assert result["hg"] == "13"

    def test_no_match_returns_none(self):
        from bmw_helper.realoem import _best_match
        result = _best_match("Transmission", self._items(), key="name")
        assert result is None
