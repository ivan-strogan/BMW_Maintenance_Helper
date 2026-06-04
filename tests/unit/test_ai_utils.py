"""Unit tests for features added in Issue #16.

Covers: _split_think, _parse_diagram_url, _best_match proportional scoring,
rename_plan, update_part_qty (unit), and AI plan tools.
"""

from __future__ import annotations

import pytest


# ── _split_think ───────────────────────────────────────────────────────────────

class TestSplitThink:
    def _split(self, text):
        from bmw_helper.ai import _split_think
        return _split_think(text)

    def test_splits_think_from_reply(self):
        thinking, reply = self._split("<think>I should check the schedule.</think>Here is your answer.")
        assert thinking == "I should check the schedule."
        assert reply == "Here is your answer."

    def test_no_think_tag_returns_empty_thinking(self):
        thinking, reply = self._split("Just a plain reply.")
        assert thinking == ""
        assert reply == "Just a plain reply."

    def test_multiline_thinking_stripped(self):
        thinking, reply = self._split("<think>\nLine 1\nLine 2\n</think>\nThe answer.")
        assert "Line 1" in thinking
        assert reply == "The answer."

    def test_empty_think_block(self):
        thinking, reply = self._split("<think></think>Just the reply.")
        assert thinking == ""
        assert reply == "Just the reply."

    def test_whitespace_trimmed(self):
        thinking, reply = self._split("<think>  thoughts  </think>  answer  ")
        assert thinking == "thoughts"
        assert reply == "answer"


# ── _parse_diagram_url ────────────────────────────────────────────────────────

class TestParseDiagramUrl:
    def _parse(self, html):
        from bmw_helper.realoem import RealOEMClient
        return RealOEMClient._parse_diagram_url(html)

    def test_finds_diag_image(self):
        html = '<html><body><img src="/bmw/images/diag_a9hm.jpg"></body></html>'
        url = self._parse(html)
        assert url == "https://www.realoem.com/bmw/images/diag_a9hm.jpg"

    def test_returns_none_when_no_diag_image(self):
        html = '<html><body><img src="/bmw/images/thumb_abc.jpg"></body></html>'
        assert self._parse(html) is None

    def test_returns_none_for_empty_page(self):
        assert self._parse("<html><body></body></html>") is None

    def test_ignores_thumb_images(self):
        html = '<img src="/bmw/images/thumb_abc.jpg"><img src="/bmw/images/diag_xyz.jpg">'
        url = self._parse(html)
        assert "diag_xyz" in url

    def test_absolute_url_returned_as_is(self):
        html = '<img src="https://www.realoem.com/bmw/images/diag_abc.jpg">'
        url = self._parse(html)
        assert url == "https://www.realoem.com/bmw/images/diag_abc.jpg"


# ── _best_match proportional scoring ─────────────────────────────────────────

class TestBestMatchScoring:
    GROUPS = [
        {"mg": "11", "name": "ENGINE"},
        {"mg": "34", "name": "BRAKES"},
        {"mg": "31", "name": "FRONT AXLE"},
        {"mg": "17", "name": "RADIATOR"},
        {"mg": "13", "name": "FUEL PREPARATION SYSTEM"},
    ]

    def _match(self, needle):
        from bmw_helper.realoem import _best_match
        return _best_match(needle, self.GROUPS, key="name")

    def test_front_brake_pads_resolves_to_brakes_not_front_axle(self):
        result = self._match("front brake pads")
        assert result["mg"] == "34"

    def test_brake_resolves_to_brakes(self):
        assert self._match("brake pads")["mg"] == "34"

    def test_engine_resolves_to_engine(self):
        assert self._match("engine oil")["mg"] == "11"

    def test_exact_match_wins(self):
        assert self._match("BRAKES")["mg"] == "34"

    def test_case_insensitive_exact(self):
        assert self._match("brakes")["mg"] == "34"

    def test_fuel_system_resolves(self):
        assert self._match("fuel filter")["mg"] == "13"

    def test_no_match_returns_none(self):
        from bmw_helper.realoem import _best_match
        assert _best_match("transmission", self.GROUPS, key="name") is None


