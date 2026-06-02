"""Tests for config loading edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmw_helper.models import ServiceEvent
from datetime import date


class TestLoadAppConfig:
    def test_loads_correctly(self, config_dir):
        from bmw_helper.config import load_app_config
        cfg = load_app_config()
        assert cfg.vehicle.vin == "WBATEST00000000001"
        assert cfg.vehicle.odometer_km == 84000
        assert cfg.owner.email == "test@example.com"

    def test_missing_vehicle_yaml_raises(self, config_dir):
        (config_dir / "vehicle.yaml").unlink()
        from bmw_helper.config import load_app_config
        with pytest.raises(FileNotFoundError):
            load_app_config()

    def test_manufacture_date_parsed(self, config_dir):
        from bmw_helper.config import load_app_config
        cfg = load_app_config()
        assert cfg.vehicle.manufacture_date == date(2007, 4, 1)

    def test_preferences_loaded(self, config_dir):
        from bmw_helper.config import load_app_config
        cfg = load_app_config()
        assert cfg.preferences.currency == "CAD"
        assert cfg.preferences.tax_rate == 0.05
        assert "Elring" in cfg.preferences.preferred_brands


class TestLoadSchedule:
    def test_loads_items(self, config_dir):
        from bmw_helper.config import load_schedule
        schedule = load_schedule()
        assert len(schedule.items) == 4  # conftest defines 4 items

    def test_missing_schedule_yaml_returns_empty(self, config_dir):
        (config_dir / "schedule.yaml").unlink()
        from bmw_helper.config import load_schedule
        schedule = load_schedule()
        assert schedule.items == []

    def test_item_fields_populated(self, config_dir):
        from bmw_helper.config import load_schedule
        schedule = load_schedule()
        oil = next(it for it in schedule.items if it.id == "oil_filter")
        assert oil.interval_replace_km == 12000
        assert oil.interval_replace_months == 12
        assert oil.catalog_hint is not None


class TestLoadServiceHistory:
    def test_empty_on_start(self, config_dir):
        from bmw_helper.config import load_service_history
        history = load_service_history("WBATEST00000000001")
        assert history.history == []

    def test_missing_history_yaml_returns_empty(self, config_dir):
        (config_dir / "service_history.yaml").unlink()
        from bmw_helper.config import load_service_history
        history = load_service_history("WBATEST00000000001")
        assert history.history == []

    def test_vin_set_on_empty(self, config_dir):
        (config_dir / "service_history.yaml").unlink()
        from bmw_helper.config import load_service_history
        history = load_service_history("WBATEST00000000001")
        assert history.vehicle_vin == "WBATEST00000000001"


class TestSaveServiceHistory:
    def test_save_and_reload(self, config_dir):
        from bmw_helper.config import load_service_history, save_service_history
        history = load_service_history("WBATEST00000000001")
        event = ServiceEvent(
            item_id="oil_filter",
            date=date(2025, 6, 1),
            odometer_km=80000,
            performed_by="Self",
        )
        history.history.append(event)
        save_service_history(history)

        reloaded = load_service_history("WBATEST00000000001")
        assert len(reloaded.history) == 1
        assert reloaded.history[0].item_id == "oil_filter"
        assert reloaded.history[0].odometer_km == 80000

    def test_save_preserves_all_fields(self, config_dir):
        from bmw_helper.config import load_service_history, save_service_history
        history = load_service_history("WBATEST00000000001")
        event = ServiceEvent(
            item_id="brake_fluid",
            date=date(2024, 3, 15),
            odometer_km=72000,
            performed_by="Eurotekk",
            parts=["DOT 4 LV Ate"],
            notes="Bled all four corners",
        )
        history.history.append(event)
        save_service_history(history)

        reloaded = load_service_history("WBATEST00000000001")
        saved = reloaded.history[0]
        assert saved.performed_by == "Eurotekk"
        assert saved.parts == ["DOT 4 LV Ate"]
        assert saved.notes == "Bled all four corners"
