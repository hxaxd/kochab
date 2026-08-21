from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kochab.core.plugins import Plugins


@dataclass
class LoopResult:
    messages: list[dict[str, Any]]
    steps: int
    reason: str
    outcome: dict[str, Any] | None = None
    error: str | None = None


def run(
    llm: Any,
    tools: Any,
    messages: list[dict[str, Any]],
    plugins: Plugins | None = None,
    max_steps: int = 40,
    on_event: Any = None,
) -> LoopResult:
    """Perceive → think → tool → loop. Intentionally one screen."""
    plugins = plugins or Plugins()
    for step in range(max_steps):
        try:
            messages = plugins.compress(messages)
            reply = llm.chat(messages, tools.schemas())
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if on_event:
                on_event("error", error)
            return LoopResult(messages=messages, steps=step, reason="error", error=error)
        messages.append(reply)
        if on_event:
            on_event("model", reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            return LoopResult(messages=messages, steps=step + 1, reason="no_tools")
        for call in calls:
            try:
                result = tools.dispatch(call)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if on_event:
                    on_event("error", error)
                return LoopResult(messages=messages, steps=step + 1, reason="error", error=error)
            messages.append(result)
            if on_event:
                fn = call.get("function") or {}
                on_event(
                    "tool",
                    {"name": fn.get("name"), "content": result.get("content", "")},
                )
            if getattr(tools, "finished", False):
                return LoopResult(
                    messages=messages,
                    steps=step + 1,
                    reason="finished",
                    outcome=getattr(tools, "outcome", None),
                )
        plugins.after_step(messages)
    return LoopResult(messages=messages, steps=max_steps, reason="max_steps")
