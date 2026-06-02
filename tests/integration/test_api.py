"""Tests for FastAPI endpoints."""

from __future__ import annotations

from datetime import date
from pathlib import Path


# ── Config endpoint ────────────────────────────────────────────────────────────

class TestConfigEndpoint:
    def test_returns_vehicle_and_owner(self, client):
        res = client.get("/api/config")
        assert res.status_code == 200
        data = res.json()
        assert data["vehicle"]["vin"] == "WBATEST00000000001"
        assert data["owner"]["name"] == "Test Owner"
        assert data["vehicle"]["odometer_km"] == 84000

    def test_vehicle_has_required_fields(self, client):
        data = client.get("/api/config").json()
        v = data["vehicle"]
        for field in ("vin", "year", "make", "model", "engine_code",
                      "transmission_code", "drive", "odometer_km"):
            assert field in v, f"missing field: {field}"


# ── Schedule status endpoint ───────────────────────────────────────────────────

class TestScheduleStatus:
    def test_returns_list(self, client):
        res = client.get("/api/schedule/status")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 4  # conftest.py defines 4 items

    def test_each_item_has_required_fields(self, client):
        data = client.get("/api/schedule/status").json()
        for s in data:
            assert "item" in s
            assert "status" in s
            assert "action" in s
            assert s["status"] in ("overdue", "due_soon", "ok", "unknown")
            assert s["action"] in ("Replace", "Inspect")

    def test_all_overdue_with_no_history(self, client):
        """All items should be OVERDUE when no service history exists."""
        data = client.get("/api/schedule/status").json()
        for s in data:
            assert s["status"] == "overdue", (
                f"{s['item']['id']} expected overdue, got {s['status']}"
            )

    def test_inspect_action_for_tires(self, client):
        data = client.get("/api/schedule/status").json()
        tires = next(s for s in data if s["item"]["id"] == "tires")
        assert tires["action"] == "Inspect"

    def test_replace_action_for_oil_filter(self, client):
        data = client.get("/api/schedule/status").json()
        oil = next(s for s in data if s["item"]["id"] == "oil_filter")
        assert oil["action"] == "Replace"


# ── History endpoints ──────────────────────────────────────────────────────────

class TestHistoryEndpoints:
    def test_empty_history_on_start(self, client):
        res = client.get("/api/history")
        assert res.status_code == 200
        assert res.json()["history"] == []

    def test_post_history_creates_event(self, client):
        payload = {
            "item_id": "oil_filter",
            "date": "2025-10-01",
            "odometer_km": 78000,
            "performed_by": "Self",
            "parts": ["11427541827 OEM"],
            "notes": "Test note",
        }
        res = client.post("/api/history", json=payload)
        assert res.status_code == 201
        event = res.json()
        assert event["item_id"] == "oil_filter"
        assert event["odometer_km"] == 78000
        assert "id" in event

    def test_posted_event_appears_in_get(self, client):
        payload = {
            "item_id": "brake_fluid",
            "date": "2024-01-15",
            "odometer_km": 60000,
            "performed_by": "Shop",
            "parts": [],
            "notes": None,
        }
        client.post("/api/history", json=payload)
        history = client.get("/api/history").json()["history"]
        ids = [e["item_id"] for e in history]
        assert "brake_fluid" in ids

    def test_posted_event_changes_status_to_ok(self, client):
        """Recording a recent service for oil_filter should flip it from OVERDUE to OK."""
        payload = {
            "item_id": "oil_filter",
            "date": "2026-01-01",
            "odometer_km": 80000,
            "performed_by": "Self",
            "parts": [],
            "notes": None,
        }
        client.post("/api/history", json=payload)
        statuses = client.get("/api/schedule/status").json()
        oil = next(s for s in statuses if s["item"]["id"] == "oil_filter")
        assert oil["status"] == "ok"

    def test_delete_history_event(self, client):
        payload = {
            "item_id": "spark_plugs",
            "date": "2024-06-01",
            "odometer_km": 72000,
            "performed_by": "Test",
            "parts": [],
            "notes": None,
        }
        created = client.post("/api/history", json=payload).json()
        event_id = created["id"]

        del_res = client.delete(f"/api/history/{event_id}")
        assert del_res.status_code == 200

        history = client.get("/api/history").json()["history"]
        assert not any(e["id"] == event_id for e in history)

    def test_delete_nonexistent_returns_404(self, client):
        res = client.delete("/api/history/doesnotexist")
        assert res.status_code == 404


# ── Raw schedule endpoint ─────────────────────────────────────────────────────

class TestRawScheduleEndpoint:
    def test_returns_schedule_structure(self, client):
        res = client.get("/api/schedule")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 4

    def test_items_have_required_fields(self, client):
        data = client.get("/api/schedule").json()
        for item in data["items"]:
            for field in ("id", "name"):
                assert field in item, f"missing field: {field}"

    def test_inspect_item_has_inspect_interval(self, client):
        data = client.get("/api/schedule").json()
        tires = next(it for it in data["items"] if it["id"] == "tires")
        assert tires["interval_inspect_km"] == 12000
        assert tires["interval_replace_km"] is None


# ── Input validation ───────────────────────────────────────────────────────────

class TestInputValidation:
    def test_history_post_missing_item_id_returns_422(self, client):
        res = client.post("/api/history", json={
            "date": "2025-01-01",
            "odometer_km": 80000,
        })
        assert res.status_code == 422

    def test_history_post_missing_odometer_returns_422(self, client):
        res = client.post("/api/history", json={
            "item_id": "oil_filter",
            "date": "2025-01-01",
        })
        assert res.status_code == 422

    def test_history_post_invalid_date_returns_422(self, client):
        res = client.post("/api/history", json={
            "item_id": "oil_filter",
            "date": "not-a-date",
            "odometer_km": 80000,
        })
        assert res.status_code == 422

    def test_history_post_invalid_odometer_type_returns_422(self, client):
        res = client.post("/api/history", json={
            "item_id": "oil_filter",
            "date": "2025-01-01",
            "odometer_km": "eighty thousand",
        })
        assert res.status_code == 422


# ── Odometer update ────────────────────────────────────────────────────────────

class TestOdometerUpdate:
    def test_patch_updates_odometer_in_config(self, client, config_dir):
        res = client.patch("/api/vehicle/odometer?odometer_km=90000")
        assert res.status_code == 200
        assert res.json()["odometer_km"] == 90000

        # Confirm it was written to the YAML
        from ruamel.yaml import YAML
        with open(config_dir / "vehicle.yaml") as f:
            data = YAML().load(f)
        assert data["vehicle"]["odometer_km"] == 90000

    def test_updated_odometer_reflected_in_config_endpoint(self, client):
        client.patch("/api/vehicle/odometer?odometer_km=95000")
        config = client.get("/api/config").json()
        assert config["vehicle"]["odometer_km"] == 95000
