"""User authentication: salted password hashing + login verification.

Passwords are never stored — only a salted PBKDF2-SHA256 hash (stdlib, no extra
deps). Stored format: "<salt-hex>$<hash-hex>". Each user maps to exactly one
bank account (users.account_id), which the agent is then hard-scoped to.

Why hash at all? So a leaked database doesn't leak passwords: the hash can't be
reversed, the per-user salt defeats rainbow tables, and 200k iterations make
brute-forcing slow.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from . import db

_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return 'salt$hash' for storage. A fresh random salt per user."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a login attempt against the stored 'salt$hash'."""
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _ITERATIONS)
    # constant-time comparison — never compare secrets with ==
    return hmac.compare_digest(digest.hex(), digest_hex)


def authenticate(email: str, password: str) -> dict | None:
    """Return {email, account_id, name} on success, None on bad credentials."""
    row = db.query_one(
        "SELECT u.email, u.password_hash, u.account_id, a.name "
        "FROM users u JOIN accounts a ON a.account_id = u.account_id "
        "WHERE u.email = %s",
        (email.strip().lower(),),
    )
    if row and verify_password(password, row["password_hash"]):
        return {"email": row["email"], "account_id": row["account_id"], "name": row["name"]}
    return None
