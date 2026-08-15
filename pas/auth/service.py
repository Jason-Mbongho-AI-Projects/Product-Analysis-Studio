"""Authentication service: accounts, sessions, membership and audit.

Behaviours that are deliberate rather than incidental:

* Login failures are indistinguishable between "no such user" and "wrong
  password", in both message and timing, so login is not a user-enumeration
  oracle.
* Only a hash of each session token is stored.
* Repeated failures lock an account temporarily rather than forever, which
  stops brute force without handing an attacker a denial-of-service lever.
* The first account created becomes the workspace owner; later accounts get a
  configurable default role.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.repositories import _row, _rows, new_id, utcnow
from .models import (
    AuthError,
    Identity,
    Role,
    dev_identity,
    identity_for,
)
from .passwords import (
    PasswordError,
    StoredPassword,
    dummy_verify,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)

SESSION_TTL_HOURS = 12
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

#: Intentionally permissive. Strict RFC-5322 validation rejects addresses that
#: work fine in practice; the real check is whether the user can receive mail.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

#: One message for every failure mode a stranger can trigger.
_GENERIC_FAILURE = "Email or password is incorrect."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def hash_token(token: str) -> str:
    """Session tokens are stored hashed, never in the clear."""
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


class AuthService:
    """Account and session management for one database."""

    def __init__(self, conn: sqlite3.Connection, *, default_role: Role = Role.VIEWER):
        self._conn = conn
        self._default_role = default_role

    # -- audit -------------------------------------------------------------

    def _user_exists(self, user_id: str | None) -> bool:
        if not user_id:
            return False
        return (
            self._conn.execute(
                "SELECT 1 FROM users WHERE id = ? LIMIT 1", (user_id,)
            ).fetchone()
            is not None
        )

    def audit(
        self,
        *,
        workspace_id: str | None,
        identity: Identity | None,
        action: str,
        target_type: str = "",
        target_id: str | None = None,
        detail: str = "",
        succeeded: bool = True,
    ) -> None:
        """Record a state-changing action (spec 43).

        Best-effort by design. An audit write must never roll back the action it
        is describing - losing one log line is bad, but failing a user's
        legitimate operation because the logger tripped is worse. The actor is
        always preserved as text even when no user row can be referenced.
        """
        # The dev identity has no user row, and a session can outlive a deleted
        # account, so only reference a user_id that actually exists.
        user_id = identity.user_id if identity and not identity.is_dev else None
        if not self._user_exists(user_id):
            user_id = None

        try:
            self._conn.execute(
                """
                INSERT INTO audit_log (id, workspace_id, user_id, actor_label, action,
                    target_type, target_id, detail, succeeded, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("aud"),
                    workspace_id,
                    user_id,
                    identity.label if identity else "anonymous",
                    action,
                    target_type,
                    target_id,
                    detail[:2000],
                    1 if succeeded else 0,
                    utcnow(),
                ),
            )
            self._conn.commit()
        except sqlite3.Error:  # pragma: no cover - defensive
            self._conn.rollback()

    def audit_log(
        self, workspace_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        return _rows(
            self._conn.execute(
                "SELECT * FROM audit_log WHERE workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        )

    # -- accounts ----------------------------------------------------------

    def user_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return _row(self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)))

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        return _row(
            self._conn.execute(
                "SELECT * FROM users WHERE email_normalised = ?", (normalise_email(email),)
            )
        )

    def create_user(
        self,
        *,
        email: str,
        password: str,
        name: str = "",
        workspace_id: str,
        role: Role | None = None,
        is_superuser: bool = False,
    ) -> str:
        """Create an account and enrol it in a workspace.

        The first account in an empty system becomes the workspace owner -
        otherwise there would be nobody able to grant anyone else access.
        """
        email = (email or "").strip()
        if not _EMAIL_RE.match(email):
            raise AuthError("Enter a valid email address.")
        if self.find_by_email(email):
            raise AuthError("An account with that email already exists.")

        validate_password(password, email=email, name=name)
        stored = hash_password(password)

        first_user = self.user_count() == 0
        effective_role = Role.OWNER if first_user else (role or self._default_role)

        user_id = new_id("usr")
        now = utcnow()
        self._conn.execute(
            """
            INSERT INTO users (id, email, email_normalised, name, password_hash,
                password_salt, kdf, kdf_params, is_active, is_superuser,
                password_changed_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,1,?,?,?)
            """,
            (
                user_id,
                email,
                normalise_email(email),
                name.strip(),
                stored.hash_b64,
                stored.salt_b64,
                stored.kdf,
                stored.params_json,
                1 if (is_superuser or first_user) else 0,
                now,
                now,
            ),
        )
        self.add_member(workspace_id, user_id, effective_role)
        self._conn.commit()

        self.audit(
            workspace_id=workspace_id,
            identity=None,
            action="user.created",
            target_type="user",
            target_id=user_id,
            detail=f"{email} as {effective_role.value}",
        )
        return user_id

    def set_password(self, user_id: str, new_password: str) -> None:
        user = self.get_user(user_id)
        if user is None:
            raise AuthError("Account not found.")
        validate_password(new_password, email=user["email"], name=user["name"])
        stored = hash_password(new_password)
        self._conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, kdf = ?,"
            " kdf_params = ?, password_changed_at = ? WHERE id = ?",
            (
                stored.hash_b64,
                stored.salt_b64,
                stored.kdf,
                stored.params_json,
                utcnow(),
                user_id,
            ),
        )
        # A password change invalidates every existing session for that user.
        self.revoke_all_sessions(user_id)
        self._conn.commit()

    def change_password(self, user_id: str, current: str, new_password: str) -> None:
        user = self.get_user(user_id)
        if user is None or not verify_password(current, _stored_from(user)):
            raise AuthError("Your current password is incorrect.")
        if current == new_password:
            raise PasswordError("The new password must differ from the current one.")
        self.set_password(user_id, new_password)

    def set_active(self, user_id: str, active: bool) -> None:
        self._conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id)
        )
        if not active:
            self.revoke_all_sessions(user_id)
        self._conn.commit()

    # -- login -------------------------------------------------------------

    def authenticate(self, email: str, password: str, user_agent: str = "") -> str:
        """Verify credentials and return an opaque session token.

        Every failure raises the same message. The only distinguishable outcome
        is a lockout, which the account holder needs to be told about.
        """
        user = self.find_by_email(email)

        if user is None:
            # Equalise timing so a missing account is not detectable.
            dummy_verify()
            raise AuthError(_GENERIC_FAILURE)

        locked_until = _parse(user["locked_until"])
        if locked_until and locked_until > _now():
            remaining = int((locked_until - _now()).total_seconds() // 60) + 1
            raise AuthError(
                f"Too many failed attempts. Try again in {remaining} minute(s)."
            )

        if not user["is_active"]:
            dummy_verify()
            raise AuthError(_GENERIC_FAILURE)

        if not verify_password(password, _stored_from(user)):
            self._register_failure(user)
            raise AuthError(_GENERIC_FAILURE)

        # Opportunistically upgrade a hash created under weaker parameters.
        if needs_rehash(_stored_from(user)):
            stored = hash_password(password)
            self._conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ?, kdf = ?,"
                " kdf_params = ? WHERE id = ?",
                (stored.hash_b64, stored.salt_b64, stored.kdf, stored.params_json, user["id"]),
            )

        self._conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ?"
            " WHERE id = ?",
            (utcnow(), user["id"]),
        )
        token = self._create_session(user["id"], user_agent)
        self._conn.commit()

        self.audit(
            workspace_id=None,
            identity=None,
            action="auth.login",
            target_type="user",
            target_id=user["id"],
            detail=user["email"],
        )
        return token

    def _register_failure(self, user: dict[str, Any]) -> None:
        attempts = int(user["failed_attempts"]) + 1
        locked_until = None
        if attempts >= MAX_FAILED_ATTEMPTS:
            locked_until = (_now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            attempts = 0  # reset the counter; the lock is the deterrent
        self._conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, user["id"]),
        )
        self._conn.commit()
        self.audit(
            workspace_id=None,
            identity=None,
            action="auth.login_failed",
            target_type="user",
            target_id=user["id"],
            detail="locked" if locked_until else f"attempt {attempts}",
            succeeded=False,
        )

    # -- sessions ----------------------------------------------------------

    def _create_session(self, user_id: str, user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        self._conn.execute(
            "INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at,"
            " last_seen_at, revoked, user_agent) VALUES (?,?,?,?,?,?,0,?)",
            (
                new_id("ses"),
                user_id,
                hash_token(token),
                now.isoformat(),
                (now + timedelta(hours=SESSION_TTL_HOURS)).isoformat(),
                now.isoformat(),
                user_agent[:300],
            ),
        )
        return token

    def resolve_session(self, token: str) -> dict[str, Any] | None:
        """Return the session row for a token, or None if it is not usable."""
        if not token:
            return None
        session = _row(
            self._conn.execute(
                "SELECT * FROM sessions WHERE token_hash = ?", (hash_token(token),)
            )
        )
        if session is None or session["revoked"]:
            return None

        expires = _parse(session["expires_at"])
        if expires is None or expires <= _now():
            return None

        self._conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
            (utcnow(), session["id"]),
        )
        self._conn.commit()
        return session

    def revoke_session(self, token: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (hash_token(token),)
        )
        self._conn.commit()

    def revoke_all_sessions(self, user_id: str) -> None:
        self._conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def purge_expired_sessions(self) -> int:
        cursor = self._conn.execute(
            "DELETE FROM sessions WHERE datetime(expires_at) < datetime('now')"
        )
        self._conn.commit()
        return cursor.rowcount

    # -- membership --------------------------------------------------------

    def add_member(self, workspace_id: str, user_id: str, role: Role) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO workspace_members (workspace_id, user_id, role,"
            " created_at) VALUES (?,?,?,?)",
            (workspace_id, user_id, Role(role).value, utcnow()),
        )
        self._conn.commit()

    def remove_member(self, workspace_id: str, user_id: str) -> None:
        """Remove a member, refusing to leave a workspace without an owner."""
        if self._owner_count(workspace_id) <= 1 and self.role_for(workspace_id, user_id) is Role.OWNER:
            raise AuthError("A workspace must keep at least one owner.")
        self._conn.execute(
            "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        )
        self._conn.commit()

    def set_role(self, workspace_id: str, user_id: str, role: Role) -> None:
        if (
            self.role_for(workspace_id, user_id) is Role.OWNER
            and Role(role) is not Role.OWNER
            and self._owner_count(workspace_id) <= 1
        ):
            raise AuthError("A workspace must keep at least one owner.")
        self.add_member(workspace_id, user_id, role)

    def _owner_count(self, workspace_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM workspace_members WHERE workspace_id = ? AND role = ?",
            (workspace_id, Role.OWNER.value),
        ).fetchone()["n"]

    def role_for(self, workspace_id: str, user_id: str) -> Role | None:
        row = self._conn.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        ).fetchone()
        if row is None:
            return None
        try:
            return Role(row["role"])
        except ValueError:
            return None

    def members(self, workspace_id: str) -> list[dict[str, Any]]:
        return _rows(
            self._conn.execute(
                """
                SELECT u.id, u.email, u.name, u.is_active, u.last_login_at,
                       m.role, m.created_at
                FROM workspace_members m
                JOIN users u ON u.id = m.user_id
                WHERE m.workspace_id = ?
                ORDER BY m.created_at
                """,
                (workspace_id,),
            )
        )

    def workspaces_for(self, user_id: str) -> list[dict[str, Any]]:
        return _rows(
            self._conn.execute(
                """
                SELECT w.id, w.name, m.role
                FROM workspace_members m
                JOIN workspaces w ON w.id = m.workspace_id
                WHERE m.user_id = ?
                ORDER BY w.created_at
                """,
                (user_id,),
            )
        )

    # -- identity resolution ----------------------------------------------

    def identity_from_token(self, token: str, workspace_id: str) -> Identity | None:
        """Resolve a session token into an :class:`Identity` for a workspace.

        Returns None when the session is invalid, the account is inactive, or
        the user is not a member of that workspace - membership is what
        enforces tenant isolation.
        """
        session = self.resolve_session(token)
        if session is None:
            return None

        user = self.get_user(session["user_id"])
        if user is None or not user["is_active"]:
            return None

        role = self.role_for(workspace_id, user["id"])
        if role is None:
            return None

        return identity_for(
            user_id=user["id"],
            email=user["email"],
            name=user["name"],
            workspace_id=workspace_id,
            role=role,
            session_id=session["id"],
        )

    def open_identity(self, workspace_id: str) -> Identity:
        """The development identity used when authentication is disabled."""
        return dev_identity(workspace_id)


def _stored_from(user: dict[str, Any]) -> StoredPassword:
    return StoredPassword(
        hash_b64=user["password_hash"],
        salt_b64=user["password_salt"],
        kdf=user["kdf"],
        params_json=user["kdf_params"],
    )
