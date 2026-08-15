"""Roles, permissions and the authenticated identity (spec 32 / 41).

The permission matrix is data, not scattered ``if role == "admin"`` checks, so
it can be read in one place and asserted against in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.enums import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    PRODUCT_MANAGER = "product_manager"
    EXECUTIVE = "executive"
    VIEWER = "viewer"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def description(self) -> str:
        return {
            "owner": "Full control, including deleting the workspace.",
            "admin": "Manage members and every part of the intelligence.",
            "analyst": "Run analyses, manage research sources and monitors.",
            "product_manager": "Decide on recommendations and own the roadmap.",
            "executive": "Read everything and ask questions. No edits.",
            "viewer": "Read-only access to analyses and reports.",
        }[self.value]


class Permission(StrEnum):
    VIEW = "view"
    ASK = "ask"
    EXPORT = "export"
    CREATE_PRODUCT = "create_product"
    RUN_ANALYSIS = "run_analysis"
    MANAGE_SOURCES = "manage_sources"
    MANAGE_MONITORS = "manage_monitors"
    DECIDE = "decide"
    MANAGE_ROADMAP = "manage_roadmap"
    MANAGE_ALERTS = "manage_alerts"
    DELETE_PRODUCT = "delete_product"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_WORKSPACE = "manage_workspace"
    VIEW_DIAGNOSTICS = "view_diagnostics"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


_VIEWER: set[Permission] = {Permission.VIEW}
_EXECUTIVE: set[Permission] = _VIEWER | {
    Permission.ASK,
    Permission.EXPORT,
}
_PRODUCT_MANAGER: set[Permission] = _EXECUTIVE | {
    Permission.DECIDE,
    Permission.MANAGE_ROADMAP,
    Permission.MANAGE_ALERTS,
    Permission.CREATE_PRODUCT,
    Permission.RUN_ANALYSIS,
}
_ANALYST: set[Permission] = _EXECUTIVE | {
    Permission.CREATE_PRODUCT,
    Permission.RUN_ANALYSIS,
    Permission.MANAGE_SOURCES,
    Permission.MANAGE_MONITORS,
    Permission.MANAGE_ALERTS,
}
_ADMIN: set[Permission] = (
    _ANALYST
    | _PRODUCT_MANAGER
    | {
        Permission.DELETE_PRODUCT,
        Permission.MANAGE_MEMBERS,
        Permission.VIEW_DIAGNOSTICS,
    }
)
_OWNER: set[Permission] = set(Permission)

#: Role -> permissions. The single source of truth for authorisation.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.EXECUTIVE: frozenset(_EXECUTIVE),
    Role.PRODUCT_MANAGER: frozenset(_PRODUCT_MANAGER),
    Role.ANALYST: frozenset(_ANALYST),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset(_OWNER),
}


class AuthError(Exception):
    """Authentication failed."""


class PermissionDenied(Exception):
    """The identity is authenticated but not allowed to do this."""

    def __init__(self, permission: "Permission | str", role: "Role | str | None" = None):
        self.permission = str(permission)
        self.role = str(role) if role else None
        detail = f" Your role ({role}) does not include it." if role else ""
        super().__init__(f"Not permitted: {self.permission}.{detail}")


@dataclass(frozen=True)
class Identity:
    """Who is acting, and what they may do.

    Constructed once per request and threaded through the service layer. In
    open (development) mode this is :func:`dev_identity`, which holds every
    permission - so the authorisation code path is always exercised rather than
    lying dormant until auth is switched on.
    """

    user_id: str
    email: str
    name: str
    workspace_id: str
    role: Role
    permissions: frozenset[Permission]
    is_authenticated: bool = True
    is_dev: bool = False
    session_id: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.email or self.user_id

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        """Raise :class:`PermissionDenied` unless the identity holds ``permission``."""
        if permission not in self.permissions:
            raise PermissionDenied(permission, self.role)


DEV_USER_ID = "usr_dev_local"


def dev_identity(workspace_id: str) -> Identity:
    """The identity used when authentication is disabled.

    Deliberately holds owner-level rights so development is unobstructed, and
    is flagged ``is_dev`` so the UI can display an unmistakable warning.
    """
    return Identity(
        user_id=DEV_USER_ID,
        email="",
        name="Development user",
        workspace_id=workspace_id,
        role=Role.OWNER,
        permissions=ROLE_PERMISSIONS[Role.OWNER],
        is_authenticated=True,
        is_dev=True,
    )


def identity_for(
    *, user_id: str, email: str, name: str, workspace_id: str, role: Role, session_id: str
) -> Identity:
    return Identity(
        user_id=user_id,
        email=email,
        name=name,
        workspace_id=workspace_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        session_id=session_id,
    )
