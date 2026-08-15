"""The specialist analysis agents (spec 23).

Each agent owns one narrow question, one contract, and one persistence path.
Adding a new discipline means adding a class here and a line in the pipeline -
not editing a monolithic prompt.
"""

from __future__ import annotations

from ..domain.contracts import (
    CompetitorDiscovery,
    CustomerIntelligence,
    ExecutiveSynthesis,
    GapAnalysis,
    IntakeClassification,
    MarketAnalysis,
    ProductProfile,
    ScoringResult,
)
from ..domain.enums import SCORE_WEIGHTS, ScoreDimension
from ..storage import repositories as repo
from .base import Agent, AnalysisContext, store_claims


class IntakeAgent(Agent[IntakeClassification]):
    """Turns raw input - including a one-line idea - into a structured concept."""

    name = "intake"
    title = "Intake & classification"
    contract = IntakeClassification
    max_tokens = 2000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        return (
            f"{ctx.product_context()}\n"
            f"{ctx.research.as_prompt_context(max_chars=12000)}\n\n"
            "Classify this product concept. If the user gave only a rough idea, "
            "infer a sensible structure and record every inference in `assumptions`. "
            "Ask the clarifying questions whose answers would most change the analysis."
        )

    def persist(self, ctx: AnalysisContext, result: IntakeClassification) -> None:
        repo.update_product_classification(
            ctx.conn,
            ctx.product["id"],
            name=result.product_name or ctx.product.get("name"),
            one_liner=result.one_liner,
            category=result.category,
            subcategory=result.subcategory,
            industry=result.industry,
            business_model=result.business_model.value,
            market_segment=result.market_segment.value,
            maturity=result.maturity.value,
            revenue_model=result.revenue_model,
        )
        # Refresh so downstream agents see the enriched classification.
        updated = repo.get_product(ctx.conn, ctx.product["id"], ctx.workspace_id)
        if updated:
            ctx.product.update(updated)


class ProductAnalystAgent(Agent[ProductProfile]):
    """Builds the Product Intelligence Profile (spec 2)."""

    name = "product_analyst"
    title = "Product analyst"
    contract = ProductProfile
    deep = True
    max_tokens = 9000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        return (
            f"{ctx.product_context()}\n"
            f"{ctx.research.as_prompt_context()}\n\n"
            "Produce a Product Intelligence Profile. Be concrete about what the "
            "product actually does. Distinguish capabilities observed in source "
            "material from capabilities you are assuming. SWOT entries must each be "
            "a specific claim with an honest grade - not generic business platitudes."
        )

    def persist(self, ctx: AnalysisContext, result: ProductProfile) -> None:
        repo.save_product_profile(
            ctx.conn,
            ctx.analysis_id,
            {
                "summary": result.summary,
                "primary_problem": result.primary_problem,
                "pricing_model": result.pricing_model,
                "distribution_model": result.distribution_model,
                "switching_costs": result.switching_costs,
                "defensibility": result.defensibility,
                "features": [f.model_dump(mode="json") for f in result.features],
                "lists": {
                    "use_cases": result.use_cases,
                    "core_capabilities": result.core_capabilities,
                    "secondary_problems": result.secondary_problems,
                    "target_customers": result.target_customers,
                    "decision_makers": result.decision_makers,
                    "technology": result.technology,
                    "integrations": result.integrations,
                    "adoption_barriers": result.adoption_barriers,
                },
            },
        )
        for bucket, claims in (
            ("strength", result.strengths),
            ("weakness", result.weaknesses),
            ("opportunity", result.opportunities),
            ("threat", result.threats),
            ("differentiator", result.differentiators),
        ):
            store_claims(ctx, self.name, claims, subject_type=bucket)


class CompetitiveIntelligenceAgent(Agent[CompetitorDiscovery]):
    """Discovers and classifies competitors (spec 6)."""

    name = "competitive_intelligence"
    title = "Competitive intelligence"
    contract = CompetitorDiscovery
    deep = True
    max_tokens = 8000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        profile = ctx.results.get("product_analyst")
        capability_note = ""
        if profile is not None:
            capabilities = ", ".join(profile.core_capabilities[:12])  # type: ignore[attr-defined]
            capability_note = f"\nThe product's core capabilities: {capabilities}\n"

        return (
            f"{ctx.product_context()}{capability_note}\n"
            f"{ctx.research.as_prompt_context(max_chars=16000)}\n\n"
            "Identify the competitive set. Cover the full range: direct rivals, "
            "indirect alternatives, substitutes, legacy incumbents, the manual or "
            "spreadsheet workaround customers use today, open-source options, and "
            "large players who could plausibly enter.\n\n"
            "Name real, existing companies you are confident exist. If you are not "
            "confident a company exists, leave it out rather than inventing one. "
            "Set website to null rather than guessing a URL. Grade honestly: unless "
            "the retrieved material describes a competitor, your knowledge of them "
            "is at best a strong_inference and their current pricing is likely stale."
        )

    def persist(self, ctx: AnalysisContext, result: CompetitorDiscovery) -> None:
        for position, candidate in enumerate(result.competitors):
            repo.save_competitor(
                ctx.conn,
                workspace_id=ctx.workspace_id,
                analysis_id=ctx.analysis_id,
                data=candidate.model_dump(mode="json"),
                position=position,
            )


class MarketAnalystAgent(Agent[MarketAnalysis]):
    """Market conditions and transparent TAM/SAM/SOM (spec 12/13)."""

    name = "market_analyst"
    title = "Market analyst"
    contract = MarketAnalysis
    deep = True
    max_tokens = 9000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        return (
            f"{ctx.product_context()}\n"
            f"{ctx.research.as_prompt_context(max_chars=16000)}\n\n"
            "Analyse the market this product competes in.\n\n"
            "For TAM/SAM/SOM you must SHOW YOUR WORK. Each figure needs an explicit "
            "formula with named variables, and every variable must state where its "
            "value came from - retrieved source, published industry figure you are "
            "confident of, or your own assumption. A number with no derivation is "
            "worse than no number. Prefer a bottom-up build (population x adoption x "
            "price) over quoting a headline market size. Confidence should be low "
            "when the inputs are assumptions, and say so."
        )

    def persist(self, ctx: AnalysisContext, result: MarketAnalysis) -> None:
        repo.save_market(
            ctx.conn,
            ctx.analysis_id,
            {
                "market_definition": result.market_definition,
                "maturity": result.maturity,
                "competitive_concentration": result.competitive_concentration,
                "entry_barriers": result.entry_barriers,
                "adjacent_markets": result.adjacent_markets,
                "sizing": [model.model_dump(mode="json") for model in result.sizing],
            },
        )
        store_claims(ctx, self.name, [result.growth_outlook], subject_type="market_growth")
        store_claims(ctx, self.name, result.drivers, subject_type="market_driver")
        store_claims(ctx, self.name, result.inhibitors, subject_type="market_inhibitor")
        store_claims(ctx, self.name, result.trends, subject_type="market_trend")
        store_claims(
            ctx, self.name, [result.regulatory_environment], subject_type="market_regulatory"
        )


class CustomerIntelligenceAgent(Agent[CustomerIntelligence]):
    """ICP and personas, explicitly labelled as inferred (spec 10)."""

    name = "customer_intelligence"
    title = "Customer intelligence"
    contract = CustomerIntelligence
    max_tokens = 7000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        return (
            f"{ctx.product_context()}\n"
            f"{ctx.research.as_prompt_context(max_chars=12000)}\n\n"
            "Define the ideal customer profile and the personas that matter for "
            "buying decisions. Separate the person who uses the product from the "
            "person who signs the contract.\n\n"
            "Critical: unless real customer research was supplied, these personas "
            "are hypotheses. Grade them 'ai_hypothesis' and keep confidence "
            "realistic. Do not present invented personas as established customer fact."
        )

    def persist(self, ctx: AnalysisContext, result: CustomerIntelligence) -> None:
        repo.save_customers(
            ctx.conn,
            ctx.analysis_id,
            {
                "icp": result.icp,
                "switching_concerns": result.switching_concerns,
                "personas": [p.model_dump(mode="json") for p in result.personas],
            },
        )
        store_claims(ctx, self.name, result.adoption_barriers, subject_type="adoption_barrier")


class ScoringAgent(Agent[ScoringResult]):
    """Scores each dimension. The composite is computed in Python (spec 3)."""

    name = "scoring"
    title = "Product scoring"
    contract = ScoringResult
    deep = True
    max_tokens = 9000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        dimensions = "\n".join(
            f"- {dimension.value} ({dimension.label})"
            + (
                "  [INVERTED: score how much of this pressure exists; "
                "100 = extremely high pressure]"
                if dimension.is_inverted
                else ""
            )
            for dimension in ScoreDimension
        )
        competitors = repo.list_competitors(ctx.conn, ctx.analysis_id)
        competitor_note = (
            "Competitors identified: "
            + ", ".join(f"{c['name']} ({c['competitor_type']})" for c in competitors[:15])
            if competitors
            else "No competitors identified yet."
        )
        profile = ctx.results.get("product_analyst")
        summary = getattr(profile, "summary", "") if profile else ""

        return (
            f"{ctx.product_context()}\n"
            f"Product summary: {summary}\n"
            f"{competitor_note}\n\n"
            f"{ctx.research.as_prompt_context(max_chars=10000)}\n\n"
            f"Score this product on EVERY dimension below, 0-100:\n{dimensions}\n\n"
            "Rules:\n"
            "- Return one entry per dimension listed. Omit none.\n"
            "- Every score needs an explanation that justifies THAT NUMBER "
            "specifically - why 62 and not 45 or 80.\n"
            "- List the assumptions the score depends on.\n"
            "- Confidence must reflect how much real evidence you had. With no "
            "retrieved source material, confidence above 0.6 is not defensible.\n"
            "- Do not cluster everything at 70-80. Use the full range and be willing "
            "to score harshly where the product is genuinely weak."
        )

    def persist(self, ctx: AnalysisContext, result: ScoringResult) -> None:
        repo.save_scores(
            ctx.conn,
            ctx.analysis_id,
            [score.model_dump(mode="json") for score in result.scores],
        )


class GapAnalysisAgent(Agent[GapAnalysis]):
    """Gap engine and build/don't-build recommendations (spec 9)."""

    name = "gap_analysis"
    title = "Product gap analysis"
    contract = GapAnalysis
    deep = True
    max_tokens = 9000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        competitors = repo.list_competitors(ctx.conn, ctx.analysis_id)
        competitor_block = "\n".join(
            f"- {c['name']} ({c['competitor_type']}, threat: {c['threat_level']}): "
            f"{c['positioning']} | features: {', '.join(c['features'][:10]) or 'unknown'}"
            for c in competitors[:15]
        ) or "No competitors identified."

        profile = ctx.results.get("product_analyst")
        capabilities = ", ".join(getattr(profile, "core_capabilities", [])[:20]) if profile else ""
        features = ", ".join(f.name for f in getattr(profile, "features", [])[:25]) if profile else ""

        return (
            f"{ctx.product_context()}\n"
            f"This product's capabilities: {capabilities}\n"
            f"This product's features: {features}\n\n"
            f"COMPETITORS:\n{competitor_block}\n\n"
            f"{ctx.memory_context()}\n\n"
            f"{ctx.research.as_prompt_context(max_chars=10000)}\n\n"
            "Perform a gap analysis across features, pricing, integrations, security, "
            "compliance, onboarding, retention, distribution, mobile, accessibility "
            "and monetisation.\n\n"
            "Then produce prioritised recommendations. Requirements:\n"
            "- Use the full verdict range. At least one recommendation should be "
            "DO_NOT_BUILD or INVESTIGATE_FIRST if the evidence supports it - "
            "telling the user what NOT to build is as valuable as what to build.\n"
            "- 'reason' must explain the verdict, including why something is not "
            "worth building when that is your call.\n"
            "- Effort must be a real engineering judgement, not a default.\n"
            "- Priority is a strict ordering starting at 1.\n"
            "- Also list capabilities competitors have that this product lacks, and "
            "capabilities this product has that no listed competitor advertises."
        )

    def persist(self, ctx: AnalysisContext, result: GapAnalysis) -> None:
        repo.save_recommendations(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            analysis_id=ctx.analysis_id,
            product_id=ctx.product["id"],
            recommendations=[r.model_dump(mode="json") for r in result.recommendations],
        )
        repo.record_memory(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            product_id=ctx.product["id"],
            kind="gap_snapshot",
            summary=f"{len(result.recommendations)} recommendations generated",
            detail="; ".join(result.capabilities_competitors_have[:10]),
            payload={
                "missing": result.capabilities_competitors_have,
                "unique": result.capabilities_unique_to_product,
            },
        )


class ChiefStrategyAgent(Agent[ExecutiveSynthesis]):
    """Synthesises every other agent into an executive verdict (spec 23)."""

    name = "chief_strategy"
    title = "Chief strategy synthesis"
    contract = ExecutiveSynthesis
    deep = True
    max_tokens = 6000

    def build_prompt(self, ctx: AnalysisContext) -> str:
        conn, analysis_id = ctx.conn, ctx.analysis_id

        scores = repo.get_scores(conn, analysis_id)
        score_block = "\n".join(
            f"- {ScoreDimension(s['dimension']).label}: {s['score']:.0f}/100 "
            f"(confidence {s['confidence']:.0%}) - {s['explanation'][:180]}"
            for s in scores
        ) or "Scoring did not complete."

        competitors = repo.list_competitors(conn, analysis_id)
        competitor_block = "\n".join(
            f"- {c['name']} ({c['competitor_type']}, threat {c['threat_level']})"
            for c in competitors[:12]
        ) or "No competitors identified."

        recommendations = repo.list_recommendations(conn, analysis_id)
        rec_block = "\n".join(
            f"- [{r['verdict'].upper()}] {r['title']}: {r['reason'][:150]}"
            for r in recommendations[:15]
        ) or "No recommendations generated."

        market = repo.get_market(conn, analysis_id)
        market_block = ""
        if market:
            sizing = "; ".join(
                f"{m['label']} ${m['value_usd']:,.0f} (confidence {m['confidence']:.0%})"
                for m in market["sizing"]
            )
            market_block = f"Market: {market['market_definition']}\nSizing: {sizing}\n"

        quality = repo.evidence_quality_summary(conn, analysis_id)

        return (
            f"{ctx.product_context()}\n"
            f"{market_block}\n"
            f"SCORES:\n{score_block}\n\n"
            f"COMPETITIVE SET:\n{competitor_block}\n\n"
            f"RECOMMENDATIONS:\n{rec_block}\n\n"
            f"EVIDENCE QUALITY: {quality['total']} claims recorded, "
            f"{quality['evidence_backed_ratio']:.0%} evidence-backed, "
            f"{quality['distinct_sources']} distinct sources.\n\n"
            f"{ctx.memory_context()}\n\n"
            f"Audience: {ctx.mode.replace('_', ' ')} mode.\n\n"
            "Synthesise the above into an executive verdict. Give a direct answer on "
            "whether this is worth pursuing and why. Rank the real opportunities and "
            "the real risks. Name the immediate 30-day actions.\n\n"
            "In `key_uncertainties`, be blunt about what this analysis could NOT "
            "establish and what evidence would resolve it. If the evidence base was "
            "thin, say so plainly and keep your confidence low - an honest 0.4 is "
            "more useful than a false 0.9."
        )


#: Execution order. Later agents read earlier agents' persisted output, so this
#: sequence is a real dependency chain, not a cosmetic ordering.
PIPELINE: list[type[Agent]] = [
    IntakeAgent,
    ProductAnalystAgent,
    CompetitiveIntelligenceAgent,
    MarketAnalystAgent,
    CustomerIntelligenceAgent,
    ScoringAgent,
    GapAnalysisAgent,
    ChiefStrategyAgent,
]


def composite_score(scores: list[dict]) -> dict[str, float]:
    """Compute the headline score from stored dimensions.

    Deliberately arithmetic rather than model-generated: the headline number
    must be reproducible and explainable from its parts (spec 3).
    """
    if not scores:
        return {"score": 0.0, "confidence": 0.0, "coverage": 0.0}

    total_weight = 0.0
    weighted = 0.0
    confidence_sum = 0.0

    for entry in scores:
        try:
            dimension = ScoreDimension(entry["dimension"])
        except ValueError:
            continue
        weight = SCORE_WEIGHTS.get(dimension, 0.0)
        raw = float(entry["score"])
        # Inverted dimensions measure pressure against the product, so they are
        # flipped before contributing to a "higher is better" composite.
        value = (100.0 - raw) if dimension.is_inverted else raw
        weighted += value * weight
        total_weight += weight
        confidence_sum += float(entry.get("confidence", 0.5)) * weight

    if total_weight == 0:
        return {"score": 0.0, "confidence": 0.0, "coverage": 0.0}

    return {
        "score": round(weighted / total_weight, 1),
        "confidence": round(confidence_sum / total_weight, 3),
        "coverage": round(total_weight / sum(SCORE_WEIGHTS.values()), 3),
    }
