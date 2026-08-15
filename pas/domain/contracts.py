"""Agent output contracts (spec 24).

Every agent returns a validated Pydantic model, never free-form prose. These
schemas are converted to strict JSON Schema and handed to the model, so a
malformed agent response is a validation error we can retry - not silent
garbage that flows into the UI.

Nesting is deliberately kept shallow (<= 3 levels) because strict structured
output has depth and property-count limits.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    BusinessModel,
    CompetitorType,
    EffortSize,
    EvidenceGrade,
    MarketSegment,
    ProductMaturity,
    RecommendationVerdict,
    ScoreDimension,
    SourceType,
    ThreatLevel,
)


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
    confidence: float = Field(description="Confidence from 0.0 to 1.0.")
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
    confidence: float


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
    confidence: float


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
    confidence: float
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
    confidence: float


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
    confidence: float


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
    confidence: float


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
    confidence: float


class ExecutiveSynthesis(Contract):
    verdict: str = Field(description="Direct answer: is this worth pursuing, and why?")
    headline_summary: str
    top_opportunities: list[RankedItem]
    top_risks: list[RankedItem]
    immediate_actions: list[str] = Field(description="What to do in the next 30 days.")
    key_uncertainties: list[str] = Field(
        description="What we could not establish, and what would resolve it."
    )
    confidence: float
