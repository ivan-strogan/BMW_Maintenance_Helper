from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─── Vehicle / Config ────────────────────────────────────────────────────────

class OwnerConfig(BaseModel):
    name: str
    email: Optional[str] = None


class VehicleConfig(BaseModel):
    vin: str
    year: int
    make: str
    model: str
    body: str
    manufacture_date: Optional[date] = None
    engine_code: str
    engine_desc: str
    transmission_code: str
    transmission_desc: str
    drive: str
    odometer_km: int


class Preferences(BaseModel):
    currency: str = "CAD"
    tax_name: str = "GST"
    tax_rate: float = 0.05
    preferred_brands: list[str] = Field(default_factory=list)
    oem_only_systems: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    owner: OwnerConfig
    vehicle: VehicleConfig
    preferences: Preferences = Field(default_factory=Preferences)


# ─── Maintenance Schedule ─────────────────────────────────────────────────────

class ScheduleItem(BaseModel):
    id: str
    name: str
    interval_inspect_km: Optional[int] = None
    interval_replace_km: Optional[int] = None
    interval_inspect_months: Optional[int] = None
    interval_replace_months: Optional[int] = None
    bmw_recommendation_km: Optional[int] = None
    bmw_recommendation_months: Optional[int] = None
    notes: Optional[str] = None
    catalog_hint: Optional[str] = None


class MaintenanceSchedule(BaseModel):
    source: str = ""
    engine: str = ""
    unit: str = "km"
    version: str = ""
    items: list[ScheduleItem] = Field(default_factory=list)


# ─── Service History ──────────────────────────────────────────────────────────

class ServiceEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    item_id: str
    date: date
    odometer_km: int
    performed_by: Optional[str] = None   # "Self" or shop name
    parts: list[str] = Field(default_factory=list)  # e.g. ["11127565286 Elring", "07119963182"]
    notes: Optional[str] = None


class ServiceHistory(BaseModel):
    vehicle_vin: str
    history: list[ServiceEvent] = Field(default_factory=list)


# ─── Schedule Status ──────────────────────────────────────────────────────────

class MaintenanceStatus(str, Enum):
    OVERDUE = "overdue"
    DUE_SOON = "due_soon"
    OK = "ok"
    UNKNOWN = "unknown"


class ScheduleItemStatus(BaseModel):
    item: ScheduleItem
    last_event: Optional[ServiceEvent] = None
    # km dimension
    next_due_km: Optional[int] = None
    overdue_by_km: Optional[int] = None
    remaining_km: Optional[int] = None
    # time dimension
    next_due_date: Optional[date] = None
    overdue_by_days: Optional[int] = None
    remaining_days: Optional[int] = None
    # overall
    status: MaintenanceStatus
    overdue_reason: Optional[str] = None  # "km", "time", or "both"


# ─── Parts / Catalog ──────────────────────────────────────────────────────────

class CatalogPart(BaseModel):
    oem_pn: str
    description: str
    qty_required: int = 1
    realoem_price: Optional[float] = None
    superseded_by: Optional[str] = None
    diagram_ref: Optional[str] = None
    catalog_path: list[str] = Field(default_factory=list)


class DiagramHotspot(BaseModel):
    ref_no: int
    oem_pn: str
    x: int
    y: int
    radius: int = 12


class DiagramGroup(BaseModel):
    group_code: str
    title: str
    image_url: str
    parts: list[CatalogPart] = Field(default_factory=list)
    hotspots: list[DiagramHotspot] = Field(default_factory=list)


class RockAutoAlternative(BaseModel):
    brand: str
    part_number: str
    oem_interchange: list[str] = Field(default_factory=list)
    price: float
    currency: str = "CAD"
    availability: str = ""
    url: str = ""
    notes: Optional[str] = None


class SelectedPart(BaseModel):
    catalog_part: CatalogPart
    rockauto_alternatives: list[RockAutoAlternative] = Field(default_factory=list)
    preferred_brand: Optional[str] = None
    notes: Optional[str] = None
    customer_supplied: bool = False


# ─── Service Plan ─────────────────────────────────────────────────────────────

class Job(BaseModel):
    id: str
    name: str
    parts: list[SelectedPart] = Field(default_factory=list)
    labour_notes: Optional[str] = None
    overlaps_with: list[str] = Field(default_factory=list)
    customer_supplied_labour: bool = False
    no_warranty: bool = False
    special_instructions: Optional[str] = None


class ServicePlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    created: datetime = Field(default_factory=datetime.now)
    vehicle_vin: str
    jobs: list[Job] = Field(default_factory=list)
    ungrouped_parts: list[SelectedPart] = Field(default_factory=list)
    notes: Optional[str] = None


# ─── Estimates ────────────────────────────────────────────────────────────────

class EstimateLineItem(BaseModel):
    activity: str  # "Repair", "Parts", "Media Package", etc.
    description: str
    oem_pns: list[str] = Field(default_factory=list)
    brand: Optional[str] = None
    tax: Optional[str] = None
    qty: float
    rate: float
    amount: float


class ShopEstimate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_file: str
    shop_name: str
    shop_address: Optional[str] = None
    shop_phone: Optional[str] = None
    shop_email: Optional[str] = None
    gst_number: Optional[str] = None
    estimate_number: str
    date: date
    vehicle_vin: Optional[str] = None
    line_items: list[EstimateLineItem] = Field(default_factory=list)
    subtotal: float
    tax_amount: float
    total: float
    status: str = "received"  # received, accepted, declined, expired
    valid_days: Optional[int] = None
    raw_notes: Optional[str] = None
