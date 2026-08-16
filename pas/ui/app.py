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
from .components import esc, format_cost, kpi
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

#: route -> (label, one-line purpose, requires a product, permission)
#:
#: The purpose text is not decoration. Eleven bare nouns in a sidebar are only
#: navigable by someone who already knows the product.
ROUTES: dict[str, tuple[str, str, bool, Permission]] = {
    "intake": (
        "Products", "Start here. Add a product or open a previous analysis.",
        False, Permission.VIEW,
    ),
    "workroom": (
        "Analysis", "What is true: score, profile, competitors, market, customers.",
        True, Permission.VIEW,
    ),
    "strategy": (
        "Strategy", "What to do: positioning, pricing, growth, launch plan.",
        True, Permission.VIEW,
    ),
    "radar": (
        "Radar", "What is coming: ranked opportunities, threats and what-if scenarios.",
        True, Permission.VIEW,
    ),
    "voice": (
        "Customers", "What buyers actually say. Upload reviews or interviews.",
        True, Permission.VIEW,
    ),
    "decide": (
        "Decide", "Accept or reject recommendations, and own the roadmap.",
        True, Permission.VIEW,
    ),
    "ask": (
        "Ask", "Question the intelligence in plain English, with citations.",
        True, Permission.ASK,
    ),
    "alerts": (
        "Alerts", "Competitor changes worth knowing about, and what to watch.",
        True, Permission.VIEW,
    ),
    "reports": (
        "Reports", "Download findings as documents or structured data.",
        True, Permission.EXPORT,
    ),
    "account": (
        "Account", "People, roles, API keys and activity.",
        False, Permission.VIEW,
    ),
    "diagnostics": (
        "Diagnostics", "Spend, failures, jobs and system health.",
        False, Permission.VIEW_DIAGNOSTICS,
    ),
}

#: Sidebar grouping. Ordering follows the actual workflow rather than an
#: alphabetical list, so the sidebar reads as a sequence.
NAV_GROUPS: list[tuple[str, list[str]]] = [
    ("Analyse", ["intake", "workroom", "voice"]),
    ("Strategise", ["strategy", "radar"]),
    ("Act", ["decide", "ask", "alerts", "reports"]),
    ("System", ["account", "diagnostics"]),
]


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
        # Routes the identity may use at all, regardless of product selection.
        permitted = [
            key
            for key, (_label, _purpose, _needs, permission) in ROUTES.items()
            if identity.can(permission)
        ]
        # Of those, the ones reachable right now.
        options = [
            key for key in permitted
            if product is not None or not ROUTES[key][2]
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
                return f"{label}  ({unread})"
            return label

        # Nav buttons rather than one radio per group: several radios each hold
        # their own selection, so two groups can show a selected item at once
        # and clicking one does not clear the other. Buttons set the route
        # explicitly, which is both correct and closer to how a sidebar reads.
        route = current
        for group_name, members in NAV_GROUPS:
            available = [key for key in members if key in permitted]
            if not available:
                continue
            st.markdown(
                f"<div style='font-size:0.64rem;letter-spacing:0.12em;"
                f"text-transform:uppercase;color:#626d7d;font-weight:650;"
                f"margin:1rem 0 0.35rem'>{group_name}</div>",
                unsafe_allow_html=True,
            )
            for key in available:
                reachable = key in options
                # Unreachable routes are shown disabled rather than hidden, so a
                # new user can see the shape of the product instead of guessing
                # what appears once they pick something.
                if st.button(
                    label_for(key),
                    key=f"nav_{key}",
                    width="stretch",
                    type="primary" if key == current else "secondary",
                    disabled=not reachable,
                    help=None if reachable else "Select a product first",
                ):
                    # `current` was read before these buttons rendered, so the
                    # highlight would lag the content by one render without an
                    # explicit rerun.
                    st.session_state["route"] = key
                    st.rerun()

        st.caption(ROUTES[route][1])

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
        if not identity.is_dev and st.button("Sign out", width="stretch"):
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
    from .components import lead, page_header

    page_header(
        "Decide",
        "Turn findings into commitments. Accepting a recommendation puts it on the "
        "roadmap; rejecting it is remembered, so future analyses stop suggesting it.",
    )

    tabs = st.tabs(["Decision board", "Roadmap"])
    with tabs[0]:
        lead(
            "Each recommendation with its reasoning and evidence. Verdicts include "
            "'Do not build' - being told what to skip is as useful as what to ship."
        )
        if not analysis_id:
            from .components import empty_state

            empty_state("Run an analysis first")
        else:
            workroom.render_board(service, service.dashboard(analysis_id))
    with tabs[1]:
        lead(
            "Now, Next and Later. Items arrive here when you accept a recommendation, "
            "and can be reordered, assigned and discussed."
        )
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

        # Formatted rather than raw floats: the tile above says "$0.1224", so an
        # unformatted 0.1224 in the table reads as a different quantity.
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Model": row["model"],
                        "Calls": f"{int(row['calls'] or 0):,}",
                        "Tokens": f"{int(row['tokens'] or 0):,}",
                        "Cost": format_cost(row["cost"]),
                    }
                    for row in usage["by_model"]
                ]
            ),
            width="stretch",
            hide_index=True,
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
    """Warn only when an open app is actually reachable by other people.

    Running open on localhost is a deliberate development choice, and a banner
    repeating that on every screen is noise. Running open on an address other
    machines can route to is a different situation entirely, and stays loud -
    a warning nobody sees is worth nothing, but so is one everybody ignores.
    """
    if service.config.auth_enabled:
        return

    exposure = network_exposure_warning(service.config.auth_enabled)
    if exposure:
        st.error(exposure, icon=":material/gpp_bad:")


if __name__ == "__main__":
    main()
