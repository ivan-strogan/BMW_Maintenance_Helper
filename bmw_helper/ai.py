"""Ollama-powered LLM agent for the BMW Maintenance Helper.

Hard requirement: Ollama must be running and qwen3:8b must be pulled.
The app raises RuntimeError at startup if either condition is not met.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

import ollama


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
You are a BMW maintenance assistant. You help the owner understand their \
maintenance schedule, look up OEM parts in the RealOEM catalog, find \
aftermarket alternatives on RockAuto, and build service plans.

You have access to tools that fetch live data from the app. Always use \
the appropriate tool before answering. Be concise — the owner is \
technically knowledgeable. Quote part numbers and prices when you have them.

Rules:
- When asked what needs doing: call get_overdue_items first.
- When asked about a specific system: call get_schedule_status.
- When asked about parts: use search_catalog (format: "Group > Subgroup", \
  e.g. "Brakes > Front Brake Pads") then get_rockauto_alternatives for \
  aftermarket pricing.
- When asked to build a plan: call list_plans first to check for an \
  existing plan, then create_plan if needed. Search the catalog with \
  search_catalog to find the correct diagram, then call add_parts_to_plan \
  with the relevant OEM part numbers, descriptions, diagram_ref, and diag_id. \
  Confirm to the user which parts were added and what the plan is called.
- Never invent part numbers. Only add parts you found via search_catalog.
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


# ── Module-level singleton ─────────────────────────────────────────────────────

_ai_client: AIClient | None = None


def get_ai_client() -> AIClient:
    global _ai_client
    if _ai_client is None:
        _ai_client = AIClient()
    return _ai_client
