"""Sign-in, account and member management screens (spec 32 / 41).

These render only when ``PAS_AUTH_ENABLED`` is on. In open development mode the
app skips straight past them, but the member/account surfaces remain reachable
so the configuration can be prepared before auth is switched on.
"""

from __future__ import annotations

import streamlit as st

from ...auth.models import ROLE_PERMISSIONS, AuthError, Permission, Role
from ...auth.passwords import MIN_PASSWORD_LENGTH, PasswordError
from ...service import StudioService
from ..components import chip, empty_state, esc, kpi
from ..theme import PALETTE

SESSION_TOKEN_KEY = "auth_token"


def render_login(service: StudioService) -> None:
    """The sign-in gate. Returns nothing; sets the session token on success."""
    st.markdown(
        '<div class="hero"><div class="title">Product Analysis Studio</div>'
        '<div class="subtitle">Sign in to continue</div></div>',
        unsafe_allow_html=True,
    )

    first_run = service.auth.user_count() == 0
    if first_run:
        st.info(
            "No accounts exist yet. The first account you create becomes the "
            "workspace owner.",
            icon=":material/admin_panel_settings:",
        )
        _signup_form(service, first_run=True)
        return

    tabs = ["Sign in"] + (["Create account"] if service.config.allow_signup else [])
    rendered = st.tabs(tabs)

    with rendered[0]:
        _login_form(service)
    if len(rendered) > 1:
        with rendered[1]:
            _signup_form(service, first_run=False)


def _login_form(service: StudioService) -> None:
    with st.form("login"):
        email = st.text_input("Email", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

    if not submitted:
        return
    try:
        token = service.auth.authenticate(email, password, user_agent="streamlit")
    except AuthError as exc:
        # One message for every credential failure - no user enumeration.
        st.error(str(exc), icon=":material/lock:")
        return

    st.session_state[SESSION_TOKEN_KEY] = token
    st.rerun()


def _signup_form(service: StudioService, *, first_run: bool) -> None:
    with st.form("signup"):
        name = st.text_input("Your name")
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input(
            "Password",
            type="password",
            autocomplete="new-password",
            help=(
                f"At least {MIN_PASSWORD_LENGTH} characters. A memorable phrase "
                "beats a short complex string."
            ),
        )
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button(
            "Create account", type="primary", use_container_width=True
        )

    if not submitted:
        return
    if password != confirm:
        st.error("Those passwords do not match.", icon=":material/error:")
        return

    try:
        service.auth.create_user(
            email=email,
            password=password,
            name=name,
            workspace_id=service.workspace_id,
        )
    except (AuthError, PasswordError) as exc:
        st.error(str(exc), icon=":material/error:")
        return

    st.success(
        "Account created."
        + (" You are the workspace owner." if first_run else " Sign in to continue.")
    )
    try:
        token = service.auth.authenticate(email, password, user_agent="streamlit")
        st.session_state[SESSION_TOKEN_KEY] = token
        st.rerun()
    except AuthError:
        pass


# ---------------------------------------------------------------------------
# Account and members
# ---------------------------------------------------------------------------


def render_account(service: StudioService) -> None:
    identity = service.identity
    st.markdown("### Account & access")

    if identity.is_dev:
        st.warning(
            "**Authentication is disabled.** You are acting as the development "
            "user with full owner rights. Accounts created here will apply once "
            "you set `PAS_AUTH_ENABLED=true` and restart.",
            icon=":material/lock_open:",
        )

    tabs = st.tabs(["Your account", "Members", "Roles", "Audit log"])
    with tabs[0]:
        _account_tab(service)
    with tabs[1]:
        _members_tab(service)
    with tabs[2]:
        _roles_tab(service)
    with tabs[3]:
        _audit_tab(service)


def _account_tab(service: StudioService) -> None:
    identity = service.identity

    cols = st.columns(3)
    with cols[0]:
        kpi("Signed in as", identity.label)
    with cols[1]:
        kpi("Role", identity.role.label)
    with cols[2]:
        kpi("Permissions", str(len(identity.permissions)))

    if identity.is_dev:
        st.caption(
            "The development user is not a stored account, so there is no "
            "password to change."
        )
        return

    st.markdown("#### Change password")
    with st.form("change_password"):
        current = st.text_input("Current password", type="password")
        new_password = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Update password", type="primary"):
            if new_password != confirm:
                st.error("Those passwords do not match.")
            else:
                try:
                    service.auth.change_password(identity.user_id, current, new_password)
                except (AuthError, PasswordError) as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    # Changing a password revokes every session, including this one.
                    st.session_state.pop(SESSION_TOKEN_KEY, None)
                    st.success("Password updated. Sign in again.")
                    st.rerun()


def _members_tab(service: StudioService) -> None:
    identity = service.identity
    can_manage = identity.can(Permission.MANAGE_MEMBERS)

    members = service.auth.members(service.workspace_id)
    if not members:
        empty_state(
            "No accounts yet",
            "Create the first account below; it becomes the workspace owner.",
        )

    for member in members:
        with st.container(border=True):
            head, role_col, action = st.columns([3, 1.4, 1])
            with head:
                st.markdown(f"**{esc(member['name'] or member['email'])}**")
                st.caption(member["email"])
                st.caption(
                    "Last signed in "
                    + (str(member["last_login_at"])[:16].replace("T", " ")
                       if member["last_login_at"] else "never")
                    + ("" if member["is_active"] else " · disabled")
                )
            with role_col:
                if can_manage:
                    roles = [r.value for r in Role]
                    chosen = st.selectbox(
                        "Role",
                        roles,
                        index=roles.index(member["role"]),
                        key=f"role_{member['id']}",
                        format_func=lambda v: Role(v).label,
                        label_visibility="collapsed",
                    )
                    if chosen != member["role"]:
                        try:
                            service.auth.set_role(
                                service.workspace_id, member["id"], Role(chosen)
                            )
                            st.rerun()
                        except AuthError as exc:
                            st.error(str(exc))
                else:
                    st.markdown(
                        chip(Role(member["role"]).label, PALETTE["primary_2"]),
                        unsafe_allow_html=True,
                    )
            with action:
                if can_manage and member["id"] != identity.user_id:
                    if st.button("Remove", key=f"rm_{member['id']}", use_container_width=True):
                        try:
                            service.auth.remove_member(service.workspace_id, member["id"])
                            st.rerun()
                        except AuthError as exc:
                            st.error(str(exc))

    if not can_manage:
        st.caption("Your role does not allow managing members.")
        return

    st.markdown("#### Add an account")
    with st.form("add_member", clear_on_submit=True):
        cols = st.columns(2)
        name = cols[0].text_input("Name")
        email = cols[1].text_input("Email")
        cols = st.columns([2, 2, 1])
        password = cols[0].text_input(
            "Initial password", type="password",
            help=f"At least {MIN_PASSWORD_LENGTH} characters.",
        )
        role = cols[1].selectbox(
            "Role", [r.value for r in Role], index=[r.value for r in Role].index("viewer"),
            format_func=lambda v: Role(v).label,
        )
        cols[2].markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
        if cols[2].form_submit_button("Add", type="primary", use_container_width=True):
            try:
                service.auth.create_user(
                    email=email, password=password, name=name,
                    workspace_id=service.workspace_id, role=Role(role),
                )
            except (AuthError, PasswordError) as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                st.success(f"Added {email}. Share the password securely and have them change it.")
                st.rerun()


def _roles_tab(service: StudioService) -> None:
    st.caption(
        "The permission matrix is the single source of truth for authorisation. "
        "Your current role is highlighted."
    )
    current = service.identity.role

    for role in Role:
        granted = ROLE_PERMISSIONS[role]
        with st.expander(
            f"{role.label}" + ("  ← you" if role is current else ""),
            expanded=role is current,
        ):
            st.caption(role.description)
            cols = st.columns(3)
            for index, permission in enumerate(Permission):
                held = permission in granted
                cols[index % 3].markdown(
                    f"<span style='color:{PALETTE['success'] if held else PALETTE['muted']}'>"
                    f"{'✓' if held else '·'} {esc(permission.label)}</span>",
                    unsafe_allow_html=True,
                )


def _audit_tab(service: StudioService) -> None:
    if not service.identity.can(Permission.MANAGE_MEMBERS):
        st.caption("Your role does not allow viewing the audit log.")
        return

    entries = service.auth.audit_log(service.workspace_id, limit=300)
    if not entries:
        empty_state("Nothing recorded yet")
        return

    import pandas as pd

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "When": str(e["created_at"])[:19].replace("T", " "),
                    "Actor": e["actor_label"],
                    "Action": e["action"],
                    "Target": f"{e['target_type']}:{(e['target_id'] or '')[:12]}",
                    "Detail": (e["detail"] or "")[:60],
                    "OK": "yes" if e["succeeded"] else "no",
                }
                for e in entries
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
