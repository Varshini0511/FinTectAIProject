"""LangSmith wiring.

`get_client()` returns an OpenAI client pointed at xAI's Grok endpoint, wrapped
by LangSmith so every `chat.completions.create` call is captured as a child run
in the trace tree — with the full request, response, latency, and token counts —
no manual logging needed.

Combined with the `@traceable` decorators on tools and on `FintechAgent.run`,
LangSmith renders the whole turn as a nested trace:

    agent.run
    ├── llm: chat.completions.create   (tokens, latency)
    ├── tool.search_knowledge_base     (input/output)
    ├── llm: chat.completions.create
    └── guardrail.validate_output

Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY in .env to send traces.
With tracing off, `wrap_openai` is a no-op passthrough.
"""

from __future__ import annotations

from openai import OpenAI

from .config import settings


def get_client() -> OpenAI:
    """Return an OpenAI-compatible client for xAI, LangSmith-wrapped when enabled."""
    base = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
    if not settings.tracing_enabled:
        return base
    try:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(base)
    except Exception:
        # langsmith not installed or wrap failed — degrade to an untraced client.
        return base
