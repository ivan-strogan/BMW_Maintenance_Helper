"""Unit tests for Issue #22: Gemini backend, rate limiter, request counter."""

from __future__ import annotations

import datetime
import time
from unittest.mock import patch

import pytest


# ── GeminiRateLimiter ─────────────────────────────────────────────────────────

class TestGeminiRateLimiter:
    def _make(self, rpm=5, tpm=10_000):
        from bmw_helper.ai import GeminiRateLimiter
        return GeminiRateLimiter(rpm=rpm, tpm=tpm)

    # RPM

    def test_starts_empty(self):
        lim = self._make()
        assert lim.current_rpm() == 0

    def test_wait_for_rpm_claims_slot(self):
        lim = self._make(rpm=3)
        lim.wait_for_rpm()
        assert lim.current_rpm() == 1

    def test_wait_for_rpm_fills_window(self):
        lim = self._make(rpm=3)
        lim.wait_for_rpm()
        lim.wait_for_rpm()
        lim.wait_for_rpm()
        assert lim.current_rpm() == 3

    def test_wait_for_rpm_sleeps_when_full(self):
        lim = self._make(rpm=2)
        now = time.monotonic()
        # Pre-fill with entries that are 30s old (still within 60s window)
        lim._req_times.append(now - 30)
        lim._req_times.append(now - 25)

        slept = []
        def fake_sleep(s):
            slept.append(s)
            # Advance the window by expiring both entries
            lim._req_times.clear()

        with patch("bmw_helper.ai.time.sleep", side_effect=fake_sleep):
            lim.wait_for_rpm()

        assert len(slept) == 1
        assert slept[0] > 0

    def test_evict_removes_old_rpm_entries(self):
        lim = self._make(rpm=2)
        now = time.monotonic()
        lim._req_times.append(now - 90)  # older than 60s
        lim._req_times.append(now - 10)  # still valid
        lim._evict()
        assert lim.current_rpm() == 1

    # TPM

    def test_starts_at_zero_tpm(self):
        lim = self._make()
        assert lim.current_tpm() == 0

    def test_record_tokens_accumulates(self):
        lim = self._make()
        lim.record_tokens(1000)
        lim.record_tokens(2000)
        assert lim.current_tpm() == 3000

    def test_wait_for_tpm_returns_immediately_when_under_limit(self):
        lim = self._make(tpm=10_000)
        lim.record_tokens(5_000)
        with patch("bmw_helper.ai.time.sleep") as mock_sleep:
            lim.wait_for_tpm(estimate=4_000)  # 5K + 4K = 9K < 10K
        mock_sleep.assert_not_called()

    def test_wait_for_tpm_sleeps_when_over_limit(self):
        lim = self._make(tpm=10_000)
        lim.record_tokens(9_500)

        slept = []
        def fake_sleep(s):
            slept.append(s)
            lim._token_log.clear()  # simulate time passing, entries evicted

        with patch("bmw_helper.ai.time.sleep", side_effect=fake_sleep):
            lim.wait_for_tpm(estimate=1_000)  # 9.5K + 1K = 10.5K > 10K

        assert len(slept) == 1

    def test_evict_removes_old_token_entries(self):
        lim = self._make(tpm=10_000)
        now = time.monotonic()
        lim._token_log.append((now - 90, 8_000))  # older than 60s
        lim._token_log.append((now - 10, 1_000))  # still valid
        lim._evict()
        assert lim.current_tpm() == 1_000

    def test_wait_for_tpm_no_log_returns_immediately(self):
        lim = self._make(tpm=100)
        with patch("bmw_helper.ai.time.sleep") as mock_sleep:
            lim.wait_for_tpm(estimate=50)
        mock_sleep.assert_not_called()


# ── Request counter ───────────────────────────────────────────────────────────

class TestRequestCounter:
    @pytest.fixture(autouse=True)
    def reset_counter(self):
        import bmw_helper.ai as ai_mod
        import datetime as _dt
        ai_mod._counter["date"] = _dt.date.today().isoformat()
        ai_mod._counter["count"] = 0
        yield
        ai_mod._counter["date"] = _dt.date.today().isoformat()
        ai_mod._counter["count"] = 0

    def test_initial_count_is_zero(self):
        from bmw_helper.ai import get_request_count
        result = get_request_count()
        assert result["count"] == 0

    def test_increment_increases_count(self):
        from bmw_helper.ai import _increment_counter, get_request_count
        _increment_counter()
        _increment_counter()
        assert get_request_count()["count"] == 2

    def test_get_request_count_includes_date(self):
        from bmw_helper.ai import get_request_count
        result = get_request_count()
        assert "date" in result
        datetime.date.fromisoformat(result["date"])  # must be valid ISO date

    def test_counter_resets_on_new_day(self):
        import bmw_helper.ai as ai_mod
        from bmw_helper.ai import _increment_counter, get_request_count
        _increment_counter()
        _increment_counter()
        # Simulate yesterday's date stored in the counter
        ai_mod._counter["date"] = "2000-01-01"
        result = get_request_count()
        assert result["count"] == 0

    def test_increment_resets_on_new_day(self):
        import bmw_helper.ai as ai_mod
        from bmw_helper.ai import _increment_counter, get_request_count
        ai_mod._counter["date"] = "2000-01-01"
        ai_mod._counter["count"] = 99
        _increment_counter()
        assert get_request_count()["count"] == 1


# ── _history_to_gemini ────────────────────────────────────────────────────────

class TestHistoryToGemini:
    def _convert(self, history):
        from bmw_helper.ai import _history_to_gemini
        return _history_to_gemini(history)

    def test_empty_history(self):
        assert self._convert([]) == []

    def test_user_message(self):
        result = self._convert([{"role": "user", "content": "hello"}])
        assert result[0]["role"] == "user"
        assert result[0]["parts"][0]["text"] == "hello"

    def test_assistant_maps_to_model(self):
        result = self._convert([{"role": "assistant", "content": "hi there"}])
        assert result[0]["role"] == "model"

    def test_tool_message_maps_to_user(self):
        result = self._convert([{"role": "tool", "content": "{}"}])
        assert result[0]["role"] == "user"

    def test_preserves_order(self):
        history = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        result = self._convert(history)
        assert [r["role"] for r in result] == ["user", "model", "user"]

    def test_none_content_becomes_empty_string(self):
        result = self._convert([{"role": "user", "content": None}])
        assert result[0]["parts"][0]["text"] == ""

    def test_missing_content_becomes_empty_string(self):
        result = self._convert([{"role": "user"}])
        assert result[0]["parts"][0]["text"] == ""


# ── _tools_to_gemini ──────────────────────────────────────────────────────────

class TestToolsToGemini:
    def _convert(self, tools):
        from bmw_helper.ai import _tools_to_gemini
        return _tools_to_gemini(tools)

    def _make_tool(self, name="my_tool", description="does something", params=None):
        t = {"function": {"name": name, "description": description}}
        if params:
            t["function"]["parameters"] = params
        return t

    def test_returns_tool_object(self):
        from google.genai import types as gtypes
        result = self._convert([self._make_tool()])
        assert isinstance(result, gtypes.Tool)

    def test_function_declaration_name(self):
        result = self._convert([self._make_tool(name="get_parts")])
        assert result.function_declarations[0].name == "get_parts"

    def test_function_declaration_description(self):
        result = self._convert([self._make_tool(description="fetches parts")])
        assert result.function_declarations[0].description == "fetches parts"

    def test_multiple_tools(self):
        tools = [self._make_tool("tool_a"), self._make_tool("tool_b")]
        result = self._convert(tools)
        names = [d.name for d in result.function_declarations]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_tool_without_properties_has_no_params(self):
        result = self._convert([self._make_tool(params={"type": "object"})])
        assert result.function_declarations[0].parameters is None

    def test_tool_with_properties_passes_params(self):
        params = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = self._convert([self._make_tool(params=params)])
        assert result.function_declarations[0].parameters is not None


# ── get_backend_name / thinking_supported ────────────────────────────────────

class TestBackendHelpers:
    def test_get_backend_name_ollama_when_no_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from bmw_helper.ai import get_backend_name
        assert get_backend_name() == "ollama"

    def test_get_backend_name_gemini_when_key_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from bmw_helper.ai import get_backend_name
        assert get_backend_name() == "gemini"

    def test_thinking_supported_ollama(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from bmw_helper.ai import thinking_supported
        assert thinking_supported() is True

    def test_thinking_supported_gemini_25_flash(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
        from bmw_helper.ai import thinking_supported
        assert thinking_supported() is True

    def test_thinking_not_supported_flash_lite(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        from bmw_helper.ai import thinking_supported
        assert thinking_supported() is False


# ── get_gemini_api_key / get_gemini_model ─────────────────────────────────────

class TestGeminiConfig:
    def test_api_key_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from bmw_helper.config import get_gemini_api_key
        assert get_gemini_api_key() is None

    def test_api_key_returns_value(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "my-secret-key")
        from bmw_helper.config import get_gemini_api_key
        assert get_gemini_api_key() == "my-secret-key"

    def test_model_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        from bmw_helper.config import get_gemini_model
        assert get_gemini_model() == "gemini-3.1-flash-lite"

    def test_model_override(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
        from bmw_helper.config import get_gemini_model
        assert get_gemini_model() == "gemini-2.5-flash"


# ── _MODEL_LIMITS coverage ────────────────────────────────────────────────────

class TestModelLimits:
    def test_known_models_have_rpm_and_tpm(self):
        from bmw_helper.ai import _MODEL_LIMITS
        for model, limits in _MODEL_LIMITS.items():
            assert "rpm" in limits, f"{model} missing rpm"
            assert "tpm" in limits, f"{model} missing tpm"
            assert limits["rpm"] > 0
            assert limits["tpm"] > 0

    def test_flash_lite_rpm_is_15(self):
        from bmw_helper.ai import _MODEL_LIMITS
        assert _MODEL_LIMITS["gemini-3.1-flash-lite"]["rpm"] == 15

    def test_gemini_25_flash_rpm_is_5(self):
        from bmw_helper.ai import _MODEL_LIMITS
        assert _MODEL_LIMITS["gemini-2.5-flash"]["rpm"] == 5
