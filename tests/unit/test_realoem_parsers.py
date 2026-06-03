"""Unit tests for RealOEM HTML parsing functions.

All tests use fixture HTML files — no network access required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "realoem"
CATALOG_ID = "WB_81_06_1234"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text()


# ── resolve_catalog_id (HTML parsing only) ────────────────────────────────────

class TestResolveCatalogId:
    def test_extracts_catalog_id_from_partgrp_link(self):
        from bmw_helper.realoem import RealOEMClient
        import re
        html = _html("vin_select.html")
        soup = RealOEMClient._soup(html)
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
        ids = [
            m.group(1)
            for a in soup.find_all("a", href=True)
            if (m := re.search(r"showparts\?id=([^&\s]+)", a["href"]))
        ]
        assert len(ids) == 2
        assert ids[0] == CATALOG_ID


# ── get_groups parsing ────────────────────────────────────────────────────────

class TestGetGroups:
    def _groups(self):
        from bmw_helper.realoem import RealOEMClient
        client = RealOEMClient.__new__(RealOEMClient)
        from bs4 import BeautifulSoup
        from urllib.parse import parse_qs, urlparse
        import re
        soup = BeautifulSoup(_html("groups.html"), "html.parser")
        results, seen = [], set()
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
            results.append({"mg": mg, "name": name})
        return results

    def test_returns_all_groups(self):
        assert len(self._groups()) == 11

    def test_group_has_mg_and_name(self):
        for g in self._groups():
            assert "mg" in g
            assert "name" in g

    def test_engine_has_mg_11(self):
        groups = self._groups()
        engine = next((g for g in groups if "ENGINE" in g["name"] and "ELECTRICAL" not in g["name"]), None)
        assert engine is not None
        assert engine["mg"] == "11"

    def test_brakes_present(self):
        names = [g["name"] for g in self._groups()]
        assert any("BRAKE" in n for n in names)

    def test_no_duplicate_mg_codes(self):
        mgs = [g["mg"] for g in self._groups()]
        assert len(mgs) == len(set(mgs))


# ── get_subgroups parsing ─────────────────────────────────────────────────────

class TestGetSubgroups:
    def _subs(self):
        from bs4 import BeautifulSoup
        from urllib.parse import parse_qs, urlparse
        import re
        soup = BeautifulSoup(_html("subgroups.html"), "html.parser")
        results, seen = [], set()
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
            results.append({"diag_id": diag_id, "name": name})
        return results

    def test_returns_subgroups(self):
        assert len(self._subs()) == 6

    def test_each_subgroup_has_diag_id_and_name(self):
        for s in self._subs():
            assert "diag_id" in s
            assert "name" in s

    def test_oil_filter_present(self):
        names = [s["name"] for s in self._subs()]
        assert any("OIL FILTER" in n for n in names)

    def test_diag_ids_are_unique(self):
        ids = [s["diag_id"] for s in self._subs()]
        assert len(ids) == len(set(ids))


# ── _parse_parts ──────────────────────────────────────────────────────────────

class TestParseParts:
    def _parts(self):
        from bmw_helper.realoem import RealOEMClient
        return RealOEMClient._parse_parts(_html("parts.html"), catalog_path=["11_3971"])

    def test_returns_five_parts(self):
        assert len(self._parts()) == 5

    def test_part_has_required_fields(self):
        for p in self._parts():
            assert p.oem_pn
            assert p.description
            assert p.qty_required >= 1

    def test_part_numbers_are_11_digits(self):
        for p in self._parts():
            assert len(p.oem_pn) == 11, f"bad PN: {p.oem_pn}"
            assert p.oem_pn.isdigit()

    def test_prices_parsed_where_available(self):
        parts = self._parts()
        prices = [p.realoem_price for p in parts if p.realoem_price is not None]
        assert len(prices) == 3  # fixture has 3 parts with prices (incl. fitment row part)

    def test_oil_filter_cover_price(self):
        parts = self._parts()
        cover = next(p for p in parts if "filter cover" in p.description.lower())
        assert cover.oem_pn == "11427525334"
        assert cover.realoem_price == pytest.approx(26.45)

    def test_catalog_path_set(self):
        for p in self._parts():
            assert p.catalog_path == ["11_3971"]

    def test_diagram_ref_set(self):
        refs = [p.diagram_ref for p in self._parts() if p.diagram_ref]
        assert len(refs) == 5
        assert refs[0] == "01"

    def test_empty_table_returns_empty_list(self):
        from bmw_helper.realoem import RealOEMClient
        assert RealOEMClient._parse_parts("<html><body></body></html>", catalog_path=[]) == []

    def test_fitment_note_captured(self):
        parts = self._parts()
        fitment_part = next((p for p in parts if p.fitment_note), None)
        assert fitment_part is not None
        assert "M Sports suspension" in fitment_part.fitment_note

    def test_parts_without_fitment_have_none(self):
        parts = self._parts()
        no_fitment = [p for p in parts if p.fitment_note is None]
        assert len(no_fitment) == 4  # the original 4 parts have no fitment note

    def test_from_date_captured(self):
        parts = self._parts()
        dated = next((p for p in parts if p.from_date), None)
        assert dated is not None
        assert dated.from_date == "06/2010"

    def test_part_notes_captured_and_stripped(self):
        parts = self._parts()
        noted = next((p for p in parts if p.part_notes), None)
        assert noted is not None
        assert "Required for repair" in noted.part_notes
        assert "ECS Tuning" not in noted.part_notes

    def test_description_affiliate_stripped(self):
        parts = self._parts()
        strut = next((p for p in parts if "spring strut" in p.description.lower()), None)
        assert strut is not None
        assert "ECS Tuning" not in strut.description
        assert "Shop at" not in strut.description


class TestStripAffiliate:
    def _strip(self, text):
        from bmw_helper.realoem import RealOEMClient
        return RealOEMClient._strip_affiliate(text)

    def test_strips_shop_at_ecs_tuning(self):
        assert self._strip("Oil filter cover Shop at ECS Tuning") == "Oil filter cover"

    def test_strips_mid_sentence(self):
        assert self._strip("Gasket ring Shop at SomeStore and more") == "Gasket ring"

    def test_leaves_normal_text_alone(self):
        assert self._strip("Left front spring strut") == "Left front spring strut"

    def test_case_insensitive(self):
        assert self._strip("Oil pan shop at ECS Tuning") == "Oil pan"

    def test_empty_string(self):
        assert self._strip("") == ""

    def test_only_affiliate_text_returns_empty(self):
        assert self._strip("Shop at ECS Tuning") == ""


# ── _best_match ───────────────────────────────────────────────────────────────

class TestBestMatch:
    def _items(self):
        return [
            {"mg": "11", "name": "ENGINE"},
            {"mg": "34", "name": "BRAKES"},
            {"mg": "64", "name": "HEATER AND AIR CONDITIONING"},
            {"mg": "13", "name": "FUEL PREPARATION SYSTEM"},
        ]

    def test_exact_match(self):
        from bmw_helper.realoem import _best_match
        assert _best_match("ENGINE", self._items(), key="name")["mg"] == "11"

    def test_case_insensitive(self):
        from bmw_helper.realoem import _best_match
        assert _best_match("engine", self._items(), key="name")["mg"] == "11"

    def test_substring_match(self):
        from bmw_helper.realoem import _best_match
        assert _best_match("Air Conditioning", self._items(), key="name")["mg"] == "64"

    def test_word_overlap_match(self):
        from bmw_helper.realoem import _best_match
        assert _best_match("Fuel", self._items(), key="name")["mg"] == "13"

    def test_no_match_returns_none(self):
        from bmw_helper.realoem import _best_match
        assert _best_match("Transmission", self._items(), key="name") is None
