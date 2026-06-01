from pathlib import Path

from ruamel.yaml import YAML

from .models import AppConfig, MaintenanceSchedule, ServiceHistory

CONFIG_DIR = Path(__file__).parent.parent / "config"
_yaml = YAML()


def load_app_config() -> AppConfig:
    path = CONFIG_DIR / "vehicle.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Vehicle config not found: {path}\nRun: cp config/vehicle.yaml.example config/vehicle.yaml")
    with open(path) as f:
        data = _yaml.load(f)
    return AppConfig.model_validate(data)


def load_schedule() -> MaintenanceSchedule:
    path = CONFIG_DIR / "schedule.yaml"
    if not path.exists():
        return MaintenanceSchedule()
    with open(path) as f:
        data = _yaml.load(f)
    return MaintenanceSchedule.model_validate(data or {})


def load_service_history(vin: str) -> ServiceHistory:
    path = CONFIG_DIR / "service_history.yaml"
    if not path.exists():
        return ServiceHistory(vehicle_vin=vin)
    with open(path) as f:
        data = _yaml.load(f)
    if not data:
        return ServiceHistory(vehicle_vin=vin)
    return ServiceHistory.model_validate(data)


def save_service_history(history: ServiceHistory) -> None:
    path = CONFIG_DIR / "service_history.yaml"
    with open(path, "w") as f:
        _yaml.dump(history.model_dump(mode="json"), f)
