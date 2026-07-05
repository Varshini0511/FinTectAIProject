"""Postgres access for account / card / transaction data.

A thin helper layer over psycopg (v3). Opens a short-lived connection per call —
simple and thread-safe (each Streamlit rerun / request gets its own connection),
which is fine for a support-agent workload. Rows come back as dicts.

Connection string comes from settings.database_url (env: DATABASE_URL).
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from .config import settings


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """Return the first row as a dict, or None."""
    with _connect() as conn:
        return conn.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    """Return all rows as a list of dicts."""
    with _connect() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    """Run an INSERT/UPDATE/DELETE. Commits on success. Returns affected row count."""
    with _connect() as conn:
        cur = conn.execute(sql, params)
        # `with conn` commits automatically on clean exit.
        return cur.rowcount
