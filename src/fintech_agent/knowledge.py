"""Tiny dependency-free retriever over the markdown knowledge base.

Splits the KB into `##` sections and ranks them by term overlap with the query.
This is deliberately simple — the point of the project is observability/eval/
safety, not retrieval. Swap in pgvector / a real vector store later without
touching the agent: just keep `search(query) -> str`.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .config import KNOWLEDGE_BASE_PATH

_WORD = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@lru_cache(maxsize=1)
def _sections() -> list[tuple[str, str]]:
    """Return [(heading, body)] parsed once from the KB file."""
    raw = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    sections: list[tuple[str, str]] = []
    current_heading = "Overview"
    current_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return [(h, b) for h, b in sections if b]


def search(query: str, top_k: int = 2) -> str:
    """Return the most relevant KB sections as a single context string."""
    query_terms = set(_tokenize(query))
    scored: list[tuple[int, str, str]] = []
    for heading, body in _sections():
        body_terms = _tokenize(heading + " " + body)
        overlap = sum(1 for t in body_terms if t in query_terms)
        if overlap:
            scored.append((overlap, heading, body))

    scored.sort(key=lambda s: s[0], reverse=True)
    top = scored[:top_k]
    if not top:
        return "NO_MATCH: The knowledge base has no section relevant to this query."

    return "\n\n".join(f"## {heading}\n{body}" for _, heading, body in top)
