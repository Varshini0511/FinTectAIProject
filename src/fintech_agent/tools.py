"""Fintech support tools: schemas + a Postgres-backed backend + dispatcher.

`TOOLS` is the function-schema list passed to the OpenAI-compatible chat API.
`dispatch()` executes a tool call and returns a string result.

Account, card, and transaction data live in Postgres (see `db.py` and
`scripts/setup_db.py`). `block_card` actually writes back to the database.

Tools that mutate account state (`block_card`, `file_dispute`) are flagged
`sensitive=True` so the agent harness can gate them behind human approval.
"""

from __future__ import annotations

from langsmith import traceable

from . import db, knowledge


def _fmt_money(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{currency} {abs(cents) / 100:,.2f}"


# --- Tool schemas (sent to the model) ----------------------------------------

# OpenAI / xAI function-calling format: each tool is
# {"type": "function", "function": {name, description, parameters}}.
def _fn(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


# Shared description for every ID argument. Deliberately gives NO example value,
# so the model can't fall back to a placeholder like "acc_1001" — it must use the
# ID the customer actually provided, or ask for it.
_ID_HINT = "as the customer provided it. Never guess or use a placeholder — if it is missing, ask the customer for it."

TOOLS: list[dict] = [
    _fn(
        "search_knowledge_base",
        "Search the NimbusPay policy knowledge base for fees, limits, timelines, "
        "and procedures. Call this for ANY policy question before answering — "
        "never state a policy from memory.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up, e.g. 'international transfer fee'"}
            },
            "required": ["query"],
        },
    ),
    _fn(
        "get_account_balance",
        "Get the current balance and tier for a customer account.",
        {
            "type": "object",
            "properties": {"account_id": {"type": "string", "description": _ID_HINT}},
            "required": ["account_id"],
        },
    ),
    _fn(
        "get_recent_transactions",
        "List the most recent transactions for an account.",
        {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": _ID_HINT},
                "limit": {"type": "integer", "description": "Max transactions to return (default 5)"},
            },
            "required": ["account_id"],
        },
    ),
    _fn(
        "get_card_status",
        "Get the status (active/frozen/blocked) of a card by its id.",
        {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": _ID_HINT},
                "card_id": {"type": "string", "description": _ID_HINT},
            },
            "required": ["account_id", "card_id"],
        },
    ),
    _fn(
        "block_card",
        "Block (permanently deactivate) a card — use for lost/stolen cards or "
        "confirmed fraud. This is irreversible; a new card must be issued. "
        "Confirm the customer's intent before calling.",
        {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": _ID_HINT},
                "card_id": {"type": "string", "description": _ID_HINT},
                "reason": {"type": "string", "enum": ["lost", "stolen", "fraud", "customer_request"]},
            },
            "required": ["account_id", "card_id", "reason"],
        },
    ),
    _fn(
        "file_dispute",
        "File a dispute against a settled transaction. Provisional credit is "
        "issued within 10 business days. Confirm the transaction with the "
        "customer before calling.",
        {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": _ID_HINT},
                "transaction_id": {"type": "string", "description": _ID_HINT},
                "reason": {"type": "string", "description": "Why the customer disputes the charge"},
            },
            "required": ["account_id", "transaction_id", "reason"],
        },
    ),
]

# Tools that change account state — the harness gates these.
SENSITIVE_TOOLS = {"block_card", "file_dispute"}


# --- Implementations ----------------------------------------------------------


@traceable(name="tool.search_knowledge_base", run_type="retriever")
def _search_kb(query: str) -> str:
    return knowledge.search(query)


@traceable(name="tool.get_account_balance", run_type="tool")
def _get_balance(account_id: str) -> str:
    acc = db.query_one(
        "SELECT name, tier, balance_cents, currency FROM accounts WHERE account_id = %s",
        (account_id,),
    )
    if not acc:
        return f"ERROR: no account {account_id}."
    return f"{acc['name']} ({acc['tier']}): balance {_fmt_money(acc['balance_cents'], acc['currency'])}."


@traceable(name="tool.get_recent_transactions", run_type="tool")
def _get_transactions(account_id: str, limit: int = 5) -> str:
    if not db.query_one("SELECT 1 FROM accounts WHERE account_id = %s", (account_id,)):
        return f"ERROR: no account {account_id}."
    txns = db.query_all(
        "SELECT id, txn_date, merchant, amount_cents FROM transactions "
        "WHERE account_id = %s ORDER BY txn_date DESC, id DESC LIMIT %s",
        (account_id, max(1, limit)),
    )
    if not txns:
        return "No transactions."
    return "\n".join(
        f"{t['id']} | {t['txn_date']} | {t['merchant']} | {_fmt_money(t['amount_cents'])}" for t in txns
    )


@traceable(name="tool.get_card_status", run_type="tool")
def _get_card_status(account_id: str, card_id: str) -> str:
    card = db.query_one(
        "SELECT last4, type, status FROM cards WHERE card_id = %s AND account_id = %s",
        (card_id, account_id),
    )
    if not card:
        return f"ERROR: no card {card_id} on {account_id}."
    return f"Card ending {card['last4']} ({card['type']}): {card['status']}."


@traceable(name="tool.block_card", run_type="tool")
def _block_card(account_id: str, card_id: str, reason: str) -> str:
    card = db.query_one(
        "SELECT last4 FROM cards WHERE card_id = %s AND account_id = %s",
        (card_id, account_id),
    )
    if not card:
        return f"ERROR: no card {card_id} on {account_id}."
    db.execute("UPDATE cards SET status = 'blocked' WHERE card_id = %s", (card_id,))  # real write-back
    return f"Card ending {card['last4']} blocked (reason: {reason}). A replacement card will be mailed in 5-7 days."


@traceable(name="tool.file_dispute", run_type="tool")
def _file_dispute(account_id: str, transaction_id: str, reason: str) -> str:
    txn = db.query_one(
        "SELECT 1 FROM transactions WHERE id = %s AND account_id = %s",
        (transaction_id, account_id),
    )
    if not txn:
        return f"ERROR: transaction {transaction_id} not found on {account_id}."
    ref = f"DSP-{transaction_id[-4:]}"
    return (
        f"Dispute {ref} filed for {transaction_id} (reason: {reason}). "
        "Provisional credit within 10 business days; resolution within 45 days."
    )


_DISPATCH = {
    "search_knowledge_base": lambda a: _search_kb(a["query"]),
    "get_account_balance": lambda a: _get_balance(a["account_id"]),
    "get_recent_transactions": lambda a: _get_transactions(a["account_id"], a.get("limit", 5)),
    "get_card_status": lambda a: _get_card_status(a["account_id"], a["card_id"]),
    "block_card": lambda a: _block_card(a["account_id"], a["card_id"], a["reason"]),
    "file_dispute": lambda a: _file_dispute(a["account_id"], a["transaction_id"], a["reason"]),
}


def dispatch(name: str, args: dict) -> str:
    """Execute a tool by name. Returns a string result (or an ERROR: string)."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"ERROR: unknown tool {name}."
    try:
        return fn(args)
    except Exception as exc:  # surface tool failures to the model, don't crash the loop
        return f"ERROR: tool {name} failed: {exc}"
