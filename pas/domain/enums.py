"""Controlled vocabularies shared by agents, storage and UI.

Using enums rather than free strings is what lets the platform query and
aggregate intelligence instead of only rendering prose.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String enum that serialises cleanly through Pydantic and sqlite."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class EvidenceGrade(StrEnum):
    """How much epistemic weight a claim carries.

    This is the single most important distinction in the product: an AI guess
    must never be rendered the same way as a verified fact (spec 4).
    """

    VERIFIED_FACT = "verified_fact"
    STRONG_INFERENCE = "strong_inference"
    WEAK_INFERENCE = "weak_inference"
    AI_HYPOTHESIS = "ai_hypothesis"
    USER_SUPPLIED = "user_supplied"

    @property
    def label(self) -> str:
        return {
            "verified_fact": "Verified fact",
            "strong_inference": "Strong inference",
            "weak_inference": "Weak inference",
            "ai_hypothesis": "AI hypothesis",
            "user_supplied": "User supplied",
        }[self.value]

    @property
    def is_evidence_backed(self) -> bool:
        """True when the claim rests on a retrieved source, not on model priors."""
        return self in {
            EvidenceGrade.VERIFIED_FACT,
            EvidenceGrade.STRONG_INFERENCE,
            EvidenceGrade.USER_SUPPLIED,
        }


class SourceType(StrEnum):
    PRODUCT_WEBSITE = "product_website"
    PRICING_PAGE = "pricing_page"
    DOCUMENTATION = "documentation"
    CHANGELOG = "changelog"
    BLOG = "blog"
    NEWS = "news"
    REVIEW_SITE = "review_site"
    APP_STORE = "app_store"
    FORUM = "forum"
    JOB_POSTING = "job_posting"
    GITHUB = "github"
    FILING = "filing"
    USER_UPLOAD = "user_upload"
    USER_STATEMENT = "user_statement"
    MODEL_KNOWLEDGE = "model_knowledge"
    OTHER = "other"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    FAILED = "failed"
    DISABLED = "disabled"
    BLOCKED = "blocked"


class IntakeKind(StrEnum):
    """How the user described what they want analysed (spec 1)."""

    URL = "url"
    IDEA = "idea"
    DESCRIPTION = "description"
    DOCUMENT = "document"


class BusinessModel(StrEnum):
    SAAS = "saas"
    MARKETPLACE = "marketplace"
    ECOMMERCE = "ecommerce"
    HARDWARE = "hardware"
    SERVICE = "service"
    PLATFORM = "platform"
    MOBILE_APP = "mobile_app"
    OPEN_SOURCE = "open_source"
    OTHER = "other"


class MarketSegment(StrEnum):
    B2B = "b2b"
    B2C = "b2c"
    B2B2C = "b2b2c"
    B2G = "b2g"


class ProductMaturity(StrEnum):
    IDEA = "idea"
    PROTOTYPE = "prototype"
    MVP = "mvp"
    EARLY_TRACTION = "early_traction"
    GROWTH = "growth"
    MATURE = "mature"


class CompetitorType(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    EMERGING = "emerging"
    SUBSTITUTE = "substitute"
    LEGACY = "legacy"
    MANUAL_ALTERNATIVE = "manual_alternative"
    OPEN_SOURCE = "open_source"
    POTENTIAL = "potential"


class ThreatLevel(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ScoreDimension(StrEnum):
    """The transparent scoring model (spec 3).

    Weights live alongside the dimension so the overall score is reproducible
    arithmetic rather than a number the model invented.
    """

    MARKET_OPPORTUNITY = "market_opportunity"
    CUSTOMER_PAIN_SEVERITY = "customer_pain_severity"
    PRODUCT_DIFFERENTIATION = "product_differentiation"
    COMPETITIVE_PRESSURE = "competitive_pressure"
    MONETIZATION_POTENTIAL = "monetization_potential"
    PRODUCT_MATURITY = "product_maturity"
    GTM_READINESS = "gtm_readiness"
    DEFENSIBILITY = "defensibility"
    GROWTH_POTENTIAL = "growth_potential"
    PMF_POTENTIAL = "pmf_potential"
    ACQUISITION_DIFFICULTY = "acquisition_difficulty"
    RETENTION_POTENTIAL = "retention_potential"
    PRICING_POWER = "pricing_power"
    IMPLEMENTATION_COMPLEXITY = "implementation_complexity"
    MARKET_TIMING = "market_timing"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_inverted(self) -> bool:
        """Dimensions where a high raw value is bad news for the product.

        Stored raw (high = more pressure/difficulty/complexity) but inverted
        when rolled into the overall score, so the composite always reads
        "higher is better".
        """
        return self in {
            ScoreDimension.COMPETITIVE_PRESSURE,
            ScoreDimension.ACQUISITION_DIFFICULTY,
            ScoreDimension.IMPLEMENTATION_COMPLEXITY,
        }


#: Relative weights for the composite product score. Kept explicit and summing
#: to 1.0 so the headline number can always be re-derived and explained.
SCORE_WEIGHTS: dict[ScoreDimension, float] = {
    ScoreDimension.MARKET_OPPORTUNITY: 0.12,
    ScoreDimension.CUSTOMER_PAIN_SEVERITY: 0.11,
    ScoreDimension.PRODUCT_DIFFERENTIATION: 0.11,
    ScoreDimension.COMPETITIVE_PRESSURE: 0.07,
    ScoreDimension.MONETIZATION_POTENTIAL: 0.09,
    ScoreDimension.PRODUCT_MATURITY: 0.05,
    ScoreDimension.GTM_READINESS: 0.06,
    ScoreDimension.DEFENSIBILITY: 0.08,
    ScoreDimension.GROWTH_POTENTIAL: 0.08,
    ScoreDimension.PMF_POTENTIAL: 0.09,
    ScoreDimension.ACQUISITION_DIFFICULTY: 0.04,
    ScoreDimension.RETENTION_POTENTIAL: 0.05,
    ScoreDimension.PRICING_POWER: 0.03,
    ScoreDimension.IMPLEMENTATION_COMPLEXITY: 0.01,
    ScoreDimension.MARKET_TIMING: 0.01,
}


class RecommendationVerdict(StrEnum):
    """Gap-engine verdicts (spec 9). DO_NOT_BUILD is deliberately first-class."""

    MUST_BUILD = "must_build"
    SHOULD_BUILD = "should_build"
    COULD_BUILD = "could_build"
    DO_NOT_BUILD = "do_not_build"
    INVESTIGATE_FIRST = "investigate_first"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").upper()


class DecisionState(StrEnum):
    """User decisions on recommendations (spec 19)."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INVESTIGATING = "investigating"
    POSTPONED = "postponed"


class RoadmapHorizon(StrEnum):
    NOW = "now"
    NEXT = "next"
    LATER = "later"


class EffortSize(StrEnum):
    XS = "xs"
    S = "s"
    M = "m"
    L = "l"
    XL = "xl"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class PricingModel(StrEnum):
    """Monetisation shapes the pricing studio can recommend (spec 15)."""

    FREE = "free"
    FREEMIUM = "freemium"
    FREE_TRIAL = "free_trial"
    SUBSCRIPTION = "subscription"
    USAGE_BASED = "usage_based"
    PER_SEAT = "per_seat"
    TIERED = "tiered"
    ENTERPRISE = "enterprise"
    TRANSACTION = "transaction"
    HYBRID = "hybrid"
    CREDIT_BASED = "credit_based"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class GrowthChannel(StrEnum):
    """Acquisition channels scored by the growth agent (spec 16)."""

    SEO = "seo"
    CONTENT = "content"
    YOUTUBE = "youtube"
    SOCIAL = "social"
    PARTNERSHIPS = "partnerships"
    AFFILIATES = "affiliates"
    COMMUNITIES = "communities"
    PAID_SEARCH = "paid_search"
    PAID_SOCIAL = "paid_social"
    INFLUENCERS = "influencers"
    PRODUCT_LED = "product_led"
    OUTBOUND_SALES = "outbound_sales"
    ENTERPRISE_SALES = "enterprise_sales"
    MARKETPLACES = "marketplaces"
    INTEGRATIONS = "integrations"
    REFERRAL = "referral"

    @property
    def label(self) -> str:
        return {
            "seo": "SEO",
            "youtube": "YouTube",
            "paid_search": "Paid search",
            "paid_social": "Paid social",
            "product_led": "Product-led growth",
        }.get(self.value, self.value.replace("_", " ").title())


class LaunchHorizon(StrEnum):
    """GTM launch phases (spec 17)."""

    D30 = "30_days"
    D60 = "60_days"
    D90 = "90_days"
    M6 = "6_months"
    M12 = "12_months"

    @property
    def label(self) -> str:
        return {
            "30_days": "First 30 days",
            "60_days": "Days 30-60",
            "90_days": "Days 60-90",
            "6_months": "Months 3-6",
            "12_months": "Months 6-12",
        }[self.value]


class AlertCategory(StrEnum):
    COMPETITOR = "competitor"
    MARKET = "market"
    CUSTOMER = "customer"
    PRODUCT = "product"
    PRICING = "pricing"
    RISK = "risk"
    OPPORTUNITY = "opportunity"
    RECOMMENDATION = "recommendation"


class AlertSeverity(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {
            "informational": 0,
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }[self.value]


class AlertStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"
    SNOOZED = "snoozed"


class ChangeType(StrEnum):
    """What changed about a competitor between snapshots (spec 8)."""

    PRICING = "pricing"
    FEATURE_ADDED = "feature_added"
    FEATURE_REMOVED = "feature_removed"
    POSITIONING = "positioning"
    INTEGRATION = "integration"
    SECURITY = "security"
    CONTENT = "content"
    OTHER = "other"


class AnalysisMode(StrEnum):
    """Lenses over the same intelligence (spec 58-62)."""

    FOUNDER = "founder"
    PRODUCT_MANAGER = "product_manager"
    EXECUTIVE = "executive"
    INVESTOR = "investor"
    CONSULTANT = "consultant"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class FeedbackSource(StrEnum):
    """Where a piece of customer feedback came from (spec 11)."""

    REVIEW = "review"
    APP_REVIEW = "app_review"
    INTERVIEW = "interview"
    SURVEY = "survey"
    SUPPORT_TICKET = "support_ticket"
    SALES_CALL = "sales_call"
    CRM_NOTE = "crm_note"
    FORUM = "forum"
    SOCIAL = "social"
    NPS = "nps"
    UPLOAD = "upload"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    MIXED = "mixed"

    @property
    def colour_key(self) -> str:
        return self.value


class FeedbackTheme(StrEnum):
    """What a cluster of feedback is fundamentally about."""

    PRICING = "pricing"
    ONBOARDING = "onboarding"
    USABILITY = "usability"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    MISSING_FEATURE = "missing_feature"
    INTEGRATIONS = "integrations"
    MOBILE = "mobile"
    SUPPORT = "support"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    BILLING = "billing"
    PRAISE = "praise"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class SignalType(StrEnum):
    """Radar entries (spec 27 / 28)."""

    OPPORTUNITY = "opportunity"
    THREAT = "threat"


class TimeHorizon(StrEnum):
    IMMEDIATE = "immediate"
    NEAR_TERM = "near_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"

    @property
    def label(self) -> str:
        return {
            "immediate": "Now (0-3 months)",
            "near_term": "Near (3-6 months)",
            "medium_term": "Medium (6-12 months)",
            "long_term": "Long (12+ months)",
        }[self.value]

    @property
    def rank(self) -> int:
        return ["immediate", "near_term", "medium_term", "long_term"].index(self.value)
