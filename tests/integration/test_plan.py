"""Integration tests for the service plan builder — plan.py + API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def plans_dir(tmp_path, monkeypatch):
    """Redirect plan storage to a temp directory."""
    import bmw_helper.plan as plan_module
    monkeypatch.setattr(plan_module, "PLANS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def plan_client(config_dir, plans_dir, monkeypatch):
    """TestClient with both config and plans redirected to temp dirs."""
    import bmw_helper.plan as plan_module
    monkeypatch.setattr(plan_module, "PLANS_DIR", plans_dir)
    from bmw_helper.api import api
    from fastapi.testclient import TestClient
    return TestClient(api)


# ── plan.py unit-level tests ──────────────────────────────────────────────────

class TestCreatePlan:
    def test_creates_json_file(self, plans_dir):
        from bmw_helper.plan import create_plan
        plan = create_plan("Spring Service", "VIN123")
        assert (plans_dir / f"{plan.id}.json").exists()

    def test_plan_has_name_and_vin(self, plans_dir):
        from bmw_helper.plan import create_plan
        plan = create_plan("Spring Service", "VIN123")
        assert plan.name == "Spring Service"
        assert plan.vehicle_vin == "VIN123"

    def test_plan_starts_empty(self, plans_dir):
        from bmw_helper.plan import create_plan
        plan = create_plan("Empty Plan", "VIN123")
        assert plan.jobs == []
        assert plan.ungrouped_parts == []


class TestAddRemovePart:
    def test_add_to_ungrouped(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        updated = add_part(plan.id, "11427541827", description="Oil Filter", qty=1)
        assert len(updated.ungrouped_parts) == 1
        assert updated.ungrouped_parts[0].catalog_part.oem_pn == "11427541827"

    def test_add_multiple_parts(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        add_part(plan.id, "11427541827", description="Oil Filter")
        updated = add_part(plan.id, "07119963200", description="Sealing Ring")
        assert len(updated.ungrouped_parts) == 2

    def test_remove_part(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part, remove_part
        plan = create_plan("Test", "VIN123")
        add_part(plan.id, "11427541827", description="Oil Filter")
        updated = remove_part(plan.id, "11427541827")
        assert len(updated.ungrouped_parts) == 0

    def test_remove_nonexistent_part_is_noop(self, plans_dir):
        from bmw_helper.plan import create_plan, remove_part
        plan = create_plan("Test", "VIN123")
        updated = remove_part(plan.id, "99999999999")
        assert updated.ungrouped_parts == []

    def test_preferred_brand_stored(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        updated = add_part(plan.id, "11427541827", preferred_brand="Elring")
        assert updated.ungrouped_parts[0].preferred_brand == "Elring"

    def test_customer_supplied_flag(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part
        plan = create_plan("Test", "VIN123")
        updated = add_part(plan.id, "11427541827", customer_supplied=True)
        assert updated.ungrouped_parts[0].customer_supplied is True


class TestJobManagement:
    def test_add_job(self, plans_dir):
        from bmw_helper.plan import create_plan, add_job
        plan = create_plan("Test", "VIN123")
        updated = add_job(plan.id, "Oil Service")
        assert len(updated.jobs) == 1
        assert updated.jobs[0].name == "Oil Service"

    def test_job_has_unique_id(self, plans_dir):
        from bmw_helper.plan import create_plan, add_job
        plan = create_plan("Test", "VIN123")
        add_job(plan.id, "Job A")
        updated = add_job(plan.id, "Job B")
        ids = [j.id for j in updated.jobs]
        assert ids[0] != ids[1]

    def test_update_job_name(self, plans_dir):
        from bmw_helper.plan import create_plan, add_job, update_job
        plan = create_plan("Test", "VIN123")
        updated = add_job(plan.id, "Original Name")
        job_id = updated.jobs[0].id
        updated = update_job(plan.id, job_id, name="New Name")
        assert updated.jobs[0].name == "New Name"

    def test_update_job_flags(self, plans_dir):
        from bmw_helper.plan import create_plan, add_job, update_job
        plan = create_plan("Test", "VIN123")
        updated = add_job(plan.id, "Clutch Job")
        job_id = updated.jobs[0].id
        updated = update_job(plan.id, job_id, no_warranty=True, customer_supplied_labour=True)
        job = updated.jobs[0]
        assert job.no_warranty is True
        assert job.customer_supplied_labour is True

    def test_update_nonexistent_job_raises(self, plans_dir):
        from bmw_helper.plan import create_plan, update_job
        plan = create_plan("Test", "VIN123")
        with pytest.raises(ValueError, match="not found"):
            update_job(plan.id, "bad_id", name="X")

    def test_assign_part_to_job(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part, add_job, assign_part_to_job
        plan = create_plan("Test", "VIN123")
        add_part(plan.id, "11427541827", description="Oil Filter")
        updated = add_job(plan.id, "Oil Service")
        job_id = updated.jobs[0].id
        updated = assign_part_to_job(plan.id, "11427541827", job_id)
        assert len(updated.ungrouped_parts) == 0
        assert len(updated.jobs[0].parts) == 1

    def test_assign_nonexistent_part_raises(self, plans_dir):
        from bmw_helper.plan import create_plan, add_job, assign_part_to_job
        plan = create_plan("Test", "VIN123")
        updated = add_job(plan.id, "Job")
        job_id = updated.jobs[0].id
        with pytest.raises(ValueError, match="not found"):
            assign_part_to_job(plan.id, "99999999999", job_id)


class TestPersistence:
    def test_load_returns_same_plan(self, plans_dir):
        from bmw_helper.plan import create_plan, add_part, load_plan
        plan = create_plan("Spring Service", "VIN123")
        add_part(plan.id, "11427541827", description="Oil Filter", qty=2)
        reloaded = load_plan(plan.id)
        assert reloaded.name == "Spring Service"
        assert reloaded.ungrouped_parts[0].catalog_part.qty_required == 2

    def test_list_plans(self, plans_dir):
        from bmw_helper.plan import create_plan, list_plans
        create_plan("Plan A", "VIN123")
        create_plan("Plan B", "VIN123")
        plans = list_plans()
        assert len(plans) == 2
        names = {p.name for p in plans}
        assert names == {"Plan A", "Plan B"}

    def test_delete_plan(self, plans_dir):
        from bmw_helper.plan import create_plan, delete_plan, list_plans
        plan = create_plan("To Delete", "VIN123")
        delete_plan(plan.id)
        assert list_plans() == []

    def test_load_nonexistent_raises(self, plans_dir):
        from bmw_helper.plan import load_plan
        with pytest.raises(FileNotFoundError):
            load_plan("doesnotexist")


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestPlanAPI:
    def test_list_empty(self, plan_client):
        res = plan_client.get("/api/plans")
        assert res.status_code == 200
        assert res.json() == []

    def test_create_plan(self, plan_client):
        res = plan_client.post("/api/plans", json={"name": "Spring Service"})
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Spring Service"
        assert "id" in data

    def test_created_plan_appears_in_list(self, plan_client):
        plan_client.post("/api/plans", json={"name": "Spring Service"})
        plans = plan_client.get("/api/plans").json()
        assert len(plans) == 1
        assert plans[0]["name"] == "Spring Service"

    def test_get_plan(self, plan_client):
        created = plan_client.post("/api/plans", json={"name": "Test Plan"}).json()
        res = plan_client.get(f"/api/plans/{created['id']}")
        assert res.status_code == 200
        assert res.json()["id"] == created["id"]

    def test_get_nonexistent_plan_returns_404(self, plan_client):
        res = plan_client.get("/api/plans/doesnotexist")
        assert res.status_code == 404

    def test_delete_plan(self, plan_client):
        created = plan_client.post("/api/plans", json={"name": "To Delete"}).json()
        res = plan_client.delete(f"/api/plans/{created['id']}")
        assert res.status_code == 200
        assert plan_client.get(f"/api/plans/{created['id']}").status_code == 404

    def test_add_part(self, plan_client):
        plan = plan_client.post("/api/plans", json={"name": "Test"}).json()
        res = plan_client.post(f"/api/plans/{plan['id']}/parts", json={
            "oem_pn": "11427541827",
            "description": "Oil Filter",
            "qty": 1,
        })
        assert res.status_code == 201
        assert len(res.json()["ungrouped_parts"]) == 1

    def test_remove_part(self, plan_client):
        plan = plan_client.post("/api/plans", json={"name": "Test"}).json()
        plan_client.post(f"/api/plans/{plan['id']}/parts", json={
            "oem_pn": "11427541827", "description": "Oil Filter",
        })
        res = plan_client.delete(f"/api/plans/{plan['id']}/parts/11427541827")
        assert res.status_code == 200
        assert res.json()["ungrouped_parts"] == []

    def test_add_job(self, plan_client):
        plan = plan_client.post("/api/plans", json={"name": "Test"}).json()
        res = plan_client.post(f"/api/plans/{plan['id']}/jobs", json={"name": "Oil Service"})
        assert res.status_code == 201
        assert len(res.json()["jobs"]) == 1

    def test_update_job(self, plan_client):
        plan = plan_client.post("/api/plans", json={"name": "Test"}).json()
        updated = plan_client.post(f"/api/plans/{plan['id']}/jobs", json={"name": "Job"}).json()
        job_id = updated["jobs"][0]["id"]
        res = plan_client.patch(
            f"/api/plans/{plan['id']}/jobs/{job_id}",
            json={"labour_notes": "Drain oil first", "no_warranty": True},
        )
        assert res.status_code == 200
        job = res.json()["jobs"][0]
        assert job["labour_notes"] == "Drain oil first"
        assert job["no_warranty"] is True

    def test_assign_part_to_job(self, plan_client):
        plan = plan_client.post("/api/plans", json={"name": "Test"}).json()
        plan_client.post(f"/api/plans/{plan['id']}/parts", json={
            "oem_pn": "11427541827", "description": "Oil Filter",
        })
        updated = plan_client.post(f"/api/plans/{plan['id']}/jobs", json={"name": "Oil Service"}).json()
        job_id = updated["jobs"][0]["id"]
        res = plan_client.post(f"/api/plans/{plan['id']}/assign", json={
            "oem_pn": "11427541827", "job_id": job_id,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["ungrouped_parts"] == []
        assert len(data["jobs"][0]["parts"]) == 1
