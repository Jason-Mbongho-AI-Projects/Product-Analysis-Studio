"""Strategy agents (spec 14-17).

Where ``analysts.py`` establishes *what is true*, these agents decide *what to
do about it*. They run after the intelligence agents and read their persisted
output, so positioning is grounded in the actual competitive set rather than
invented alongside it.
"""

from __future__ import annotations

from ..domain.contracts import GrowthStrategy, GTMPlan, PositioningStudio, PricingStudio
from ..storage import repositories as repo
from .base import Agent, AnalysisContext


def _competitor_digest(ctx: AnalysisContext, limit: int = 12) -> str:
    competitors = repo.list_competitors(ctx.conn, ctx.analysis_id)
    if not competitors:
        return "No competitors were identified."
    return "\n".join(
        f"- {c['name']} ({c['competitor_type']}, threat {c['threat_level']}): "
        f"{c['positioning']} | targets {c['target_customer']} | pricing: {c['pricing_summary']}"
        for c in competitors[:limit]
    )


def _customer_digest(ctx: AnalysisContext) -> str:
    customers = repo.get_customers(ctx.conn, ctx.analysis_id)
    if not customers:
        return "No customer intelligence available."
    personas = "; ".join(
        f"{p['name']}{' (buyer)' if p['is_buyer'] else ''}" for p in customers["personas"][:6]
    )
    return f"ICP: {customers['icp']}\nPersonas: {personas or 'none'}"


def _profile_digest(ctx: AnalysisContext) -> str:
    profile = repo.get_product_profile(ctx.conn, ctx.analysis_id)
    if not profile:
        return "No product profile available."
    lists = profile.get("lists", {})
    return (
        f"Summary: {profile['summary']}\n"
        f"Primary problem: {profile['primary_problem']}\n"
        f"Capabilities: {', '.join(lists.get('core_capabilities', [])[:12])}\n"
        f"Current pricing model: {profile['pricing_model']}\n"
        f"Distribution: {profile['distribution_model']}\n"
        f"Defensibility: {profile['defensibility']}"
    )


def _market_digest(ctx: AnalysisContext) -> str:
    market = repo.get_market(ctx.conn, ctx.analysis_id)
    if not market:
        return "No market analysis available."
    sizing = "; ".join(
        f"{m['label']} ${m['value_usd']:,.0f} ({m['confidence']:.0%} confidence)"
        for m in market["sizing"]
    )
    return (
        f"Market: {market['market_definition']}\n"
        f"Maturity: {market['maturity']} | Concentration: {market['competitive_concentration']}\n"
        f"Sizing: {sizing or 'none'}"
    )


class PositioningStrategistAgent(Agent[PositioningStudio]):
    """Generates genuinely different positioning strategies and picks one."""

    name = "positioning_strategist"
    title = "Positioning strategist"
    contract = PositioningStudio
    deep = True
    max_tokens = 9000
    requires = (
        "product_analyst",
        "customer_intelligence",
        "competitive_intelligence",
        "market_analyst",
    )

    def build_prompt(self, ctx: AnalysisContext) -> str:
        return (
            f"{ctx.product_context()}\n"
            f"{_profile_digest(ctx)}\n\n"
            f"{_customer_digest(ctx)}\n\n"
            f"COMPETITIVE SET:\n{_competitor_digest(ctx)}\n\n"
            f"{_market_digest(ctx)}\n\n"
            f"{ctx.research.as_prompt_context(max_chars=10000)}\n\n"
            "Develop positioning options. Requirements:\n"
            "- Produce at least three strategies that are genuinely DIFFERENT bets "
            "(e.g. premium enterprise vs developer-first vs compliance-first), not "
            "three rewordings of the same idea.\n"
            "- Each must state what the product would have to CHANGE to earn that "
            "position. A position the product cannot currently support is a "
            "roadmap commitment, and should say so.\n"
            "- fit_score must reflect the evidence, not the appeal of the strategy. "
            "Score a compelling strategy low if this product cannot credibly hold it.\n"
            "- Consider how each competitor would react.\n\n"
            "Then write the messaging for your RECOMMENDED strategy only. The "
            "homepage headline must be under 12 words and say something specific - "
            "no 'Supercharge your workflow' filler."
        )

    def persist(self, ctx: AnalysisContext, result: PositioningStudio) -> None:
        repo.save_positioning(
            ctx.conn,
            ctx.analysis_id,
            {
                "recommended_strategy": result.recommended_strategy,
                "recommendation_reason": result.recommendation_reason,
                "messaging": result.messaging.model_dump(mode="json"),
                "options": [option.model_dump(mode="json") for option in result.options],
            },
        )


class PricingStrategistAgent(Agent[PricingStudio]):
    """Recommends a pricing model and supplies inputs for the simulator."""

    name = "pricing_strategist"
    title = "Pricing strategist"
    contract = PricingStudio
    deep = True
    max_tokens = 9000
    requires = (
        "product_analyst",
        "customer_intelligence",
        "competitive_intelligence",
    )

    def build_prompt(self, ctx: AnalysisContext) -> str:
        return (
            f"{ctx.product_context()}\n"
            f"{_profile_digest(ctx)}\n\n"
            f"{_customer_digest(ctx)}\n\n"
            f"COMPETITIVE SET:\n{_competitor_digest(ctx)}\n\n"
            f"{ctx.research.as_prompt_context(max_chars=12000)}\n\n"
            "Develop a pricing strategy.\n\n"
            "On competitor pricing: report only what you can actually support. If a "
            "price did not appear in the retrieved material, set price_monthly_usd "
            "to -1 and grade the entry honestly. A wrong price is worse than an "
            "admitted unknown, because someone will price against it.\n\n"
            "On the value metric: identify what should be charged for - the unit "
            "that grows as the customer gets more value. Explain why it beats the "
            "alternatives.\n\n"
            "On economics: these estimates feed a simulator that computes LTV, "
            "CAC payback and revenue scenarios. Give realistic figures for a product "
            "at this stage in this market, and state plainly in `basis` where each "
            "came from. price_elasticity must be negative - roughly -0.5 to -1.5 for "
            "B2B with switching costs, -1.5 to -3.0 for consumer or low-friction "
            "products. Do not compute LTV or payback yourself; supply the inputs."
        )

    def persist(self, ctx: AnalysisContext, result: PricingStudio) -> None:
        repo.save_pricing(
            ctx.conn,
            ctx.analysis_id,
            {
                "current_assessment": result.current_assessment,
                "recommended_model": result.recommended_model.value,
                "value_metric": result.value_metric,
                "rationale": result.rationale,
                "pricing_power": result.pricing_power,
                "risks": result.risks,
                "assumptions": result.assumptions,
                "economics": result.economics.model_dump(mode="json"),
                "tiers": [tier.model_dump(mode="json") for tier in result.tiers],
                "competitor_pricing": [
                    point.model_dump(mode="json") for point in result.competitor_pricing
                ],
            },
        )


class GrowthStrategistAgent(Agent[GrowthStrategy]):
    """Scores acquisition channels against this specific product and buyer."""

    name = "growth_strategist"
    title = "Growth strategist"
    contract = GrowthStrategy
    deep = True
    max_tokens = 9000
    requires = (
        "pricing_strategist",
        "customer_intelligence",
        "competitive_intelligence",
        "market_analyst",
    )

    def build_prompt(self, ctx: AnalysisContext) -> str:
        pricing = repo.get_pricing(ctx.conn, ctx.analysis_id)
        price_note = ""
        if pricing:
            price_note = (
                f"Recommended pricing: {pricing['recommended_model']} "
                f"(ARPU estimate ${pricing['economics'].get('arpu_monthly_usd', 0):,.0f}/mo)\n"
            )

        return (
            f"{ctx.product_context()}\n"
            f"{_profile_digest(ctx)}\n\n"
            f"{_customer_digest(ctx)}\n"
            f"{price_note}\n"
            f"COMPETITIVE SET:\n{_competitor_digest(ctx)}\n\n"
            f"{_market_digest(ctx)}\n\n"
            "Build an acquisition strategy.\n\n"
            "Score channels against THIS product specifically: its price point, "
            "buying behaviour, sales cycle, and who holds the budget. A $20/month "
            "self-serve tool and a $80k enterprise contract need opposite motions - "
            "generic channel advice is useless.\n\n"
            "Every channel needs `why_appropriate` tied to a concrete property of "
            "this product or buyer. 'SEO drives organic traffic' is not a reason. "
            "'Buyers search for HIPAA compliance checklists before they know "
            "products exist' is.\n\n"
            "Score channels you consider poor fits too, and list what to avoid. "
            "Telling someone which channel NOT to spend on is as valuable as the "
            "recommendation. Sequencing must be realistic for a team with limited "
            "resources - not eight channels at once."
        )

    def persist(self, ctx: AnalysisContext, result: GrowthStrategy) -> None:
        repo.save_growth(
            ctx.conn,
            ctx.analysis_id,
            {
                "primary_motion": result.primary_motion,
                "motion_rationale": result.motion_rationale,
                "sequencing": result.sequencing,
                "channels_to_avoid": result.channels_to_avoid,
                "channels": [c.model_dump(mode="json") for c in result.channels],
            },
        )


class GTMStrategistAgent(Agent[GTMPlan]):
    """Assembles positioning, pricing and growth into a phased launch plan."""

    name = "gtm_strategist"
    title = "Go-to-market strategist"
    contract = GTMPlan
    deep = True
    max_tokens = 9000
    requires = (
        "positioning_strategist",
        "pricing_strategist",
        "growth_strategist",
        "competitive_intelligence",
    )

    def build_prompt(self, ctx: AnalysisContext) -> str:
        conn, analysis_id = ctx.conn, ctx.analysis_id

        positioning = repo.get_positioning(conn, analysis_id)
        positioning_note = "No positioning analysis available."
        if positioning:
            messaging = positioning.get("messaging", {})
            positioning_note = (
                f"Recommended positioning: {positioning['recommended_strategy']}\n"
                f"Statement: {messaging.get('positioning_statement', '')}\n"
                f"UVP: {messaging.get('unique_value_proposition', '')}"
            )

        pricing = repo.get_pricing(conn, analysis_id)
        pricing_note = "No pricing analysis available."
        if pricing:
            from ..analysis.reports import format_price

            tiers = "; ".join(
                f"{t['name']} {format_price(t['price_monthly_usd'], '/mo')}"
                for t in pricing["tiers"]
            )
            pricing_note = f"Model: {pricing['recommended_model']} | Tiers: {tiers}"

        growth = repo.get_growth(conn, analysis_id)
        growth_note = "No growth analysis available."
        if growth:
            channels = ", ".join(
                f"{c['channel']} ({c['fit_score']:.0f})" for c in growth["channels"][:6]
            )
            growth_note = f"Motion: {growth['primary_motion']} | Top channels: {channels}"

        return (
            f"{ctx.product_context()}\n"
            f"{_customer_digest(ctx)}\n\n"
            f"POSITIONING:\n{positioning_note}\n\n"
            f"PRICING:\n{pricing_note}\n\n"
            f"GROWTH:\n{growth_note}\n\n"
            f"COMPETITIVE SET:\n{_competitor_digest(ctx, limit=8)}\n\n"
            "Build a go-to-market plan that is CONSISTENT with the positioning, "
            "pricing and growth work above - do not contradict it or invent a "
            "different strategy.\n\n"
            "Pick one beachhead segment and justify it. 'Everyone who needs "
            "compliance' is not a beachhead.\n\n"
            "Produce one phase per horizon (30 days, 60, 90, 6 months, 12 months). "
            "Activities must be things a small team could actually execute, ordered "
            "so each phase depends on the last. Metrics should be the few numbers "
            "that genuinely indicate progress, not a vanity dashboard."
        )

    def persist(self, ctx: AnalysisContext, result: GTMPlan) -> None:
        repo.save_gtm(
            ctx.conn,
            ctx.analysis_id,
            {
                "target_segment": result.target_segment,
                "beachhead_rationale": result.beachhead_rationale,
                "positioning_summary": result.positioning_summary,
                "messaging_summary": result.messaging_summary,
                "pricing_summary": result.pricing_summary,
                "channel_strategy": result.channel_strategy,
                "sales_strategy": result.sales_strategy,
                "launch_strategy": result.launch_strategy,
                "content_strategy": result.content_strategy,
                "partnership_strategy": result.partnership_strategy,
                "metrics": result.metrics,
                "budget_assumptions": result.budget_assumptions,
                "risks": result.risks,
                "experiments": [e.model_dump(mode="json") for e in result.experiments],
                "phases": [p.model_dump(mode="json") for p in result.phases],
            },
        )
