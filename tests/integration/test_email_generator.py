"""Integration tests for the quote email generator."""

from __future__ import annotations

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def plans_dir(tmp_path, monkeypatch):
    import bmw_helper.plan as m
    monkeypatch.setattr(m, "PLANS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def sample_plan(config_dir, plans_dir):
    """A plan with two jobs and an ungrouped part."""
    from bmw_helper.plan import create_plan, add_part, add_job, assign_part_to_job

    plan = create_plan("Spring Service 2026", "WBATEST00000000001")

    # Parts
    add_part(plan.id, "11427541827", description="Oil Filter Element", qty=1, preferred_brand="Mann")
    add_part(plan.id, "07119963200", description="Oil Drain Plug Sealing Ring", qty=1)
    add_part(plan.id, "34336792217", description="Brake Fluid DOT4 LV", qty=1)
    # ungrouped
    add_part(plan.id, "07119904878", description="Drain Plug")

    # Jobs
    updated = add_job(plan.id, "Engine Oil & Filter Service",
                      labour_notes="Use BMW LL-01 spec oil.",
                      overlaps_with=[])
    job1_id = updated.jobs[0].id

    updated = add_job(plan.id, "Brake Fluid Flush",
                      labour_notes="Bleed all four corners.",
                      no_warranty=False)
    job2_id = updated.jobs[1].id

    assign_part_to_job(plan.id, "11427541827", job1_id)
    assign_part_to_job(plan.id, "07119963200", job1_id)
    assign_part_to_job(plan.id, "34336792217", job2_id)

    from bmw_helper.plan import load_plan
    return load_plan(plan.id)


@pytest.fixture
def email_client(config_dir, plans_dir, monkeypatch):
    import bmw_helper.plan as m
    monkeypatch.setattr(m, "PLANS_DIR", plans_dir)
    from bmw_helper.api import api
    from fastapi.testclient import TestClient
    return TestClient(api)


# ── render_email tests ─────────────────────────────────────────────────────────

class TestRenderEmail:
    def test_contains_vehicle_info(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "WBATEST00000000001" in text
        assert "2007" in text
        assert "335i" in text
        assert "N54" in text

    def test_contains_owner_name(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "Test Owner" in text

    def test_contains_job_names(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "Engine Oil & Filter Service" in text
        assert "Brake Fluid Flush" in text

    def test_contains_oem_part_numbers(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "11427541827" in text
        assert "34336792217" in text

    def test_contains_preferred_brand(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "Mann" in text

    def test_contains_labour_notes(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "BMW LL-01 spec oil" in text
        assert "Bleed all four corners" in text

    def test_ungrouped_parts_section(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "Drain Plug" in text
        assert "07119904878" in text

    def test_odometer_formatted_with_commas(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "84,000 km" in text

    def test_preferred_brands_in_intro(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "Elring" in text
        assert "Bosch" in text

    def test_job_ids_filter(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        job1_id = sample_plan.jobs[0].id
        text = render_email(sample_plan, job_ids=[job1_id])
        assert "Engine Oil & Filter Service" in text
        assert "Brake Fluid Flush" not in text

    def test_empty_job_ids_renders_nothing(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan, job_ids=[])
        assert "Engine Oil & Filter Service" not in text
        assert "Brake Fluid Flush" not in text

    def test_returns_string(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        assert isinstance(render_email(sample_plan), str)

    def test_no_html_in_output(self, config_dir, sample_plan):
        from bmw_helper.email_generator import render_email
        text = render_email(sample_plan)
        assert "<" not in text and ">" not in text


# ── API endpoint tests ─────────────────────────────────────────────────────────

class TestEmailAPI:
    def _create_plan(self, client):
        return client.post("/api/plans", json={"name": "Test Plan"}).json()

    def test_generate_returns_email_text(self, email_client, sample_plan):
        res = email_client.post("/api/email/generate", json={"plan_id": sample_plan.id})
        assert res.status_code == 200
        data = res.json()
        assert "email" in data
        assert len(data["email"]) > 100

    def test_generate_contains_vehicle_info(self, email_client, sample_plan):
        res = email_client.post("/api/email/generate", json={"plan_id": sample_plan.id})
        assert "WBATEST00000000001" in res.json()["email"]

    def test_generate_nonexistent_plan_returns_404(self, email_client):
        res = email_client.post("/api/email/generate", json={"plan_id": "doesnotexist"})
        assert res.status_code == 404

    def test_generate_with_job_filter(self, email_client, sample_plan):
        job1_id = sample_plan.jobs[0].id
        res = email_client.post("/api/email/generate", json={
            "plan_id": sample_plan.id,
            "job_ids": [job1_id],
        })
        assert res.status_code == 200
        text = res.json()["email"]
        assert "Engine Oil & Filter Service" in text
        assert "Brake Fluid Flush" not in text
