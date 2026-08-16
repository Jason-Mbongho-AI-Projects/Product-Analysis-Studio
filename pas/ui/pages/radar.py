"""Opportunity and threat radar, plus the scenario lab (spec 20 / 27 / 28)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...domain.enums import TimeHorizon
from ...service import StudioService
from ..components import chip, empty_state, esc, kpi, lead, meter, page_header
from ..theme import PALETTE, score_colour

SUGGESTED_SCENARIOS = [
    "What happens if we increase prices by 30%?",
    "What happens if we add a free tier?",
    "What happens if we target enterprise customers instead of SMBs?",
    "What happens if our biggest competitor cuts their price in half?",
    "What happens if we launch a public API?",
    "What happens if churn doubles?",
    "What happens if we expand into Europe?",
]


def render(service: StudioService, product: dict, analysis_id: str | None) -> None:
    page_header(
        "Radar",
        "What is coming rather than what is true today - ranked opportunities and "
        "threats, plus a lab for modelling what-if decisions before you make them.",
    )

    tabs = st.tabs(["Opportunity radar", "Threat radar", "Scenario lab"])
    with tabs[0]:
        lead(
            "Where the upside is. Ranked by expected value (impact x probability), so "
            "a large but unlikely prize does not outrank a modest certain one."
        )
        _radar(service, analysis_id, "opportunities", "opportunity")
    with tabs[1]:
        lead(
            "What could go wrong, ranked the same way. Impact and probability are "
            "scored separately so you can tell a catastrophe-if-it-happens from a "
            "near-certainty."
        )
        _radar(service, analysis_id, "threats", "threat")
    with tabs[2]:
        lead(
            "Ask what happens if something changes - a price rise, a competitor move, "
            "a new segment. Returns best, base and worst cases with the assumptions "
            "each rests on. These are projections, not predictions."
        )
        _scenarios(service, product, analysis_id)


def _radar(service: StudioService, analysis_id: str | None, key: str, kind: str) -> None:
    if not analysis_id:
        empty_state("Run an analysis first")
        return

    signals = service.radar(analysis_id)[key]
    if not signals:
        empty_state(
            f"No {kind}s identified",
            "The radar agent runs as part of a full analysis. Run a new version if "
            "this analysis predates it.",
        )
        return

    positive = kind == "opportunity"
    accent = PALETTE["success"] if positive else PALETTE["danger"]

    cols = st.columns(4)
    with cols[0]:
        kpi(f"{kind.title()}s", str(len(signals)), colour=accent)
    with cols[1]:
        immediate = [s for s in signals if s["horizon"] == "immediate"]
        kpi("Immediate", str(len(immediate)), "next 3 months")
    with cols[2]:
        high = [s for s in signals if s["priority_score"] >= 50]
        kpi("High priority", str(len(high)), "impact x probability >= 50")
    with cols[3]:
        top = signals[0]
        kpi("Top ranked", f"{top['priority_score']:.0f}", top["title"][:28])

    st.markdown("#### Impact vs probability")
    st.caption(
        "Ranked by expected value (impact x probability), so a catastrophic but "
        "unlikely signal does not outrank a moderate but near-certain one."
    )
    st.scatter_chart(
        pd.DataFrame(
            [
                {
                    "Probability": s["probability"],
                    "Impact": s["impact"],
                    "Signal": s["title"][:40],
                }
                for s in signals
            ]
        ),
        x="Probability",
        y="Impact",
        color="Signal",
        height=380,
    )

    st.markdown(f"#### Ranked {kind}s")
    for signal in signals:
        _signal_card(signal, accent)


def _signal_card(signal: dict[str, Any], accent: str) -> None:
    with st.container(border=True):
        head, score = st.columns([4, 1])
        with head:
            horizon = signal["horizon"]
            label = (
                TimeHorizon(horizon).label
                if horizon in {h.value for h in TimeHorizon}
                else horizon
            )
            st.markdown(
                f"**{esc(signal['title'])}**<br>"
                f"{chip(signal['category'].replace('_', ' '), PALETTE['primary_2'])} "
                f"{chip(label, PALETTE['muted'])}",
                unsafe_allow_html=True,
            )
        with score:
            priority = float(signal["priority_score"])
            st.markdown(
                f"<div style='text-align:right;font-size:1.5rem;font-weight:800;"
                f"color:{score_colour(priority)}'>{priority:.0f}</div>"
                f"<div style='text-align:right;font-size:0.68rem;color:{PALETTE['muted']}'>"
                f"PRIORITY</div>",
                unsafe_allow_html=True,
            )

        st.write(signal["description"])

        bars = st.columns(2)
        with bars[0]:
            st.markdown(
                f"<span style='font-size:0.78rem;color:{PALETTE['muted']}'>IMPACT "
                f"{signal['impact']:.0f}</span>{meter(signal['impact'], colour=accent)}",
                unsafe_allow_html=True,
            )
        with bars[1]:
            st.markdown(
                f"<span style='font-size:0.78rem;color:{PALETTE['muted']}'>PROBABILITY "
                f"{signal['probability']:.0f}</span>"
                f"{meter(signal['probability'], colour=PALETTE['primary_2'])}",
                unsafe_allow_html=True,
            )

        with st.expander("Why now, and what to do"):
            st.markdown(f"**Why now:** {esc(signal['why_now'])}")
            st.markdown(f"**Recommended response:** {esc(signal['recommended_response'])}")
            evidence = signal.get("supporting_evidence") or []
            if evidence:
                st.markdown("**Supporting evidence**")
                for item in evidence:
                    st.markdown(f"- {esc(item)}")
            st.caption(f"Confidence {float(signal['confidence']):.0%}")


# ---------------------------------------------------------------------------
# Scenario lab
# ---------------------------------------------------------------------------


def _scenarios(service: StudioService, product: dict, analysis_id: str | None) -> None:
    st.caption(
        "Model an open-ended what-if. Outcomes are projections under stated "
        "assumptions — not predictions."
    )

    if not analysis_id:
        empty_state("Run an analysis first", "Scenarios are grounded in analysis output.")
        return

    prefill = st.session_state.pop("scenario_prefill", "")
    with st.form("scenario"):
        question = st.text_area(
            "Scenario",
            value=prefill,
            height=90,
            placeholder="What happens if we increase prices by 30%?",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button(
            "Model this scenario", type="primary", width="stretch"
        )

    cols = st.columns(2)
    for index, suggestion in enumerate(SUGGESTED_SCENARIOS):
        if cols[index % 2].button(suggestion, key=f"scn_{index}", width="stretch"):
            st.session_state["scenario_prefill"] = suggestion
            st.rerun()

    if submitted and question.strip():
        try:
            with st.spinner("Modelling..."):
                service.run_scenario(product["id"], analysis_id, question)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc), icon=":material/error:")

    runs = service.scenario_runs(product["id"])
    if not runs:
        return

    st.markdown("---")
    st.markdown("#### Modelled scenarios")
    for run in runs:
        with st.expander(run["question"][:110], expanded=run is runs[0]):
            st.markdown(f"**Recommendation:** {esc(run['recommendation'])}")
            st.caption(f"Reversibility: {run['reversibility']}")

            outcomes = run.get("outcomes") or []
            if outcomes:
                outcome_cols = st.columns(len(outcomes))
                for column, outcome in zip(outcome_cols, outcomes):
                    with column, st.container(border=True):
                        case = (outcome.get("case") or "").lower()
                        colour = {
                            "best": PALETTE["success"],
                            "base": PALETTE["primary_2"],
                            "worst": PALETTE["danger"],
                        }.get(case, PALETTE["muted"])
                        st.markdown(
                            f"<div style='font-weight:800;color:{colour};"
                            f"text-transform:uppercase;font-size:0.78rem;"
                            f"letter-spacing:0.1em'>{esc(case)} case</div>"
                            f"<div style='font-size:1.3rem;font-weight:800'>"
                            f"{float(outcome.get('probability', 0)):.0f}%</div>",
                            unsafe_allow_html=True,
                        )
                        st.caption(outcome.get("narrative", ""))
                        st.markdown(f"**Revenue:** {esc(outcome.get('revenue_impact', ''))}")
                        st.markdown(f"**Customers:** {esc(outcome.get('customer_impact', ''))}")
                        st.markdown(
                            f"**Competitive:** {esc(outcome.get('competitive_impact', ''))}"
                        )

            detail = st.columns(2)
            with detail[0]:
                st.markdown("**Assumptions**")
                for item in run.get("assumptions", []):
                    st.markdown(f"- {esc(item)}")
                st.markdown("**Leading indicators**")
                for item in run.get("leading_indicators", []):
                    st.markdown(f"- {esc(item)}")
            with detail[1]:
                st.markdown("**Risks**")
                for item in run.get("risks", []):
                    st.markdown(f"- {esc(item)}")

            st.caption(
                f"Confidence {float(run['confidence']):.0%} · "
                f"{str(run['created_at'])[:16].replace('T', ' ')} · "
                "Projection under the assumptions above, not a prediction."
            )
            if st.button("Delete", key=f"delscn_{run['id']}"):
                service.delete_scenario_run(run["id"])
                st.rerun()
