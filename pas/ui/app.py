"""Streamlit entry point and routing.

Navigation is organised into sections rather than one long tab strip: the
workroom answers "what is true", strategy answers "what to do", and the rest
are working surfaces. Sixteen tabs on one page would be the dashboard clutter
the product is supposed to avoid.
"""

from __future__ import annotations

import streamlit as st

from ..auth.models import Identity, Permission, PermissionDenied
from ..config import load_config, network_exposure_warning
from ..service import StudioService
from . import theme
from .components import esc, kpi
from .pages import (
    alerts,
    ask,
    auth_pages,
    intake,
    radar,
    reports,
    strategy,
    voice,
    workroom,
)

#: route -> (label, requires a product, permission needed to see it)
ROUTES: dict[str, tuple[str, bool, Permission]] = {
    "intake": ("Products", False, Permission.VIEW),
    "workroom": ("Analysis", True, Permission.VIEW),
    "strategy": ("Strategy", True, Permission.VIEW),
    "radar": ("Radar", True, Permission.VIEW),
    "voice": ("Customers", True, Permission.VIEW),
    "decide": ("Decide", True, Permission.VIEW),
    "ask": ("Ask", True, Permission.ASK),
    "alerts": ("Alerts", True, Permission.VIEW),
    "reports": ("Reports", True, Permission.EXPORT),
    "account": ("Account", False, Permission.VIEW),
    "diagnostics": ("Diagnostics", False, Permission.VIEW_DIAGNOSTICS),
}


@st.cache_resource(show_spinner=False)
def _base_service() -> StudioService:
    """Process-wide service used before an identity is resolved.

    Cached so migrations run once rather than on every Streamlit rerun.
    """
    return StudioService()


def _resolve_identity(base: StudioService) -> Identity | None:
    """Determine who is acting, or None when a sign-in is required."""
    config = base.config
    if not config.auth_enabled:
        return base.auth.open_identity(base.workspace_id)

    token = st.session_state.get(auth_pages.SESSION_TOKEN_KEY, "")
    if not token:
        return None
    identity = base.auth.identity_from_token(token, base.workspace_id)
    if identity is None:
        # Expired, revoked, or the account lost access to this workspace.
        st.session_state.pop(auth_pages.SESSION_TOKEN_KEY, None)
        return None
    return identity


def _active_jobs():
    from ..jobs.runner import get_runner

    return get_runner().active_jobs()


def _sidebar(service: StudioService, product: dict | None) -> str:
    identity = service.identity

    with st.sidebar:
        st.markdown("### Product Analysis Studio")
        st.caption("AI product intelligence & strategy OS")

        # Only offer routes this identity may actually use.
        options = [
            key
            for key, (_label, needs_product, permission) in ROUTES.items()
            if (product is not None or not needs_product) and identity.can(permission)
        ]
        if not options:
            options = ["account"]

        current = st.session_state.get("route", "intake")
        if current not in options:
            current = options[0]

        unread = service.unread_alerts(product["id"]) if product else 0

        def label_for(key: str) -> str:
            label = ROUTES[key][0]
            if key == "alerts" and unread:
                return f"{label} ({unread})"
            return label

        route = st.radio(
            "Navigation",
            options=options,
            format_func=label_for,
            index=options.index(current),
            label_visibility="collapsed",
        )

        st.markdown("---")
        if product:
            st.caption("Current product")
            st.markdown(f"**{esc(product['name'])}**")
            analysis_id = st.session_state.get("active_analysis")
            if analysis_id:
                analysis = service.get_analysis(analysis_id)
                if analysis:
                    st.caption(f"v{analysis['version']} · {analysis['status']}")
        else:
            st.caption("No product selected.")

        st.markdown("---")
        mentions = service.mentions()
        if mentions:
            st.info(
                f"{len(mentions)} mention(s) awaiting you", icon=":material/alternate_email:"
            )
        st.caption(f"{esc(identity.label)} · {identity.role.label}")
        if identity.is_dev:
            st.warning("Auth disabled (dev)", icon=":material/lock_open:")
        elif st.button("Sign out", use_container_width=True):
            token = st.session_state.pop(auth_pages.SESSION_TOKEN_KEY, "")
            if token:
                service.auth.revoke_session(token)
            st.rerun()

        if not service.config.is_configured:
            st.warning("No API key configured", icon=":material/key_off:")

        active = len(_active_jobs())
        if active:
            st.info(f"{active} job running", icon=":material/sync:")

    return route


def _decide(service: StudioService, product: dict, analysis_id: str | None) -> None:
    """Decision board and roadmap together - accept a recommendation, see it land."""
    tabs = st.tabs(["Decision board", "Roadmap"])
    with tabs[0]:
        if not analysis_id:
            from .components import empty_state

            empty_state("Run an analysis first")
        else:
            workroom.render_board(service, service.dashboard(analysis_id))
    with tabs[1]:
        workroom.render_roadmap(service, product)


def _diagnostics(service: StudioService) -> None:
    """Operational view (spec 51)."""
    st.markdown("### Diagnostics")
    diagnostics = service.diagnostics()
    usage = diagnostics["usage"]

    cols = st.columns(4)
    with cols[0]:
        kpi(
            "Provider",
            "Connected" if diagnostics["provider_configured"] else "Not configured",
            "OpenRouter",
            None if diagnostics["provider_configured"] else theme.PALETTE["danger"],
        )
    with cols[1]:
        kpi("Total spend", f"${float(usage.get('cost', 0)):.4f}", f"{usage.get('calls', 0)} calls")
    with cols[2]:
        kpi("Failed agent runs", str(diagnostics["failed_agent_runs"]))
    with cols[3]:
        kpi("Unavailable sources", str(diagnostics["failed_sources"]))

    st.markdown("#### Configuration")
    st.json(
        {
            "fast_model": diagnostics["fast_model"],
            "deep_model": diagnostics["deep_model"],
            "database": diagnostics["database"],
            "active_jobs": diagnostics["active_jobs"],
        }
    )
    st.caption("Secrets are never rendered here or sent to the browser.")

    if usage.get("by_model"):
        st.markdown("#### Spend by model")
        import pandas as pd

        st.dataframe(
            pd.DataFrame(usage["by_model"]), use_container_width=True, hide_index=True
        )

    jobs = _active_jobs()
    if jobs:
        st.markdown("#### Running jobs")
        for job in jobs:
            st.caption(f"{job.job_id} — {job.status} ({len(job.events)} events)")

    st.markdown("#### Semantic retrieval")
    retrieval = service.retrieval_stats()
    cols = st.columns(3)
    cols[0].metric("Cached vectors", f"{retrieval['cached_vectors']:,}")
    cols[1].metric("Cache size", f"{retrieval['cache_bytes'] / 1024:,.0f} KB")
    cols[2].metric("Enabled", "yes" if retrieval["enabled"] else "no")
    st.caption(
        f"Model: {retrieval['model']}. Embeddings are cached by content hash, so "
        "a claim is embedded once regardless of how many questions reference it."
    )

    st.markdown("#### Monitor scheduler")
    state = service.scheduler_state()
    if not service.config.scheduler_enabled:
        st.caption(
            "Disabled. Set PAS_SCHEDULER=true to run due monitors automatically "
            "while the app is open, or point cron at run_due_monitors()."
        )
    elif state is None:
        st.caption("Enabled but not yet started.")
    else:
        cols = st.columns(4)
        cols[0].metric("Ticks", state.ticks)
        cols[1].metric("Dispatched", state.dispatched)
        cols[2].metric("Errors", state.errors)
        cols[3].metric("Running", "yes" if state.running else "no")
        if state.last_error:
            st.caption(f"Last error: {state.last_error}")

    if st.button("Run due monitors now"):
        try:
            count = service.run_due_monitors()
            st.success(f"Dispatched {count} monitor(s).")
        except Exception as exc:
            st.error(str(exc))


def main() -> None:
    st.set_page_config(
        page_title="Product Analysis Studio",
        page_icon=":material/insights:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.inject()

    st.session_state.setdefault("route", "intake")
    st.session_state.setdefault("active_product", None)
    st.session_state.setdefault("active_analysis", None)

    try:
        base = _base_service()
    except Exception as exc:  # database or migration failure
        st.error(f"Could not start: {exc}", icon=":material/error:")
        st.stop()
        return

    identity = _resolve_identity(base)
    if identity is None:
        auth_pages.render_login(base)
        return

    # A per-run service bound to the resolved identity, so every permission
    # check below reflects the actual signed-in user.
    service = StudioService(config=base.config, identity=identity)
    base.start_scheduler()

    _security_banner(service)

    product_id = st.session_state.get("active_product")
    product = service.get_product(product_id) if product_id else None
    if product is None and product_id:
        # The product was deleted, or belongs to a workspace this user left.
        st.session_state["active_product"] = None
        st.session_state["active_analysis"] = None

    route = _sidebar(service, product)
    st.session_state["route"] = route

    try:
        _dispatch(service, route, product)
    except PermissionDenied as exc:
        # Belt and braces: the sidebar already hides routes the user cannot
        # reach, but a stale session_state route must not leak data.
        st.error(str(exc), icon=":material/block:")


def _dispatch(service: StudioService, route: str, product: dict | None) -> None:
    if route == "account":
        auth_pages.render_account(service)
        return
    if route == "diagnostics":
        _diagnostics(service)
        return
    if route == "intake" or product is None:
        intake.render(service)
        return

    analysis_id = st.session_state.get("active_analysis")

    if route == "workroom":
        workroom.render(service)
    elif route == "strategy":
        strategy.render(service, product, analysis_id)
    elif route == "radar":
        radar.render(service, product, analysis_id)
    elif route == "voice":
        voice.render(service, product, analysis_id)
    elif route == "decide":
        _decide(service, product, analysis_id)
    elif route == "ask":
        ask.render(service, product, analysis_id)
    elif route == "alerts":
        alerts.render(service, product, analysis_id)
    elif route == "reports":
        reports.render(service, product, analysis_id)
    else:
        intake.render(service)


def _security_banner(service: StudioService) -> None:
    """Make an unauthenticated deployment impossible to miss."""
    if service.config.auth_enabled:
        return

    exposure = network_exposure_warning(service.config.auth_enabled)
    if exposure:
        # Reachable off-machine with no auth: this is not a dev convenience.
        st.error(exposure, icon=":material/gpp_bad:")
    else:
        st.caption(
            ":material/lock_open: Development mode — authentication is disabled and "
            "everyone has full access. Set `PAS_AUTH_ENABLED=true` before exposing "
            "this to anyone else."
        )


if __name__ == "__main__":
    main()
