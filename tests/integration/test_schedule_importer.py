"""Integration tests for the maintenance schedule PDF importer.

Tests here read the real fixture PDF and write to temp directories.
Pure regex logic for _extract_intervals lives in tests/unit/test_extract_intervals.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

N54_PDF = Path(__file__).parent.parent / "fixtures" / "bmw_335i_n54_maint_schedule.pdf"


@pytest.fixture(scope="module")
def n54_items():
    """Parse the N54 PDF once and reuse across tests in this module."""
    from bmw_helper.schedule_importer import parse_schedule_pdf
    return {item["id"]: item for item in parse_schedule_pdf(N54_PDF)}


class TestN54ItemCount:
    def test_all_seventeen_items_extracted(self, n54_items):
        expected = {
            "oil_filter", "tires", "battery", "wheel_alignment", "brake_fluid",
            "clutch_fluid", "interior_air_filter", "engine_air_filter",
            "engine_coolant", "power_steering_fluid", "gearbox_oil",
            "differential_oil", "spark_plugs", "fuel_filter", "drive_belts",
            "oxygen_sensors", "water_fuel_hoses",
        }
        assert set(n54_items.keys()) == expected


class TestKmIntervals:
    def test_oil_filter_replace_12000(self, n54_items):
        assert n54_items["oil_filter"]["interval_replace_km"] == 12000

    def test_brake_fluid_replace_48000(self, n54_items):
        assert n54_items["brake_fluid"]["interval_replace_km"] == 48000

    def test_interior_air_filter_replace_15000(self, n54_items):
        assert n54_items["interior_air_filter"]["interval_replace_km"] == 15000

    def test_engine_air_filter_inspect_24000(self, n54_items):
        assert n54_items["engine_air_filter"]["interval_inspect_km"] == 24000

    def test_engine_air_filter_replace_48000(self, n54_items):
        assert n54_items["engine_air_filter"]["interval_replace_km"] == 48000

    def test_spark_plugs_replace_72000(self, n54_items):
        assert n54_items["spark_plugs"]["interval_replace_km"] == 72000

    def test_gearbox_oil_replace_90000(self, n54_items):
        assert n54_items["gearbox_oil"]["interval_replace_km"] == 90000

    def test_differential_oil_replace_96000(self, n54_items):
        assert n54_items["differential_oil"]["interval_replace_km"] == 96000

    def test_drive_belts_inspect_24000_replace_192000(self, n54_items):
        assert n54_items["drive_belts"]["interval_inspect_km"] == 24000
        assert n54_items["drive_belts"]["interval_replace_km"] == 192000

    def test_fuel_filter_replace_240000(self, n54_items):
        assert n54_items["fuel_filter"]["interval_replace_km"] == 240000


class TestMonthIntervals:
    def test_brake_fluid_30_months(self, n54_items):
        assert n54_items["brake_fluid"]["interval_replace_months"] == 30

    def test_engine_coolant_24_months(self, n54_items):
        assert n54_items["engine_coolant"]["interval_replace_months"] == 24


class TestBmwRecommendations:
    def test_oil_filter_bmw_rec_24000(self, n54_items):
        assert n54_items["oil_filter"]["bmw_recommendation_km"] == 24000

    def test_engine_air_filter_bmw_rec_45000(self, n54_items):
        assert n54_items["engine_air_filter"]["bmw_recommendation_km"] == 45000


class TestWriteYaml:
    def test_writes_valid_yaml(self, n54_items, tmp_path):
        from bmw_helper.schedule_importer import write_schedule_yaml
        from bmw_helper.models import MaintenanceSchedule

        out = tmp_path / "schedule.yaml"
        write_schedule_yaml(list(n54_items.values()), out, source_file="test.pdf")
        assert out.exists()

        # Must load back as a valid MaintenanceSchedule
        from ruamel.yaml import YAML
        with open(out) as f:
            data = YAML().load(f)
        schedule = MaintenanceSchedule.model_validate(data)
        assert len(schedule.items) == 17


class TestImportIntoConfigDir:
    """Integration test: import PDF -> config_dir/schedule.yaml -> status computation."""

    def test_import_replaces_schedule_yaml(self, config_dir):
        from bmw_helper.schedule_importer import import_schedule

        out = config_dir / "schedule.yaml"
        items = import_schedule(N54_PDF, out)

        assert out.exists()
        assert len(items) == 17

    def test_imported_schedule_loads_via_config(self, config_dir):
        from bmw_helper.schedule_importer import import_schedule
        from bmw_helper.config import load_schedule

        import_schedule(N54_PDF, config_dir / "schedule.yaml")
        schedule = load_schedule()

        assert len(schedule.items) == 17
        ids = {it.id for it in schedule.items}
        assert "oil_filter" in ids
        assert "spark_plugs" in ids
        assert "water_fuel_hoses" in ids

    def test_status_computed_from_imported_schedule(self, config_dir):
        """Full pipeline: PDF -> schedule.yaml -> compute_status -> all OVERDUE (no history)."""
        from bmw_helper.schedule_importer import import_schedule
        from bmw_helper.config import load_app_config, load_schedule, load_service_history
        from bmw_helper.schedule import compute_status
        from bmw_helper.models import MaintenanceStatus

        import_schedule(N54_PDF, config_dir / "schedule.yaml")

        cfg = load_app_config()
        schedule = load_schedule()
        history = load_service_history(cfg.vehicle.vin)
        statuses = compute_status(
            schedule, history,
            cfg.vehicle.odometer_km,
            manufacture_date=cfg.vehicle.manufacture_date,
        )

        assert len(statuses) == 17

        # Items with extractable intervals must have a computed status (not UNKNOWN).
        # Items whose prose contains no parseable interval (e.g. Tires: "Replace when
        # below minimums") will correctly be UNKNOWN.
        for s in statuses:
            has_interval = any([
                s.item.interval_replace_km, s.item.interval_inspect_km,
                s.item.interval_replace_months, s.item.interval_inspect_months,
            ])
            if has_interval:
                assert s.status != MaintenanceStatus.UNKNOWN, (
                    f"{s.item.id} has intervals but got UNKNOWN"
                )
            else:
                assert s.status == MaintenanceStatus.UNKNOWN, (
                    f"{s.item.id} has no intervals — expected UNKNOWN, got {s.status}"
                )

    def test_imported_schedule_via_api(self, config_dir, client):
        """API returns 17 items after importing the real PDF into the test config dir."""
        from bmw_helper.schedule_importer import import_schedule

        import_schedule(N54_PDF, config_dir / "schedule.yaml")

        res = client.get("/api/schedule/status")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 17
