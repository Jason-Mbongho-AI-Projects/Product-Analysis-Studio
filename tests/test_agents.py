"""Agent framework, contract and scoring tests.

These use a stub provider rather than the network, so the pipeline's control
flow is verified deterministically and without cost.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pas.agents.analysts import composite_score
from pas.agents.pipeline import FULL_PIPELINE as PIPELINE
from pas.agents.base import Agent, AnalysisContext, BudgetExceeded, ResearchBundle
from pas.ai.provider import Completion, LLMProvider, ProviderError, Usage
from pas.ai.schema import to_strict_schema
from pas.domain import contracts as C
from pas.domain.enums import SCORE_WEIGHTS, EvidenceGrade, ScoreDimension
from pas.storage import repositories as repo


class StubProvider(LLMProvider):
    """Returns canned contract instances; records what it was asked."""

    name = "stub"

    def __init__(self, responses=None, fail=False):
        self.responses = responses or {}
        self.fail = fail
        self.calls = []

    def complete_structured(self, *, model, system, user, schema, max_tokens=8000, temperature=None):
        self.calls.append({"model": model, "schema": schema.__name__, "user": user})
        if self.fail:
            raise ProviderError("stub failure")
        data = self.responses.get(schema.__name__)
        if data is None:
            raise ProviderError(f"no stub for {schema.__name__}")
        return Completion(
            data=data,
            raw="{}",
            usage=Usage(provider="stub", model=model, total_tokens=100, cost_usd=0.001),
        )

    def complete_text(self, *, model, system, user, max_tokens=4000, temperature=None):
        return Completion(data="text", raw="text", usage=Usage(provider="stub", model=model))


# ---------------------------------------------------------------------------
# Schema contracts
# ---------------------------------------------------------------------------


ALL_CONTRACTS = [
    C.IntakeClassification,
    C.ProductProfile,
    C.CompetitorDiscovery,
    C.MarketAnalysis,
    C.CustomerIntelligence,
    C.ScoringResult,
    C.GapAnalysis,
    C.ExecutiveSynthesis,
    C.PositioningStudio,
    C.PricingStudio,
    C.GrowthStrategy,
    C.GTMPlan,
    C.ChangeReport,
    C.CitedAnswer,
    C.FeedbackAnalysis,
    C.RadarReport,
    C.ScenarioAnalysis,
]


def test_every_pipeline_agent_contract_is_covered():
    """Guards against adding an agent whose schema is never strict-checked."""
    from pas.agents.pipeline import FULL_PIPELINE

    covered = {contract.__name__ for contract in ALL_CONTRACTS}
    for agent in FULL_PIPELINE:
        assert agent.contract.__name__ in covered, (
            f"{agent.name} uses {agent.contract.__name__}, which is not in ALL_CONTRACTS"
        )


@pytest.mark.parametrize("contract", ALL_CONTRACTS)
def test_strict_schema_satisfies_provider_rules(contract):
    """Every object must forbid extras and require all properties."""
    schema = to_strict_schema(contract)

    def walk(node, path="root"):
        if isinstance(node, dict):
            # A $ref may not carry sibling keywords.
            if "$ref" in node:
                assert set(node) == {"$ref"}, f"{path}: $ref has siblings {set(node)}"
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False, f"{path}: extras allowed"
                assert set(node.get("required", [])) == set(node.get("properties", {})), (
                    f"{path}: required must list every property"
                )
            for key in ("default", "minimum", "maxLength", "format", "pattern"):
                assert key not in node, f"{path}: unsupported keyword {key}"
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(schema)


def test_contracts_reject_unknown_fields():
    with pytest.raises(ValidationError):
        C.SourceCitation.model_validate(
            {"url": None, "title": "t", "source_type": "blog",
             "published_date": None, "surprise": 1}
        )


def test_contracts_reject_invalid_enum_values():
    with pytest.raises(ValidationError):
        C.EvidencedClaim.model_validate(
            {"claim": "c", "detail": "d", "grade": "totally_true",
             "confidence": 0.9, "citations": []}
        )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_weights_sum_to_one():
    assert sum(SCORE_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_dimension_has_a_weight():
    assert set(SCORE_WEIGHTS) == set(ScoreDimension)


def test_composite_inverts_pressure_dimensions():
    """High competitive pressure must lower, not raise, the composite."""
    low_pressure = composite_score(
        [{"dimension": "competitive_pressure", "score": 10, "confidence": 0.8}]
    )
    high_pressure = composite_score(
        [{"dimension": "competitive_pressure", "score": 90, "confidence": 0.8}]
    )
    assert low_pressure["score"] > high_pressure["score"]
    assert low_pressure["score"] == 90.0
    assert high_pressure["score"] == 10.0


def test_composite_is_reproducible_arithmetic():
    scores = [
        {"dimension": "market_opportunity", "score": 80, "confidence": 0.7},
        {"dimension": "defensibility", "score": 40, "confidence": 0.5},
    ]
    expected = (80 * 0.12 + 40 * 0.08) / (0.12 + 0.08)
    assert composite_score(scores)["score"] == pytest.approx(round(expected, 1))


def test_composite_handles_empty_and_unknown_dimensions():
    assert composite_score([])["score"] == 0.0
    assert composite_score([{"dimension": "not_a_dimension", "score": 90}])["score"] == 0.0


def test_coverage_reflects_missing_dimensions():
    partial = composite_score([{"dimension": "market_opportunity", "score": 50, "confidence": 0.5}])
    assert partial["coverage"] == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# Agent framework
# ---------------------------------------------------------------------------


def _context(conn, workspace, product_id, analysis_id, provider, config):
    return AnalysisContext(
        conn=conn,
        config=config,
        provider=provider,
        workspace_id=workspace,
        analysis_id=analysis_id,
        product=dict(repo.get_product(conn, product_id, workspace)),
    )


class _Dummy(Agent[C.ExecutiveSynthesis]):
    name = "dummy"
    title = "Dummy"
    contract = C.ExecutiveSynthesis

    def build_prompt(self, ctx):
        return "prompt"


def _synthesis():
    return C.ExecutiveSynthesis(
        verdict="Proceed", headline_summary="ok", top_opportunities=[],
        top_risks=[], immediate_actions=[], key_uncertainties=[], confidence=0.5,
    )


def test_agent_records_run_and_usage(conn, workspace, product, analysis, config):
    provider = StubProvider({"ExecutiveSynthesis": _synthesis()})
    ctx = _context(conn, workspace, product, analysis, provider, config)

    result = _Dummy().run(ctx)

    assert result is not None
    runs = repo.list_agent_runs(conn, analysis)
    assert len(runs) == 1 and runs[0]["status"] == "succeeded"
    assert repo.usage_summary(conn, workspace, analysis)["calls"] == 1


def test_failing_agent_is_recorded_and_does_not_raise(conn, workspace, product, analysis, config):
    """One agent failing must degrade the analysis, not abort it."""
    ctx = _context(conn, workspace, product, analysis, StubProvider(fail=True), config)

    assert _Dummy().run(ctx) is None

    runs = repo.list_agent_runs(conn, analysis)
    assert runs[0]["status"] == "failed"
    assert "stub failure" in runs[0]["error"]


def test_call_budget_is_enforced(conn, workspace, product, analysis, config):
    ctx = _context(conn, workspace, product, analysis, StubProvider(), config)
    ctx.llm_calls = 10_000
    with pytest.raises(BudgetExceeded):
        ctx.charge_call()


def test_pipeline_is_ordered_and_unique():
    names = [agent.name for agent in PIPELINE]
    assert len(names) == len(set(names))
    assert names[0] == "intake", "classification must run first"
    assert names[-1] == "chief_strategy", "synthesis must run last"
    # GTM consumes positioning, pricing and growth output.
    for upstream in ("positioning_strategist", "pricing_strategist", "growth_strategist"):
        assert names.index(upstream) < names.index("gtm_strategist")
    # Gap analysis reads competitors, so discovery must precede it.
    assert names.index("competitive_intelligence") < names.index("gap_analysis")
    assert names.index("scoring") < names.index("chief_strategy")


def test_every_agent_declares_a_contract():
    for agent in PIPELINE:
        assert issubclass(agent.contract, C.Contract)
        assert agent.name and agent.title


# ---------------------------------------------------------------------------
# Evidence discipline
# ---------------------------------------------------------------------------


def test_research_bundle_without_sources_forbids_citation():
    prompt = ResearchBundle().as_prompt_context()
    assert "NO SOURCE MATERIAL" in prompt
    assert "ai_hypothesis" in prompt
    assert "Do not invent" in prompt


def test_research_bundle_budgets_content_by_page_count():
    pages = [{"url": f"https://e.com/{i}", "title": "t", "source_type": "blog", "text": "x" * 50_000}
             for i in range(4)]
    prompt = ResearchBundle(pages=pages).as_prompt_context(max_chars=8000)
    assert prompt.count("--- SOURCE") == 4
    assert len(prompt) < 12_000, "content must be truncated to the budget"


def test_evidence_grades_classify_backing_correctly():
    assert EvidenceGrade.VERIFIED_FACT.is_evidence_backed
    assert EvidenceGrade.USER_SUPPLIED.is_evidence_backed
    assert not EvidenceGrade.AI_HYPOTHESIS.is_evidence_backed
    assert not EvidenceGrade.WEAK_INFERENCE.is_evidence_backed


# ---------------------------------------------------------------------------
# Confidence normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        (0.95, 0.95),      # already correct
        (95, 0.95),        # percentage scale - the observed failure mode
        (85.0, 0.85),      # percentage as float
        (100, 1.0),
        (1, 1.0),          # ambiguous, but 1.0 is the honest reading
        (0, 0.0),
        (-0.5, 0.0),       # clamped
        (150, 1.0),        # rescaled then clamped
    ],
)
def test_confidence_is_normalised_not_clamped(given, expected):
    """A model returning 95 must become 0.95, never 1.0.

    Clamping would report maximum certainty for what was meant as 95% - the
    most damaging possible failure for an evidence-graded platform.
    """
    claim = C.EvidencedClaim.model_validate(
        {"claim": "c", "detail": "d", "grade": "ai_hypothesis",
         "confidence": given, "citations": []}
    )
    assert claim.confidence == pytest.approx(expected)


def test_percentage_confidence_does_not_become_false_certainty():
    claim = C.EvidencedClaim.model_validate(
        {"claim": "c", "detail": "d", "grade": "ai_hypothesis",
         "confidence": 40, "citations": []}
    )
    assert claim.confidence == pytest.approx(0.4)
    assert claim.confidence < 1.0


def test_confidence_normalisation_applies_across_contracts():
    """Every contract carrying confidence must use the normalising type."""
    answer = C.CitedAnswer.model_validate(
        {"answer": "a", "used_evidence_ids": [], "confidence": 85,
         "caveats": [], "followup_questions": []}
    )
    assert answer.confidence == pytest.approx(0.85)

    score = C.DimensionScore.model_validate(
        {"dimension": "market_opportunity", "score": 70, "explanation": "e",
         "supporting_evidence": [], "assumptions": [], "confidence": 60}
    )
    assert score.confidence == pytest.approx(0.6)
    assert score.score == 70, "0-100 scores must NOT be rescaled"


def test_every_confidence_field_uses_the_normalising_type():
    """Guards against a new contract field reintroducing raw float confidence."""
    import inspect

    from pas.domain import contracts as module

    offenders = []
    for name, obj in vars(module).items():
        if not (inspect.isclass(obj) and issubclass(obj, C.Contract)):
            continue
        for field_name, field in obj.model_fields.items():
            if "confidence" not in field_name:
                continue
            probe = {field_name: 90}
            try:
                normalised = obj.__pydantic_validator__.validate_assignment(
                    obj.model_construct(), field_name, 90
                )
                value = getattr(normalised, field_name)
            except Exception:
                continue
            if value > 1.0:
                offenders.append(f"{obj.__name__}.{field_name}")
    assert not offenders, f"raw float confidence fields: {offenders}"
