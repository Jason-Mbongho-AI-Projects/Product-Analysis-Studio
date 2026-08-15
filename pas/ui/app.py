"""Streamlit entry point and routing.

Navigation is organised into sections rather than one long tab strip: the
workroom answers "what is true", strategy answers "what to do", and the rest
are working surfaces. Sixteen tabs on one page would be the dashboard clutter
the product is supposed to avoid.
"""

from __future__ import annotations

import streamlit as st

from ..service import StudioService
from . import theme
from .components import esc, kpi
from .pages import alerts, ask, intake, reports, strategy, workroom

#: route -> (label, icon, requires a selected product)
ROUTES: dict[str, tuple[str, str, bool]] = {
    "intake": ("Products", ":material/inventory_2:", False),
    "workroom": ("Analysis", ":material/analytics:", True),
    "strategy": ("Strategy", ":material/target:", True),
    "decide": ("Decide", ":material/checklist:", True),
    "ask": ("Ask", ":material/forum:", True),
    "alerts": ("Alerts", ":material/notifications:", True),
    "reports": ("Reports", ":material/description:", True),
    "diagnostics": ("Diagnostics", ":material/monitoring:", False),
}


@st.cache_resource(show_spinner=False)
def _service() -> StudioService:
    """One service per process. Cached so migrations run once, not per rerun."""
    return StudioService()


def _active_jobs():
    from ..jobs.runner import get_runner

    return get_runner().active_jobs()


def _sidebar(service: StudioService, product: dict | None) -> str:
    with st.sidebar:
        st.markdown("### Product Analysis Studio")
        st.caption("AI product intelligence & strategy OS")

        options = [
            key
            for key, (_label, _icon, needs_product) in ROUTES.items()
            if product is not None or not needs_product
        ]
        current = st.session_state.get("route", "intake")
        if current not in options:
            current = "intake"

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
        service = _service()
    except Exception as exc:  # database or migration failure
        st.error(f"Could not start: {exc}", icon=":material/error:")
        st.stop()
        return

    product_id = st.session_state.get("active_product")
    product = service.get_product(product_id) if product_id else None
    if product is None and product_id:
        # The product was deleted in another tab or session.
        st.session_state["active_product"] = None
        st.session_state["active_analysis"] = None

    route = _sidebar(service, product)
    st.session_state["route"] = route

    if route == "intake":
        intake.render(service)
        return

    if product is None:
        intake.render(service)
        return

    analysis_id = st.session_state.get("active_analysis")

    if route == "workroom":
        workroom.render(service)
    elif route == "strategy":
        strategy.render(service, product, analysis_id)
    elif route == "decide":
        _decide(service, product, analysis_id)
    elif route == "ask":
        ask.render(service, product, analysis_id)
    elif route == "alerts":
        alerts.render(service, product, analysis_id)
    elif route == "reports":
        reports.render(service, product, analysis_id)
    else:
        _diagnostics(service)


if __name__ == "__main__":
    main()
