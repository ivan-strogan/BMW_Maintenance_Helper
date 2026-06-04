"""Service plan persistence and manipulation.

Plans are stored as JSON files in plans/<id>.json.
Each plan has a list of ungrouped parts and named jobs that group parts together.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import CatalogPart, Job, SelectedPart, ServicePlan

PLANS_DIR = Path(__file__).parent.parent / "plans"


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _plan_path(plan_id: str) -> Path:
    return PLANS_DIR / f"{plan_id}.json"


def save_plan(plan: ServicePlan) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    _plan_path(plan.id).write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )


def load_plan(plan_id: str) -> ServicePlan:
    path = _plan_path(plan_id)
    if not path.exists():
        raise FileNotFoundError(f"Plan '{plan_id}' not found")
    return ServicePlan.model_validate_json(path.read_text(encoding="utf-8"))


def list_plans() -> list[ServicePlan]:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plans = []
    for p in sorted(PLANS_DIR.glob("*.json")):
        try:
            plans.append(ServicePlan.model_validate_json(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return plans


def delete_plan(plan_id: str) -> None:
    path = _plan_path(plan_id)
    if not path.exists():
        raise FileNotFoundError(f"Plan '{plan_id}' not found")
    path.unlink()


# ── Plan creation ─────────────────────────────────────────────────────────────

def create_plan(name: str, vehicle_vin: str) -> ServicePlan:
    plan = ServicePlan(name=name, vehicle_vin=vehicle_vin)
    save_plan(plan)
    return plan


# ── Part management ───────────────────────────────────────────────────────────

def add_part(
    plan_id: str,
    oem_pn: str,
    description: str = "",
    qty: int = 1,
    preferred_brand: Optional[str] = None,
    notes: Optional[str] = None,
    customer_supplied: bool = False,
    job_id: Optional[str] = None,
    catalog_path: list[str] | None = None,
    diagram_url: Optional[str] = None,
    diagram_ref: Optional[str] = None,
) -> ServicePlan:
    plan = load_plan(plan_id)

    catalog_part = CatalogPart(
        oem_pn=oem_pn,
        description=description,
        qty_required=qty,
        catalog_path=catalog_path or [],
        diagram_url=diagram_url,
        diagram_ref=diagram_ref,
    )
    selected = SelectedPart(
        catalog_part=catalog_part,
        preferred_brand=preferred_brand,
        notes=notes,
        customer_supplied=customer_supplied,
    )

    if job_id:
        job = _find_job(plan, job_id)
        job.parts.append(selected)
    else:
        plan.ungrouped_parts.append(selected)

    save_plan(plan)
    return plan


def update_part_qty(plan_id: str, oem_pn: str, qty: int) -> ServicePlan:
    """Update the quantity of a part wherever it lives in the plan."""
    if qty < 1:
        raise ValueError("qty must be >= 1")
    plan = load_plan(plan_id)
    for sp in plan.ungrouped_parts:
        if sp.catalog_part.oem_pn == oem_pn:
            sp.catalog_part.qty_required = qty
            save_plan(plan)
            return plan
    for job in plan.jobs:
        for sp in job.parts:
            if sp.catalog_part.oem_pn == oem_pn:
                sp.catalog_part.qty_required = qty
                save_plan(plan)
                return plan
    raise ValueError(f"Part {oem_pn} not found in plan {plan_id}")


def remove_part(plan_id: str, oem_pn: str) -> ServicePlan:
    """Remove a part by OEM PN from ungrouped parts or any job."""
    plan = load_plan(plan_id)

    plan.ungrouped_parts = [
        p for p in plan.ungrouped_parts if p.catalog_part.oem_pn != oem_pn
    ]
    for job in plan.jobs:
        job.parts = [p for p in job.parts if p.catalog_part.oem_pn != oem_pn]

    save_plan(plan)
    return plan


# ── Job management ────────────────────────────────────────────────────────────

def rename_plan(plan_id: str, name: str) -> ServicePlan:
    """Rename a service plan."""
    name = name.strip()
    if not name:
        raise ValueError("Plan name cannot be empty")
    plan = load_plan(plan_id)
    plan.name = name
    save_plan(plan)
    return plan


def add_job(
    plan_id: str,
    name: str,
    labour_notes: Optional[str] = None,
    overlaps_with: Optional[list[str]] = None,
    customer_supplied_labour: bool = False,
    no_warranty: bool = False,
    special_instructions: Optional[str] = None,
) -> ServicePlan:
    plan = load_plan(plan_id)
    import uuid
    job = Job(
        id=str(uuid.uuid4())[:8],
        name=name,
        labour_notes=labour_notes,
        overlaps_with=overlaps_with or [],
        customer_supplied_labour=customer_supplied_labour,
        no_warranty=no_warranty,
        special_instructions=special_instructions,
    )
    plan.jobs.append(job)
    save_plan(plan)
    return plan


def update_job(
    plan_id: str,
    job_id: str,
    *,
    name: Optional[str] = None,
    labour_notes: Optional[str] = None,
    overlaps_with: Optional[list[str]] = None,
    customer_supplied_labour: Optional[bool] = None,
    no_warranty: Optional[bool] = None,
    special_instructions: Optional[str] = None,
) -> ServicePlan:
    plan = load_plan(plan_id)
    job = _find_job(plan, job_id)

    if name is not None:
        job.name = name
    if labour_notes is not None:
        job.labour_notes = labour_notes
    if overlaps_with is not None:
        job.overlaps_with = overlaps_with
    if customer_supplied_labour is not None:
        job.customer_supplied_labour = customer_supplied_labour
    if no_warranty is not None:
        job.no_warranty = no_warranty
    if special_instructions is not None:
        job.special_instructions = special_instructions

    save_plan(plan)
    return plan


def delete_job(plan_id: str, job_id: str) -> ServicePlan:
    """Delete a job, returning its parts to ungrouped."""
    plan = load_plan(plan_id)
    job = _find_job(plan, job_id)
    plan.ungrouped_parts.extend(job.parts)
    plan.jobs = [j for j in plan.jobs if j.id != job_id]
    save_plan(plan)
    return plan


def unassign_part_from_job(plan_id: str, oem_pn: str, job_id: str) -> ServicePlan:
    """Move a part from a job back to ungrouped_parts."""
    plan = load_plan(plan_id)
    job = _find_job(plan, job_id)
    part = next((p for p in job.parts if p.catalog_part.oem_pn == oem_pn), None)
    if part is None:
        raise ValueError(f"Part '{oem_pn}' not found in job '{job_id}'")
    job.parts.remove(part)
    plan.ungrouped_parts.append(part)
    save_plan(plan)
    return plan


def assign_part_to_job(plan_id: str, oem_pn: str, job_id: str) -> ServicePlan:
    """Move a part from ungrouped_parts into the specified job."""
    plan = load_plan(plan_id)
    job = _find_job(plan, job_id)

    part = next(
        (p for p in plan.ungrouped_parts if p.catalog_part.oem_pn == oem_pn), None
    )
    if part is None:
        raise ValueError(f"Part '{oem_pn}' not found in ungrouped parts")

    plan.ungrouped_parts.remove(part)
    job.parts.append(part)
    save_plan(plan)
    return plan


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_job(plan: ServicePlan, job_id: str) -> Job:
    for job in plan.jobs:
        if job.id == job_id:
            return job
    raise ValueError(f"Job '{job_id}' not found in plan '{plan.id}'")
