"""A tiny local trace recorder — the self-hosted version of a LangSmith trace.

A `Trace` records one "span" per stage of `agent.run` (PII, each LLM call, each
tool call, guardrails), capturing the stage's **latency** and any **metadata**
you attach (tokens, tool input/output, the model's decision). `render_tree()`
draws those spans as an indented tree — the same information LangSmith shows in
its dashboard, but printed locally with no account required.

Usage:
    trace = Trace()
    with trace.span("pii.redact") as sp:
        ...
        sp.data["entities"] = [...]      # attach anything you want shown
    spans = trace.to_list()              # serializable; store on AgentResult
    print(render_tree(spans))            # draw the tree
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Span:
    name: str
    duration_ms: float = 0.0
    data: dict = field(default_factory=dict)


class Trace:
    """Collects timed spans for one agent run."""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **data):
        """Time the enclosed block and record it as a span. Mutate `sp.data` inside."""
        sp = Span(name=name, data=dict(data))
        self.spans.append(sp)
        start = time.perf_counter()
        try:
            yield sp
        finally:
            sp.duration_ms = (time.perf_counter() - start) * 1000.0

    def to_list(self) -> list[dict]:
        return [{"name": s.name, "duration_ms": round(s.duration_ms, 1), "data": s.data} for s in self.spans]


def _fmt_value(v) -> str:
    if isinstance(v, (dict, list)):
        v = json.dumps(v, separators=(",", ":"))
    v = str(v)
    return v if len(v) <= 70 else v[:67] + "..."


def render_tree(spans: list[dict], header: str = "agent.run", total: str | None = None) -> str:
    """Draw spans as an indented tree (string)."""
    root = header + (f"   [{total}]" if total else "")
    lines = [root]
    n = len(spans)
    for i, s in enumerate(spans):
        branch = "\\-" if i == n - 1 else "|-"  # ASCII so it prints on any console
        meta = "  ".join(f"{k}={_fmt_value(v)}" for k, v in s["data"].items())
        lines.append(f"   {branch} {s['name']:<26} {s['duration_ms']:>7.1f} ms   {meta}")
    return "\n".join(lines)
