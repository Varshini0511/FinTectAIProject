"""Create the nimbuspay database, its tables, and seed the demo data.

Run once (idempotent — safe to re-run; it resets the demo data):
    python scripts/setup_db.py

Reads the connection string from .env (DATABASE_URL). If the target database
doesn't exist yet, it is created automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from fintech_agent.config import settings  # noqa: E402

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS accounts (
        account_id    TEXT PRIMARY KEY,
        name          TEXT   NOT NULL,
        tier          TEXT   NOT NULL,
        balance_cents BIGINT NOT NULL,
        currency      TEXT   NOT NULL DEFAULT 'USD'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cards (
        card_id    TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(account_id),
        last4      TEXT NOT NULL,
        type       TEXT NOT NULL,
        status     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id           TEXT PRIMARY KEY,
        account_id   TEXT   NOT NULL REFERENCES accounts(account_id),
        txn_date     DATE   NOT NULL,
        merchant     TEXT   NOT NULL,
        amount_cents BIGINT NOT NULL
    )
    """,
    # Login users — each maps to exactly one account (per-user data scoping).
    """
    CREATE TABLE IF NOT EXISTS users (
        email         TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        account_id    TEXT NOT NULL REFERENCES accounts(account_id)
    )
    """,
    # Persisted chat history (survives browser refresh). Not truncated on re-seed.
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id              BIGSERIAL PRIMARY KEY,
        conversation_id TEXT        NOT NULL,
        role            TEXT        NOT NULL,
        content         TEXT        NOT NULL,
        meta            JSONB,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]

ACCOUNTS = [
    ("acc_1001", "Alex Rivera", "standard", 482_355, "USD"),
    ("acc_1002", "Priya Shah", "premium", 1_905_012, "USD"),
]

CARDS = [
    ("card_8842", "acc_1001", "8842", "physical", "active"),
    ("card_2207", "acc_1001", "2207", "virtual", "active"),
    ("card_5519", "acc_1002", "5519", "physical", "frozen"),
]

# Demo logins (email, plain password — hashed at seed time, account).
USERS = [
    ("alex@nimbuspay.demo", "demo1234", "acc_1001"),
    ("priya@nimbuspay.demo", "demo1234", "acc_1002"),
]

TRANSACTIONS = [
    ("txn_5501", "acc_1001", "2026-06-20", "Blue Bottle Coffee", -650),
    ("txn_5502", "acc_1001", "2026-06-19", "Payroll — Acme Corp", 320_000),
    ("txn_5503", "acc_1001", "2026-06-18", "Unknown — 0x99 Online", -129_900),
    ("txn_5504", "acc_1001", "2026-06-17", "Whole Foods Market", -8_412),
    ("txn_7701", "acc_1002", "2026-06-21", "Apple Store", -99_900),
    ("txn_7702", "acc_1002", "2026-06-20", "Transfer to J. Doe", -500_000),
]


def ensure_database() -> None:
    """Create the target database if it doesn't already exist.

    On managed Postgres (Neon, Supabase, RDS) you usually can't CREATE DATABASE
    and the database in your connection string already exists — so we tolerate a
    failure here and just proceed to create the tables in that database.
    """
    target = conninfo_to_dict(settings.database_url).get("dbname", "nimbuspay")
    admin = make_conninfo(settings.database_url, dbname="postgres")
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
            if exists:
                print(f"database '{target}' already exists")
            else:
                conn.execute(f'CREATE DATABASE "{target}"')
                print(f"created database '{target}'")
    except Exception as exc:
        print(f"skipping database creation (managed host?): {exc}")
        print(f"assuming database '{target}' already exists — creating tables in it")


def setup() -> None:
    ensure_database()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        for ddl in TABLES:
            conn.execute(ddl)
        conn.execute("TRUNCATE accounts, cards, transactions, users CASCADE")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO accounts (account_id, name, tier, balance_cents, currency) VALUES (%s, %s, %s, %s, %s)",
                ACCOUNTS,
            )
            from fintech_agent.auth import hash_password

            cur.executemany(
                "INSERT INTO users (email, password_hash, account_id) VALUES (%s, %s, %s)",
                [(email, hash_password(pw), acc) for email, pw, acc in USERS],
            )
            cur.executemany(
                "INSERT INTO cards (card_id, account_id, last4, type, status) VALUES (%s, %s, %s, %s, %s)",
                CARDS,
            )
            cur.executemany(
                "INSERT INTO transactions (id, account_id, txn_date, merchant, amount_cents) VALUES (%s, %s, %s, %s, %s)",
                TRANSACTIONS,
            )
    print(f"seeded {len(ACCOUNTS)} accounts, {len(CARDS)} cards, "
          f"{len(TRANSACTIONS)} transactions, {len(USERS)} users")
    print("[OK] database ready")


if __name__ == "__main__":
    setup()
