"""Unit tests for RockAuto mapping and conversion functions.

No network access — tests pure data-transformation logic.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from bmw_helper.rockauto import hint_to_category, _parse_price, _part_to_alternative, _parse_partsearch_results
from bmw_helper.models import RockAutoAlternative


# ── _parse_partsearch_results ─────────────────────────────────────────────────

def _partsearch_html(rows: str) -> str:
    """Wrap rows in minimal RealOEM-style partsearch HTML."""
    return f"""<html><body>
    <tr>
      <span class="listing-final-manufacturer">{{}}</span>
    </tr>
    {rows}
    </body></html>"""


def _make_row(brand: str, pn: str, price_html: str, notes: str = "") -> str:
    return f"""<tr>
      <span class="listing-final-manufacturer">{brand}</span>
      <span class="listing-final-partnumber as-link-if-js">{pn}</span>
      <span class="span-link-underline-remover">{notes}</span>
      <span class="ra-formatted-amount listing-price listing-amount-bold">
        <span id="dprice[1][v]">{price_html}</span>
      </span>
      <a href="https://www.rockauto.com/en/moreinfo.php?pk=123">Info</a>
    </tr>"""


class TestParsePartsearchResults:
    def test_parses_brand_and_pn(self):
        html = _make_row("MAHLE / CLEVITE", "OX387D", "CAD$5.21")
        results = _parse_partsearch_results(html)
        assert len(results) == 1
        assert results[0].brand == "MAHLE / CLEVITE"
        assert results[0].part_number == "OX387D"

    def test_parses_cad_price(self):
        html = _make_row("MANN", "HU816X", "CAD$10.30")
        results = _parse_partsearch_results(html)
        assert results[0].price == pytest.approx(10.30)
        assert results[0].currency == "CAD"

    def test_parses_notes(self):
        html = _make_row("MAHLE", "OX387D", "CAD$5.21", notes="79mm Height; O-ring Included")
        results = _parse_partsearch_results(html)
        assert results[0].notes == "79mm Height; O-ring Included"

    def test_out_of_stock_detected(self):
        html = _make_row("URO PARTS", "11117530262",
                         '<span class="oos-price-text">Out of Stock</span>')
        results = _parse_partsearch_results(html)
        assert results[0].availability == "out_of_stock"
        assert results[0].price == 0.0

    def test_map_price_detected(self):
        html = _make_row("BILSTEIN", "35120377",
                         '<span class="map-price-text">Add to Cart to See Price</span>')
        results = _parse_partsearch_results(html)
        assert results[0].availability == "map_price"
        assert results[0].price == 0.0

    def test_in_stock_availability(self):
        html = _make_row("CHAMP", "P969", "CAD$2.49")
        results = _parse_partsearch_results(html)
        assert results[0].availability == "in_stock"

    def test_skips_unknown_part_numbers(self):
        html = _make_row("SOME BRAND", "Unknown", "CAD$5.00")
        results = _parse_partsearch_results(html)
        assert results == []

    def test_captures_moreinfo_url(self):
        html = _make_row("MAHLE", "OX387D", "CAD$5.21")
        results = _parse_partsearch_results(html)
        assert "rockauto.com" in results[0].url

    def test_multiple_parts_parsed(self):
        html = (
            _make_row("CHAMP", "P969", "CAD$2.49") +
            _make_row("MANN", "HU816X", "CAD$10.30") +
            _make_row("MAHLE", "OX387D", "CAD$5.21")
        )
        results = _parse_partsearch_results(html)
        assert len(results) == 3

    def test_empty_html_returns_empty(self):
        assert _parse_partsearch_results("<html><body></body></html>") == []

    def test_oos_price_is_zero(self):
        """Out-of-stock parts must have price=0 so frontend filter excludes them."""
        html = _make_row("URO PARTS", "11117530262",
                         '<span class="oos-price-text">Out of Stock</span>')
        r = _parse_partsearch_results(html)[0]
        assert r.price == 0.0
        assert r.availability == "out_of_stock"

    def test_map_price_is_zero(self):
        """MAP (add-to-cart) parts must have price=0 so frontend filter excludes them."""
        html = _make_row("BILSTEIN", "35120377",
                         '<span class="map-price-text">Add to Cart to See Price</span>')
        r = _parse_partsearch_results(html)[0]
        assert r.price == 0.0
        assert r.availability == "map_price"

    def test_only_priced_items_have_positive_price(self):
        """Mixed list: only in-stock priced items should have price > 0."""
        html = (
            _make_row("CHAMP", "P969", "CAD$2.49") +
            _make_row("URO", "U0001234", '<span class="oos-price-text">Out of Stock</span>') +
            _make_row("BILSTEIN", "B9999999", '<span class="map-price-text">Add to Cart to See Price</span>') +
            _make_row("MANN", "HU816X", "CAD$10.30")
        )
        results = _parse_partsearch_results(html)
        priced = [r for r in results if r.price > 0]
        assert len(priced) == 2
        assert all(r.availability == "in_stock" for r in priced)

    def test_results_ordered_cheapest_first(self):
        """RockAuto returns results sorted by price ascending on their site."""
        html = (
            _make_row("CHAMP", "P969", "CAD$2.49") +
            _make_row("MAHLE", "OX387D", "CAD$5.21") +
            _make_row("MANN", "HU816X", "CAD$10.30")
        )
        results = _parse_partsearch_results(html)
        prices = [r.price for r in results if r.price > 0]
        assert prices == sorted(prices)

    def test_large_price_with_comma(self):
        html = _make_row("BILSTEIN", "B4567890", "CAD$1,234.56")
        results = _parse_partsearch_results(html)
        assert results[0].price == pytest.approx(1234.56)

    def test_price_with_cad_prefix(self):
        """CAD$ prefix must be stripped correctly by _parse_price."""
        assert _parse_price("CAD$49.99") == pytest.approx(49.99)

    def test_price_zero_string(self):
        assert _parse_price("CAD$0.00") == pytest.approx(0.0)


# ── savings_vs_oem ────────────────────────────────────────────────────────────

class TestSavingsVsOem:
    """Tests for the savings calculation helper used by the frontend."""

    def _savings(self, oem_usd: float, ra_cad: float) -> float | None:
        from bmw_helper.rockauto import savings_vs_oem
        return savings_vs_oem(oem_usd, ra_cad)

    def test_positive_savings(self):
        assert self._savings(50.00, 30.00) == pytest.approx(20.00)

    def test_negative_savings_when_ra_more_expensive(self):
        assert self._savings(10.00, 15.00) == pytest.approx(-5.00)

    def test_zero_savings_when_equal(self):
        assert self._savings(25.00, 25.00) == pytest.approx(0.00)

    def test_none_when_oem_price_missing(self):
        assert self._savings(None, 10.00) is None

    def test_none_when_ra_price_zero(self):
        """Zero RA price means OOS or MAP — no meaningful savings to show."""
        assert self._savings(50.00, 0.00) is None


class TestHintToCategory:
    def test_engine_hint(self):
        assert hint_to_category("Engine > Oil Filter") == "Engine"

    def test_engine_cooling(self):
        assert hint_to_category("Engine > Cooling System") == "Engine"

    def test_brakes_hint(self):
        assert hint_to_category("Brakes > Brake Fluid") == "Brake & Wheel Hub"

    def test_brake_singular(self):
        assert hint_to_category("Brake > Pads") == "Brake & Wheel Hub"

    def test_clutch_hint(self):
        assert hint_to_category("Clutch > Clutch Hydraulics") == "Transmission-Manual & Clutch"

    def test_gearbox_hint(self):
        assert hint_to_category("Gearbox > Oil") == "Transmission-Manual & Clutch"

    def test_ignition_hint(self):
        assert hint_to_category("Ignition > Spark Plugs") == "Ignition"

    def test_heating_slash_ac(self):
        result = hint_to_category("Heating / Air Conditioning > Microfilter")
        assert result == "Heat & Air Conditioning"

    def test_electrical(self):
        assert hint_to_category("Electrical > Battery") == "Electrical"

    def test_case_insensitive(self):
        assert hint_to_category("engine > oil filter") == "Engine"
        assert hint_to_category("BRAKES > PADS") == "Brake & Wheel Hub"

    def test_unknown_hint_returns_none(self):
        assert hint_to_category("Wheels > Lug Nuts") is None

    def test_empty_hint_returns_none(self):
        assert hint_to_category("") is None

    def test_no_arrow_uses_full_string(self):
        assert hint_to_category("Engine") == "Engine"


class TestParsePrice:
    def test_dollar_sign_price(self):
        assert _parse_price("$49.99") == pytest.approx(49.99)

    def test_price_with_comma(self):
        assert _parse_price("$1,234.56") == pytest.approx(1234.56)

    def test_price_embedded_in_text(self):
        assert _parse_price("Price: $12.49") == pytest.approx(12.49)

    def test_none_returns_none(self):
        assert _parse_price(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_price("") is None

    def test_no_price_pattern_returns_none(self):
        assert _parse_price("In Stock") is None

    def test_zero_price(self):
        assert _parse_price("$0.00") == pytest.approx(0.0)


class TestPartToAlternative:
    def _mock_part(self, **kwargs):
        defaults = {
            "brand": "BOSCH",
            "part_number": "3323",
            "name": "Oil Filter",
            "url": "https://www.rockauto.com/...",
            "compatibility_notes": "",
            "availability": "In Stock",
        }
        defaults.update(kwargs)
        part = MagicMock()
        for k, v in defaults.items():
            setattr(part, k, v)
        part.get_current_price = MagicMock(return_value="$12.49")
        return part

    def test_basic_conversion(self):
        part = self._mock_part()
        alt = _part_to_alternative(part)
        assert alt is not None
        assert isinstance(alt, RockAutoAlternative)
        assert alt.brand == "BOSCH"
        assert alt.part_number == "3323"
        assert alt.price == pytest.approx(12.49)
        assert alt.currency == "USD"

    def test_no_price_defaults_to_zero(self):
        part = self._mock_part()
        part.get_current_price = MagicMock(return_value=None)
        alt = _part_to_alternative(part)
        assert alt is not None
        assert alt.price == 0.0

    def test_unknown_part_number_returns_none(self):
        part = self._mock_part(part_number="Unknown")
        assert _part_to_alternative(part) is None

    def test_empty_part_number_returns_none(self):
        part = self._mock_part(part_number="")
        assert _part_to_alternative(part) is None

    def test_oem_interchange_extracted_from_compat_notes(self):
        part = self._mock_part(compatibility_notes="OEM: 11427541827, also fits 11428507683")
        alt = _part_to_alternative(part)
        assert alt is not None
        assert "11427541827" in alt.oem_interchange
        assert "11428507683" in alt.oem_interchange

    def test_availability_preserved(self):
        part = self._mock_part(availability="Usually Ships in 1-2 Business Days")
        alt = _part_to_alternative(part)
        assert alt is not None
        assert "1-2 Business Days" in alt.availability

    def test_url_preserved(self):
        part = self._mock_part(url="https://www.rockauto.com/en/partsearch/")
        alt = _part_to_alternative(part)
        assert alt is not None
        assert alt.url == "https://www.rockauto.com/en/partsearch/"
