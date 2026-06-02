"""Quote-request email generator.

Renders a Jinja2 template from a ServicePlan + vehicle config into a
plain-text email ready to paste and send to a shop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import load_app_config
from .models import ServicePlan
from .plan import load_plan

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape([]),  # plain text — no HTML escaping
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["format_km"] = lambda km: f"{km:,} km"
    return env


def render_email(
    plan: ServicePlan,
    job_ids: Optional[list[str]] = None,
) -> str:
    """Render the quote-request email for a plan.

    Args:
        plan: The ServicePlan to render.
        job_ids: Optional list of job IDs to include. If None, all jobs are included.

    Returns:
        Rendered plain-text email string.
    """
    cfg = load_app_config()

    jobs = plan.jobs
    if job_ids is not None:
        id_set = set(job_ids)
        jobs = [j for j in jobs if j.id in id_set]

    env = _make_env()
    template = env.get_template("quote_email.j2")
    return template.render(
        vehicle=cfg.vehicle,
        owner=cfg.owner,
        prefs=cfg.preferences,
        plan=plan,
        jobs=jobs,
        ungrouped=plan.ungrouped_parts,
    )


def render_email_for_plan_id(
    plan_id: str,
    job_ids: Optional[list[str]] = None,
) -> str:
    """Load a plan by ID and render its quote email."""
    plan = load_plan(plan_id)
    return render_email(plan, job_ids=job_ids)
