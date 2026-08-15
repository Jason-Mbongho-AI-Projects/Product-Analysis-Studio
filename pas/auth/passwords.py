"""Password hashing and verification.

Uses ``hashlib.scrypt`` - memory-hard, in the standard library, and therefore
no new dependency. Parameters are stored per hash so the work factor can be
raised later and existing hashes upgraded transparently on next login.

Nothing here logs, returns or formats a password.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import unicodedata
from dataclasses import dataclass

#: n=2^15 costs roughly 120ms per hash on a modern desktop - slow enough to
#: make offline cracking expensive, fast enough for interactive login.
DEFAULT_PARAMS = {"n": 2**15, "r": 8, "p": 1, "dklen": 32}

#: scrypt needs 128 * n * r bytes; give it headroom or it raises.
_MAXMEM = 256 * 1024 * 1024

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024

#: Passwords that are long enough to pass the length rule but are still among
#: the first things any attacker tries.
_OBVIOUS_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "passw0rd123",
        "123456789012", "1234567890123", "qwertyuiop12",
        "letmein12345", "administrator", "adminadmin12",
        "changeme1234", "welcome12345", "iloveyou1234",
        "productanalysis", "productanalysisstudio",
    }
)


class PasswordError(ValueError):
    """The supplied password is not acceptable."""


@dataclass(frozen=True)
class StoredPassword:
    hash_b64: str
    salt_b64: str
    kdf: str
    params_json: str


def _normalise(password: str) -> bytes:
    """NFKC-normalise so visually identical passwords hash identically."""
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def validate_password(password: str, *, email: str = "", name: str = "") -> None:
    """Raise :class:`PasswordError` if the password is unacceptable.

    Length is the dominant factor in resisting offline attack, so the rule is a
    generous minimum length rather than a composition rule that mostly produces
    ``Password1!``.
    """
    if not password or password.strip() != password.rstrip("\n"):
        password = password or ""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. "
            "A short phrase you can remember beats a short complex string."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordError("That password is unreasonably long.")

    lowered = password.lower()
    if lowered in _OBVIOUS_PASSWORDS:
        raise PasswordError("That password is too common. Choose something else.")
    if len(set(password)) < 5:
        raise PasswordError("That password repeats too few distinct characters.")

    local_part = (email or "").split("@")[0].lower()
    if local_part and len(local_part) >= 4 and local_part in lowered:
        raise PasswordError("Your password must not contain your email address.")
    if name and len(name) >= 4 and name.lower() in lowered:
        raise PasswordError("Your password must not contain your name.")


def hash_password(password: str, params: dict | None = None) -> StoredPassword:
    """Hash a password with a fresh random salt."""
    params = {**DEFAULT_PARAMS, **(params or {})}
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        _normalise(password),
        salt=salt,
        n=params["n"],
        r=params["r"],
        p=params["p"],
        dklen=params["dklen"],
        maxmem=_MAXMEM,
    )
    return StoredPassword(
        hash_b64=base64.b64encode(digest).decode(),
        salt_b64=base64.b64encode(salt).decode(),
        kdf="scrypt",
        params_json=json.dumps(params, sort_keys=True),
    )


def verify_password(password: str, stored: StoredPassword) -> bool:
    """Constant-time verification of a password against a stored hash."""
    try:
        params = {**DEFAULT_PARAMS, **json.loads(stored.params_json or "{}")}
        salt = base64.b64decode(stored.salt_b64)
        expected = base64.b64decode(stored.hash_b64)
    except (ValueError, json.JSONDecodeError):
        return False

    if stored.kdf != "scrypt":
        return False

    try:
        candidate = hashlib.scrypt(
            _normalise(password),
            salt=salt,
            n=params["n"],
            r=params["r"],
            p=params["p"],
            dklen=len(expected) or params["dklen"],
            maxmem=_MAXMEM,
        )
    except ValueError:
        return False

    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: StoredPassword) -> bool:
    """True when a stored hash uses weaker parameters than the current default."""
    try:
        params = json.loads(stored.params_json or "{}")
    except json.JSONDecodeError:
        return True
    if stored.kdf != "scrypt":
        return True
    return int(params.get("n", 0)) < DEFAULT_PARAMS["n"]


def dummy_verify() -> None:
    """Burn equivalent work when a user does not exist.

    Without this, a missing account returns visibly faster than a wrong
    password, which turns login into a user-enumeration oracle.
    """
    hashlib.scrypt(
        b"timing-equalisation",
        salt=b"0123456789abcdef",
        n=DEFAULT_PARAMS["n"],
        r=DEFAULT_PARAMS["r"],
        p=DEFAULT_PARAMS["p"],
        dklen=DEFAULT_PARAMS["dklen"],
        maxmem=_MAXMEM,
    )
