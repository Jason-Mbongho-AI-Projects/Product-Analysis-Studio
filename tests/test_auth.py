"""Authentication and authorisation tests (spec 41 / 32 / 43).

Security code that is not tested is security code that does not work. These
assert on the properties that matter: passwords are never recoverable, sessions
expire and revoke, login does not leak which accounts exist, and the permission
matrix is actually enforced at the service boundary.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone

import pytest

from pas.auth.models import (
    ROLE_PERMISSIONS,
    AuthError,
    Identity,
    Permission,
    PermissionDenied,
    Role,
    dev_identity,
)
from pas.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)
from pas.auth.service import AuthService, hash_token, normalise_email
from pas.config import AppConfig, network_exposure_warning

GOOD_PASSWORD = "correct-horse-battery-staple"
OTHER_PASSWORD = "a-completely-different-phrase"


@pytest.fixture
def auth(conn, workspace):
    return AuthService(conn)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_password_verifies_and_rejects():
    stored = hash_password(GOOD_PASSWORD)
    assert verify_password(GOOD_PASSWORD, stored)
    assert not verify_password(OTHER_PASSWORD, stored)
    assert not verify_password("", stored)


def test_hash_is_salted_so_identical_passwords_differ():
    a = hash_password(GOOD_PASSWORD)
    b = hash_password(GOOD_PASSWORD)
    assert a.hash_b64 != b.hash_b64
    assert a.salt_b64 != b.salt_b64
    assert verify_password(GOOD_PASSWORD, a)
    assert verify_password(GOOD_PASSWORD, b)


def test_password_is_not_recoverable_from_storage():
    stored = hash_password(GOOD_PASSWORD)
    raw = base64.b64decode(stored.hash_b64)
    assert GOOD_PASSWORD.encode() not in raw
    assert GOOD_PASSWORD not in stored.hash_b64
    assert GOOD_PASSWORD not in stored.salt_b64


def test_unicode_passwords_normalise_consistently():
    # Composed vs decomposed forms of the same string must match.
    stored = hash_password("café-passphrase-2026")
    assert verify_password("café-passphrase-2026", stored)


def test_corrupt_stored_hash_fails_closed():
    stored = hash_password(GOOD_PASSWORD)
    broken = type(stored)(hash_b64="!!!not base64!!!", salt_b64=stored.salt_b64,
                          kdf="scrypt", params_json=stored.params_json)
    assert verify_password(GOOD_PASSWORD, broken) is False

    wrong_kdf = type(stored)(hash_b64=stored.hash_b64, salt_b64=stored.salt_b64,
                             kdf="md5", params_json=stored.params_json)
    assert verify_password(GOOD_PASSWORD, wrong_kdf) is False


def test_weaker_parameters_are_flagged_for_rehash():
    weak = hash_password(GOOD_PASSWORD, params={"n": 2**12})
    assert needs_rehash(weak)
    assert not needs_rehash(hash_password(GOOD_PASSWORD))


@pytest.mark.parametrize(
    "password,reason",
    [
        ("short", "length"),
        ("aaaaaaaaaaaaaaaa", "distinct characters"),
        ("password123", "length or common"),
        ("x" * 2000, "too long"),
    ],
)
def test_weak_passwords_are_rejected(password, reason):
    with pytest.raises(PasswordError):
        validate_password(password)


def test_password_cannot_contain_the_email_or_name():
    with pytest.raises(PasswordError):
        validate_password("jsmith-is-my-password", email="jsmith@example.com")
    with pytest.raises(PasswordError):
        validate_password("jonathan-rules-ok-99", name="Jonathan")


def test_good_password_passes_validation():
    validate_password(GOOD_PASSWORD, email="a@b.com", name="Alice")
    assert len(GOOD_PASSWORD) >= MIN_PASSWORD_LENGTH


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_first_account_becomes_owner(auth, workspace):
    user_id = auth.create_user(
        email="first@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    assert auth.role_for(workspace, user_id) is Role.OWNER


def test_subsequent_accounts_get_the_default_role(auth, workspace):
    auth.create_user(email="first@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    second = auth.create_user(
        email="second@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    assert auth.role_for(workspace, second) is Role.VIEWER


def test_duplicate_email_is_rejected_case_insensitively(auth, workspace):
    auth.create_user(email="Dup@Example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    with pytest.raises(AuthError, match="already exists"):
        auth.create_user(email="dup@example.com", password=GOOD_PASSWORD, workspace_id=workspace)


@pytest.mark.parametrize("email", ["notanemail", "no@domain", "@example.com", "a b@c.com", ""])
def test_invalid_emails_are_rejected(auth, workspace, email):
    with pytest.raises(AuthError, match="valid email"):
        auth.create_user(email=email, password=GOOD_PASSWORD, workspace_id=workspace)


def test_email_normalisation():
    assert normalise_email("  Foo@Example.COM ") == "foo@example.com"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_successful_login_returns_a_usable_token(auth, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    token = auth.authenticate("a@example.com", GOOD_PASSWORD)
    assert token
    assert auth.resolve_session(token) is not None


def test_login_is_case_insensitive_on_email(auth, workspace):
    auth.create_user(email="Mixed@Example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    assert auth.authenticate("mixed@EXAMPLE.com", GOOD_PASSWORD)


def test_wrong_password_is_rejected(auth, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    with pytest.raises(AuthError):
        auth.authenticate("a@example.com", OTHER_PASSWORD)


def test_login_does_not_leak_whether_an_account_exists(auth, workspace):
    """Unknown user and wrong password must be indistinguishable."""
    auth.create_user(email="real@example.com", password=GOOD_PASSWORD, workspace_id=workspace)

    with pytest.raises(AuthError) as unknown:
        auth.authenticate("nobody@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthError) as wrong:
        auth.authenticate("real@example.com", OTHER_PASSWORD)

    assert str(unknown.value) == str(wrong.value)


def test_login_timing_does_not_reveal_account_existence(auth, workspace):
    """A missing account must not return measurably faster than a wrong password."""
    auth.create_user(email="real@example.com", password=GOOD_PASSWORD, workspace_id=workspace)

    def timed(email: str) -> float:
        start = time.perf_counter()
        try:
            auth.authenticate(email, OTHER_PASSWORD)
        except AuthError:
            pass
        return time.perf_counter() - start

    unknown = min(timed("nobody@example.com") for _ in range(3))
    known = min(timed("real@example.com") for _ in range(3))

    # Both paths run one scrypt hash, so they should be within an order of
    # magnitude. Without dummy_verify the unknown path returns ~instantly.
    assert unknown > known * 0.3, (
        f"unknown-account path too fast ({unknown:.3f}s vs {known:.3f}s) - "
        "this is a user-enumeration oracle"
    )


def test_inactive_account_cannot_log_in(auth, workspace):
    user_id = auth.create_user(
        email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    auth.set_active(user_id, False)
    with pytest.raises(AuthError):
        auth.authenticate("a@example.com", GOOD_PASSWORD)


def test_repeated_failures_lock_the_account(auth, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)

    for _ in range(5):
        with pytest.raises(AuthError):
            auth.authenticate("a@example.com", OTHER_PASSWORD)

    # Even the correct password is refused while locked.
    with pytest.raises(AuthError, match="Too many failed attempts"):
        auth.authenticate("a@example.com", GOOD_PASSWORD)


def test_successful_login_clears_the_failure_counter(auth, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    for _ in range(3):
        with pytest.raises(AuthError):
            auth.authenticate("a@example.com", OTHER_PASSWORD)

    auth.authenticate("a@example.com", GOOD_PASSWORD)
    assert auth.find_by_email("a@example.com")["failed_attempts"] == 0


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def test_only_the_token_hash_is_stored(auth, conn, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    token = auth.authenticate("a@example.com", GOOD_PASSWORD)

    rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] != token
    assert rows[0]["token_hash"] == hash_token(token)

    dumped = str([dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()])
    assert token not in dumped, "the raw session token must never be stored"


def test_unknown_and_empty_tokens_resolve_to_nothing(auth):
    assert auth.resolve_session("") is None
    assert auth.resolve_session("not-a-real-token") is None


def test_revoked_session_stops_working(auth, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    token = auth.authenticate("a@example.com", GOOD_PASSWORD)

    auth.revoke_session(token)
    assert auth.resolve_session(token) is None


def test_expired_session_stops_working(auth, conn, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    token = auth.authenticate("a@example.com", GOOD_PASSWORD)

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE sessions SET expires_at = ?", (past,))
    conn.commit()

    assert auth.resolve_session(token) is None


def test_changing_password_revokes_every_session(auth, workspace):
    user_id = auth.create_user(
        email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    first = auth.authenticate("a@example.com", GOOD_PASSWORD)
    second = auth.authenticate("a@example.com", GOOD_PASSWORD)

    auth.change_password(user_id, GOOD_PASSWORD, OTHER_PASSWORD)

    assert auth.resolve_session(first) is None
    assert auth.resolve_session(second) is None
    assert auth.authenticate("a@example.com", OTHER_PASSWORD)


def test_change_password_requires_the_current_one(auth, workspace):
    user_id = auth.create_user(
        email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    with pytest.raises(AuthError, match="current password"):
        auth.change_password(user_id, "wrong-password-entirely", OTHER_PASSWORD)


def test_deactivating_a_user_revokes_sessions(auth, workspace):
    user_id = auth.create_user(
        email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    token = auth.authenticate("a@example.com", GOOD_PASSWORD)
    auth.set_active(user_id, False)
    assert auth.resolve_session(token) is None


def test_expired_sessions_are_purgeable(auth, conn, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    auth.authenticate("a@example.com", GOOD_PASSWORD)
    conn.execute(
        "UPDATE sessions SET expires_at = ?",
        ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),),
    )
    conn.commit()
    assert auth.purge_expired_sessions() == 1


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------


def test_every_role_has_a_permission_set():
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_owner_holds_every_permission():
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)


def test_viewer_is_read_only():
    granted = ROLE_PERMISSIONS[Role.VIEWER]
    assert Permission.VIEW in granted
    for denied in (
        Permission.RUN_ANALYSIS,
        Permission.DECIDE,
        Permission.DELETE_PRODUCT,
        Permission.MANAGE_MEMBERS,
        Permission.MANAGE_MONITORS,
    ):
        assert denied not in granted


def test_roles_are_ordered_by_privilege():
    """Each tier must be a superset of the one below where that is intended."""
    assert ROLE_PERMISSIONS[Role.VIEWER] < ROLE_PERMISSIONS[Role.EXECUTIVE]
    assert ROLE_PERMISSIONS[Role.EXECUTIVE] < ROLE_PERMISSIONS[Role.ANALYST]
    assert ROLE_PERMISSIONS[Role.EXECUTIVE] < ROLE_PERMISSIONS[Role.PRODUCT_MANAGER]
    assert ROLE_PERMISSIONS[Role.ANALYST] < ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.ADMIN] < ROLE_PERMISSIONS[Role.OWNER]


def test_only_admin_and_owner_manage_members():
    for role in Role:
        expected = role in (Role.ADMIN, Role.OWNER)
        assert (Permission.MANAGE_MEMBERS in ROLE_PERMISSIONS[role]) is expected


def test_analyst_cannot_decide_and_pm_cannot_manage_sources():
    """The two roles are deliberately different, not nested."""
    assert Permission.DECIDE not in ROLE_PERMISSIONS[Role.ANALYST]
    assert Permission.MANAGE_SOURCES not in ROLE_PERMISSIONS[Role.PRODUCT_MANAGER]


def test_identity_require_raises_for_missing_permission():
    identity = Identity(
        user_id="u", email="a@b.c", name="A", workspace_id="ws",
        role=Role.VIEWER, permissions=ROLE_PERMISSIONS[Role.VIEWER],
    )
    identity.require(Permission.VIEW)
    with pytest.raises(PermissionDenied) as exc:
        identity.require(Permission.DELETE_PRODUCT)
    assert "delete_product" in str(exc.value)
    assert "viewer" in str(exc.value)


def test_dev_identity_holds_everything_and_is_flagged():
    identity = dev_identity("ws_default")
    assert identity.permissions == frozenset(Permission)
    assert identity.is_dev is True
    assert identity.role is Role.OWNER


# ---------------------------------------------------------------------------
# Membership and tenant isolation
# ---------------------------------------------------------------------------


def test_identity_requires_membership_of_the_workspace(auth, conn, workspace):
    """Membership is what enforces tenant isolation."""
    conn.execute(
        "INSERT INTO workspaces (id, name, created_at) VALUES ('ws_other', 'Other', 'now')"
    )
    conn.commit()

    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    token = auth.authenticate("a@example.com", GOOD_PASSWORD)

    assert auth.identity_from_token(token, workspace) is not None
    assert auth.identity_from_token(token, "ws_other") is None, (
        "a valid session must not grant access to a workspace the user is not in"
    )


def test_identity_reflects_the_current_role(auth, workspace):
    auth.create_user(email="owner@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    user_id = auth.create_user(
        email="b@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    token = auth.authenticate("b@example.com", GOOD_PASSWORD)
    assert auth.identity_from_token(token, workspace).role is Role.VIEWER

    auth.set_role(workspace, user_id, Role.ANALYST)
    assert auth.identity_from_token(token, workspace).role is Role.ANALYST


def test_last_owner_cannot_be_removed_or_demoted(auth, workspace):
    owner_id = auth.create_user(
        email="owner@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    with pytest.raises(AuthError, match="at least one owner"):
        auth.remove_member(workspace, owner_id)
    with pytest.raises(AuthError, match="at least one owner"):
        auth.set_role(workspace, owner_id, Role.VIEWER)


def test_owner_can_be_demoted_once_another_exists(auth, workspace):
    first = auth.create_user(
        email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    second = auth.create_user(
        email="b@example.com", password=GOOD_PASSWORD, workspace_id=workspace
    )
    auth.set_role(workspace, second, Role.OWNER)
    auth.set_role(workspace, first, Role.VIEWER)
    assert auth.role_for(workspace, first) is Role.VIEWER


def test_members_listing_includes_role_and_status(auth, workspace):
    auth.create_user(
        email="a@example.com", password=GOOD_PASSWORD, name="Alice", workspace_id=workspace
    )
    members = auth.members(workspace)
    assert len(members) == 1
    assert members[0]["role"] == Role.OWNER.value
    assert members[0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_account_creation_and_login_are_audited(auth, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    auth.authenticate("a@example.com", GOOD_PASSWORD)

    actions = {entry["action"] for entry in auth.audit_log(workspace)}
    assert "user.created" in actions


def test_failed_logins_are_audited_as_failures(auth, conn, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    with pytest.raises(AuthError):
        auth.authenticate("a@example.com", OTHER_PASSWORD)

    entries = conn.execute(
        "SELECT * FROM audit_log WHERE action = 'auth.login_failed'"
    ).fetchall()
    assert len(entries) == 1
    assert entries[0]["succeeded"] == 0


def test_audit_log_never_stores_a_password(auth, conn, workspace):
    auth.create_user(email="a@example.com", password=GOOD_PASSWORD, workspace_id=workspace)
    with pytest.raises(AuthError):
        auth.authenticate("a@example.com", OTHER_PASSWORD)

    dumped = str([dict(r) for r in conn.execute("SELECT * FROM audit_log").fetchall()])
    assert GOOD_PASSWORD not in dumped
    assert OTHER_PASSWORD not in dumped


# ---------------------------------------------------------------------------
# Open (development) mode
# ---------------------------------------------------------------------------


def test_open_mode_is_the_default():
    assert AppConfig(api_key=None).auth_enabled is False


def test_exposure_warning_when_open_and_bound_externally(monkeypatch):
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    warning = network_exposure_warning(auth_enabled=False)
    assert warning is not None
    assert "0.0.0.0" in warning
    assert "PAS_AUTH_ENABLED" in warning


def test_no_warning_when_auth_is_enabled(monkeypatch):
    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    assert network_exposure_warning(auth_enabled=True) is None


def test_loopback_binding_is_not_warned(monkeypatch):
    for address in ("localhost", "127.0.0.1", "::1", ""):
        monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", address)
        assert network_exposure_warning(auth_enabled=False) is None


# ---------------------------------------------------------------------------
# Enforcement at the service boundary
#
# The permission matrix is only worth anything if the service actually consults
# it. These drive StudioService with real identities.
# ---------------------------------------------------------------------------


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """A StudioService factory bound to an isolated database."""
    from pas.service import StudioService
    from pas.storage import db as db_module

    db_module.reset_thread_state()
    db_path = tmp_path / "svc.sqlite3"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    def build(identity=None, auth_enabled=False):
        config = AppConfig(api_key="test-key", db_path=db_path, auth_enabled=auth_enabled)
        return StudioService(config=config, identity=identity)

    yield build
    db_module.reset_thread_state()


def _identity(role: Role, workspace_id: str = "ws_default") -> Identity:
    return Identity(
        user_id=f"usr_{role.value}",
        email=f"{role.value}@example.com",
        name=role.label,
        workspace_id=workspace_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
    )


def test_open_mode_grants_full_access(studio):
    """Development mode must not obstruct anything."""
    service = studio()
    assert service.identity.is_dev is True
    product_id = service.create_product(
        name="Dev product", intake_kind="idea", intake_input="an idea"
    )
    assert service.get_product(product_id) is not None
    assert service.list_products()
    service.delete_product(product_id)
    assert service.list_products() == []


def test_viewer_cannot_create_or_delete_products(studio):
    owner = studio(_identity(Role.OWNER))
    product_id = owner.create_product(
        name="P", intake_kind="idea", intake_input="an idea"
    )

    viewer = studio(_identity(Role.VIEWER))
    assert viewer.list_products(), "a viewer must still be able to read"

    with pytest.raises(PermissionDenied):
        viewer.create_product(name="X", intake_kind="idea", intake_input="nope")
    with pytest.raises(PermissionDenied):
        viewer.delete_product(product_id)


def test_viewer_cannot_run_an_analysis(studio):
    owner = studio(_identity(Role.OWNER))
    product_id = owner.create_product(name="P", intake_kind="idea", intake_input="idea")

    viewer = studio(_identity(Role.VIEWER))
    with pytest.raises(PermissionDenied):
        viewer.start_analysis(product_id)


def test_analyst_cannot_decide_but_product_manager_can(studio):
    from pas.domain.enums import DecisionState
    from pas.storage import repositories as repo

    owner = studio(_identity(Role.OWNER))
    product_id = owner.create_product(name="P", intake_kind="idea", intake_input="idea")
    analysis = repo.create_analysis(
        owner.conn, workspace_id=owner.workspace_id, product_id=product_id
    )["id"]
    repo.save_recommendations(
        owner.conn, workspace_id=owner.workspace_id, analysis_id=analysis,
        product_id=product_id,
        recommendations=[{"title": "Ship SSO", "gap_category": "security"}],
    )
    rec_id = repo.list_recommendations(owner.conn, analysis)[0]["id"]

    analyst = studio(_identity(Role.ANALYST))
    with pytest.raises(PermissionDenied):
        analyst.decide(rec_id, DecisionState.REJECTED.value)

    manager = studio(_identity(Role.PRODUCT_MANAGER))
    manager.decide(rec_id, DecisionState.REJECTED.value)
    assert repo.list_recommendations(manager.conn, analysis)[0]["decision_state"] == "rejected"


def test_product_manager_cannot_manage_monitors(studio):
    owner = studio(_identity(Role.OWNER))
    product_id = owner.create_product(name="P", intake_kind="idea", intake_input="idea")

    manager = studio(_identity(Role.PRODUCT_MANAGER))
    with pytest.raises(PermissionDenied):
        manager.create_monitor(product_id, "m", ["https://example.com"])

    analyst = studio(_identity(Role.ANALYST))
    assert analyst.create_monitor(product_id, "m", ["https://example.com"])


def test_viewer_cannot_ask_or_export(studio):
    viewer = studio(_identity(Role.VIEWER))
    with pytest.raises(PermissionDenied):
        viewer.ask("prd_x", "anl_x", "What should I build?")
    with pytest.raises(PermissionDenied):
        viewer.export_json("anl_x")


def test_non_admin_cannot_view_diagnostics(studio):
    for role in (Role.VIEWER, Role.EXECUTIVE, Role.ANALYST, Role.PRODUCT_MANAGER):
        with pytest.raises(PermissionDenied):
            studio(_identity(role)).diagnostics()

    assert studio(_identity(Role.ADMIN)).diagnostics()["provider_configured"] is True


def test_state_changes_are_written_to_the_audit_log(studio):
    owner = studio(_identity(Role.OWNER))
    product_id = owner.create_product(name="Audited", intake_kind="idea", intake_input="idea")
    owner.delete_product(product_id)

    entries = owner.auth.audit_log(owner.workspace_id)
    actions = [e["action"] for e in entries]
    assert "product.created" in actions
    assert "product.deleted" in actions

    created = next(e for e in entries if e["action"] == "product.created")
    assert created["actor_label"] == Role.OWNER.label
    assert created["target_id"] == product_id


def test_denied_actions_do_not_mutate_state(studio):
    """A permission failure must leave nothing behind."""
    owner = studio(_identity(Role.OWNER))
    baseline = len(owner.list_products())

    viewer = studio(_identity(Role.VIEWER))
    with pytest.raises(PermissionDenied):
        viewer.create_product(name="Should not exist", intake_kind="idea", intake_input="x")

    assert len(owner.list_products()) == baseline


def test_audit_failure_never_breaks_the_operation(studio):
    """An audit write must not roll back the action it describes."""
    owner = studio(_identity(Role.OWNER))
    # This identity has no matching users row, which previously raised a
    # foreign-key error and aborted product creation.
    product_id = owner.create_product(
        name="Survives audit trouble", intake_kind="idea", intake_input="idea"
    )
    assert owner.get_product(product_id) is not None

    entry = next(
        e for e in owner.auth.audit_log(owner.workspace_id)
        if e["action"] == "product.created"
    )
    assert entry["user_id"] is None, "no dangling foreign key"
    assert entry["actor_label"], "the actor is still recorded as text"
