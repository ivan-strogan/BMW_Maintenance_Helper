"""Integration tests for new plan features added in Issue #16.

Covers: rename_plan, update_part_qty, add_part with catalog metadata,
and AI plan tools (list_plans, create_plan, add_parts_to_plan).
"""

from __future__ import annotations

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def plans_dir(tmp_path, monkeypatch):
    import bmw_helper.plan as m
    monkeypatch.setattr(m, "PLANS_DIR", tmp_path)
    return tmp_path


# ── rename_plan ───────────────────────────────────────────────────────────────

class TestRenamePlan:
    def test_rename_changes_name(self, plans_dir):
        from bmw_helper.plan import create_plan, rename_plan, load_plan
        plan = create_plan("Old", "VIN123")
        renamed = rename_plan(plan.id, "New Name")
        assert renamed.name == "New Name"
        assert load_plan(plan.id).name == "New Name"

    def test_rename_empty_string_raises(self, plans_dir):
        from bmw_helper.plan import create_plan, rename_plan
        plan = create_plan("Test", "VIN123")
        with pytest.raises(ValueError):
            rename_plan(plan.id, "")

    def test_rename_whitespace_only_raises(self, plans_dir):
        from bmw_helper.plan import create_plan, rename_plan
        plan = create_plan("Test", "VIN123")
        with pytest.raises(ValueError):
            rename_plan(plan.id, "   ")

    def test_rename_nonexistent_raises(self, plans_dir):
        from bmw_helper.plan import rename_plan
        with pytest.raises(FileNotFoundError):
            rename_plan("doesnotexist", "New Name")


# ── update_part_qty ───────────────────────────────────────────────────────────

class TestUpdatePartQty:
    def test_updates_ungrouped_part(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part, update_part_qty
        plan = create_plan("Test", "VIN123")
        add_part(plan.id, "11427541827", description="Oil Filter", qty=1)
        updated = update_part_qty(plan.id, "11427541827", 3)
        assert updated.ungrouped_parts[0].catalog_part.qty_required == 3

    def test_updates_job_part(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part, add_job, assign_part_to_job, update_part_qty
        plan = create_plan("Test", "VIN123")
        add_part(plan.id, "11427541827", description="Filter")
        updated = add_job(plan.id, "Oil Service")
        job_id = updated.jobs[0].id
        assign_part_to_job(plan.id, "11427541827", job_id)
        result = update_part_qty(plan.id, "11427541827", 2)
        assert result.jobs[0].parts[0].catalog_part.qty_required == 2

    def test_qty_zero_raises(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part, update_part_qty
        plan = create_plan("Test", "VIN123")
        add_part(plan.id, "11427541827", description="Filter")
        with pytest.raises(ValueError):
            update_part_qty(plan.id, "11427541827", 0)

    def test_unknown_pn_raises(self, plans_dir):
        from bmw_helper.plan import create_plan, update_part_qty
        plan = create_plan("Test", "VIN123")
        with pytest.raises(ValueError):
            update_part_qty(plan.id, "99999999999", 1)


# ── add_part catalog metadata ─────────────────────────────────────────────────

class TestAddPartMetadata:
    def test_stores_catalog_path(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        updated = add_part(plan.id, "11427541827", description="Filter",
                           catalog_path=["11_3971"])
        assert updated.ungrouped_parts[0].catalog_part.catalog_path == ["11_3971"]

    def test_stores_diagram_url(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        url = "https://www.realoem.com/bmw/images/diag_abc.jpg"
        updated = add_part(plan.id, "11427541827", description="Filter",
                           diagram_url=url)
        assert updated.ungrouped_parts[0].catalog_part.diagram_url == url

    def test_stores_diagram_ref(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        updated = add_part(plan.id, "11427541827", description="Filter",
                           diagram_ref="03")
        assert updated.ungrouped_parts[0].catalog_part.diagram_ref == "03"

    def test_defaults_empty_catalog_path(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        updated = add_part(plan.id, "11427541827", description="Filter")
        assert updated.ungrouped_parts[0].catalog_part.catalog_path == []


# ── AI plan tools ─────────────────────────────────────────────────────────────

class TestAiPlanTools:
    def test_list_plans_empty(self, plans_dir):
        from bmw_helper.ai_tools import list_plans
        assert list_plans() == []

    def test_create_plan_returns_plan_id(self, config_dir, plans_dir):
        from bmw_helper.ai_tools import create_plan
        result = create_plan("Brake Service")
        assert "plan_id" in result
        assert result["name"] == "Brake Service"

    def test_create_plan_appears_in_list(self, config_dir, plans_dir):
        from bmw_helper.ai_tools import create_plan, list_plans
        create_plan("Spring Service")
        plans = list_plans()
        assert len(plans) == 1
        assert plans[0]["name"] == "Spring Service"

    def test_add_parts_to_plan(self, config_dir, plans_dir):
        from bmw_helper.ai_tools import create_plan, add_parts_to_plan
        result = create_plan("Test Plan")
        plan_id = result["plan_id"]
        add_result = add_parts_to_plan(plan_id, [
            {"oem_pn": "11427541827", "description": "Oil Filter Element", "qty": 1},
            {"oem_pn": "07119963200", "description": "Drain Plug Seal", "qty": 1},
        ])
        assert len(add_result["added"]) == 2
        assert add_result["errors"] == []

    def test_add_parts_skips_empty_pn(self, config_dir, plans_dir):
        from bmw_helper.ai_tools import create_plan, add_parts_to_plan
        result = create_plan("Test Plan")
        add_result = add_parts_to_plan(result["plan_id"], [
            {"oem_pn": "", "description": "No PN"},
            {"oem_pn": "11427541827", "description": "Oil Filter"},
        ])
        assert add_result["added"] == ["11427541827"]

    def test_add_parts_stores_diagram_ref(self, config_dir, plans_dir):
        from bmw_helper.ai_tools import create_plan, add_parts_to_plan
        from bmw_helper.plan import load_plan
        result = create_plan("Test Plan")
        plan_id = result["plan_id"]
        add_parts_to_plan(plan_id, [
            {"oem_pn": "11427541827", "description": "Oil Filter", "diagram_ref": "03"},
        ])
        plan = load_plan(plan_id)
        assert plan.ungrouped_parts[0].catalog_part.diagram_ref == "03"

    def test_list_plans_returns_part_count(self, config_dir, plans_dir):
        from bmw_helper.ai_tools import create_plan, add_parts_to_plan, list_plans
        result = create_plan("Test Plan")
        add_parts_to_plan(result["plan_id"], [
            {"oem_pn": "11427541827", "description": "Filter"},
        ])
        plans = list_plans()
        assert plans[0]["parts"] == 1
