"""Agent framework, contract and scoring tests.

These use a stub provider rather than the network, so the pipeline's control
flow is verified deterministically and without cost.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pas.agents.analysts import PIPELINE, composite_score
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
]


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
