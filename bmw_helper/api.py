from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import load_app_config, load_schedule, load_service_history, save_service_history
from .models import ServiceEvent
from .schedule import compute_status

api = FastAPI(title="BMW Maintenance Helper", version="0.1.0")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ─── Frontend ─────────────────────────────────────────────────────────────────

@api.get("/", include_in_schema=False)
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")


# ─── Config ───────────────────────────────────────────────────────────────────

@api.get("/api/config")
async def get_config():
    cfg = load_app_config()
    return cfg.model_dump()


@api.patch("/api/vehicle/odometer")
async def update_odometer(odometer_km: int):
    from ruamel.yaml import YAML
    from .config import CONFIG_DIR

    path = CONFIG_DIR / "vehicle.yaml"
    y = YAML()
    y.preserve_quotes = True
    with open(path) as f:
        data = y.load(f)
    data["vehicle"]["odometer_km"] = odometer_km
    with open(path, "w") as f:
        y.dump(data, f)
    return {"odometer_km": odometer_km}


# ─── Schedule ─────────────────────────────────────────────────────────────────

@api.get("/api/schedule")
async def get_schedule():
    schedule = load_schedule()
    return schedule.model_dump()


@api.get("/api/schedule/status")
async def get_schedule_status():
    cfg = load_app_config()
    schedule = load_schedule()
    history = load_service_history(cfg.vehicle.vin)
    statuses = compute_status(
        schedule, history,
        cfg.vehicle.odometer_km,
        manufacture_date=cfg.vehicle.manufacture_date,
    )
    return [s.model_dump(mode="json") for s in statuses]


# ─── History ──────────────────────────────────────────────────────────────────

@api.get("/api/history")
async def get_history():
    cfg = load_app_config()
    history = load_service_history(cfg.vehicle.vin)
    return history.model_dump(mode="json")


@api.post("/api/history", status_code=201)
async def record_history(event: ServiceEvent):
    cfg = load_app_config()
    history = load_service_history(cfg.vehicle.vin)
    history.history.append(event)
    save_service_history(history)
    return event.model_dump(mode="json")


@api.delete("/api/history/{event_id}")
async def delete_history_event(event_id: str):
    cfg = load_app_config()
    history = load_service_history(cfg.vehicle.vin)
    before = len(history.history)
    history.history = [e for e in history.history if e.id != event_id]
    if len(history.history) == before:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    save_service_history(history)
    return {"deleted": event_id}


# ─── Catalog ──────────────────────────────────────────────────────────────────

@api.get("/api/catalog/groups")
async def catalog_groups():
    from .realoem import get_client
    cfg = load_app_config()
    client = get_client()
    catalog_id = cfg.vehicle.catalog_id or client.resolve_catalog_id(cfg.vehicle.vin)
    return {"catalog_id": catalog_id, "groups": client.get_groups(catalog_id)}


@api.get("/api/catalog/subgroups")
async def catalog_subgroups(hg: str, catalog_id: str | None = None):
    from .realoem import get_client
    cfg = load_app_config()
    client = get_client()
    cat_id = catalog_id or cfg.vehicle.catalog_id or client.resolve_catalog_id(cfg.vehicle.vin)
    return {"catalog_id": cat_id, "hg": hg, "subgroups": client.get_subgroups(cat_id, hg)}


@api.get("/api/catalog/parts")
async def catalog_parts(mospid: str, hg: str, fg: str, catalog_id: str | None = None):
    from .realoem import get_client
    cfg = load_app_config()
    client = get_client()
    cat_id = catalog_id or cfg.vehicle.catalog_id or client.resolve_catalog_id(cfg.vehicle.vin)
    parts = client.get_parts(cat_id, mospid=mospid, hg=hg, fg=fg)
    return {"catalog_id": cat_id, "parts": [p.model_dump() for p in parts]}


@api.get("/api/catalog/hint")
async def catalog_by_hint(hint: str, catalog_id: str | None = None):
    """Return sub-groups matching a schedule catalog_hint string."""
    from .realoem import get_client
    cfg = load_app_config()
    client = get_client()
    cat_id = catalog_id or cfg.vehicle.catalog_id or client.resolve_catalog_id(cfg.vehicle.vin)
    matches = client.find_by_hint(cat_id, hint)
    return {"catalog_id": cat_id, "hint": hint, "matches": matches}


# ─── RockAuto ─────────────────────────────────────────────────────────────────

@api.get("/api/rockauto/hint")
async def rockauto_by_hint(hint: str):
    """Find aftermarket alternatives using a schedule catalog_hint string."""
    from .rockauto import RockAutoClient
    cfg = load_app_config()
    client = RockAutoClient(cfg.vehicle)
    parts = await client.search_by_hint(hint)
    return {"hint": hint, "count": len(parts), "parts": [p.model_dump() for p in parts]}


@api.get("/api/rockauto/category")
async def rockauto_by_category(category: str):
    """Find aftermarket alternatives for a given RockAuto category name."""
    from .rockauto import RockAutoClient
    cfg = load_app_config()
    client = RockAutoClient(cfg.vehicle)
    parts = await client.search_by_category(category)
    return {"category": category, "count": len(parts), "parts": [p.model_dump() for p in parts]}


@api.get("/api/rockauto/oem")
async def rockauto_by_oem(pn: str):
    """Find aftermarket alternatives that cross-reference to an OEM part number."""
    from .rockauto import RockAutoClient
    cfg = load_app_config()
    client = RockAutoClient(cfg.vehicle)
    parts = await client.search_by_oem(pn)
    return {"oem_pn": pn, "count": len(parts), "parts": [p.model_dump() for p in parts]}


# ─── Service Plans ────────────────────────────────────────────────────────────

from pydantic import BaseModel as _PBM

class _NewPlan(_PBM):
    name: str

class _AddPart(_PBM):
    oem_pn: str
    description: str = ""
    qty: int = 1
    preferred_brand: str | None = None
    notes: str | None = None
    customer_supplied: bool = False
    job_id: str | None = None

class _NewJob(_PBM):
    name: str
    labour_notes: str | None = None
    overlaps_with: list[str] = []
    customer_supplied_labour: bool = False
    no_warranty: bool = False
    special_instructions: str | None = None

class _UpdateJob(_PBM):
    name: str | None = None
    labour_notes: str | None = None
    overlaps_with: list[str] | None = None
    customer_supplied_labour: bool | None = None
    no_warranty: bool | None = None
    special_instructions: str | None = None

class _AssignPart(_PBM):
    oem_pn: str
    job_id: str


@api.get("/api/plans")
async def list_plans_endpoint():
    from .plan import list_plans
    return [p.model_dump(mode="json") for p in list_plans()]


@api.post("/api/plans", status_code=201)
async def create_plan_endpoint(body: _NewPlan):
    from .plan import create_plan
    cfg = load_app_config()
    plan = create_plan(body.name, cfg.vehicle.vin)
    return plan.model_dump(mode="json")


@api.get("/api/plans/{plan_id}")
async def get_plan_endpoint(plan_id: str):
    from .plan import load_plan
    try:
        return load_plan(plan_id).model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")


@api.delete("/api/plans/{plan_id}")
async def delete_plan_endpoint(plan_id: str):
    from .plan import delete_plan
    try:
        delete_plan(plan_id)
        return {"deleted": plan_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")


@api.post("/api/plans/{plan_id}/parts", status_code=201)
async def add_part_endpoint(plan_id: str, body: _AddPart):
    from .plan import add_part
    try:
        plan = add_part(plan_id, **body.model_dump())
        return plan.model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@api.delete("/api/plans/{plan_id}/parts/{oem_pn}")
async def remove_part_endpoint(plan_id: str, oem_pn: str):
    from .plan import remove_part
    try:
        plan = remove_part(plan_id, oem_pn)
        return plan.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")


@api.post("/api/plans/{plan_id}/jobs", status_code=201)
async def add_job_endpoint(plan_id: str, body: _NewJob):
    from .plan import add_job
    try:
        plan = add_job(plan_id, **body.model_dump())
        return plan.model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")


@api.patch("/api/plans/{plan_id}/jobs/{job_id}")
async def update_job_endpoint(plan_id: str, job_id: str, body: _UpdateJob):
    from .plan import update_job
    try:
        plan = update_job(plan_id, job_id, **body.model_dump(exclude_none=True))
        return plan.model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@api.post("/api/plans/{plan_id}/assign")
async def assign_part_endpoint(plan_id: str, body: _AssignPart):
    from .plan import assign_part_to_job
    try:
        plan = assign_part_to_job(plan_id, body.oem_pn, body.job_id)
        return plan.model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ─── Email Generator ──────────────────────────────────────────────────────────

class _EmailRequest(_PBM):
    plan_id: str
    job_ids: list[str] | None = None


@api.post("/api/email/generate")
async def generate_email(body: _EmailRequest):
    from .email_generator import render_email_for_plan_id
    try:
        text = render_email_for_plan_id(body.plan_id, job_ids=body.job_ids)
        return {"plan_id": body.plan_id, "email": text}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plan '{body.plan_id}' not found")


# ─── AI / Chat ────────────────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel

class ChatRequest(_BaseModel):
    message: str
    history: list[dict] = []


@api.post("/api/ai/chat")
async def ai_chat(req: ChatRequest):
    from .ai import get_ai_client
    client = get_ai_client()
    result = client.chat(req.message, req.history)
    return result


@api.get("/api/ai/status")
async def ai_status():
    """Check whether Ollama is reachable and qwen3:8b is available."""
    try:
        from .ai import check_ollama
        check_ollama()
        return {"ok": True, "model": "qwen3:8b"}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}


# ─── Static files (last — catch-all) ──────────────────────────────────────────

api.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
