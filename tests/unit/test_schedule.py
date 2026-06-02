"""Unit tests for schedule status computation and helpers."""

from __future__ import annotations

from datetime import date

import pytest

from bmw_helper.models import (
    MaintenanceSchedule,
    MaintenanceStatus,
    ScheduleItem,
    ServiceEvent,
    ServiceHistory,
)
from bmw_helper.schedule import _add_months, compute_status


# ── _add_months ────────────────────────────────────────────────────────────────

class TestAddMonths:
    def test_simple(self):
        assert _add_months(date(2024, 1, 15), 3) == date(2024, 4, 15)

    def test_crosses_year(self):
        assert _add_months(date(2023, 11, 1), 3) == date(2024, 2, 1)

    def test_end_of_month_clamped(self):
        # Jan 31 + 1 month = Feb 28 (or 29 in leap year)
        result = _add_months(date(2023, 1, 31), 1)
        assert result == date(2023, 2, 28)

    def test_leap_year(self):
        result = _add_months(date(2024, 1, 31), 1)
        assert result == date(2024, 2, 29)

    def test_twelve_months_equals_one_year(self):
        assert _add_months(date(2022, 6, 15), 12) == date(2023, 6, 15)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _item(**kwargs) -> ScheduleItem:
    defaults = dict(id="test_item", name="Test Item")
    return ScheduleItem(**{**defaults, **kwargs})


def _history(vin: str, events: list[ServiceEvent]) -> ServiceHistory:
    return ServiceHistory(vehicle_vin=vin, history=events)


def _schedule(*items: ScheduleItem) -> MaintenanceSchedule:
    return MaintenanceSchedule(items=list(items))


def _event(item_id: str, km: int, event_date: date) -> ServiceEvent:
    return ServiceEvent(item_id=item_id, date=event_date, odometer_km=km)


MANUFACTURE = date(2007, 4, 1)
TODAY = date(2026, 5, 31)


# ── No history — manufacture date baseline ─────────────────────────────────────

class TestManufactureBaseline:
    def test_overdue_by_km(self):
        item = _item(id="oil", interval_replace_km=12000)
        statuses = compute_status(
            _schedule(item), _history("V", []),
            current_odometer_km=84000,
            current_date=TODAY,
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.OVERDUE
        assert s.overdue_by_km == 84000 - 12000   # 72,000 km overdue
        assert s.action == "Replace"

    def test_overdue_by_time(self):
        item = _item(id="brake", interval_replace_km=48000, interval_replace_months=30)
        statuses = compute_status(
            _schedule(item), _history("V", []),
            current_odometer_km=40000,           # km not yet due
            current_date=TODAY,
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        # km: 40000 < 48000 -> not overdue by km
        # time: manufacture 2007-04 + 30 months = 2009-10 -> overdue by time
        assert s.status == MaintenanceStatus.OVERDUE
        assert s.overdue_reason == "time"
        assert s.remaining_km is not None and s.remaining_km > 0

    def test_unknown_without_manufacture_date(self):
        item = _item(id="oil", interval_replace_km=12000)
        statuses = compute_status(
            _schedule(item), _history("V", []),
            current_odometer_km=84000,
            current_date=TODAY,
            manufacture_date=None,
        )
        assert statuses[0].status == MaintenanceStatus.UNKNOWN

    def test_unknown_no_intervals(self):
        item = _item(id="misc")  # no intervals defined
        statuses = compute_status(
            _schedule(item), _history("V", []),
            current_odometer_km=84000,
            current_date=TODAY,
            manufacture_date=MANUFACTURE,
        )
        assert statuses[0].status == MaintenanceStatus.UNKNOWN


# ── With service history ───────────────────────────────────────────────────────

class TestWithHistory:
    def test_ok_after_recent_service(self):
        item = _item(id="oil", interval_replace_km=12000, interval_replace_months=12)
        event = _event("oil", km=80000, event_date=date(2026, 1, 1))
        statuses = compute_status(
            _schedule(item),
            _history("V", [event]),
            current_odometer_km=84000,
            current_date=date(2026, 5, 31),
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.OK
        assert s.next_due_km == 80000 + 12000  # 92,000
        assert s.remaining_km == 92000 - 84000  # 8,000

    def test_due_soon_by_km(self):
        item = _item(id="oil", interval_replace_km=12000)
        event = _event("oil", km=80000, event_date=date(2025, 6, 1))
        statuses = compute_status(
            _schedule(item),
            _history("V", [event]),
            current_odometer_km=91500,          # 500 km from due
            current_date=date(2026, 5, 31),
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.DUE_SOON
        assert s.remaining_km == 500

    def test_due_soon_by_time(self):
        # 3-month interval, last done 2.5 months ago -> 2 weeks remaining (< 60 days)
        item = _item(id="brake", interval_replace_months=3)
        event = _event("brake", km=50000, event_date=date(2026, 3, 31))
        statuses = compute_status(
            _schedule(item),
            _history("V", [event]),
            current_odometer_km=55000,
            current_date=date(2026, 5, 31),  # next due 2026-06-30 -> 30 days left
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.DUE_SOON
        assert s.remaining_days is not None and s.remaining_days <= 60

    def test_overdue_reason_km_only(self):
        """Item with only a km interval should report overdue_reason='km', not 'both'."""
        item = _item(id="oil", interval_replace_km=12000)  # no month interval
        event = _event("oil", km=50000, event_date=date(2024, 1, 1))
        statuses = compute_status(
            _schedule(item),
            _history("V", [event]),
            current_odometer_km=70000,  # 70000 > 50000 + 12000 = 62000
            current_date=date(2024, 6, 1),
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.OVERDUE
        assert s.overdue_reason == "km"
        assert s.overdue_by_km == 8000

    def test_overdue_reason_time_only(self):
        """Item overdue by time but not km should report overdue_reason='time'."""
        item = _item(id="brake", interval_replace_km=48000, interval_replace_months=6)
        event = _event("brake", km=50000, event_date=date(2023, 1, 1))
        statuses = compute_status(
            _schedule(item),
            _history("V", [event]),
            current_odometer_km=52000,  # 52000 < 50000+48000 — not overdue by km
            current_date=date(2024, 1, 15),  # 12+ months later — overdue by time (6-month interval)
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.OVERDUE
        assert s.overdue_reason == "time"
        assert s.remaining_km is not None and s.remaining_km > 0  # km still has margin

    def test_overdue_by_both(self):
        item = _item(id="brake", interval_replace_km=48000, interval_replace_months=30)
        event = _event("brake", km=20000, event_date=date(2020, 1, 1))
        statuses = compute_status(
            _schedule(item),
            _history("V", [event]),
            current_odometer_km=84000,
            current_date=TODAY,
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.status == MaintenanceStatus.OVERDUE
        assert s.overdue_reason == "both"
        assert s.overdue_by_km == 84000 - (20000 + 48000)   # 16,000 km over
        assert s.overdue_by_days is not None and s.overdue_by_days > 0

    def test_most_recent_event_used(self):
        """When multiple history entries exist, the most recent by odometer is used."""
        item = _item(id="oil", interval_replace_km=12000)
        events = [
            _event("oil", km=60000, event_date=date(2023, 1, 1)),
            _event("oil", km=72000, event_date=date(2024, 1, 1)),  # most recent
        ]
        statuses = compute_status(
            _schedule(item),
            _history("V", events),
            current_odometer_km=80000,
            current_date=date(2024, 6, 1),
            manufacture_date=MANUFACTURE,
        )
        s = statuses[0]
        assert s.last_event is not None
        assert s.last_event.odometer_km == 72000
        assert s.next_due_km == 72000 + 12000  # 84,000


# ── Action field ───────────────────────────────────────────────────────────────

class TestAction:
    def test_replace_action(self):
        item = _item(id="oil", interval_replace_km=12000, interval_replace_months=12)
        s = compute_status(
            _schedule(item), _history("V", []),
            84000, TODAY, MANUFACTURE,
        )[0]
        assert s.action == "Replace"

    def test_inspect_action(self):
        item = _item(id="tires", interval_inspect_km=12000, interval_inspect_months=12)
        s = compute_status(
            _schedule(item), _history("V", []),
            84000, TODAY, MANUFACTURE,
        )[0]
        assert s.action == "Inspect"

    def test_inspect_only_ok(self):
        item = _item(id="tires", interval_inspect_km=12000, interval_inspect_months=12)
        event = _event("tires", km=80000, event_date=date(2026, 1, 1))
        s = compute_status(
            _schedule(item), _history("V", [event]),
            84000, date(2026, 5, 31), MANUFACTURE,
        )[0]
        assert s.status == MaintenanceStatus.OK
        assert s.action == "Inspect"

    def test_inspect_only_due_soon_by_km(self):
        item = _item(id="tires", interval_inspect_km=12000)
        event = _event("tires", km=80000, event_date=date(2025, 1, 1))
        s = compute_status(
            _schedule(item), _history("V", [event]),
            current_odometer_km=91000,  # 1,000 km before due at 92,000
            current_date=TODAY,
            manufacture_date=MANUFACTURE,
        )[0]
        assert s.status == MaintenanceStatus.DUE_SOON
        assert s.action == "Inspect"
        assert s.remaining_km == 1000

    def test_replace_takes_precedence_when_both_defined(self):
        item = _item(
            id="filter",
            interval_inspect_km=24000,
            interval_replace_km=48000,
        )
        s = compute_status(
            _schedule(item), _history("V", []),
            84000, TODAY, MANUFACTURE,
        )[0]
        assert s.action == "Replace"


# ── Multiple items ─────────────────────────────────────────────────────────────

class TestMultipleItems:
    def test_each_item_computed_independently(self):
        items = [
            _item(id="oil",   interval_replace_km=12000),
            _item(id="plugs", interval_replace_km=72000),
        ]
        oil_event = _event("oil", km=80000, event_date=date(2025, 6, 1))
        statuses = compute_status(
            _schedule(*items),
            _history("V", [oil_event]),
            current_odometer_km=84000,
            current_date=TODAY,
            manufacture_date=MANUFACTURE,
        )
        assert len(statuses) == 2
        oil_s   = next(s for s in statuses if s.item.id == "oil")
        plugs_s = next(s for s in statuses if s.item.id == "plugs")
        assert oil_s.status   == MaintenanceStatus.OK       # recent service
        assert plugs_s.status == MaintenanceStatus.OVERDUE  # no history, from manufacture
