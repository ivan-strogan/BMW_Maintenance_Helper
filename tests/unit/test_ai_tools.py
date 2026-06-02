"""Unit tests for AI tool implementations.

Tools are tested directly — no Ollama required. The agent loop
(which does require Ollama) is tested in tests/integration/.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from bmw_helper.ai_tools import dispatch, get_overdue_items


class TestGetVehicleInfo:
    def test_returns_required_fields(self, config_dir):
        from bmw_helper.ai_tools import get_vehicle_info
        info = get_vehicle_info()
        for field in ("vin", "year", "make", "model", "engine_code",
                      "odometer_km", "transmission_code"):
            assert field in info, f"missing: {field}"

    def test_vin_matches_config(self, config_dir):
        from bmw_helper.ai_tools import get_vehicle_info
        info = get_vehicle_info()
        assert info["vin"] == "WBATEST00000000001"

    def test_manufacture_date_is_iso_string_or_none(self, config_dir):
        from bmw_helper.ai_tools import get_vehicle_info
        info = get_vehicle_info()
        if info["manufacture_date"] is not None:
            date.fromisoformat(info["manufacture_date"])  # must not raise


class TestGetScheduleStatus:
    def test_returns_list(self, config_dir):
        from bmw_helper.ai_tools import get_schedule_status
        result = get_schedule_status()
        assert isinstance(result, list)
        assert len(result) == 4  # conftest has 4 items

    def test_each_item_has_required_fields(self, config_dir):
        from bmw_helper.ai_tools import get_schedule_status
        for item in get_schedule_status():
            for f in ("id", "name", "status", "action"):
                assert f in item

    def test_status_values_are_valid(self, config_dir):
        from bmw_helper.ai_tools import get_schedule_status
        valid = {"overdue", "due_soon", "ok", "unknown"}
        for item in get_schedule_status():
            assert item["status"] in valid


class TestGetServiceHistory:
    def test_empty_initially(self, config_dir):
        from bmw_helper.ai_tools import get_service_history
        assert get_service_history() == []

    def test_filter_by_item_id(self, config_dir, client):
        client.post("/api/history", json={
            "item_id": "oil_filter",
            "date": "2025-01-01",
            "odometer_km": 80000,
            "performed_by": "Self",
            "parts": [],
            "notes": None,
        })
        client.post("/api/history", json={
            "item_id": "brake_fluid",
            "date": "2025-06-01",
            "odometer_km": 82000,
            "performed_by": "Self",
            "parts": [],
            "notes": None,
        })
        from bmw_helper.ai_tools import get_service_history
        oil = get_service_history("oil_filter")
        assert all(e["item_id"] == "oil_filter" for e in oil)
        assert len(oil) == 1


class TestGetOverdueItems:
    def test_returns_only_overdue_and_due_soon(self, config_dir):
        items = get_overdue_items()
        for item in items:
            assert item["status"] in ("overdue", "due_soon")

    def test_overdue_before_due_soon(self, config_dir):
        items = get_overdue_items()
        statuses = [i["status"] for i in items]
        if "due_soon" in statuses and "overdue" in statuses:
            assert statuses.index("overdue") < statuses.index("due_soon")


class TestDispatch:
    def test_unknown_tool_returns_error(self, config_dir):
        result = dispatch("nonexistent_tool", {})
        assert "error" in result

    def test_get_vehicle_info_via_dispatch(self, config_dir):
        result = dispatch("get_vehicle_info", {})
        assert "vin" in result

    def test_get_schedule_status_via_dispatch(self, config_dir):
        result = dispatch("get_schedule_status", {})
        assert isinstance(result, list)

    def test_get_service_history_with_item_id(self, config_dir):
        result = dispatch("get_service_history", {"item_id": "oil_filter"})
        assert isinstance(result, list)

    def test_get_overdue_items_via_dispatch(self, config_dir):
        result = dispatch("get_overdue_items", {})
        assert isinstance(result, list)
