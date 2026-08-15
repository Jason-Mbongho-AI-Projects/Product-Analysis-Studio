"""Agent execution order.

Kept in its own module so the dependency chain is stated in one readable place
rather than implied across imports. Later stages read what earlier stages
persisted, so this ordering is load-bearing, not cosmetic.
"""

from __future__ import annotations

from .analysts import (
    ChiefStrategyAgent,
    CompetitiveIntelligenceAgent,
    CustomerIntelligenceAgent,
    GapAnalysisAgent,
    IntakeAgent,
    MarketAnalystAgent,
    ProductAnalystAgent,
    ScoringAgent,
)
from .base import Agent
from .strategists import (
    GrowthStrategistAgent,
    GTMStrategistAgent,
    PositioningStrategistAgent,
    PricingStrategistAgent,
)

#: Establish what is true about the product, market and competition.
INTELLIGENCE_STAGE: list[type[Agent]] = [
    IntakeAgent,
    ProductAnalystAgent,
    CompetitiveIntelligenceAgent,
    MarketAnalystAgent,
    CustomerIntelligenceAgent,
    ScoringAgent,
    GapAnalysisAgent,
]

#: Decide what to do about it. GTM runs last because it consumes the output of
#: positioning, pricing and growth.
STRATEGY_STAGE: list[type[Agent]] = [
    PositioningStrategistAgent,
    PricingStrategistAgent,
    GrowthStrategistAgent,
    GTMStrategistAgent,
]

#: Synthesis sees everything.
SYNTHESIS_STAGE: list[type[Agent]] = [ChiefStrategyAgent]

FULL_PIPELINE: list[type[Agent]] = [
    *INTELLIGENCE_STAGE,
    *STRATEGY_STAGE,
    *SYNTHESIS_STAGE,
]

#: Intelligence only - cheaper and faster when the user wants analysis without
#: the strategy studios.
INTELLIGENCE_ONLY: list[type[Agent]] = [*INTELLIGENCE_STAGE, *SYNTHESIS_STAGE]


def pipeline_for(depth: str = "full") -> list[type[Agent]]:
    """Return the agent sequence for a requested analysis depth."""
    return INTELLIGENCE_ONLY if depth == "intelligence" else FULL_PIPELINE
