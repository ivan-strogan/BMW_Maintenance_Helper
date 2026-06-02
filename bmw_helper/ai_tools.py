"""Tool implementations for the BMW Maintenance Helper LLM agent.

Each function is a thin wrapper over existing app functions. The TOOLS list
contains the Ollama-compatible JSON schema for every tool.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import load_app_config, load_schedule, load_service_history
from .schedule import compute_status


# ── Tool schemas (Ollama tool-use format) ─────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_vehicle_info",
            "description": "Return the vehicle configuration: VIN, year, make, model, engine, transmission, odometer.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schedule_status",
            "description": "Return the current maintenance schedule status for all items, including overdue/due-soon/ok status, next due km and date.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_history",
            "description": "Return past service events, optionally filtered to a specific maintenance item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Optional schedule item ID to filter by (e.g. 'oil_filter', 'brake_fluid'). Omit to get all history.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": "Search the RealOEM parts catalog for a given natural-language query or catalog hint (e.g. 'Engine > Oil Filter'). Returns matching catalog groups.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hint": {
                        "type": "string",
                        "description": "Catalog hint string or natural language part description.",
                    }
                },
                "required": ["hint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rockauto_alternatives",
            "description": "Find aftermarket part alternatives on RockAuto for a given OEM part number or catalog hint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "oem_pn": {
                        "type": "string",
                        "description": "11-digit OEM part number (e.g. '11427541827'). Provide this OR hint, not both.",
                    },
                    "hint": {
                        "type": "string",
                        "description": "Catalog hint like 'Engine > Oil Filter'. Used when no OEM PN is known.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overdue_items",
            "description": "Return only the maintenance items that are currently overdue or due soon, sorted by urgency.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────────

def get_vehicle_info() -> dict:
    cfg = load_app_config()
    v = cfg.vehicle
    return {
        "vin": v.vin,
        "year": v.year,
        "make": v.make,
        "model": v.model,
        "body": v.body,
        "engine_code": v.engine_code,
        "engine_desc": v.engine_desc,
        "transmission_code": v.transmission_code,
        "transmission_desc": v.transmission_desc,
        "drive": v.drive,
        "odometer_km": v.odometer_km,
        "manufacture_date": v.manufacture_date.isoformat() if v.manufacture_date else None,
    }


def get_schedule_status() -> list[dict]:
    cfg = load_app_config()
    schedule = load_schedule()
    history = load_service_history(cfg.vehicle.vin)
    statuses = compute_status(
        schedule, history,
        cfg.vehicle.odometer_km,
        manufacture_date=cfg.vehicle.manufacture_date,
    )
    return [
        {
            "id": s.item.id,
            "name": s.item.name,
            "status": s.status.value,
            "action": s.action,
            "next_due_km": s.next_due_km,
            "remaining_km": s.remaining_km,
            "overdue_by_km": s.overdue_by_km,
            "next_due_date": s.next_due_date.isoformat() if s.next_due_date else None,
            "remaining_days": s.remaining_days,
            "overdue_by_days": s.overdue_by_days,
            "overdue_reason": s.overdue_reason,
            "last_service_km": s.last_event.odometer_km if s.last_event else None,
            "last_service_date": s.last_event.date.isoformat() if s.last_event else None,
        }
        for s in statuses
    ]


def get_service_history(item_id: str | None = None) -> list[dict]:
    cfg = load_app_config()
    history = load_service_history(cfg.vehicle.vin)
    events = history.history
    if item_id:
        events = [e for e in events if e.item_id == item_id]
    return [
        {
            "id": e.id,
            "item_id": e.item_id,
            "date": e.date.isoformat(),
            "odometer_km": e.odometer_km,
            "performed_by": e.performed_by,
            "parts": e.parts,
            "notes": e.notes,
        }
        for e in sorted(events, key=lambda e: e.odometer_km, reverse=True)
    ]


def get_overdue_items() -> list[dict]:
    items = get_schedule_status()
    priority = {"overdue": 0, "due_soon": 1}
    urgent = [i for i in items if i["status"] in priority]
    urgent.sort(key=lambda i: (priority[i["status"]], -(i["overdue_by_km"] or 0)))
    return urgent


def search_catalog(hint: str) -> dict:
    """Synchronous wrapper — catalog search returns groups, not parts."""
    cfg = load_app_config()
    from .realoem import RealOEMClient
    client = RealOEMClient()
    try:
        catalog_id = cfg.vehicle.catalog_id or client.resolve_catalog_id(cfg.vehicle.vin)
        matches = client.find_by_hint(catalog_id, hint)
        return {"catalog_id": catalog_id, "hint": hint, "matches": matches}
    except Exception as exc:
        return {"error": str(exc), "hint": hint, "matches": []}


def get_rockauto_alternatives(oem_pn: str | None = None, hint: str | None = None) -> list[dict]:
    """Synchronous wrapper for the async RockAuto client."""
    import asyncio
    from .rockauto import RockAutoClient

    cfg = load_app_config()
    client = RockAutoClient(cfg.vehicle)

    async def _fetch():
        if oem_pn:
            return await client.search_by_oem(oem_pn)
        if hint:
            return await client.search_by_hint(hint)
        return []

    try:
        parts = asyncio.run(_fetch())
    except Exception as exc:
        return [{"error": str(exc)}]

    return [p.model_dump() for p in parts]


# ── Dispatcher ────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Any] = {
    "get_vehicle_info": lambda **_: get_vehicle_info(),
    "get_schedule_status": lambda **_: get_schedule_status(),
    "get_service_history": lambda item_id=None, **_: get_service_history(item_id),
    "get_overdue_items": lambda **_: get_overdue_items(),
    "search_catalog": lambda hint="", **_: search_catalog(hint),
    "get_rockauto_alternatives": lambda oem_pn=None, hint=None, **_: get_rockauto_alternatives(oem_pn, hint),
}


def dispatch(tool_name: str, args: dict) -> Any:
    """Execute a tool by name with the given arguments."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(**args)
    except Exception as exc:
        return {"error": str(exc)}
