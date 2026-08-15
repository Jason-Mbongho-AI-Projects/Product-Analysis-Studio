"""Agent output contracts (spec 24).

Every agent returns a validated Pydantic model, never free-form prose. These
schemas are converted to strict JSON Schema and handed to the model, so a
malformed agent response is a validation error we can retry - not silent
garbage that flows into the UI.

Nesting is deliberately kept shallow (<= 3 levels) because strict structured
output has depth and property-count limits.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .enums import (
    AlertSeverity,
    BusinessModel,
    ChangeType,
    CompetitorType,
    EffortSize,
    EvidenceGrade,
    FeedbackTheme,
    GrowthChannel,
    LaunchHorizon,
    MarketSegment,
    PricingModel,
    ProductMaturity,
    RecommendationVerdict,
    ScoreDimension,
    Sentiment,
    SignalType,
    SourceType,
    ThreatLevel,
    TimeHorizon,
)


def _normalise_confidence(value: Any) -> Any:
    """Coerce a confidence value into the 0.0-1.0 range.

    Models intermittently return ``95`` where the contract asks for ``0.95``,
    despite the instruction. Strict structured output rejects ``minimum`` /
    ``maximum`` keywords, so the range cannot be enforced in the schema itself.

    Rescaling beats clamping here: clamping 95 to 1.0 would silently report
    *maximum* certainty, which is the most damaging possible failure for a
    platform whose entire premise is honest confidence.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    number = float(value)
    if number > 1.0:
        number = number / 100.0
    return max(0.0, min(1.0, number))


#: A 0.0-1.0 confidence that tolerates percentage-scale model output.
Confidence = Annotated[float, BeforeValidator(_normalise_confidence)]


class Contract(BaseModel):
    """Base for all agent outputs."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class SourceCitation(Contract):
    """A pointer back to where a claim came from.

    ``url`` is null when the claim rests on model knowledge or on something the
    user told us; in that case ``source_type`` records which it was, and the
    claim must not be graded as a verified fact.
    """

    url: str | None = Field(description="Source URL, or null if not web-sourced.")
    title: str = Field(description="Human-readable source title.")
    source_type: SourceType
    published_date: str | None = Field(
        description="ISO-8601 date the source was published, or null if unknown."
    )


class EvidencedClaim(Contract):
    """Claim -> Evidence -> Source -> Confidence (spec 4).

    The unit of intelligence in the entire platform.
    """

    claim: str = Field(description="A single, specific, falsifiable statement.")
    detail: str = Field(description="Supporting reasoning or elaboration.")
    grade: EvidenceGrade = Field(
        description=(
            "verified_fact only when a cited source directly states this. "
            "Use ai_hypothesis when reasoning from model knowledge alone."
        )
    )
    confidence: Confidence = Field(description="Confidence from 0.0 to 1.0.")
    citations: list[SourceCitation] = Field(
        description="Sources backing this claim. Empty list if none exist."
    )


# --------------------------------------------------------------------------
# Intake / classification
# --------------------------------------------------------------------------


class IntakeClassification(Contract):
    """Turns any input - even a one-line idea - into a structured concept (spec 1)."""

    product_name: str = Field(description="Concise product name, invented if necessary.")
    one_liner: str = Field(description="One sentence describing what this product is.")
    category: str
    subcategory: str
    industry: str
    business_model: BusinessModel
    market_segment: MarketSegment
    maturity: ProductMaturity
    likely_users: list[str] = Field(description="Who uses the product day to day.")
    likely_buyers: list[str] = Field(description="Who holds the budget.")
    revenue_model: str
    assumptions: list[str] = Field(
        description="Anything you inferred that the user did not state."
    )
    clarifying_questions: list[str] = Field(
        description="Questions whose answers would most improve this analysis."
    )
    confidence: Confidence


# --------------------------------------------------------------------------
# Product intelligence profile (spec 2)
# --------------------------------------------------------------------------


class Feature(Contract):
    name: str
    description: str
    grade: EvidenceGrade = Field(
        description="verified_fact if observed in provided source material."
    )


class ProductProfile(Contract):
    summary: str = Field(description="Executive summary of the product, 2-4 sentences.")
    use_cases: list[str]
    core_capabilities: list[str]
    features: list[Feature]
    primary_problem: str = Field(description="The single most important problem solved.")
    secondary_problems: list[str]
    target_customers: list[str]
    decision_makers: list[str]
    differentiators: list[EvidencedClaim]
    pricing_model: str
    distribution_model: str
    technology: list[str]
    integrations: list[str]
    strengths: list[EvidencedClaim]
    weaknesses: list[EvidencedClaim]
    opportunities: list[EvidencedClaim]
    threats: list[EvidencedClaim]
    adoption_barriers: list[str]
    switching_costs: str
    defensibility: str


# --------------------------------------------------------------------------
# Competitors (spec 6)
# --------------------------------------------------------------------------


class CompetitorCandidate(Contract):
    name: str
    company: str
    website: str | None = Field(description="Root URL, or null if genuinely unknown.")
    competitor_type: CompetitorType
    positioning: str = Field(description="How they position themselves in one sentence.")
    target_customer: str
    known_features: list[str]
    pricing_summary: str = Field(
        description="What is publicly known about pricing, or 'unknown'."
    )
    strengths: list[str]
    weaknesses: list[str]
    threat_level: ThreatLevel
    rationale: str = Field(description="Why this is a competitor to THIS product.")
    grade: EvidenceGrade
    confidence: Confidence


class CompetitorDiscovery(Contract):
    competitors: list[CompetitorCandidate]
    market_structure: str = Field(
        description="Is this market fragmented, consolidating, or dominated?"
    )
    notes: list[str]


# --------------------------------------------------------------------------
# Market (spec 12 / 13)
# --------------------------------------------------------------------------


class MarketSizeModel(Contract):
    """A TAM/SAM/SOM figure that shows its work (spec 13)."""

    label: str = Field(description="One of: TAM, SAM, SOM.")
    value_usd: float = Field(description="Estimated annual value in USD.")
    formula: str = Field(description="The arithmetic, e.g. '50,000 hospitals x $24,000'.")
    variables: list[str] = Field(description="Each input with its value and origin.")
    assumptions: list[str]
    confidence: Confidence
    basis: str = Field(description="One of: top_down, bottom_up, value_theory.")


class MarketAnalysis(Contract):
    market_definition: str
    maturity: str
    growth_outlook: EvidencedClaim
    drivers: list[EvidencedClaim]
    inhibitors: list[EvidencedClaim]
    trends: list[EvidencedClaim]
    regulatory_environment: EvidencedClaim
    entry_barriers: list[str]
    competitive_concentration: str
    adjacent_markets: list[str]
    sizing: list[MarketSizeModel]


# --------------------------------------------------------------------------
# Customers (spec 10)
# --------------------------------------------------------------------------


class Persona(Contract):
    name: str = Field(description="Role-based label, e.g. 'Hospital CISO'.")
    is_buyer: bool
    is_user: bool
    jobs_to_be_done: list[str]
    pain_points: list[str]
    desired_outcomes: list[str]
    buying_triggers: list[str]
    objections: list[str]
    decision_criteria: list[str]
    current_alternatives: list[str]
    grade: EvidenceGrade = Field(
        description="ai_hypothesis unless real customer data was supplied."
    )
    confidence: Confidence


class CustomerIntelligence(Contract):
    icp: str = Field(description="Ideal customer profile in 2-3 sentences.")
    personas: list[Persona]
    adoption_barriers: list[EvidencedClaim]
    switching_concerns: list[str]


# --------------------------------------------------------------------------
# Scoring (spec 3)
# --------------------------------------------------------------------------


class DimensionScore(Contract):
    dimension: ScoreDimension
    score: float = Field(description="0-100. For inverted dimensions, higher = more of that pressure.")
    explanation: str
    supporting_evidence: list[str]
    assumptions: list[str]
    confidence: Confidence


class ScoringResult(Contract):
    scores: list[DimensionScore] = Field(
        description="One entry per requested dimension. Do not omit any."
    )
    headline: str = Field(description="One sentence verdict on the product's position.")


# --------------------------------------------------------------------------
# Gaps and recommendations (spec 9)
# --------------------------------------------------------------------------


class Recommendation(Contract):
    title: str
    gap_category: str = Field(
        description="e.g. feature, pricing, integration, security, onboarding, distribution."
    )
    problem: str = Field(description="The gap or problem this addresses.")
    recommendation: str = Field(description="The specific action to take.")
    verdict: RecommendationVerdict
    reason: str = Field(description="Why this verdict, including why NOT to build if so.")
    supporting_evidence: list[str]
    customer_impact: str
    competitive_impact: str
    effort: EffortSize
    risk: str
    dependencies: list[str]
    expected_outcome: str
    priority: int = Field(description="1 = highest priority.")
    confidence: Confidence


class GapAnalysis(Contract):
    recommendations: list[Recommendation]
    capabilities_competitors_have: list[str] = Field(
        description="Capabilities competitors offer that this product lacks."
    )
    capabilities_unique_to_product: list[str] = Field(
        description="Capabilities this product has that no listed competitor advertises."
    )


# --------------------------------------------------------------------------
# Executive synthesis (spec 23 - Chief Strategy Agent)
# --------------------------------------------------------------------------


class RankedItem(Contract):
    title: str
    detail: str
    severity: str = Field(description="One of: critical, high, medium, low.")
    confidence: Confidence


# --------------------------------------------------------------------------
# Positioning studio (spec 14)
# --------------------------------------------------------------------------


class PositioningOption(Contract):
    strategy_name: str = Field(
        description="e.g. Premium Enterprise, AI First, Privacy First, Developer First."
    )
    target_customer: str
    value_proposition: str
    differentiation: str
    supporting_evidence: list[str]
    benefits: list[str]
    risks: list[str]
    required_product_changes: list[str]
    pricing_implications: str
    gtm_implications: str
    competitive_reaction_risk: str
    fit_score: float = Field(
        description="0-100: how well this strategy fits the product's actual evidence."
    )
    confidence: Confidence


class ObjectionResponse(Contract):
    objection: str
    response: str


class PositioningMessaging(Contract):
    positioning_statement: str = Field(
        description="For [customer] who [need], [product] is a [category] that [benefit]."
    )
    unique_value_proposition: str
    category_definition: str
    elevator_pitch: str
    homepage_headline: str = Field(description="Under 12 words.")
    homepage_subheadline: str
    product_description: str
    sales_narrative: str
    differentiation_statement: str
    messaging_hierarchy: list[str] = Field(description="Ordered: primary message first.")
    objection_handling: list[ObjectionResponse]


class PositioningStudio(Contract):
    options: list[PositioningOption] = Field(
        description="At least 3 genuinely different strategies, not variations of one."
    )
    recommended_strategy: str = Field(description="The strategy_name you recommend.")
    recommendation_reason: str
    messaging: PositioningMessaging = Field(
        description="Messaging written for the RECOMMENDED strategy."
    )


# --------------------------------------------------------------------------
# Pricing studio (spec 15)
# --------------------------------------------------------------------------


class CompetitorPricePoint(Contract):
    competitor: str
    plan_name: str
    price_monthly_usd: float = Field(
        description=(
            "Monthly USD price. Use 0 when the plan is genuinely free. "
            "Use -1 when the price is not published (custom/contact-sales) or you "
            "could not establish it. Never guess a number."
        )
    )
    pricing_model: PricingModel
    notes: str = Field(
        description="If price is -1, say whether it is contact-sales or simply unknown."
    )
    grade: EvidenceGrade = Field(
        description=(
            "Grades the price claim. verified_fact only when retrieved material "
            "states this price - or states the plan is free, or that pricing is "
            "custom. If you could not establish the price at all, this is at best "
            "a weak_inference."
        )
    )
    confidence: Confidence


class PricingTier(Contract):
    name: str
    price_monthly_usd: float = Field(
        description=(
            "Monthly USD price. Use 0 for a free tier and -1 for a "
            "custom/contact-sales tier. Every other tier needs a real number."
        )
    )
    target_segment: str
    included_capabilities: list[str]
    limits: str
    rationale: str


class EconomicsInputs(Contract):
    """Seeds the deterministic simulator. Estimates, clearly labelled as such."""

    arpu_monthly_usd: float = Field(description="Expected average revenue per account.")
    gross_margin_pct: float = Field(description="0-100.")
    cac_usd: float = Field(description="Expected customer acquisition cost.")
    monthly_churn_pct: float = Field(description="0-100. Monthly logo churn.")
    trial_conversion_pct: float = Field(description="0-100.")
    monthly_expansion_pct: float = Field(description="0-100. Net expansion per month.")
    price_elasticity: float = Field(
        description=(
            "Negative. % change in demand per 1% price change. "
            "Typical B2B SaaS -0.5 to -1.5; consumer -1.5 to -3.0."
        )
    )
    basis: str = Field(description="Where these numbers came from. Be honest.")


class PricingStudio(Contract):
    current_assessment: str = Field(description="How this product's pricing stands today.")
    competitor_pricing: list[CompetitorPricePoint]
    recommended_model: PricingModel
    value_metric: str = Field(description="The unit you should charge for, and why.")
    rationale: str
    tiers: list[PricingTier]
    pricing_power: str
    risks: list[str]
    assumptions: list[str]
    economics: EconomicsInputs


# --------------------------------------------------------------------------
# Growth strategy (spec 16)
# --------------------------------------------------------------------------


class ChannelRecommendation(Contract):
    channel: GrowthChannel
    fit_score: float = Field(description="0-100 fit for THIS product and buyer.")
    why_appropriate: str = Field(
        description="Why this channel suits this product, price point and buying behaviour."
    )
    expected_cac: str
    time_to_traction: str
    scalability: str
    effort: EffortSize
    first_experiment: str = Field(description="The cheapest test that would validate it.")
    supporting_evidence: list[str]
    confidence: Confidence
    priority: int


class GrowthStrategy(Contract):
    primary_motion: str = Field(
        description="e.g. product-led, sales-led, community-led, partner-led."
    )
    motion_rationale: str
    channels: list[ChannelRecommendation] = Field(
        description="Score the plausible channels. Include ones you rate poorly and say why."
    )
    sequencing: list[str] = Field(description="Ordered: what to do first, second, third.")
    channels_to_avoid: list[str]


# --------------------------------------------------------------------------
# Go-to-market (spec 17)
# --------------------------------------------------------------------------


class Experiment(Contract):
    hypothesis: str
    test: str
    success_metric: str
    effort: EffortSize


class LaunchPhase(Contract):
    horizon: LaunchHorizon
    objectives: list[str]
    activities: list[str]
    milestones: list[str]
    owner_role: str


class GTMPlan(Contract):
    target_segment: str
    beachhead_rationale: str = Field(description="Why start with this segment specifically.")
    positioning_summary: str
    messaging_summary: str
    pricing_summary: str
    channel_strategy: str
    sales_strategy: str
    launch_strategy: str
    content_strategy: str
    partnership_strategy: str
    metrics: list[str] = Field(description="The few numbers that actually indicate progress.")
    experiments: list[Experiment]
    budget_assumptions: list[str]
    risks: list[str]
    phases: list[LaunchPhase] = Field(description="One entry per launch horizon.")


# --------------------------------------------------------------------------
# Change detection and alerts (spec 8 / 34)
# --------------------------------------------------------------------------


class DetectedChange(Contract):
    change_type: ChangeType
    summary: str = Field(description="What changed, in one sentence.")
    previous_state: str
    current_state: str
    evidence: str = Field(description="What in the source material shows this.")
    estimated_impact: str
    severity: AlertSeverity
    recommended_action: str
    is_meaningful: bool = Field(
        description=(
            "False for cosmetic changes (copy tweaks, layout). Only true when this "
            "would plausibly change a product or pricing decision."
        )
    )
    confidence: Confidence


class ChangeReport(Contract):
    changes: list[DetectedChange]
    summary: str


# --------------------------------------------------------------------------
# Conversational answers (spec 25)
# --------------------------------------------------------------------------


class CitedAnswer(Contract):
    answer: str = Field(description="Direct answer first, then reasoning. Markdown allowed.")
    used_evidence_ids: list[str] = Field(
        description="IDs of evidence records you actually relied on. Empty if none applied."
    )
    confidence: Confidence
    caveats: list[str] = Field(
        description="What you could not determine from the available intelligence."
    )
    followup_questions: list[str]


class ExecutiveSynthesis(Contract):
    verdict: str = Field(description="Direct answer: is this worth pursuing, and why?")
    headline_summary: str
    top_opportunities: list[RankedItem]
    top_risks: list[RankedItem]
    immediate_actions: list[str] = Field(description="What to do in the next 30 days.")
    key_uncertainties: list[str] = Field(
        description="What we could not establish, and what would resolve it."
    )
    confidence: Confidence


# --------------------------------------------------------------------------
# Voice of Customer (spec 11)
# --------------------------------------------------------------------------


class FeedbackCluster(Contract):
    """A recurring theme found across many pieces of feedback."""

    label: str = Field(description="Short name for the theme, e.g. 'Onboarding is slow'.")
    theme: FeedbackTheme
    sentiment: Sentiment
    summary: str = Field(description="What customers are actually saying, specifically.")
    share_of_feedback: float = Field(
        description="0-100. Percentage of the supplied feedback in this cluster."
    )
    item_count: int = Field(description="How many supplied items belong to this cluster.")
    representative_quotes: list[str] = Field(
        description=(
            "Verbatim excerpts from the supplied feedback ONLY. Never invent or "
            "paraphrase a quote. Empty list if none are quotable."
        )
    )
    customer_language: list[str] = Field(
        description="Recurring words and phrases customers themselves use."
    )
    is_churn_driver: bool
    is_feature_request: bool
    suggested_action: str
    severity: AlertSeverity
    confidence: Confidence


class FeedbackAnalysis(Contract):
    total_items_analysed: int = Field(
        description="How many distinct pieces of feedback you were given."
    )
    overall_sentiment: Sentiment
    sentiment_positive_pct: float = Field(description="0-100.")
    sentiment_neutral_pct: float = Field(description="0-100.")
    sentiment_negative_pct: float = Field(description="0-100.")
    clusters: list[FeedbackCluster] = Field(
        description="Ordered by share_of_feedback, largest first."
    )
    top_complaints: list[str]
    top_praise: list[str]
    unmet_needs: list[str]
    emerging_trends: list[str] = Field(
        description="Themes that look new or growing, if the data shows timing."
    )
    summary: str
    caveats: list[str] = Field(
        description="Sampling bias, small volume, or anything limiting these conclusions."
    )


# --------------------------------------------------------------------------
# Opportunity and threat radar (spec 27 / 28)
# --------------------------------------------------------------------------


class RadarSignal(Contract):
    title: str
    signal_type: SignalType
    category: str = Field(
        description=(
            "For opportunities: customer_pain, competitor_weakness, market_trend, "
            "product_gap, technology, pricing, geographic, integration, partnership, "
            "segment, distribution, regulatory. For threats: competitor, market, "
            "technology_disruption, pricing_pressure, regulatory, churn, new_entrant, "
            "substitute, platform_dependency, security, reputation."
        )
    )
    description: str
    why_now: str = Field(description="What makes this current rather than perennial.")
    impact: float = Field(description="0-100 potential magnitude if it materialises.")
    probability: float = Field(description="0-100 likelihood it materialises.")
    horizon: TimeHorizon
    supporting_evidence: list[str]
    recommended_response: str
    confidence: Confidence


class RadarReport(Contract):
    opportunities: list[RadarSignal]
    threats: list[RadarSignal]
    summary: str
    biggest_opportunity: str
    biggest_threat: str


# --------------------------------------------------------------------------
# Scenario simulation (spec 20)
# --------------------------------------------------------------------------


class ScenarioOutcome(Contract):
    case: str = Field(description="One of: best, base, worst.")
    narrative: str
    revenue_impact: str
    customer_impact: str
    competitive_impact: str
    probability: float = Field(description="0-100. The three cases should total ~100.")


class ScenarioAnalysis(Contract):
    """A what-if projection. Explicitly NOT a prediction."""

    question: str = Field(description="Restate the scenario being modelled.")
    assumptions: list[str] = Field(
        description="Every assumption this projection rests on. Be exhaustive."
    )
    outcomes: list[ScenarioOutcome] = Field(
        description="Exactly three: best, base and worst case."
    )
    leading_indicators: list[str] = Field(
        description="What to watch to tell early which case is unfolding."
    )
    risks: list[str]
    reversibility: str = Field(description="How hard would this be to undo?")
    recommendation: str
    confidence: Confidence
