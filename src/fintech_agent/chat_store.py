"""Persist chat conversations in Postgres so they survive a browser refresh.

Each conversation has an id (kept in the URL). Messages are stored one row per
turn; the assistant's observability sidecar (tools/cost/pii/guardrail/trace) is
stored as JSONB in `meta` so the 🔍 panel can be re-rendered after a reload.

Note: user messages are stored **redacted** (PII already stripped by the agent),
so no personal data is persisted.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from . import db


def ensure_table() -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id              BIGSERIAL PRIMARY KEY,
            conversation_id TEXT        NOT NULL,
            role            TEXT        NOT NULL,
            content         TEXT        NOT NULL,
            meta            JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def append(conversation_id: str, role: str, content: str, meta: dict | None = None) -> None:
    db.execute(
        "INSERT INTO chat_messages (conversation_id, role, content, meta) VALUES (%s, %s, %s, %s)",
        (conversation_id, role, content, Jsonb(meta) if meta is not None else None),
    )


def load(conversation_id: str) -> list[dict]:
    """Return this conversation's messages as [{role, content, meta?}], oldest first."""
    rows = db.query_all(
        "SELECT role, content, meta FROM chat_messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    )
    messages = []
    for r in rows:
        msg = {"role": r["role"], "content": r["content"]}
        if r["meta"]:
            msg["meta"] = r["meta"]  # psycopg returns JSONB already parsed to a dict
        messages.append(msg)
    return messages


def clear(conversation_id: str) -> None:
    db.execute("DELETE FROM chat_messages WHERE conversation_id = %s", (conversation_id,))
