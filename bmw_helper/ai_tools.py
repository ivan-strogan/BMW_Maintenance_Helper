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
            "description": (
                "Search the RealOEM parts catalog for OEM parts. "
                "Use 'Group > Subgroup' format for best results, e.g. 'Brakes > Front Brake Pads', "
                "'Engine > Oil Filter', 'Radiator > Cooling System Water Hoses'. "
                "The group name should match a RealOEM top-level group (ENGINE, BRAKES, RADIATOR, etc.). "
                "Returns matching diagram sub-groups with diag_id values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hint": {
                        "type": "string",
                        "description": "Hint in 'Group > Subgroup' format, e.g. 'Brakes > Front Brake Pads'. Use the RealOEM group name as the first segment.",
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
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": "List all existing service plans by name and ID. Call this before creating a plan to check if one already exists.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Create a new service plan with a given name. Returns the plan_id needed for add_parts_to_plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "A short descriptive name for the plan, e.g. 'Front Brake Service' or 'Oil Change Spring 2026'.",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_parts_to_plan",
            "description": (
                "Add one or more OEM parts to a service plan. "
                "Call search_catalog first to find the diag_id, then fetch the parts list. "
                "Each part needs oem_pn and description at minimum. "
                "Always add parts from the same diagram in a single call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "The plan ID returned by create_plan or list_plans.",
                    },
                    "parts": {
                        "type": "array",
                        "description": "List of parts to add.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "oem_pn":      {"type": "string", "description": "11-digit OEM part number."},
                                "description": {"type": "string", "description": "Part description."},
                                "qty":         {"type": "integer", "description": "Quantity needed.", "default": 1},
                                "diagram_ref": {"type": "string", "description": "Position number in the diagram (e.g. '01')."},
                                "diag_id":     {"type": "string", "description": "Diagram ID (e.g. '34_0123') from search_catalog."},
                            },
                            "required": ["oem_pn", "description"],
                        },
                    },
                },
                "required": ["plan_id", "parts"],
            },
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
    """Return RockAuto aftermarket alternatives by OEM PN or catalog hint."""
    import asyncio
    from .rockauto import RockAutoClient

    cfg = load_app_config()
    client = RockAutoClient(cfg.vehicle)

    try:
        if oem_pn:
            # sync scraper — no event loop needed
            parts = client.search_by_oem(oem_pn)
        elif hint:
            parts = asyncio.run(client.search_by_hint(hint))
        else:
            parts = []
    except Exception as exc:
        return [{"error": str(exc)}]

    return [p.model_dump() for p in parts]


def list_plans() -> list[dict]:
    from .plan import list_plans as _list_plans
    plans = _list_plans()
    return [{"id": p.id, "name": p.name, "parts": len(p.ungrouped_parts), "jobs": len(p.jobs)} for p in plans]


def create_plan(name: str) -> dict:
    from .plan import create_plan as _create_plan
    cfg = load_app_config()
    plan = _create_plan(name, cfg.vehicle.vin)
    return {"plan_id": plan.id, "name": plan.name, "message": f"Plan '{name}' created successfully."}


def add_parts_to_plan(plan_id: str, parts: list[dict]) -> dict:
    from .plan import add_part
    from .realoem import get_client

    cfg = load_app_config()
    added = []
    errors = []

    for p in parts:
        oem_pn = p.get("oem_pn", "").strip()
        if not oem_pn:
            continue

        # Resolve diagram_url from diag_id if provided
        diagram_url = None
        diag_id = p.get("diag_id")
        if diag_id:
            try:
                client = get_client()
                cat_id = cfg.vehicle.catalog_id or client.resolve_catalog_id(cfg.vehicle.vin)
                fetched_parts, diagram_url = client.get_parts(cat_id, diag_id)
                # Fill in diagram_url on individual part if not already set
            except Exception:
                pass

        try:
            add_part(
                plan_id,
                oem_pn=oem_pn,
                description=p.get("description", ""),
                qty=int(p.get("qty", 1)),
                diagram_ref=p.get("diagram_ref"),
                catalog_path=[diag_id] if diag_id else [],
                diagram_url=diagram_url,
            )
            added.append(oem_pn)
        except Exception as exc:
            errors.append(f"{oem_pn}: {exc}")

    return {
        "plan_id": plan_id,
        "added": added,
        "errors": errors,
        "message": f"Added {len(added)} part(s) to plan." + (f" Errors: {errors}" if errors else ""),
    }


# ── Dispatcher ────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Any] = {
    "get_vehicle_info": lambda **_: get_vehicle_info(),
    "get_schedule_status": lambda **_: get_schedule_status(),
    "get_service_history": lambda item_id=None, **_: get_service_history(item_id),
    "get_overdue_items": lambda **_: get_overdue_items(),
    "search_catalog": lambda hint="", **_: search_catalog(hint),
    "get_rockauto_alternatives": lambda oem_pn=None, hint=None, **_: get_rockauto_alternatives(oem_pn, hint),
    "list_plans": lambda **_: list_plans(),
    "create_plan": lambda name="", **_: create_plan(name),
    "add_parts_to_plan": lambda plan_id="", parts=None, **_: add_parts_to_plan(plan_id, parts or []),
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
