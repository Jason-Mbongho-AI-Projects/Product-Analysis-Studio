"""The analysis workroom: executive view, intelligence tabs and the decision board.

Each tab is a small function reading from the service layer. Progressive
disclosure is the organising idea - the executive answer first, drill-downs and
raw evidence behind it (spec 47/50).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...domain.enums import (
    AnalysisStatus,
    CompetitorType,
    DecisionState,
    RoadmapHorizon,
    ScoreDimension,
    ThreatLevel,
)
from ...service import StudioService
from ..components import (
    citation_links,
    claim_list,
    confidence_banner,
    confidence_chip,
    empty_state,
    esc,
    grade_chip,
    kpi,
    meter,
    score_row,
    threat_chip,
    verdict_chip,
)
from ..theme import PALETTE, score_colour

LIVE_STATUSES = {AnalysisStatus.PENDING.value, AnalysisStatus.RUNNING.value}


def render(service: StudioService) -> None:
    product_id = st.session_state.get("active_product")
    analysis_id = st.session_state.get("active_analysis")

    product = service.get_product(product_id) if product_id else None
    if product is None:
        empty_state("No product selected", "Pick one from your products list.")
        return

    _render_header(service, product, analysis_id)

    if not analysis_id:
        empty_state(
            "No analysis has been run for this product yet",
            "Use 'Run new version' above to start one.",
        )
        return

    analysis = service.get_analysis(analysis_id)
    if analysis is None:
        empty_state("Analysis not found.")
        return

    if analysis["status"] in LIVE_STATUSES:
        _render_progress(service, analysis)
        return

    if analysis["status"] == AnalysisStatus.FAILED.value:
        st.error(f"This analysis failed: {analysis.get('error')}", icon=":material/error:")
        return

    data = service.dashboard(analysis_id)
    if analysis["status"] == AnalysisStatus.PARTIAL.value and analysis.get("error"):
        st.warning(
            f"Completed with gaps. {esc(analysis['error'])}", icon=":material/warning:"
        )

    confidence_banner(data["quality"])

    tabs = st.tabs(
        [
            "Executive",
            "Product",
            "Competitors",
            "Market",
            "Customers",
            "Scores",
            "Evidence",
            "Sources",
            "Audit",
        ]
    )
    with tabs[0]:
        _tab_executive(data, analysis.get("mode", "founder"))
    with tabs[1]:
        _tab_product(service, analysis_id, data)
    with tabs[2]:
        _tab_competitors(data, service, analysis_id)
    with tabs[3]:
        _tab_market(service, analysis_id, data)
    with tabs[4]:
        _tab_customers(data)
    with tabs[5]:
        _tab_scores(data)
    with tabs[6]:
        _tab_evidence(service, analysis_id)
    with tabs[7]:
        _tab_sources(service, data)
    with tabs[8]:
        _tab_audit(service, product, data)


# ---------------------------------------------------------------------------
# Header and progress
# ---------------------------------------------------------------------------


def _render_header(service: StudioService, product: dict, analysis_id: str | None) -> None:
    st.markdown(f"### {esc(product['name'])}")
    if product.get("one_liner"):
        st.caption(product["one_liner"])

    versions = service.list_analyses(product["id"])
    left, middle, right = st.columns([2, 1, 1])

    with left:
        if versions:
            labels = {
                v["id"]: (
                    f"v{v['version']} · {v['status']} · "
                    f"{str(v['started_at'])[:10]}"
                )
                for v in versions
            }
            current = analysis_id if analysis_id in labels else versions[0]["id"]
            chosen = st.selectbox(
                "Analysis version",
                options=list(labels.keys()),
                format_func=lambda key: labels[key],
                index=list(labels.keys()).index(current),
            )
            if chosen != analysis_id:
                st.session_state["active_analysis"] = chosen
                st.rerun()

    with middle:
        st.write("")
        if st.button("Run new version", use_container_width=True, type="primary"):
            try:
                new_id, _ = service.start_analysis(
                    product["id"], mode=product.get("mode", "founder")
                )
                st.session_state["active_analysis"] = new_id
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with right:
        st.write("")
        if len(versions) >= 2 and st.button("Compare versions", use_container_width=True):
            st.session_state["show_compare"] = not st.session_state.get("show_compare", False)

    if st.session_state.get("show_compare") and len(versions) >= 2:
        _render_comparison(service, product, versions)


def _render_comparison(service: StudioService, product: dict, versions: list[dict]) -> None:
    """Then-vs-now (spec 37)."""
    with st.container(border=True):
        st.markdown("#### Then vs now")
        labels = {v["id"]: f"v{v['version']} ({str(v['started_at'])[:10]})" for v in versions}
        col_a, col_b = st.columns(2)
        older = col_a.selectbox(
            "Earlier", list(labels), format_func=lambda k: labels[k], index=len(versions) - 1
        )
        newer = col_b.selectbox(
            "Later", list(labels), format_func=lambda k: labels[k], index=0
        )
        if older == newer:
            st.caption("Choose two different versions.")
            return

        diff = service.compare_versions(product["id"], older, newer)
        before = diff["composite_before"]["score"]
        after = diff["composite_after"]["score"]
        st.metric("Product score", f"{after:.0f}", delta=f"{after - before:+.1f}")

        if diff["score_deltas"]:
            st.markdown("**Largest movements**")
            for entry in diff["score_deltas"][:6]:
                if entry["delta"] == 0:
                    continue
                colour = PALETTE["success"] if entry["delta"] > 0 else PALETTE["danger"]
                st.markdown(
                    f"- **{ScoreDimension(entry['dimension']).label}**: "
                    f"{entry['before']:.0f} → {entry['after']:.0f} "
                    f"<span style='color:{colour}'>({entry['delta']:+.0f})</span>  \n"
                    f"<span style='color:{PALETTE['muted']};font-size:0.82rem'>"
                    f"{esc(entry['explanation'][:220])}</span>",
                    unsafe_allow_html=True,
                )
        if diff["new_competitors"]:
            st.markdown("**Competitors that appeared since**")
            for competitor in diff["new_competitors"]:
                st.markdown(f"- {esc(competitor['name'])} ({esc(competitor['competitor_type'])})")


def _render_progress(service: StudioService, analysis: dict) -> None:
    """Live progress with partial results as they land (spec 50)."""
    job = service.job_for(analysis["id"])
    progress = float(analysis.get("progress", 0))
    st.progress(progress, text=f"{analysis.get('stage') or 'Working'} · {progress:.0%}")

    col_a, col_b = st.columns([1, 4])
    with col_a:
        if st.button("Cancel", use_container_width=True):
            service.cancel_analysis(analysis["id"])
            st.rerun()
    with col_b:
        if st.button("Refresh", use_container_width=True):
            st.rerun()

    if job:
        events = job.snapshot()
        ready = [e for e in events if e["event"] == "section_ready"]
        if ready:
            st.markdown("**Completed so far**")
            for event in ready:
                st.markdown(f"- {esc(event['message'])}")

        with st.expander("Activity log", expanded=not ready):
            for event in reversed(events[-40:]):
                st.caption(f"{event['event']} — {event['message']}")
    else:
        st.caption(
            "This analysis is not running in the current process. "
            "Refresh to pick up its stored state."
        )

    st.caption("This page does not auto-refresh; use Refresh to poll progress.")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


#: What each mode leads with (spec 58-62). The same intelligence, ordered for
#: the question that reader actually has.
MODE_FRAMING: dict[str, dict[str, Any]] = {
    "founder": {
        "question": "Is this worth building, and what do I do first?",
        "lead": ["verdict", "actions", "risks"],
        "kpi": ("Product score", "Must build", "Biggest risk", "Evidence"),
    },
    "product_manager": {
        "question": "What should the team build next?",
        "lead": ["gaps", "actions", "roadmap"],
        "kpi": ("Must build", "Competitor gaps", "Customer themes", "Evidence"),
    },
    "executive": {
        "question": "Where are the threats and where should we invest?",
        "lead": ["risks", "opportunities", "verdict"],
        "kpi": ("Product score", "Critical threats", "Top opportunities", "Evidence"),
    },
    "investor": {
        "question": "Is this defensible, and what could kill it?",
        "lead": ["market", "defensibility", "risks"],
        "kpi": ("Product score", "Market size", "Defensibility", "Evidence"),
    },
    "consultant": {
        "question": "What is the client-ready finding?",
        "lead": ["verdict", "gaps", "evidence"],
        "kpi": ("Product score", "Findings", "Evidence quality", "Sources"),
    },
}


def _tab_executive(data: dict[str, Any], mode: str = "founder") -> None:
    framing = MODE_FRAMING.get(mode, MODE_FRAMING["founder"])
    st.caption(
        f":material/visibility: **{mode.replace('_', ' ').title()} view** — "
        f"{framing['question']}"
    )
    composite = data["composite"]
    scores = data["scores"]
    recommendations = data["recommendations"]
    competitors = data["competitors"]

    cols = st.columns(4)
    with cols[0]:
        kpi(
            "Product score",
            f"{composite['score']:.0f}/100" if scores else "—",
            f"{composite['confidence']:.0%} avg confidence"
            if scores
            else "Scoring did not complete",
            score_colour(composite["score"]) if scores else PALETTE["muted"],
        )
    with cols[1]:
        critical = [c for c in competitors if c["threat_level"] in ("critical", "high")]
        kpi(
            "Competitive threat",
            str(len(critical)),
            f"of {len(competitors)} competitors rated high or critical",
        )
    with cols[2]:
        must = [r for r in recommendations if r["verdict"] == "must_build"]
        kpi("Must build", str(len(must)), f"of {len(recommendations)} recommendations")
    with cols[3]:
        quality = data["quality"]
        kpi(
            "Evidence backed",
            f"{quality['evidence_backed_ratio']:.0%}",
            f"{quality['total']} claims · {quality['distinct_sources']} sources",
        )

    st.markdown("---")

    if not scores and not recommendations:
        empty_state("No intelligence was produced for this analysis.")
        return

    radar_signals = data.get("radar") or {"opportunities": [], "threats": []}
    _mode_highlights(mode, data, radar_signals)

    left, right = st.columns([3, 2])

    with left:
        st.markdown("#### Highest priority actions")
        pending = [r for r in recommendations if r["decision_state"] == "pending"]
        for rec in (pending or recommendations)[:5]:
            with st.container(border=True):
                st.markdown(
                    f"{verdict_chip(rec['verdict'])} &nbsp; **{esc(rec['title'])}**",
                    unsafe_allow_html=True,
                )
                st.caption(rec["reason"][:320])
                st.markdown(
                    f"<span style='color:{PALETTE['muted']};font-size:0.78rem'>"
                    f"Effort {esc(rec['effort'].upper())} · "
                    f"Confidence {float(rec['confidence']):.0%} · "
                    f"Priority {rec['priority']}</span>",
                    unsafe_allow_html=True,
                )

    with right:
        st.markdown("#### Score profile")
        if scores:
            frame = pd.DataFrame(
                [
                    {
                        "Dimension": ScoreDimension(s["dimension"]).label,
                        "Score": (100 - s["score"]) if s["inverted"] else s["score"],
                    }
                    for s in scores
                ]
            ).set_index("Dimension")
            st.bar_chart(frame, height=420, color=PALETTE["primary_2"])
            st.caption(
                "Inverted dimensions (competitive pressure, acquisition difficulty, "
                "implementation complexity) are shown flipped so higher is always better."
            )


def _mode_highlights(mode: str, data: dict[str, Any], radar_signals: dict) -> None:
    """Surface what this reader cares about most, above the common view."""
    threats = radar_signals.get("threats", [])
    opportunities = radar_signals.get("opportunities", [])

    if mode == "executive" and (threats or opportunities):
        cols = st.columns(2)
        with cols[0]:
            st.markdown("##### Top threats")
            for signal in threats[:3]:
                st.markdown(
                    f"- **{esc(signal['title'])}** "
                    f"<span style='color:{PALETTE['muted']};font-size:0.8rem'>"
                    f"(priority {signal['priority_score']:.0f})</span>",
                    unsafe_allow_html=True,
                )
        with cols[1]:
            st.markdown("##### Top opportunities")
            for signal in opportunities[:3]:
                st.markdown(
                    f"- **{esc(signal['title'])}** "
                    f"<span style='color:{PALETTE['muted']};font-size:0.8rem'>"
                    f"(priority {signal['priority_score']:.0f})</span>",
                    unsafe_allow_html=True,
                )
        st.markdown("---")

    elif mode == "investor":
        market = data.get("market")
        profile = data.get("profile")
        cols = st.columns(2)
        with cols[0]:
            st.markdown("##### Market sizing")
            if market and market["sizing"]:
                for model in market["sizing"]:
                    st.markdown(
                        f"- **{esc(model['label'])}** ${model['value_usd']:,.0f} "
                        f"<span style='color:{PALETTE['muted']};font-size:0.8rem'>"
                        f"({model['confidence']:.0%} confidence)</span>",
                        unsafe_allow_html=True,
                    )
                st.caption("Derived estimates, not measured market data.")
            else:
                st.caption("No sizing available.")
        with cols[1]:
            st.markdown("##### Defensibility")
            st.caption((profile or {}).get("defensibility") or "Not assessed.")
            if threats:
                st.markdown("##### Biggest risk")
                st.caption(threats[0]["title"])
        st.markdown("---")

    elif mode == "product_manager":
        recommendations = data.get("recommendations", [])
        must = [r for r in recommendations if r["verdict"] == "must_build"]
        avoid = [r for r in recommendations if r["verdict"] == "do_not_build"]
        cols = st.columns(2)
        with cols[0]:
            st.markdown("##### Build next")
            for rec in must[:4]:
                st.markdown(f"- **{esc(rec['title'])}** (effort {rec['effort'].upper()})")
            if not must:
                st.caption("Nothing rated must-build.")
        with cols[1]:
            st.markdown("##### Do not build")
            for rec in avoid[:4]:
                st.markdown(f"- {esc(rec['title'])}")
            if not avoid:
                st.caption("Nothing ruled out.")
        st.markdown("---")


def _tab_product(service: StudioService, analysis_id: str, data: dict[str, Any]) -> None:
    profile = data["profile"]
    if not profile:
        empty_state("The product analyst agent did not complete for this version.")
        return

    st.markdown(f"**{esc(profile['summary'])}**")
    st.markdown(f"**Primary problem:** {esc(profile['primary_problem'])}")

    cols = st.columns(3)
    lists = profile.get("lists", {})
    for column, (label, key) in zip(
        cols,
        [
            ("Use cases", "use_cases"),
            ("Core capabilities", "core_capabilities"),
            ("Target customers", "target_customers"),
        ],
    ):
        with column:
            st.markdown(f"**{label}**")
            for item in lists.get(key, [])[:10]:
                st.markdown(f"- {esc(item)}")

    st.markdown("#### Features")
    features = profile.get("features", [])
    if features:
        for feature in features:
            st.markdown(
                f"{grade_chip(feature['grade'])} &nbsp; **{esc(feature['name'])}** — "
                f"{esc(feature['description'])}",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No features recorded.")

    st.markdown("#### SWOT")
    swot = st.tabs(["Strengths", "Weaknesses", "Opportunities", "Threats", "Differentiators"])
    for tab, subject in zip(
        swot, ["strength", "weakness", "opportunity", "threat", "differentiator"]
    ):
        with tab:
            claim_list(service.evidence(analysis_id, subject_type=subject))

    with st.expander("Commercial model"):
        st.markdown(f"**Pricing model:** {esc(profile['pricing_model'])}")
        st.markdown(f"**Distribution:** {esc(profile['distribution_model'])}")
        st.markdown(f"**Switching costs:** {esc(profile['switching_costs'])}")
        st.markdown(f"**Defensibility:** {esc(profile['defensibility'])}")


def _tab_competitors(
    data: dict[str, Any],
    service: "StudioService | None" = None,
    analysis_id: str | None = None,
) -> None:
    competitors = data["competitors"]

    if service is not None and analysis_id:
        _add_competitor_form(service, analysis_id)

    if not competitors:
        empty_state("No competitors were identified for this version.")
        return

    st.markdown("#### Comparison matrix")
    matrix = pd.DataFrame(
        [
            {
                "Competitor": c["name"],
                "Type": c["competitor_type"],
                "Threat": c["threat_level"],
                "Target customer": c["target_customer"][:60],
                "Pricing": c["pricing_summary"][:60],
                "Features": len(c["features"]),
                "Confidence": f"{float(c['confidence']):.0%}",
            }
            for c in competitors
        ]
    )
    st.dataframe(matrix, use_container_width=True, hide_index=True)

    st.caption(
        "Competitor detail is model knowledge unless a source was retrieved. "
        "Pricing in particular goes stale quickly — verify before acting on it."
    )

    st.markdown("#### Detail")
    for competitor in competitors:
        with st.expander(
            f"{competitor['name']} — {competitor['competitor_type']}", expanded=False
        ):
            st.markdown(
                f"{threat_chip(competitor['threat_level'])} "
                f"{grade_chip(competitor['grade'])} "
                f"{confidence_chip(float(competitor['confidence']))}",
                unsafe_allow_html=True,
            )
            if competitor.get("website"):
                st.caption(competitor["website"])
            st.markdown(f"**Positioning:** {esc(competitor['positioning'])}")
            st.markdown(f"**Target customer:** {esc(competitor['target_customer'])}")
            st.markdown(f"**Pricing:** {esc(competitor['pricing_summary'])}")
            st.markdown(f"**Why a competitor:** {esc(competitor['rationale'])}")

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**Strengths**")
                for item in competitor["strengths"]:
                    st.markdown(f"- {esc(item)}")
            with col_b:
                st.markdown("**Weaknesses**")
                for item in competitor["weaknesses"]:
                    st.markdown(f"- {esc(item)}")
            if competitor["features"]:
                st.markdown("**Known features:** " + ", ".join(esc(f) for f in competitor["features"]))

            if service is not None:
                actions = st.columns(2)
                pinned = bool(competitor["pinned"])
                if actions[0].button(
                    "Unpin" if pinned else "Pin to top",
                    key=f"pin_{competitor['id']}",
                    use_container_width=True,
                ):
                    service.pin_competitor(competitor["id"], not pinned)
                    st.rerun()
                if actions[1].button(
                    "Remove", key=f"delcmp_{competitor['id']}", use_container_width=True
                ):
                    service.remove_competitor(competitor["id"])
                    st.rerun()


def _add_competitor_form(service: StudioService, analysis_id: str) -> None:
    """Let the user add a competitor the discovery agent missed (spec 7)."""
    with st.expander("Add a competitor"):
        with st.form("add_competitor", clear_on_submit=True):
            cols = st.columns([2, 2, 1])
            name = cols[0].text_input("Name")
            website = cols[1].text_input("Website (optional)")
            competitor_type = cols[2].selectbox(
                "Type",
                [t.value for t in CompetitorType],
                format_func=lambda v: v.replace("_", " ").title(),
            )
            positioning = st.text_input("How do they position themselves?")
            cols = st.columns([3, 1])
            rationale = cols[0].text_input("Why are they a competitor to you?")
            threat = cols[1].selectbox("Threat", [t.value for t in ThreatLevel], index=2)

            if st.form_submit_button("Add competitor", type="primary"):
                try:
                    service.add_competitor(
                        analysis_id,
                        {
                            "name": name,
                            "website": website,
                            "competitor_type": competitor_type,
                            "positioning": positioning,
                            "rationale": rationale,
                            "threat_level": threat,
                        },
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc), icon=":material/error:")
        st.caption(
            "Competitors you add are graded 'user supplied' rather than presented "
            "as a researched finding."
        )


def _tab_market(service: StudioService, analysis_id: str, data: dict[str, Any]) -> None:
    market = data["market"]
    if not market:
        empty_state("The market analyst agent did not complete for this version.")
        return

    st.markdown(f"**Market:** {esc(market['market_definition'])}")
    st.caption(
        f"Maturity: {market['maturity']} · Concentration: {market['competitive_concentration']}"
    )

    st.markdown("#### Market sizing")
    if market["sizing"]:
        for model in market["sizing"]:
            with st.container(border=True):
                head, value = st.columns([3, 1])
                with head:
                    st.markdown(
                        f"**{esc(model['label'])}** &nbsp; "
                        f"{confidence_chip(float(model['confidence']))} &nbsp; "
                        f"<span style='color:{PALETTE['muted']};font-size:0.78rem'>"
                        f"{esc(model['basis'])}</span>",
                        unsafe_allow_html=True,
                    )
                    st.code(model["formula"] or "No formula recorded", language=None)
                with value:
                    st.markdown(
                        f"<div style='text-align:right;font-size:1.5rem;font-weight:800'>"
                        f"${model['value_usd']:,.0f}</div>",
                        unsafe_allow_html=True,
                    )
                if model["variables"]:
                    st.markdown("**Variables**")
                    for variable in model["variables"]:
                        st.markdown(f"- {esc(variable)}")
                if model["assumptions"]:
                    st.markdown("**Assumptions**")
                    for assumption in model["assumptions"]:
                        st.markdown(f"- {esc(assumption)}")
        st.warning(
            "These are derived estimates, not measured market data. Check each "
            "variable against your own knowledge before using them externally.",
            icon=":material/functions:",
        )
    else:
        st.caption("No sizing models were produced.")

    st.markdown("#### Market forces")
    force_tabs = st.tabs(["Growth", "Drivers", "Inhibitors", "Trends", "Regulatory"])
    for tab, subject in zip(
        force_tabs,
        [
            "market_growth",
            "market_driver",
            "market_inhibitor",
            "market_trend",
            "market_regulatory",
        ],
    ):
        with tab:
            claim_list(service.evidence(analysis_id, subject_type=subject))

    if market["entry_barriers"]:
        st.markdown("**Entry barriers:** " + ", ".join(esc(b) for b in market["entry_barriers"]))
    if market["adjacent_markets"]:
        st.markdown(
            "**Adjacent markets:** " + ", ".join(esc(m) for m in market["adjacent_markets"])
        )


def _tab_customers(data: dict[str, Any]) -> None:
    customers = data["customers"]
    if not customers:
        empty_state("The customer intelligence agent did not complete for this version.")
        return

    st.markdown(f"**Ideal customer profile:** {esc(customers['icp'])}")

    personas = customers.get("personas", [])
    if not personas:
        st.caption("No personas recorded.")
        return

    inferred = [p for p in personas if p["grade"] == "ai_hypothesis"]
    if inferred:
        st.info(
            f"{len(inferred)} of {len(personas)} personas are AI-inferred, not derived "
            "from customer research. Validate them with real interviews before "
            "building around them.",
            icon=":material/psychology:",
        )

    for persona in personas:
        with st.expander(
            f"{persona['name']}"
            f"{' · buyer' if persona['is_buyer'] else ''}"
            f"{' · user' if persona['is_user'] else ''}",
            expanded=False,
        ):
            st.markdown(
                f"{grade_chip(persona['grade'])} "
                f"{confidence_chip(float(persona['confidence']))}",
                unsafe_allow_html=True,
            )
            detail = persona.get("detail", {})
            for label, key in [
                ("Jobs to be done", "jobs_to_be_done"),
                ("Pain points", "pain_points"),
                ("Desired outcomes", "desired_outcomes"),
                ("Buying triggers", "buying_triggers"),
                ("Objections", "objections"),
                ("Decision criteria", "decision_criteria"),
                ("Current alternatives", "current_alternatives"),
            ]:
                values = detail.get(key) or []
                if values:
                    st.markdown(f"**{label}**")
                    for value in values:
                        st.markdown(f"- {esc(value)}")

    if customers.get("switching_concerns"):
        st.markdown("**Switching concerns**")
        for concern in customers["switching_concerns"]:
            st.markdown(f"- {esc(concern)}")


def _tab_scores(data: dict[str, Any]) -> None:
    scores = data["scores"]
    if not scores:
        empty_state("The scoring agent did not complete for this version.")
        return

    composite = data["composite"]
    st.markdown(
        f"<div class='panel'><div class='label' style='font-size:0.72rem;"
        f"letter-spacing:0.12em;text-transform:uppercase;color:{PALETTE['muted']}'>"
        f"Composite product score</div>"
        f"<div style='font-size:2.6rem;font-weight:800;"
        f"color:{score_colour(composite['score'])}'>{composite['score']:.0f}"
        f"<span style='font-size:1.1rem;color:{PALETTE['muted']}'> / 100</span></div>"
        f"{meter(composite['score'])}"
        f"<div style='color:{PALETTE['muted']};font-size:0.82rem'>"
        f"Weighted mean of {len(scores)} dimensions · "
        f"{composite['confidence']:.0%} average confidence · "
        f"{composite['coverage']:.0%} of the weighting model covered</div></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "The composite is computed in code from the weights below, not generated "
        "by the model. Every dimension is drillable."
    )
    st.markdown("---")
    for score in scores:
        score_row(score, ScoreDimension(score["dimension"]).label)


def render_board(service: StudioService, data: dict[str, Any]) -> None:
    """AI Product Board (spec 19)."""
    recommendations = data["recommendations"]
    if not recommendations:
        empty_state("No recommendations were generated for this version.")
        return

    state_filter = st.segmented_control(
        "Filter",
        options=["All", "Pending", "Accepted", "Rejected", "Investigating"],
        default="All",
        label_visibility="collapsed",
    ) or "All"

    if state_filter != "All":
        recommendations = [
            r for r in recommendations if r["decision_state"] == state_filter.lower()
        ]
    if not recommendations:
        st.caption("Nothing in this state.")
        return

    for rec in recommendations:
        with st.container(border=True):
            st.markdown(
                f"{verdict_chip(rec['verdict'])} &nbsp; **{esc(rec['title'])}** &nbsp; "
                f"<span style='color:{PALETTE['muted']};font-size:0.78rem'>"
                f"{esc(rec['gap_category'])} · effort {esc(rec['effort'].upper())} · "
                f"priority {rec['priority']} · {float(rec['confidence']):.0%} confidence"
                f"</span>",
                unsafe_allow_html=True,
            )
            if rec["decision_state"] != DecisionState.PENDING.value:
                st.caption(
                    f"Decision: {rec['decision_state'].upper()}"
                    + (f" — {rec['decision_note']}" if rec["decision_note"] else "")
                )

            st.markdown(f"**Problem:** {esc(rec['problem'])}")
            st.markdown(f"**Recommendation:** {esc(rec['recommendation'])}")

            with st.expander("Reasoning and evidence"):
                st.markdown(f"**Why:** {esc(rec['reason'])}")
                st.markdown(f"**Customer impact:** {esc(rec['customer_impact'])}")
                st.markdown(f"**Competitive impact:** {esc(rec['competitive_impact'])}")
                st.markdown(f"**Expected outcome:** {esc(rec['expected_outcome'])}")
                st.markdown(f"**Risk:** {esc(rec['risk'])}")
                if rec["dependencies"]:
                    st.markdown(
                        "**Dependencies:** " + ", ".join(esc(d) for d in rec["dependencies"])
                    )
                if rec["supporting_evidence"]:
                    st.markdown("**Supporting evidence**")
                    for item in rec["supporting_evidence"]:
                        st.markdown(f"- {esc(item)}")

            actions = st.columns(4)
            if actions[0].button("Accept → roadmap", key=f"acc_{rec['id']}", type="primary"):
                service.accept_to_roadmap(rec["id"])
                st.rerun()
            if actions[1].button("Reject", key=f"rej_{rec['id']}"):
                service.decide(rec["id"], DecisionState.REJECTED.value)
                st.rerun()
            if actions[2].button("Investigate", key=f"inv_{rec['id']}"):
                service.decide(rec["id"], DecisionState.INVESTIGATING.value)
                st.rerun()
            if actions[3].button("Postpone", key=f"pos_{rec['id']}"):
                service.decide(rec["id"], DecisionState.POSTPONED.value)
                st.rerun()

            _comment_thread(service, rec["product_id"], "recommendation", rec["id"])

    st.caption(
        "Rejected recommendations are remembered. Future analyses of this product "
        "will not resurface them as pending unless new evidence changes the picture."
    )


def render_roadmap(service: StudioService, product: dict) -> None:
    roadmap = service.roadmap(product["id"])

    with st.form("add_roadmap", clear_on_submit=True):
        cols = st.columns([3, 1, 1])
        title = cols[0].text_input("Add an initiative", placeholder="Custom roadmap item")
        horizon = cols[1].selectbox(
            "Horizon",
            [h.value for h in RoadmapHorizon],
            format_func=lambda v: {"now": "Now (0-30d)", "next": "Next (30-90d)", "later": "Later (3-12m)"}[v],
        )
        cols[2].markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
        if cols[2].form_submit_button("Add", use_container_width=True):
            try:
                service.add_roadmap_item(product["id"], title, horizon=horizon)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    columns = st.columns(3)
    headers = {
        "now": "NOW · 0-30 days",
        "next": "NEXT · 30-90 days",
        "later": "LATER · 3-12 months",
    }
    for column, horizon in zip(columns, ["now", "next", "later"]):
        with column:
            st.markdown(f"**{headers[horizon]}**")
            items = roadmap.get(horizon, [])
            if not items:
                st.caption("Empty")
            for item in items:
                with st.container(border=True):
                    st.markdown(f"**{esc(item['title'])}**")
                    if item.get("detail"):
                        st.caption(item["detail"][:180])
                    owner = item.get("assignee_label") or "unassigned"
                    st.caption(
                        f"Effort {item['effort'].upper()} · {item['status']} · {owner}"
                    )

                    # Streamlit has no native drag-and-drop, so ordering within a
                    # horizon is explicit.
                    order_cols = st.columns(2)
                    if order_cols[0].button(
                        "↑", key=f"up_{item['id']}", use_container_width=True,
                        help="Move up",
                    ):
                        service.reorder_roadmap_item(item["id"], -1)
                        st.rerun()
                    if order_cols[1].button(
                        "↓", key=f"down_{item['id']}", use_container_width=True,
                        help="Move down",
                    ):
                        service.reorder_roadmap_item(item["id"], 1)
                        st.rerun()

                    move_cols = st.columns(3)
                    targets = [h for h in ["now", "next", "later"] if h != horizon]
                    for move_col, target in zip(move_cols, targets):
                        if move_col.button(
                            f"→ {target}", key=f"mv_{item['id']}_{target}",
                            use_container_width=True,
                        ):
                            service.move_roadmap_item(item["id"], target)
                            st.rerun()
                    if move_cols[2].button(
                        "Remove", key=f"rm_{item['id']}", use_container_width=True
                    ):
                        service.delete_roadmap_item(item["id"])
                        st.rerun()

                    _assignment_control(service, item)
                    _comment_thread(service, product["id"], "roadmap_item", item["id"])


def _assignment_control(service: StudioService, item: dict[str, Any]) -> None:
    """Assign a roadmap item to a workspace member (spec 32)."""
    members = service.auth.members(service.workspace_id)
    if not members:
        return

    options = [""] + [m["id"] for m in members]
    labels = {"": "Unassigned", **{m["id"]: (m["name"] or m["email"]) for m in members}}
    current = item.get("assignee_id") or ""
    if current not in labels:
        current = ""

    chosen = st.selectbox(
        "Owner",
        options,
        index=options.index(current),
        format_func=lambda key: labels[key],
        key=f"assign_{item['id']}",
        label_visibility="collapsed",
    )
    if chosen != current:
        service.assign_roadmap_item(item["id"], chosen or None, labels[chosen])
        st.rerun()


def _comment_thread(
    service: StudioService, product_id: str, target_type: str, target_id: str
) -> None:
    """A discussion thread attached to any object (spec 32)."""
    comments = service.comments(target_type, target_id)
    open_count = len([c for c in comments if not c["resolved"]])

    with st.expander(f"Discussion ({open_count})" if open_count else "Discussion"):
        for comment in comments:
            style = "opacity:0.55;" if comment["resolved"] else ""
            st.markdown(
                f"<div style='{style}border-left:2px solid {PALETTE['line']};"
                f"padding-left:0.6rem;margin-bottom:0.5rem'>"
                f"<strong>{esc(comment['author_label'])}</strong> "
                f"<span style='color:{PALETTE['muted']};font-size:0.72rem'>"
                f"{str(comment['created_at'])[:16].replace('T', ' ')}</span><br>"
                f"{esc(comment['body'])}</div>",
                unsafe_allow_html=True,
            )
            if not comment["resolved"] and st.button(
                "Resolve", key=f"res_{comment['id']}"
            ):
                service.resolve_comment(comment["id"])
                st.rerun()

        with st.form(f"comment_{target_id}", clear_on_submit=True):
            body = st.text_area(
                "Comment", height=68, label_visibility="collapsed",
                placeholder="Add a note. Use @name to mention a teammate.",
            )
            if st.form_submit_button("Post"):
                try:
                    service.add_comment(product_id, target_type, target_id, body)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def _tab_evidence(service: StudioService, analysis_id: str) -> None:
    """The evidence ledger (spec 4)."""
    grades = st.multiselect(
        "Filter by grade",
        options=[
            "verified_fact",
            "strong_inference",
            "weak_inference",
            "ai_hypothesis",
            "user_supplied",
        ],
        default=[],
        format_func=lambda g: g.replace("_", " ").title(),
    )
    query = st.text_input("Search claims", placeholder="e.g. pricing, compliance, integration")

    evidence = service.evidence(analysis_id, grades=grades or None, limit=400)
    if query:
        needle = query.lower()
        evidence = [
            e
            for e in evidence
            if needle in e["claim"].lower() or needle in (e.get("detail") or "").lower()
        ]

    if not evidence:
        empty_state("No evidence matches this filter.")
        return

    st.caption(f"{len(evidence)} claims")
    for item in evidence:
        with st.container(border=True):
            st.markdown(
                f"{grade_chip(item['grade'])} &nbsp; **{esc(item['claim'])}**",
                unsafe_allow_html=True,
            )
            if item.get("detail"):
                st.caption(item["detail"])
            st.markdown(
                f"<span style='color:{PALETTE['muted']};font-size:0.76rem'>"
                f"{float(item['confidence']):.0%} confidence · agent: {esc(item['agent'])} · "
                f"{str(item['created_at'])[:19].replace('T', ' ')} · "
                f"{citation_links(item.get('citations', []))}</span>",
                unsafe_allow_html=True,
            )


def _tab_sources(service: StudioService, data: dict[str, Any]) -> None:
    """Source library (spec 36)."""
    sources = data["sources"]
    if not sources:
        empty_state(
            "No sources were retrieved",
            "This analysis relied on model knowledge alone. Add a product URL and "
            "re-run to ground it in evidence.",
        )
        return

    frame = pd.DataFrame(
        [
            {
                "Title": s["title"][:60],
                "Type": s["source_type"],
                "Status": s["status"],
                "Citations": s["citation_count"],
                "Fetched": str(s.get("fetched_at") or "")[:19].replace("T", " "),
                "URL": s.get("url") or "",
            }
            for s in sources
        ]
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)

    failed = [s for s in sources if s["status"] in ("failed", "blocked")]
    if failed:
        with st.expander(f"{len(failed)} source(s) unavailable"):
            for source in failed:
                reason = source.get("failure_reason") or "Unknown reason"
                st.markdown(f"- `{esc(source.get('url'))}` — {esc(reason)}")
            st.caption(
                "Sources that block automated access are recorded and skipped rather "
                "than worked around."
            )

    st.markdown("**Disable a source**")
    active = [s for s in sources if s["status"] == "active"]
    if active:
        choice = st.selectbox(
            "Source",
            options=[s["id"] for s in active],
            format_func=lambda sid: next(s["title"][:70] for s in active if s["id"] == sid),
            label_visibility="collapsed",
        )
        if st.button("Disable this source"):
            service.disable_source(choice)
            st.rerun()


def _tab_audit(service: StudioService, product: dict, data: dict[str, Any]) -> None:
    """Auditability and cost (spec 38/43/44)."""
    usage = data["usage"]
    runs = data["runs"]

    cols = st.columns(4)
    with cols[0]:
        kpi("Model calls", str(usage.get("calls", 0)))
    with cols[1]:
        kpi("Tokens", f"{int(usage.get('tokens', 0)):,}")
    with cols[2]:
        kpi("Cost", f"${float(usage.get('cost', 0)):.4f}", "measured, not estimated")
    with cols[3]:
        kpi("Avg latency", f"{float(usage.get('avg_latency', 0))/1000:.1f}s")

    st.markdown("#### Agent runs")
    if runs:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Agent": r["agent"],
                        "Status": r["status"],
                        "Model": r["model"],
                        "Attempts": r["attempts"],
                        "Duration": f"{r['duration_ms'] / 1000:.1f}s",
                        "Error": (r.get("error") or "")[:80],
                    }
                    for r in runs
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No agent runs recorded.")

    if usage.get("by_model"):
        st.markdown("#### Cost by model")
        st.dataframe(
            pd.DataFrame(usage["by_model"]), use_container_width=True, hide_index=True
        )

    st.markdown("#### Strategic memory")
    from ...storage import repositories as repo

    memory = repo.list_memory(service.conn, product["id"], limit=40)
    if memory:
        for item in memory:
            st.markdown(
                f"- `{esc(item['kind'])}` **{esc(item['summary'])}** "
                f"<span style='color:{PALETTE['muted']};font-size:0.76rem'>"
                f"{str(item['created_at'])[:19].replace('T', ' ')}</span>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No decisions recorded yet.")
