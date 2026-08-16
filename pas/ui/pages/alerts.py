"""Alert centre, competitor monitors and change history (spec 8 / 33 / 34)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ...domain.enums import AlertSeverity, AlertStatus
from ...service import StudioService
from ..components import chip, empty_state, esc, kpi, lead, page_header
from ..theme import PALETTE

SEVERITY_COLOURS = {
    "critical": "#f87171",
    "high": "#fb923c",
    "medium": "#fbbf24",
    "low": "#38bdf8",
    "informational": "#94a3b8",
}

INTERVALS = {
    "Every 6 hours": 6,
    "Daily": 24,
    "Every 3 days": 72,
    "Weekly": 168,
    "Fortnightly": 336,
}


def render(service: StudioService, product: dict, analysis_id: str | None) -> None:
    page_header(
        "Alerts",
        "Competitor changes worth acting on. Pages are re-checked on a schedule and "
        "only genuine changes are analysed, so routine checks cost nothing.",
    )

    tabs = st.tabs(["Alert centre", "Monitors", "Change history"])
    with tabs[0]:
        lead(
            "Changes serious enough to need a decision, most severe first. Turn any "
            "of them into a roadmap item, or ask the AI whether it is a real threat."
        )
        _alert_centre(service, product)
    with tabs[1]:
        lead(
            "Pages to watch. Pricing and feature pages carry the most signal. The "
            "first run establishes a baseline; changes are detected from then on."
        )
        _monitors(service, product, analysis_id)
    with tabs[2]:
        lead("Everything detected so far, including changes too minor to alert on.")
        _changes(service, product)


def _alert_centre(service: StudioService, product: dict) -> None:
    alerts = service.alerts(product["id"])

    if not alerts:
        empty_state(
            "No alerts",
            "Set up a monitor to be told when a competitor changes something that matters.",
        )
        return

    unread = [a for a in alerts if a["status"] == AlertStatus.UNREAD.value]
    critical = [a for a in alerts if a["severity"] in ("critical", "high")]

    cols = st.columns(3)
    with cols[0]:
        kpi("Unread", str(len(unread)))
    with cols[1]:
        kpi(
            "High or critical",
            str(len(critical)),
            colour=PALETTE["danger"] if critical else None,
        )
    with cols[2]:
        kpi("Total", str(len(alerts)))

    view = st.segmented_control(
        "View",
        options=["Unread", "All", "Archived"],
        default="Unread",
        label_visibility="collapsed",
    ) or "Unread"

    if view == "Unread":
        shown = [a for a in alerts if a["status"] in (AlertStatus.UNREAD.value, AlertStatus.READ.value)]
    elif view == "Archived":
        shown = [a for a in alerts if a["status"] == AlertStatus.ARCHIVED.value]
    else:
        shown = alerts

    if not shown:
        st.caption("Nothing here.")
        return

    for alert in shown:
        colour = SEVERITY_COLOURS.get(alert["severity"], PALETTE["muted"])
        with st.container(border=True):
            st.markdown(
                f"{chip(alert['severity'], colour)} "
                f"{chip(alert['category'], PALETTE['muted'])} &nbsp; "
                f"**{esc(alert['title'])}**"
                + (
                    ""
                    if alert["status"] != AlertStatus.UNREAD.value
                    else f" <span style='color:{PALETTE['primary_2']}'>●</span>"
                ),
                unsafe_allow_html=True,
            )
            if alert.get("body"):
                st.caption(alert["body"])
            if alert.get("recommended_action"):
                st.markdown(f"**Recommended action:** {esc(alert['recommended_action'])}")
            if alert.get("source_url"):
                st.caption(f"Source: {alert['source_url']}")
            st.caption(str(alert["created_at"])[:16].replace("T", " "))

            actions = st.columns(4)
            if alert["status"] == AlertStatus.UNREAD.value:
                if actions[0].button("Mark read", key=f"rd_{alert['id']}", width="stretch"):
                    service.set_alert_status(alert["id"], AlertStatus.READ.value)
                    st.rerun()
            if actions[1].button("Add to roadmap", key=f"rm_{alert['id']}", width="stretch"):
                service.alert_to_roadmap(alert["id"])
                st.success("Added to roadmap and archived.")
                st.rerun()
            if actions[2].button("Ask AI", key=f"ak_{alert['id']}", width="stretch"):
                st.session_state["ask_prefill"] = (
                    f"A competitor change was detected: {alert['title']}. "
                    "Is this a genuine threat to us, and what should we do?"
                )
                st.session_state["route"] = "ask"
                st.rerun()
            if alert["status"] != AlertStatus.ARCHIVED.value:
                if actions[3].button("Archive", key=f"ar_{alert['id']}", width="stretch"):
                    service.set_alert_status(alert["id"], AlertStatus.ARCHIVED.value)
                    st.rerun()


def _monitors(service: StudioService, product: dict, analysis_id: str | None) -> None:
    st.caption(
        "Monitors re-check pages on a schedule. A page is only sent to the model "
        "when its content actually changed, so routine checks cost nothing."
    )

    suggestions: list[str] = []
    if analysis_id:
        for competitor in service.dashboard(analysis_id)["competitors"]:
            if competitor.get("website"):
                suggestions.append(competitor["website"])

    with st.form("add_monitor", clear_on_submit=True):
        label = st.text_input("Monitor name", placeholder="e.g. Rival pricing pages")
        urls = st.text_area(
            "URLs to watch (one per line)",
            value="\n".join(suggestions[:5]),
            height=110,
            help="Pricing and feature pages carry the most signal.",
        )
        cols = st.columns([2, 1])
        interval = cols[0].selectbox("Check frequency", list(INTERVALS), index=3)
        cols[1].markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
        if cols[1].form_submit_button("Create", type="primary", width="stretch"):
            try:
                service.create_monitor(
                    product["id"],
                    label,
                    [line for line in urls.splitlines() if line.strip()],
                    INTERVALS[interval],
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc), icon=":material/error:")

    monitors = service.monitors(product["id"])
    if not monitors:
        empty_state("No monitors configured")
        return

    due = {m["id"] for m in service.due_monitors()}

    for monitor in monitors:
        with st.container(border=True):
            head, status = st.columns([3, 1])
            with head:
                st.markdown(f"**{esc(monitor['label'])}**")
                st.caption(
                    f"{len(monitor['urls'])} page(s) · every {monitor['interval_hours']}h · "
                    + (
                        f"last run {str(monitor['last_run_at'])[:16].replace('T', ' ')} "
                        f"({monitor['last_status']})"
                        if monitor["last_run_at"]
                        else "never run"
                    )
                )
                for url in monitor["urls"][:6]:
                    st.caption(f"· {url}")
                if monitor.get("last_error"):
                    st.caption(f"Last error: {monitor['last_error']}")
            with status:
                if not monitor["enabled"]:
                    st.caption("Paused")
                elif monitor["id"] in due:
                    st.markdown(
                        chip("due now", PALETTE["accent"]), unsafe_allow_html=True
                    )
                st.caption(f"{monitor['changes_found']} changes found")

            job = service.job_for(monitor["id"])
            running = job is not None and not job.is_terminal

            actions = st.columns(3)
            if actions[0].button(
                "Running..." if running else "Check now",
                key=f"run_{monitor['id']}",
                disabled=running,
                width="stretch",
            ):
                try:
                    service.run_monitor(monitor["id"])
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if actions[1].button(
                "Resume" if not monitor["enabled"] else "Pause",
                key=f"tg_{monitor['id']}",
                width="stretch",
            ):
                service.set_monitor_enabled(monitor["id"], not monitor["enabled"])
                st.rerun()
            if actions[2].button("Delete", key=f"dl_{monitor['id']}", width="stretch"):
                service.delete_monitor(monitor["id"])
                st.rerun()

            if job:
                with st.expander("Activity", expanded=running):
                    for event in reversed(job.snapshot()[-25:]):
                        st.caption(f"{event['event']} — {event['message']}")
                    if running:
                        if st.button("Refresh", key=f"rf_{monitor['id']}"):
                            st.rerun()


def _changes(service: StudioService, product: dict) -> None:
    changes = service.changes(product["id"])
    if not changes:
        empty_state(
            "No changes detected yet",
            "Run a monitor at least twice — the first run establishes a baseline.",
        )
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Detected": str(c["detected_at"])[:10],
                    "Type": c["change_type"],
                    "Severity": c["severity"],
                    "Summary": c["summary"][:90],
                    "Confidence": f"{float(c['confidence']):.0%}",
                }
                for c in changes
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    for change in changes[:25]:
        with st.expander(f"{change['summary'][:90]}"):
            cols = st.columns(2)
            cols[0].markdown("**Was**")
            cols[0].caption(change["previous_state"] or "—")
            cols[1].markdown("**Now**")
            cols[1].caption(change["current_state"] or "—")
            st.markdown(f"**Evidence:** {esc(change['evidence'])}")
            st.markdown(f"**Estimated impact:** {esc(change['estimated_impact'])}")
            st.markdown(f"**Recommended action:** {esc(change['recommended_action'])}")
            if change.get("source_url"):
                st.caption(f"Source: {change['source_url']}")
