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


# ─── Static files (last — catch-all) ──────────────────────────────────────────

api.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
