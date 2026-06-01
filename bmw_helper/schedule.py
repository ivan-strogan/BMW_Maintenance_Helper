import calendar
from datetime import date as date_type

from .models import (
    MaintenanceSchedule,
    MaintenanceStatus,
    ScheduleItemStatus,
    ServiceEvent,
    ServiceHistory,
)

DUE_SOON_THRESHOLD_KM = 5000
DUE_SOON_THRESHOLD_DAYS = 60  # ~2 months


def _add_months(dt: date_type, months: int) -> date_type:
    total_months = dt.month - 1 + months
    year = dt.year + total_months // 12
    month = total_months % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def compute_status(
    schedule: MaintenanceSchedule,
    history: ServiceHistory,
    current_odometer_km: int,
    current_date: date_type | None = None,
    manufacture_date: date_type | None = None,
) -> list[ScheduleItemStatus]:
    if current_date is None:
        current_date = date_type.today()

    history_by_item: dict[str, list[ServiceEvent]] = {}
    for event in history.history:
        history_by_item.setdefault(event.item_id, []).append(event)
    for events in history_by_item.values():
        events.sort(key=lambda e: e.odometer_km, reverse=True)

    results: list[ScheduleItemStatus] = []

    for item in schedule.items:
        events = history_by_item.get(item.id, [])
        last_event = events[0] if events else None

        km_interval    = item.interval_replace_km    or item.interval_inspect_km
        month_interval = item.interval_replace_months or item.interval_inspect_months

        # No intervals defined → nothing to compute
        if km_interval is None and month_interval is None:
            results.append(ScheduleItemStatus(
                item=item,
                last_event=last_event,
                status=MaintenanceStatus.UNKNOWN,
            ))
            continue

        # Baseline: use last recorded service, or fall back to manufacture (0 km, manufacture_date).
        # No history + no manufacture date → UNKNOWN.
        if last_event is None:
            if manufacture_date is None:
                results.append(ScheduleItemStatus(
                    item=item,
                    last_event=None,
                    status=MaintenanceStatus.UNKNOWN,
                ))
                continue
            baseline_km   = 0
            baseline_date = manufacture_date
        else:
            baseline_km   = last_event.odometer_km
            baseline_date = last_event.date

        # ── km dimension ──────────────────────────────────────────────────
        km_overdue: int | None  = None
        km_remaining: int | None = None
        next_due_km: int | None  = None

        if km_interval is not None:
            next_due_km = baseline_km + km_interval
            delta = current_odometer_km - next_due_km
            if delta >= 0:
                km_overdue = delta
            else:
                km_remaining = -delta

        # ── time dimension ────────────────────────────────────────────────
        time_overdue: int | None  = None
        time_remaining: int | None = None
        next_due_date: date_type | None = None

        if month_interval is not None:
            next_due_date = _add_months(baseline_date, month_interval)
            day_delta = (current_date - next_due_date).days
            if day_delta >= 0:
                time_overdue = day_delta
            else:
                time_remaining = -day_delta

        # ── overall status (worst of both dimensions) ──────────────────────
        km_over   = km_overdue   is not None and km_overdue   > 0
        time_over = time_overdue is not None and time_overdue > 0
        km_soon   = km_remaining   is not None and km_remaining   <= DUE_SOON_THRESHOLD_KM
        time_soon = time_remaining is not None and time_remaining <= DUE_SOON_THRESHOLD_DAYS

        if km_over and time_over:
            status, reason = MaintenanceStatus.OVERDUE, "both"
        elif km_over:
            status, reason = MaintenanceStatus.OVERDUE, "km"
        elif time_over:
            status, reason = MaintenanceStatus.OVERDUE, "time"
        elif km_soon or time_soon:
            status, reason = MaintenanceStatus.DUE_SOON, None
        else:
            status, reason = MaintenanceStatus.OK, None

        results.append(ScheduleItemStatus(
            item=item,
            last_event=last_event,
            next_due_km=next_due_km,
            overdue_by_km=km_overdue,
            remaining_km=km_remaining,
            next_due_date=next_due_date,
            overdue_by_days=time_overdue,
            remaining_days=time_remaining,
            status=status,
            overdue_reason=reason,
        ))

    return results
