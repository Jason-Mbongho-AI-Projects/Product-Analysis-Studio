"""API key issuing and verification (spec 57).

A deliberate difference from user passwords: API keys are hashed with SHA-256,
not scrypt.

That is not an oversight. scrypt is slow *on purpose*, to make dictionary attack
against low-entropy human-chosen passwords expensive. An API key here is 256
bits from ``secrets.token_urlsafe`` — there is no dictionary to attack, so a
slow KDF would buy nothing while adding ~120ms to every single API request.
SHA-256 over high-entropy input is the appropriate choice.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.repositories import _row, _rows, new_id, utcnow

KEY_PREFIX = "pas_"
PREFIX_VISIBLE_CHARS = 8

VALID_SCOPES = frozenset({"read", "write"})


class ApiKeyError(ValueError):
    """The API key could not be issued or is not usable."""


@dataclass(frozen=True)
class IssuedKey:
    """Returned once, at creation. The secret is never retrievable again."""

    id: str
    secret: str
    prefix: str
    scopes: tuple[str, ...]


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_key() -> str:
    return f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"


def _parse_scopes(scopes: str) -> tuple[str, ...]:
    parsed = tuple(
        scope.strip().lower() for scope in (scopes or "").split(",") if scope.strip()
    )
    unknown = set(parsed) - VALID_SCOPES
    if unknown:
        raise ApiKeyError(f"Unknown scope(s): {', '.join(sorted(unknown))}")
    return parsed or ("read",)


def issue_key(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    name: str,
    scopes: str = "read",
    rate_per_minute: int = 60,
    expires_in_days: int | None = None,
    created_by: str | None = None,
) -> IssuedKey:
    """Create a key and return the secret exactly once."""
    parsed_scopes = _parse_scopes(scopes)
    secret = generate_key()

    if created_by and not conn.execute(
        "SELECT 1 FROM users WHERE id = ? LIMIT 1", (created_by,)
    ).fetchone():
        created_by = None

    expires_at = None
    if expires_in_days:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=int(expires_in_days))
        ).isoformat()

    key_id = new_id("key")
    conn.execute(
        """
        INSERT INTO api_keys (id, workspace_id, created_by, name, key_hash, key_prefix,
            scopes, rate_per_minute, revoked, expires_at, created_at)
        VALUES (?,?,?,?,?,?,?,?,0,?,?)
        """,
        (
            key_id,
            workspace_id,
            created_by,
            (name or "Unnamed key")[:120],
            hash_key(secret),
            secret[: len(KEY_PREFIX) + PREFIX_VISIBLE_CHARS],
            ",".join(parsed_scopes),
            max(1, int(rate_per_minute)),
            expires_at,
            utcnow(),
        ),
    )
    conn.commit()
    return IssuedKey(
        id=key_id,
        secret=secret,
        prefix=secret[: len(KEY_PREFIX) + PREFIX_VISIBLE_CHARS],
        scopes=parsed_scopes,
    )


def resolve_key(conn: sqlite3.Connection, secret: str) -> dict[str, Any] | None:
    """Return the key record for a presented secret, or None.

    Returns None for unknown, revoked and expired keys alike, so a caller cannot
    distinguish between them.
    """
    if not secret or not secret.startswith(KEY_PREFIX):
        return None

    digest = hash_key(secret)
    record = _row(
        conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (digest,))
    )
    if record is None or record["revoked"]:
        return None

    # Constant-time confirmation. The lookup already matched, but comparing
    # explicitly keeps the pattern correct if lookup ever becomes fuzzy.
    if not hmac.compare_digest(record["key_hash"], digest):
        return None

    if record["expires_at"]:
        try:
            expires = datetime.fromisoformat(record["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                return None
        except ValueError:
            return None

    record["scope_set"] = set(record["scopes"].split(","))
    return record


def touch_key(conn: sqlite3.Connection, key_id: str) -> None:
    conn.execute(
        "UPDATE api_keys SET last_used_at = ?, request_count = request_count + 1"
        " WHERE id = ?",
        (utcnow(), key_id),
    )
    conn.commit()


def list_keys(conn: sqlite3.Connection, workspace_id: str) -> list[dict[str, Any]]:
    """List keys without ever returning a secret."""
    return _rows(
        conn.execute(
            "SELECT id, name, key_prefix, scopes, rate_per_minute, revoked,"
            " last_used_at, request_count, expires_at, created_at"
            " FROM api_keys WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
    )


def revoke_key(conn: sqlite3.Connection, key_id: str) -> None:
    conn.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,))
    conn.commit()


def record_request(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    api_key_id: str | None,
    method: str,
    path: str,
    status: int,
    duration_ms: int,
) -> None:
    try:
        conn.execute(
            "INSERT INTO api_requests (id, workspace_id, api_key_id, method, path,"
            " status, duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_id("req"),
                workspace_id,
                api_key_id,
                method,
                path[:200],
                status,
                duration_ms,
                utcnow(),
            ),
        )
        conn.commit()
    except sqlite3.Error:  # pragma: no cover - logging must never break a request
        conn.rollback()


def usage_summary(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(*) AS requests, COALESCE(AVG(duration_ms), 0) AS avg_ms,"
        " SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors"
        " FROM api_requests WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()
    return dict(row) if row else {"requests": 0, "avg_ms": 0, "errors": 0}
