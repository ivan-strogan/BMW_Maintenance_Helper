"""Unit tests for schedule_importer._extract_intervals regex logic.

No file I/O — tests the parsing function in pure isolation.
"""

from __future__ import annotations

from bmw_helper.schedule_importer import _extract_intervals


def _run(prose: str) -> dict:
    return _extract_intervals(prose)


class TestReplaceInterval:
    def test_replace_every_km(self):
        r = _run("Replace every 12,000 BMW Recommends every 24,000")
        assert r["interval_replace_km"] == 12000

    def test_change_every_treated_as_replace(self):
        r = _run("Change every 90,000 BMW states it is a lifetime fluid")
        assert r["interval_replace_km"] == 90000

    def test_replace_with_year_interval(self):
        r = _run("Replace every 48,000 or every 2.5 years BMW recommends every 2 years")
        assert r["interval_replace_km"] == 48000
        assert r["interval_replace_months"] == 30


class TestInspectInterval:
    def test_inspect_every_km(self):
        r = _run("Inspect every 24,000 Replace on failure")
        assert r["interval_inspect_km"] == 24000

    def test_combined_inspect_and_replace(self):
        r = _run("Inspect every 24,000, replace every 48,000 BMW recommends 45,000")
        assert r["interval_inspect_km"] == 24000
        assert r["interval_replace_km"] == 48000


class TestBmwRecommendation:
    def test_bmw_recommendation_km(self):
        r = _run("Replace every 12,000 BMW Recommends every 24,000")
        assert r["bmw_recommendation_km"] == 24000

    def test_bmw_recommendation_months(self):
        r = _run("Replace every 48,000 or every 2.5 years BMW recommends every 2 years")
        assert r["bmw_recommendation_months"] == 24


class TestEdgeCases:
    def test_no_intervals_returns_none(self):
        r = _run("Inspect tread depth wear pattern Replace when below minimums")
        assert r["interval_replace_km"] is None
        assert r["interval_inspect_km"] is None
        assert r["interval_replace_months"] is None

    def test_on_failure_clause_does_not_create_extra_interval(self):
        r = _run("Replace every 192,000 or on failure BMW recommends 192,000")
        assert r["interval_replace_km"] == 192000
        assert r["bmw_recommendation_km"] == 192000
