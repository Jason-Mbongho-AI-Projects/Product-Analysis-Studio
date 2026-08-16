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
from .voice import RadarAgent

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

#: Radar reads the strategy output, then synthesis sees everything.
SYNTHESIS_STAGE: list[type[Agent]] = [RadarAgent, ChiefStrategyAgent]

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


def execution_levels(agents: list[type[Agent]]) -> list[list[type[Agent]]]:
    """Group agents into levels that can each run concurrently.

    Level N contains every agent whose dependencies are all satisfied by levels
    0..N-1. Running one level at a time preserves the exact data dependencies
    the sequential order guaranteed, while letting independent agents overlap.

    Raises ValueError on a dependency cycle or an unknown dependency name -
    both are programming errors that would otherwise deadlock or silently drop
    an agent.
    """
    remaining = list(agents)
    known = {agent.name for agent in agents}

    for agent in agents:
        unknown = set(agent.requires) - known
        if unknown:
            raise ValueError(
                f"{agent.name} requires unknown agent(s): {', '.join(sorted(unknown))}"
            )

    levels: list[list[type[Agent]]] = []
    satisfied: set[str] = set()

    while remaining:
        ready = [a for a in remaining if set(a.requires) <= satisfied]
        if not ready:
            stuck = ", ".join(a.name for a in remaining)
            raise ValueError(f"Dependency cycle among: {stuck}")
        levels.append(ready)
        satisfied.update(a.name for a in ready)
        remaining = [a for a in remaining if a not in ready]

    return levels
