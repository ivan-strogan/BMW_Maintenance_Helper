"""Unit tests for RockAuto mapping and conversion functions.

No network access — tests pure data-transformation logic.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from bmw_helper.rockauto import hint_to_category, _parse_price, _part_to_alternative
from bmw_helper.models import RockAutoAlternative


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
