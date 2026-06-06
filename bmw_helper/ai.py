"""LLM agent for the BMW Maintenance Helper.

Supports two backends:
  - Ollama (default, local): set ai_backend=ollama or leave GEMINI_API_KEY unset.
  - Gemini (Google AI): set GEMINI_API_KEY in .env; uses gemini-2.0-flash.

Backend is selected automatically: Gemini when GEMINI_API_KEY is present,
Ollama otherwise.
"""

from __future__ import annotations

import collections
import json
import re
import time
from typing import Any, Iterator

import ollama


# ── Gemini rate limits (free tier) ────────────────────────────────────────────

_MODEL_LIMITS: dict[str, dict] = {
    "gemini-3.1-flash-lite": {"rpm": 15, "tpm": 250_000},
    "gemini-2.0-flash-lite": {"rpm": 30, "tpm": 1_000_000},
    "gemini-2.5-flash":      {"rpm": 5,  "tpm": 250_000},
    "gemini-2.5-pro":        {"rpm": 2,  "tpm": 250_000},
}
_DEFAULT_LIMITS = {"rpm": 10, "tpm": 250_000}


class GeminiRateLimiter:
    """Sliding-window RPM and TPM limiter. Sleeps to stay within free-tier limits."""

    def __init__(self, rpm: int, tpm: int) -> None:
        self._rpm = rpm
        self._tpm = tpm
        self._req_times: collections.deque[float] = collections.deque()
        self._token_log: collections.deque[tuple[float, int]] = collections.deque()

    def _evict(self) -> None:
        cutoff = time.monotonic() - 60.0
        while self._req_times and self._req_times[0] < cutoff:
            self._req_times.popleft()
        while self._token_log and self._token_log[0][0] < cutoff:
            self._token_log.popleft()

    def wait_for_rpm(self) -> None:
        """Block until an RPM slot is available, then claim it."""
        while True:
            self._evict()
            if len(self._req_times) < self._rpm:
                self._req_times.append(time.monotonic())
                return
            wait = (self._req_times[0] + 60.0) - time.monotonic() + 0.05
            if wait > 0:
                time.sleep(wait)

    def wait_for_tpm(self, estimate: int = 8_000) -> None:
        """Block if recent token usage + estimate would exceed TPM limit."""
        while True:
            self._evict()
            used = sum(t for _, t in self._token_log)
            if used + estimate <= self._tpm:
                return
            if self._token_log:
                wait = (self._token_log[0][0] + 60.0) - time.monotonic() + 0.05
                if wait > 0:
                    time.sleep(wait)
                    continue
            return

    def record_tokens(self, count: int) -> None:
        self._token_log.append((time.monotonic(), count))

    def current_rpm(self) -> int:
        self._evict()
        return len(self._req_times)

    def current_tpm(self) -> int:
        self._evict()
        return sum(t for _, t in self._token_log)


def _split_think(text: str) -> tuple[str, str]:
    """Separate <think>...</think> reasoning from the final reply.

    Returns (thinking_text, reply_text). Either may be empty string.
    """
    m = re.search(r"<think>(.*?)</think>(.*)", text, flags=re.DOTALL)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", text.strip()

from .ai_tools import TOOLS, dispatch

MODEL = "qwen3:8b"

SYSTEM_PROMPT = """\
You are a BMW maintenance assistant for a technically knowledgeable owner. \
Help with maintenance status, parts lookup, pricing, and service plan building.

ALWAYS use tools to get real data before answering. Never invent part numbers, \
prices, or service history. Be concise — use bullet points and lists, not prose.

CRITICAL: Never stop mid-workflow to ask permission. If a task has multiple \
steps, complete all of them in one turn. Do not say "would you like me to \
continue?" or "shall I look that up?" — just do it.

CATALOG SEARCH STRATEGY — avoid redundant tool calls:
- If search_catalog returns the same diag_id you already have, stop retrying \
  with variations of the same hint. The catalog is not matching within that group.
- Escalate instead: try a completely different top-level group. Engine mounts \
  might not be in "Engine" — try "Engine and Transmission Suspension". Seat \
  parts might not be in "Vehicle Trim" — try "Seats". Radiator hoses might be \
  in "Radiator" not "Engine". Think about where BMW physically categorizes the part.
- If two different groups both fail to return a useful diagram, note the part as \
  not found in the catalog and move on — do not keep trying.

--- WORKFLOWS ---

Service intent ("I want to change the oil", "planning a brake job"):
1. get_overdue_items — confirm what is due and by how much.
2. search_catalog with the relevant hint. For general maintenance tasks
   (oil change, inspection, filter service), search
   "Service and Scope of Repair Work > Engine Oil Maintenance Service"
   FIRST — this single diagram contains ALL common consumables: oil filter,
   spark plugs, air filter, cabin filter, brake fluid, wiper blades, etc.
   Only search Engine/Brakes/etc. subgroups for specific component work
   (e.g. a brake pad replacement needs "Brakes > Front Brake Pads").
3. get_catalog_parts for each diag_id to get the full parts list.
4. get_rockauto_alternatives for the key consumable parts.
5. Reply with: overdue status, OEM PNs + prices, RA alternatives.
6. Answer with end-to-end completeness. Think about what the job actually
   requires, not just what was literally asked. Use your domain knowledge
   to surface consumables, fluids, and companion parts the user will need
   but may not have thought to ask for.

   Example — oil change: the user needs the oil filter element AND the
   drain plug crush washer AND the oil filter housing o-ring/gasket AND
   the engine oil itself (correct spec + quantity). None of those are
   optional, but only the filter might be mentioned in the question.

   Example — spark plug change: the user needs the plugs (correct NGK or
   OEM PN for the engine, quantity = number of cylinders) AND fresh
   ignition coil boots or coils if overdue AND anti-seize or dielectric
   grease as applicable AND the correct torque spec. If the plugs were
   oil-fouled, flag the valve cover gasket as a likely companion job.

   Apply this same thinking to any service: brake job (pads + rotors +
   brake fluid + caliper lube), coolant flush (correct BMW coolant
   concentrate + distilled water ratio), etc.

7. Offer to build a service plan with those parts (but don't build it unless asked).

Parts lookup ("find me oil filter parts", "what brake pads do I need"):
1. search_catalog to find the diagram.
2. get_catalog_parts to get the OEM PNs and prices.
3. get_rockauto_alternatives for the key consumable parts.
4. Reply with a table: ref, OEM PN, description, RealOEM price, RA best price.

Pricing / cost estimate:
- Use get_rockauto_alternatives with the OEM PN for aftermarket options.
- Always show both RealOEM (USD) and RockAuto (CAD) prices.
- Note the currency difference (RealOEM = USD, RockAuto = CAD).

Plan building ("build a plan", "add parts to my plan"):
1. list_plans — check if a relevant plan exists.
2. create_plan if needed with a clear name (e.g. "Oil Service 2026").
3. search_catalog + get_catalog_parts to find parts.
4. add_parts_to_plan with OEM PNs, descriptions, qty, diagram_ref, diag_id.
5. Confirm: plan name, number of parts added, total estimated cost if known.

Status query ("what's overdue", "how is my car doing"):
- get_overdue_items — list everything overdue, sorted by severity.
- For items with unknown last service, flag them clearly.

Service history ("when did I last change the oil"):
- get_service_history for the relevant item id.

Specific system ("how are my brakes", "check cooling system"):
- get_schedule_status for items in that system.
"""


# ── Startup check ─────────────────────────────────────────────────────────────

def check_ollama() -> None:
    """Raise RuntimeError if Ollama is unreachable or qwen3:8b is not pulled."""
    try:
        client = ollama.Client()
        models = [m.model for m in client.list().models]
    except Exception as exc:
        raise RuntimeError(
            f"Ollama is not running or unreachable: {exc}\n"
            "Start it with: ollama serve"
        ) from exc

    if MODEL not in models:
        raise RuntimeError(
            f"Model '{MODEL}' is not pulled.\n"
            f"Pull it with: ollama pull {MODEL}\n"
            f"Available models: {', '.join(models) or '(none)'}"
        )


# ── Agent ─────────────────────────────────────────────────────────────────────

class AIClient:
    """Stateless agent client. Each chat() call runs one full agent turn."""

    def __init__(self, model: str = MODEL) -> None:
        self._model = model
        self._client = ollama.Client()

    def chat(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> dict:
        """Run one agent turn: message -> tool calls (if any) -> final reply.

        Returns:
            {
                "reply": str,
                "tool_calls": [{"name": str, "args": dict, "result": Any}],
            }
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": message})

        tool_call_log: list[dict] = []

        # Agent loop — iterate until the model stops requesting tools
        while True:
            response = self._client.chat(
                model=self._model,
                messages=messages,
                tools=TOOLS,
            )
            msg = response.message

            if not msg.tool_calls:
                thinking, reply = _split_think(msg.content or "")
                return {
                    "reply": reply,
                    "thinking": thinking,
                    "tool_calls": tool_call_log,
                }

            # Execute each requested tool and feed results back
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})

            for tc in msg.tool_calls:
                name = tc.function.name
                args = dict(tc.function.arguments) if tc.function.arguments else {}
                result = dispatch(name, args)
                tool_call_log.append({"name": name, "args": args, "result": result})
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, default=str),
                })

    def stream(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> Iterator[str]:
        """Stream the final reply text token by token (tool calls run first, blocking)."""
        # Run tool calls synchronously first
        result = self.chat(message, history)

        # Build an updated history including tool results for the streaming call
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": message})

        if result["tool_calls"]:
            # Reconstruct the assistant+tool messages so the model has context
            for tc in result["tool_calls"]:
                messages.append({
                    "role": "tool",
                    "content": json.dumps(tc["result"], default=str),
                })
            # Ask for a final streaming answer with all tool results in context
            for chunk in self._client.chat(
                model=self._model,
                messages=messages,
                stream=True,
            ):
                yield chunk.message.content or ""
        else:
            yield result["reply"]


# ── Request counter (resets on server restart or midnight) ────────────────────

import datetime as _dt

_counter: dict = {"date": _dt.date.today().isoformat(), "count": 0}


def _increment_counter() -> int:
    today = _dt.date.today().isoformat()
    if _counter["date"] != today:
        _counter["date"] = today
        _counter["count"] = 0
    _counter["count"] += 1
    return _counter["count"]


def get_request_count() -> dict:
    today = _dt.date.today().isoformat()
    if _counter["date"] != today:
        return {"count": 0, "date": today}
    return {"count": _counter["count"], "date": _counter["date"]}


# ── Gemini client ──────────────────────────────────────────────────────────────

GEMINI_MODEL = "gemini-2.5-flash"


def _tools_to_gemini(tools: list[dict]):
    """Convert Ollama-style tool schemas to Gemini Tool object."""
    from google.genai import types as gtypes
    declarations = []
    for t in tools:
        fn = t["function"]
        params = fn.get("parameters", {})
        declarations.append(gtypes.FunctionDeclaration(
            name=fn["name"],
            description=fn.get("description", ""),
            parameters=params if params.get("properties") else None,
        ))
    return gtypes.Tool(function_declarations=declarations)


def _history_to_gemini(history: list[dict]) -> list[dict]:
    """Convert OpenAI-style history to Gemini contents format."""
    contents = []
    for m in history:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m.get("content") or ""}]})
    return contents


class GeminiClient:
    """Gemini-powered agent client using Google AI API (google-genai SDK)."""

    def __init__(self, api_key: str, model: str = GEMINI_MODEL) -> None:
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model = model
        limits = next(
            (v for k, v in _MODEL_LIMITS.items() if k in model),
            _DEFAULT_LIMITS,
        )
        self._limiter = GeminiRateLimiter(limits["rpm"], limits["tpm"])

    def check(self) -> None:
        """Raise RuntimeError if the API key is invalid or quota exhausted."""
        from google.genai import types as gtypes
        try:
            self._client.models.generate_content(
                model=self._model,
                contents="ping",
                config=gtypes.GenerateContentConfig(max_output_tokens=1),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini API error: {exc}") from exc

    def chat(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> dict:
        from google.genai import types as gtypes
        _increment_counter()

        tool = _tools_to_gemini(TOOLS)
        config = gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[tool],
            thinking_config=gtypes.ThinkingConfig(include_thoughts=True),
        )

        contents = _history_to_gemini(history or [])
        contents.append({"role": "user", "parts": [{"text": message}]})

        tool_call_log: list[dict] = []

        while True:
            self._limiter.wait_for_tpm()
            self._limiter.wait_for_rpm()
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
            if response.usage_metadata:
                self._limiter.record_tokens(
                    getattr(response.usage_metadata, "total_token_count", 0) or 0
                )
            candidate = response.candidates[0]
            parts = candidate.content.parts

            # Check for function calls in any non-thought part
            fn_calls = [p for p in parts if p.function_call and p.function_call.name]
            if fn_calls:
                # Pass back the raw candidate.content so Gemini's thought_signature
                # is preserved — reconstructing the parts breaks thinking models
                contents.append(candidate.content)
                tool_results = []
                for p in fn_calls:
                    fc = p.function_call
                    args = dict(fc.args) if fc.args else {}
                    result = dispatch(fc.name, args)
                    tool_call_log.append({"name": fc.name, "args": args, "result": result})
                    tool_results.append({"function_response": {
                        "name": fc.name,
                        "response": {"result": json.dumps(result, default=str)},
                    }})
                contents.append({"role": "user", "parts": tool_results})
                continue

            # Separate thinking parts (thought=True) from reply parts
            thinking = "".join(
                p.text for p in parts
                if getattr(p, "thought", False) and getattr(p, "text", None)
            )
            reply = "".join(
                p.text for p in parts
                if not getattr(p, "thought", False) and getattr(p, "text", None)
            )
            return {"reply": reply, "thinking": thinking, "tool_calls": tool_call_log}


# ── Module-level singleton ─────────────────────────────────────────────────────

_ai_client: AIClient | GeminiClient | None = None


def get_ai_client() -> AIClient | GeminiClient:
    global _ai_client
    if _ai_client is None:
        from .config import get_gemini_api_key, get_gemini_model
        api_key = get_gemini_api_key()
        if api_key:
            _ai_client = GeminiClient(api_key, model=get_gemini_model())
        else:
            _ai_client = AIClient()
    return _ai_client


def get_backend_name() -> str:
    from .config import get_gemini_api_key
    return "gemini" if get_gemini_api_key() else "ollama"


def get_rate_limits() -> dict | None:
    """Return current rate limiter state for the active Gemini client, or None."""
    client = _ai_client
    if not isinstance(client, GeminiClient):
        return None
    lim = client._limiter
    limits = next(
        (v for k, v in _MODEL_LIMITS.items() if k in client._model),
        _DEFAULT_LIMITS,
    )
    return {
        "rpm_used": lim.current_rpm(),
        "rpm_limit": limits["rpm"],
        "tpm_used": lim.current_tpm(),
        "tpm_limit": limits["tpm"],
    }


# Models known to support thinking (thought parts in response)
_THINKING_MODELS = {"gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-thinking"}


def thinking_supported() -> bool:
    """Return True if the configured model returns thought parts."""
    from .config import get_gemini_api_key, get_gemini_model
    if not get_gemini_api_key():
        return True  # Ollama/qwen3 uses <think> tags — always supported
    model = get_gemini_model()
    return any(m in model for m in _THINKING_MODELS)
