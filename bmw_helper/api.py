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


# ─── Static files (last — catch-all) ──────────────────────────────────────────

api.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
