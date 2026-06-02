"""Shared fixtures for the BMW Maintenance Helper test suite."""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Minimal YAML content for tests ────────────────────────────────────────────

VEHICLE_YAML = """\
owner:
  name: Test Owner
  email: test@example.com

vehicle:
  vin: WBATEST00000000001
  year: 2007
  make: BMW
  model: 335i
  body: E93 Convertible
  manufacture_date: 2007-04-01
  engine_code: N54
  engine_desc: 3.0L Twin-Turbo Inline-6
  transmission_code: GS6-53BZ
  transmission_desc: 6-Speed Manual
  drive: RWD
  odometer_km: 84000

preferences:
  currency: CAD
  tax_name: GST
  tax_rate: 0.05
  preferred_brands:
    - Elring
    - Bosch
  oem_only_systems: []
"""

SCHEDULE_YAML = """\
source: test
engine: N54
unit: km
version: test

items:
  - id: oil_filter
    name: Oil & Filter Change
    interval_replace_km: 12000
    interval_replace_months: 12
    bmw_recommendation_km: 24000
    bmw_recommendation_months: 24
    notes: "Replace every 12,000 km or 1 year."
    catalog_hint: "Engine > Lubrication System > Oil Filter"

  - id: brake_fluid
    name: Brake Fluid
    interval_replace_km: 48000
    interval_replace_months: 30
    bmw_recommendation_months: 24
    notes: "Replace every 48,000 km or 2.5 years."
    catalog_hint: "Brakes > Brake Fluid"

  - id: engine_air_filter
    name: Engine Air Filter
    interval_inspect_km: 24000
    interval_replace_km: 48000
    interval_inspect_months: 24
    interval_replace_months: 36
    bmw_recommendation_km: 45000
    notes: "Inspect every 24,000 km, replace every 48,000 km."
    catalog_hint: "Engine > Air Supply > Air Filter"

  - id: tires
    name: Tires
    interval_inspect_km: 12000
    interval_inspect_months: 12
    notes: "Inspect tread depth and condition."
    catalog_hint: ~
"""

HISTORY_YAML = """\
vehicle_vin: WBATEST00000000001
history: []
"""


# ── Config directory fixture ───────────────────────────────────────────────────

@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Create a temporary config directory with minimal YAML files and patch
    bmw_helper.config to read from it instead of the real config directory.
    """
    (tmp_path / "vehicle.yaml").write_text(VEHICLE_YAML)
    (tmp_path / "schedule.yaml").write_text(SCHEDULE_YAML)
    (tmp_path / "service_history.yaml").write_text(HISTORY_YAML)

    # Patch the CONFIG_DIR used by bmw_helper.config
    import bmw_helper.config as cfg_module
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", tmp_path)

    return tmp_path


# ── FastAPI test client ────────────────────────────────────────────────────────

@pytest.fixture
def client(config_dir: Path) -> TestClient:
    """FastAPI TestClient wired to the temp config directory."""
    from bmw_helper.api import api
    return TestClient(api)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_event(item_id: str, odometer_km: int, event_date: date | None = None) -> dict:
    """Return a ServiceEvent payload dict."""
    return {
        "item_id": item_id,
        "date": (event_date or date(2024, 1, 1)).isoformat(),
        "odometer_km": odometer_km,
        "performed_by": "Test",
        "parts": [],
        "notes": None,
    }
