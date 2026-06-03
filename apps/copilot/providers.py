"""LLM provider seam for the AI co-pilot (M12).

Two providers behind one interface — mirrors the SMS/push seams:
- **StubLlmProvider** (default, no key): deterministic keyword routing over the
  same tool executors the real model would call. Lets the whole co-pilot —
  endpoints, tools, clients, tests — run and ship without an API key or spend.
- **ClaudeLlmProvider**: the real Anthropic API (claude-opus-4-8) with a manual
  tool-use loop, a prompt-cached system prompt, and base64 vision for crop /
  livestock disease photos. Lazy-imports `anthropic` so dev/test without the
  package (or the key) still loads this module.

Flip via GITAKO['LLM_PROVIDER'] = "claude" once ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from django.conf import settings

log = logging.getLogger("gitako.copilot")

# A tool executor runs one tool call server-side (scoped to a farm/user) and
# returns a JSON-serialisable string for the model / reply.
ToolExecutor = Callable[[str, dict], str]


class LlmProvider(Protocol):
    def chat(
        self,
        *,
        system: str,
        user_message: str,
        history: list[dict],
        tool_specs: list[dict],
        tool_executor: ToolExecutor,
    ) -> dict: ...

    def diagnose(self, *, image_b64: str, media_type: str, prompt: str) -> dict: ...


# ---------- Stub (deterministic, no key) ----------

class StubLlmProvider:
    """Deterministic co-pilot. Routes the question to a tool by keyword, runs it,
    and templates a reply. Not an LLM — a believable stand-in for dev/tests and
    a graceful fallback when no key is configured."""

    ROUTES: list[tuple[tuple[str, ...], str]] = [
        (("cost", "spend", "spent", "profit", "margin", "cash", "money", "revenue", "income", "expense"),
         "get_financial_summary"),
        (("fcr", "mortality", "yield", "weight", "performance", "metric", "survival", "adg", "gain"),
         "get_enterprise_metrics"),
        (("due", "upcoming", "task", "schedule", "vaccinat", "deworm", "calendar", "overdue"),
         "get_upcoming_tasks"),
        (("stock", "inventory", "reorder", "low", "feed left", "running out"),
         "get_low_stock"),
        (("enterprise", "flock", "herd", "pond", "crop", "list", "what do i have"),
         "list_enterprises"),
    ]

    def chat(self, *, system, user_message, history, tool_specs, tool_executor):
        msg = user_message.lower()
        tool = next((name for kws, name in self.ROUTES if any(k in msg for k in kws)), None)
        if tool is None:
            return {
                "reply": (
                    "I can answer questions about your farm's money, enterprise "
                    "performance (FCR, mortality, yield), upcoming tasks, and low "
                    "stock. Try: \"How is my cash position?\" or \"Which tasks are due?\""
                ),
                "used_tools": [],
            }
        result = tool_executor(tool, {})
        return {
            "reply": f"Here's what I found:\n\n{result}",
            "used_tools": [tool],
            "stub": True,
        }

    def diagnose(self, *, image_b64, media_type, prompt):
        return {
            "diagnosis": "Image diagnostics are not available in stub mode.",
            "confidence": "n/a",
            "treatment": (
                "Set LLM_PROVIDER=claude and ANTHROPIC_API_KEY to enable photo "
                "disease/pest diagnostics. Meanwhile, consult your vet or extension officer."
            ),
            "stub": True,
        }


# ---------- Claude (real Anthropic API) ----------

class ClaudeLlmProvider:
    MAX_TOOL_ITERATIONS = 6

    def _client(self):
        import anthropic  # lazy — only needed when this provider is active

        key = settings.GITAKO.get("ANTHROPIC_API_KEY") or None
        return anthropic.Anthropic(api_key=key)

    @property
    def _model(self) -> str:
        return settings.GITAKO.get("ANTHROPIC_MODEL", "claude-opus-4-8")

    def chat(self, *, system, user_message, history, tool_specs, tool_executor):
        client = self._client()
        messages: list[dict[str, Any]] = list(history) + [
            {"role": "user", "content": user_message},
        ]
        used: list[str] = []

        for _ in range(self.MAX_TOOL_ITERATIONS):
            resp = client.messages.create(
                model=self._model,
                max_tokens=2048,
                # Frozen system prompt cached as a prefix (see prompt-caching).
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tool_specs,
                messages=messages,
            )
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        used.append(block.name)
                        output = tool_executor(block.name, dict(block.input))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        })
                messages.append({"role": "user", "content": tool_results})
                continue
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"reply": text, "used_tools": used}

        return {"reply": "I wasn't able to finish that — please try rephrasing.", "used_tools": used}

    def diagnose(self, *, image_b64, media_type, prompt):
        from .prompts import DIAGNOSE_SYSTEM

        client = self._client()
        resp = client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=[{"type": "text", "text": DIAGNOSE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt or "Diagnose any disease or pest visible in this farm photo."},
                ],
            }],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return {"diagnosis": text, "confidence": "model", "treatment": ""}


def get_llm_provider() -> LlmProvider:
    name = settings.GITAKO.get("LLM_PROVIDER", "stub")
    if name == "claude":
        return ClaudeLlmProvider()
    return StubLlmProvider()
