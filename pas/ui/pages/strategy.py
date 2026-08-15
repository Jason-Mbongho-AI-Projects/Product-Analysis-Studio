"""Strategy studios: positioning, pricing, growth, GTM and the simulation lab.

The simulator is the one surface where the user drives the numbers directly.
Everything it shows is computed by ``analysis.finance`` from inputs on screen,
so a projection can always be traced back to the assumptions that produced it.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...analysis import finance
from ...domain.enums import GrowthChannel, LaunchHorizon, PricingModel
from ...service import StudioService
from ..components import (
    confidence_chip,
    empty_state,
    esc,
    format_price,
    grade_chip,
    kpi,
    meter,
)
from ..theme import PALETTE, score_colour


def render(service: StudioService, product: dict, analysis_id: str | None) -> None:
    if not analysis_id:
        empty_state("Run an analysis first", "Strategy is built from analysis output.")
        return

    data = service.dashboard(analysis_id)
    tabs = st.tabs(["Positioning", "Pricing", "Growth", "Go-to-market", "Simulation lab"])

    with tabs[0]:
        _positioning(data.get("positioning"))
    with tabs[1]:
        _pricing(data.get("pricing"))
    with tabs[2]:
        _growth(data.get("growth"))
    with tabs[3]:
        _gtm(data.get("gtm"))
    with tabs[4]:
        _simulator(service, product, analysis_id)


# ---------------------------------------------------------------------------
# Positioning
# ---------------------------------------------------------------------------


def _positioning(positioning: dict[str, Any] | None) -> None:
    if not positioning:
        empty_state("The positioning strategist did not complete for this version.")
        return

    st.markdown(f"#### Recommended: {esc(positioning['recommended_strategy'])}")
    st.write(positioning["recommendation_reason"])

    messaging = positioning.get("messaging", {})
    if messaging:
        with st.container(border=True):
            st.markdown("##### Messaging")
            st.markdown(
                f"<div style='font-size:1.5rem;font-weight:800;color:#f8fafc;"
                f"line-height:1.2'>{esc(messaging.get('homepage_headline', ''))}</div>"
                f"<div style='color:{PALETTE['muted']};margin-top:0.4rem'>"
                f"{esc(messaging.get('homepage_subheadline', ''))}</div>",
                unsafe_allow_html=True,
            )
            st.markdown("---")
            for label, key in [
                ("Positioning statement", "positioning_statement"),
                ("Unique value proposition", "unique_value_proposition"),
                ("Category definition", "category_definition"),
                ("Elevator pitch", "elevator_pitch"),
                ("Differentiation statement", "differentiation_statement"),
                ("Sales narrative", "sales_narrative"),
            ]:
                if messaging.get(key):
                    st.markdown(f"**{label}**")
                    st.write(messaging[key])

            hierarchy = messaging.get("messaging_hierarchy") or []
            if hierarchy:
                st.markdown("**Messaging hierarchy**")
                for index, message in enumerate(hierarchy, start=1):
                    st.markdown(f"{index}. {esc(message)}")

            objections = messaging.get("objection_handling") or []
            if objections:
                st.markdown("**Objection handling**")
                for item in objections:
                    with st.expander(item.get("objection", "Objection")):
                        st.write(item.get("response", ""))

    st.markdown("#### Strategies considered")
    for option in positioning.get("options", []):
        recommended = bool(option.get("is_recommended"))
        with st.container(border=True):
            head, score = st.columns([4, 1])
            with head:
                badge = " ★ recommended" if recommended else ""
                st.markdown(
                    f"**{esc(option['strategy_name'])}**"
                    f"<span style='color:{PALETTE['success']}'>{badge}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Target: {option['target_customer']}")
            with score:
                fit = float(option["fit_score"])
                st.markdown(
                    f"<div style='text-align:right;font-size:1.3rem;font-weight:800;"
                    f"color:{score_colour(fit)}'>{fit:.0f}</div>"
                    f"<div style='text-align:right;font-size:0.68rem;"
                    f"color:{PALETTE['muted']}'>FIT</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(f"**Value proposition:** {esc(option['value_proposition'])}")
            st.markdown(f"**Differentiation:** {esc(option['differentiation'])}")

            detail = option.get("detail", {})
            with st.expander("Trade-offs and requirements"):
                for label, key in [
                    ("Benefits", "benefits"),
                    ("Risks", "risks"),
                    ("Required product changes", "required_product_changes"),
                    ("Supporting evidence", "supporting_evidence"),
                ]:
                    values = detail.get(key) or []
                    if values:
                        st.markdown(f"**{label}**")
                        for value in values:
                            st.markdown(f"- {esc(value)}")
                st.markdown(f"**Pricing implications:** {esc(option['pricing_implications'])}")
                st.markdown(f"**GTM implications:** {esc(option['gtm_implications'])}")
                st.markdown(
                    f"**Competitive reaction risk:** "
                    f"{esc(option['competitive_reaction_risk'])}"
                )


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def _pricing(pricing: dict[str, Any] | None) -> None:
    if not pricing:
        empty_state("The pricing strategist did not complete for this version.")
        return

    cols = st.columns(3)
    with cols[0]:
        kpi("Recommended model", PricingModel(pricing["recommended_model"]).label)
    with cols[1]:
        kpi("Value metric", pricing["value_metric"][:28] or "—")
    with cols[2]:
        economics = pricing.get("economics", {})
        kpi("Est. ARPU", f"${float(economics.get('arpu_monthly_usd', 0)):,.0f}/mo")

    st.write(pricing["rationale"])
    st.caption(f"Current state: {pricing['current_assessment']}")

    st.markdown("#### Recommended tiers")
    tiers = pricing.get("tiers", [])
    if tiers:
        tier_cols = st.columns(min(len(tiers), 4))
        for column, tier in zip(tier_cols, tiers):
            with column, st.container(border=True):
                st.markdown(f"**{esc(tier['name'])}**")
                price = float(tier["price_monthly_usd"])
                suffix = (
                    f"<span style='font-size:0.8rem;color:{PALETTE['muted']}'>/mo</span>"
                    if price > 0
                    else ""
                )
                st.markdown(
                    f"<div style='font-size:1.7rem;font-weight:800;color:#f8fafc'>"
                    f"{esc(format_price(price))}{suffix}</div>",
                    unsafe_allow_html=True,
                )
                st.caption(tier["target_segment"])
                for capability in tier.get("included_capabilities", [])[:8]:
                    st.markdown(f"- {esc(capability)}")
                if tier.get("limits"):
                    st.caption(f"Limits: {tier['limits']}")
    else:
        st.caption("No tiers recommended.")

    st.markdown("#### Competitor pricing")
    points = pricing.get("competitor_pricing", [])
    if points:
        known = [p for p in points if p["price_monthly_usd"] >= 0]
        unknown = [p for p in points if p["price_monthly_usd"] < 0]

        if known:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Competitor": p["competitor"],
                            "Plan": p["plan_name"],
                            "Price/mo": format_price(p["price_monthly_usd"]),
                            "Model": p["pricing_model"],
                            "Evidence": p["grade"].replace("_", " "),
                            "Confidence": f"{p['confidence']:.0%}",
                        }
                        for p in known
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        if unknown:
            st.caption(
                "Price not published or not established for: "
                + ", ".join(f"{p['competitor']} ({p['plan_name']})" for p in unknown)
                + ". Recorded as unknown rather than guessed."
            )
        unverified = [p for p in known if p["grade"] != "verified_fact"]
        if unverified:
            st.warning(
                f"{len(unverified)} of {len(known)} competitor prices are not "
                "source-verified. Confirm before pricing against them.",
                icon=":material/warning:",
            )
    else:
        st.caption("No competitor pricing was established.")

    with st.expander("Pricing power, risks and assumptions"):
        st.markdown(f"**Pricing power:** {esc(pricing['pricing_power'])}")
        for label, key in [("Risks", "risks"), ("Assumptions", "assumptions")]:
            values = pricing.get(key) or []
            if values:
                st.markdown(f"**{label}**")
                for value in values:
                    st.markdown(f"- {esc(value)}")
        if pricing.get("economics", {}).get("basis"):
            st.caption(f"Economics basis: {pricing['economics']['basis']}")


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------


def _growth(growth: dict[str, Any] | None) -> None:
    if not growth:
        empty_state("The growth strategist did not complete for this version.")
        return

    st.markdown(f"#### Primary motion: {esc(growth['primary_motion'])}")
    st.write(growth["motion_rationale"])

    channels = growth.get("channels", [])
    if channels:
        st.markdown("#### Channel fit")
        chart = pd.DataFrame(
            [
                {
                    "Channel": GrowthChannel(c["channel"]).label
                    if c["channel"] in {m.value for m in GrowthChannel}
                    else c["channel"],
                    "Fit": c["fit_score"],
                }
                for c in channels
            ]
        ).set_index("Channel")
        st.bar_chart(chart, height=320, color=PALETTE["primary_2"])

        for channel in channels:
            label = (
                GrowthChannel(channel["channel"]).label
                if channel["channel"] in {m.value for m in GrowthChannel}
                else channel["channel"]
            )
            fit = float(channel["fit_score"])
            with st.expander(f"{label} — fit {fit:.0f}/100", expanded=fit >= 70):
                st.markdown(meter(fit), unsafe_allow_html=True)
                st.markdown(f"**Why this channel:** {esc(channel['why_appropriate'])}")
                st.markdown(f"**First experiment:** {esc(channel['first_experiment'])}")
                detail = st.columns(3)
                detail[0].caption(f"Expected CAC: {channel['expected_cac']}")
                detail[1].caption(f"Time to traction: {channel['time_to_traction']}")
                detail[2].caption(f"Effort: {channel['effort'].upper()}")
                st.caption(f"Scalability: {channel['scalability']}")
                for item in channel.get("supporting_evidence", []):
                    st.markdown(f"- {esc(item)}")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Sequencing**")
        for index, step in enumerate(growth.get("sequencing", []), start=1):
            st.markdown(f"{index}. {esc(step)}")
    with cols[1]:
        st.markdown("**Do not spend here**")
        avoid = growth.get("channels_to_avoid", [])
        if avoid:
            for item in avoid:
                st.markdown(f"- {esc(item)}")
        else:
            st.caption("No channels ruled out.")


# ---------------------------------------------------------------------------
# Go-to-market
# ---------------------------------------------------------------------------


def _gtm(gtm: dict[str, Any] | None) -> None:
    if not gtm:
        empty_state("The go-to-market strategist did not complete for this version.")
        return

    st.markdown(f"#### Beachhead: {esc(gtm['target_segment'])}")
    st.write(gtm["beachhead_rationale"])

    strategy_cols = st.columns(2)
    entries = [
        ("Launch strategy", "launch_strategy"),
        ("Channel strategy", "channel_strategy"),
        ("Sales strategy", "sales_strategy"),
        ("Content strategy", "content_strategy"),
        ("Partnership strategy", "partnership_strategy"),
        ("Pricing summary", "pricing_summary"),
    ]
    for index, (label, key) in enumerate(entries):
        with strategy_cols[index % 2]:
            if gtm.get(key):
                st.markdown(f"**{label}**")
                st.caption(gtm[key])

    st.markdown("#### Launch phases")
    phases = gtm.get("phases", [])
    if phases:
        for phase in phases:
            horizon = phase["horizon"]
            label = (
                LaunchHorizon(horizon).label
                if horizon in {m.value for m in LaunchHorizon}
                else horizon
            )
            with st.expander(f"{label} — {phase.get('owner_role', 'unassigned')}"):
                for title, key in [
                    ("Objectives", "objectives"),
                    ("Activities", "activities"),
                    ("Milestones", "milestones"),
                ]:
                    values = phase.get(key) or []
                    if values:
                        st.markdown(f"**{title}**")
                        for value in values:
                            st.markdown(f"- {esc(value)}")
    else:
        st.caption("No phases produced.")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Metrics that matter**")
        for metric in gtm.get("metrics", []):
            st.markdown(f"- {esc(metric)}")
        st.markdown("**Budget assumptions**")
        for assumption in gtm.get("budget_assumptions", []):
            st.markdown(f"- {esc(assumption)}")
    with cols[1]:
        st.markdown("**Risks**")
        for risk in gtm.get("risks", []):
            st.markdown(f"- {esc(risk)}")

    experiments = gtm.get("experiments", [])
    if experiments:
        st.markdown("#### Experiments")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Hypothesis": e.get("hypothesis", ""),
                        "Test": e.get("test", ""),
                        "Success metric": e.get("success_metric", ""),
                        "Effort": (e.get("effort") or "").upper(),
                    }
                    for e in experiments
                ]
            ),
            width="stretch",
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Simulation lab (spec 15 / 20)
# ---------------------------------------------------------------------------


def _simulator(service: StudioService, product: dict, analysis_id: str) -> None:
    st.markdown("#### Pricing & growth simulation")
    st.caption(
        "Every figure below is computed from the inputs on this page. "
        "These are projections under stated assumptions, not predictions."
    )

    pricing = service.dashboard(analysis_id).get("pricing")
    seeded = bool(pricing and pricing.get("economics"))
    defaults = service.economics_for(analysis_id)
    elasticity_default = float(
        (pricing or {}).get("economics", {}).get("price_elasticity", -1.0) or -1.0
    )

    if seeded:
        st.caption(
            "Inputs seeded from the pricing agent's estimates. "
            f"Basis: {(pricing.get('economics') or {}).get('basis', 'not stated')}"
        )
    else:
        st.info(
            "No pricing analysis exists for this version, so these are neutral "
            "placeholder assumptions. Replace them with your real numbers.",
            icon=":material/info:",
        )

    with st.form("simulator"):
        row1 = st.columns(4)
        arpu = row1[0].number_input(
            "ARPU $/month", min_value=0.0, value=float(defaults.arpu_monthly), step=10.0
        )
        margin = row1[1].number_input(
            "Gross margin %", min_value=0.0, max_value=100.0,
            value=float(defaults.gross_margin_pct), step=5.0,
        )
        cac = row1[2].number_input(
            "CAC $", min_value=0.0, value=float(defaults.cac), step=50.0
        )
        customers = row1[3].number_input("Customers today", min_value=0, value=100, step=10)

        row2 = st.columns(4)
        churn = row2[0].number_input(
            "Monthly churn %", min_value=0.0, max_value=100.0,
            value=float(defaults.monthly_churn_pct), step=0.5,
        )
        expansion = row2[1].number_input(
            "Monthly expansion %", min_value=0.0, max_value=100.0,
            value=float(defaults.monthly_expansion_pct), step=0.5,
        )
        elasticity = row2[2].number_input(
            "Price elasticity", min_value=-5.0, max_value=-0.1,
            value=max(-5.0, min(-0.1, elasticity_default)), step=0.1,
            help=(
                "% demand change per 1% price change. More negative means "
                "customers are more price-sensitive."
            ),
        )
        new_customers = row2[3].number_input(
            "New customers/month", min_value=0.0, value=10.0, step=5.0
        )

        fixed_costs = st.number_input(
            "Monthly fixed costs $", min_value=0.0, value=0.0, step=1000.0
        )
        run = st.form_submit_button("Run simulation", type="primary", width="stretch")

    if not run and "sim_results" not in st.session_state:
        return

    if run:
        economics = finance.Economics(
            arpu_monthly=arpu,
            gross_margin_pct=margin,
            cac=cac,
            monthly_churn_pct=churn,
            monthly_expansion_pct=expansion,
            customers=int(customers),
        )
        st.session_state["sim_inputs"] = {
            "arpu_monthly": arpu, "gross_margin_pct": margin, "cac": cac,
            "monthly_churn_pct": churn, "monthly_expansion_pct": expansion,
            "customers": int(customers), "elasticity": elasticity,
            "fixed_costs": fixed_costs, "new_customers_per_month": new_customers,
        }
        st.session_state["sim_results"] = service.simulate(
            economics,
            elasticity=elasticity,
            fixed_costs=fixed_costs,
            new_customers_per_month=new_customers,
            months=24,
        )

    results = st.session_state.get("sim_results")
    if not results:
        return

    unit = results["unit_economics"]

    cols = st.columns(5)
    with cols[0]:
        kpi("LTV", f"${unit.ltv:,.0f}" if unit.ltv else "—")
    with cols[1]:
        ratio = unit.ltv_cac_ratio
        kpi(
            "LTV : CAC",
            f"{ratio:.1f}x" if ratio else "—",
            "healthy at 3x+",
            score_colour(min(100, (ratio or 0) * 25)),
        )
    with cols[2]:
        payback = unit.cac_payback_months
        kpi(
            "CAC payback",
            f"{payback:.1f} mo" if payback else "never",
            "healthy under 12mo",
            score_colour(100 - min(100, (payback or 99) * 6)),
        )
    with cols[3]:
        kpi("MRR", f"${unit.mrr:,.0f}")
    with cols[4]:
        kpi("ARR", f"${unit.arr:,.0f}")

    for warning in unit.warnings:
        st.warning(warning, icon=":material/warning:")

    st.markdown("#### Price sensitivity")
    curve = results["curve"]
    optimum = results["optimum"]

    chart = pd.DataFrame(
        [
            {
                "Price change %": f"{s.price_change_pct:+.0f}%",
                "MRR": s.new_mrr,
                "Customers": s.new_customers,
            }
            for s in curve
        ]
    ).set_index("Price change %")
    st.bar_chart(chart[["MRR"]], height=300, color=PALETTE["primary"])

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Price change": f"{s.price_change_pct:+.0f}%",
                    "New ARPU": f"${s.new_arpu:,.0f}",
                    "Customers": f"{s.new_customers:,.0f}",
                    "MRR": f"${s.new_mrr:,.0f}",
                    "MRR change": f"{s.mrr_change_pct:+.1f}%",
                    "LTV:CAC": (
                        f"{s.economics.ltv_cac_ratio:.1f}x"
                        if s.economics.ltv_cac_ratio
                        else "—"
                    ),
                }
                for s in curve
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    if optimum:
        st.info(
            f"At elasticity {st.session_state['sim_inputs']['elasticity']:.1f}, revenue "
            f"is maximised at a **{optimum.price_change_pct:+.0f}%** price change "
            f"(MRR ${optimum.new_mrr:,.0f}, {optimum.new_customers:,.0f} customers). "
            "Customer count moves with price — it is not held constant.",
            icon=":material/trending_up:",
        )

    break_even = results["break_even"]
    if break_even.customers_needed:
        st.markdown("#### Break-even")
        cols = st.columns(3)
        with cols[0]:
            kpi("Customers needed", f"{break_even.customers_needed:,.0f}")
        with cols[1]:
            kpi("MRR needed", f"${break_even.mrr_needed:,.0f}")
        with cols[2]:
            kpi(
                "Months to break even",
                f"{break_even.months_to_break_even:.0f}"
                if break_even.reachable
                else "not reachable",
                "at the current acquisition rate",
            )

    st.markdown("#### 24-month projection")
    projection = results["projection"]
    st.line_chart(
        pd.DataFrame(
            [
                {"Month": row.month, "MRR": row.mrr, "Cumulative profit": row.cumulative_profit}
                for row in projection
            ]
        ).set_index("Month"),
        height=300,
    )

    with st.form("save_scenario"):
        cols = st.columns([3, 1])
        label = cols[0].text_input("Scenario name", placeholder="e.g. 20% price rise")
        cols[1].markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
        if cols[1].form_submit_button("Save scenario", width="stretch"):
            service.save_scenario(
                product["id"],
                analysis_id,
                label,
                st.session_state.get("sim_inputs", {}),
                {
                    "ltv": unit.ltv,
                    "ltv_cac": unit.ltv_cac_ratio,
                    "payback_months": unit.cac_payback_months,
                    "mrr": unit.mrr,
                    "arr": unit.arr,
                    "optimum_price_change": optimum.price_change_pct if optimum else None,
                },
            )
            st.success("Scenario saved.")

    saved = service.list_scenarios(product["id"])
    if saved:
        st.markdown("#### Saved scenarios")
        for scenario in saved:
            with st.container(border=True):
                head, action = st.columns([5, 1])
                with head:
                    result = scenario["results"]
                    st.markdown(f"**{esc(scenario['label'])}**")
                    st.caption(
                        f"LTV ${result.get('ltv') or 0:,.0f} · "
                        f"LTV:CAC {result.get('ltv_cac') or 0:.1f}x · "
                        f"MRR ${result.get('mrr') or 0:,.0f} · "
                        f"{str(scenario['created_at'])[:16].replace('T', ' ')}"
                    )
                if action.button("Delete", key=f"delscn_{scenario['id']}"):
                    service.delete_scenario(scenario["id"])
                    st.rerun()
