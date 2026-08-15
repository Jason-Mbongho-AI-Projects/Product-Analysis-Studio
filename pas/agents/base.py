"""Agent framework (spec 23/24).

An agent is a narrow, named, observable unit of analysis: it receives a typed
context, returns a validated contract, and records its own run and cost. There
is no single mega-prompt anywhere in this codebase.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel

from ..ai.provider import Completion, LLMProvider, ProviderError
from ..config import MAX_LLM_CALLS_PER_ANALYSIS, AppConfig
from ..domain.enums import AgentRunStatus
from ..storage import repositories as repo

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    """The analysis hit its configured model-call ceiling (spec 38)."""


@dataclass
class ResearchBundle:
    """Source material gathered before the analysis agents run."""

    pages: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return bool(self.pages)

    def as_prompt_context(self, max_chars: int = 24000) -> str:
        """Render fetched pages for prompt injection, budgeted by size."""
        if not self.pages:
            return (
                "NO SOURCE MATERIAL WAS RETRIEVED.\n"
                "You have no retrieved evidence. Every claim you make must be graded "
                "'ai_hypothesis' with an honest confidence, and citations must be empty. "
                "Do not invent URLs, company facts, or statistics."
            )

        budget = max_chars // max(len(self.pages), 1)
        blocks = ["RETRIEVED SOURCE MATERIAL (cite these URLs exactly as given):"]
        for index, page in enumerate(self.pages, start=1):
            body = (page.get("text") or "")[:budget]
            blocks.append(
                f"\n--- SOURCE {index} ---\n"
                f"URL: {page.get('url')}\n"
                f"TITLE: {page.get('title')}\n"
                f"TYPE: {page.get('source_type')}\n"
                f"CONTENT:\n{body}"
            )
        blocks.append(
            "\n--- END OF SOURCE MATERIAL ---\n"
            "Claims directly supported by the text above may be graded "
            "'verified_fact' with that URL cited. Everything else is inference or "
            "hypothesis. Never cite a URL that does not appear above."
        )
        return "\n".join(blocks)


@dataclass
class AnalysisContext:
    """Everything an agent may read, and where its output is written."""

    conn: Any
    config: AppConfig
    provider: LLMProvider
    workspace_id: str
    analysis_id: str
    product: dict[str, Any]
    mode: str = "founder"
    research: ResearchBundle = field(default_factory=ResearchBundle)
    results: dict[str, BaseModel] = field(default_factory=dict)
    memory: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    emit: Callable[[str, str, dict[str, Any]], None] | None = None

    def notify(self, event: str, message: str, **payload: Any) -> None:
        if self.emit:
            self.emit(event, message, payload)

    def charge_call(self) -> None:
        if self.llm_calls >= MAX_LLM_CALLS_PER_ANALYSIS:
            raise BudgetExceeded(
                f"Analysis reached its ceiling of {MAX_LLM_CALLS_PER_ANALYSIS} model calls."
            )
        self.llm_calls += 1

    def memory_context(self) -> str:
        """Prior decisions the agent must respect (spec 22)."""
        if not self.memory:
            return ""
        lines = ["PRIOR STRATEGIC DECISIONS ON THIS PRODUCT:"]
        for item in self.memory[:25]:
            lines.append(f"- [{item['kind']}] {item['summary']}: {item.get('detail', '')}")
        lines.append(
            "Do not re-recommend anything already rejected unless you have NEW evidence "
            "that changes the situation - and if you do, say explicitly what changed."
        )
        return "\n".join(lines)

    def product_context(self) -> str:
        product = self.product
        return (
            f"PRODUCT UNDER ANALYSIS\n"
            f"Name: {product.get('name')}\n"
            f"Summary: {product.get('one_liner')}\n"
            f"Category: {product.get('category')} / {product.get('subcategory')}\n"
            f"Industry: {product.get('industry')}\n"
            f"Business model: {product.get('business_model')} | "
            f"Segment: {product.get('market_segment')} | "
            f"Maturity: {product.get('maturity')}\n"
            f"Original user input: {product.get('intake_input')}\n"
        )


#: Shared preamble. Every agent inherits the same epistemic rules so evidence
#: discipline is a property of the platform, not of individual prompts.
EVIDENCE_RULES = """You are part of an evidence-driven product intelligence platform.

Non-negotiable rules:
1. Never invent statistics, market sizes, funding figures, customer counts or URLs.
2. Grade every claim honestly:
   - verified_fact: the retrieved source material directly states it
   - strong_inference: strongly implied by retrieved material
   - weak_inference: plausible but thinly supported
   - ai_hypothesis: your own reasoning with no retrieved support
   - user_supplied: the user asserted it
3. Only cite URLs that appear in the retrieved source material. If none were
   retrieved, return empty citation lists.
4. Confidence is a real 0.0-1.0 estimate. Low confidence is acceptable and
   useful; false certainty is not.
5. Prefer "insufficient evidence" over a confident guess.
6. Be specific and decision-useful. Avoid generic consulting filler."""


class Agent(ABC, Generic[T]):
    """Base class for all analysis agents."""

    #: Stable identifier, recorded on every run and shown in the audit trail.
    name: str = "agent"
    #: Human-readable role for the progress UI.
    title: str = "Agent"
    #: Contract the agent must return.
    contract: type[T]
    #: True when this agent benefits from the stronger model.
    deep: bool = False
    max_tokens: int = 8000

    @abstractmethod
    def build_prompt(self, ctx: AnalysisContext) -> str:
        """Return the user-message body for this agent."""

    def system_prompt(self, ctx: AnalysisContext) -> str:
        return EVIDENCE_RULES

    def should_run(self, ctx: AnalysisContext) -> bool:
        return True

    def model_for(self, ctx: AnalysisContext) -> str:
        return ctx.config.deep_model if self.deep else ctx.config.fast_model

    def persist(self, ctx: AnalysisContext, result: T) -> None:
        """Write agent output to storage. Overridden by most agents."""

    def run(self, ctx: AnalysisContext) -> T | None:
        """Execute the agent with full observability and cost accounting."""
        if not self.should_run(ctx):
            return None

        model = self.model_for(ctx)
        run_id = repo.start_agent_run(ctx.conn, ctx.analysis_id, self.name, model)
        started = time.monotonic()
        ctx.notify("agent_started", f"{self.title} running", agent=self.name)

        try:
            ctx.charge_call()
            completion: Completion = ctx.provider.complete_structured(
                model=model,
                system=self.system_prompt(ctx),
                user=self.build_prompt(ctx),
                schema=self.contract,
                max_tokens=self.max_tokens,
            )
            self._record_usage(ctx, run_id, completion)

            result: T = completion.data
            ctx.results[self.name] = result
            self.persist(ctx, result)

            repo.finish_agent_run(
                ctx.conn,
                run_id,
                status=AgentRunStatus.SUCCEEDED.value,
                duration_ms=int((time.monotonic() - started) * 1000),
                attempts=completion.usage.attempts,
            )
            ctx.notify("agent_finished", f"{self.title} complete", agent=self.name)
            return result

        except (ProviderError, BudgetExceeded) as exc:
            repo.finish_agent_run(
                ctx.conn,
                run_id,
                status=AgentRunStatus.FAILED.value,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(exc)[:1000],
            )
            ctx.notify("agent_failed", f"{self.title} failed: {exc}", agent=self.name)
            # One agent failing must not abort the whole analysis; the
            # orchestrator degrades to a partial result instead.
            return None

    def _record_usage(self, ctx: AnalysisContext, run_id: str, completion: Completion) -> None:
        usage = completion.usage
        repo.record_usage(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            analysis_id=ctx.analysis_id,
            agent_run_id=run_id,
            provider=usage.provider,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
        )


def store_claims(
    ctx: AnalysisContext,
    agent: str,
    claims: list[Any],
    subject_type: str,
    subject_id: str | None = None,
) -> None:
    """Persist a list of EvidencedClaim contracts into the evidence table."""
    for claim in claims:
        repo.record_evidence(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            analysis_id=ctx.analysis_id,
            claim=claim.claim,
            detail=claim.detail,
            grade=claim.grade.value,
            confidence=claim.confidence,
            agent=agent,
            subject_type=subject_type,
            subject_id=subject_id,
            citations=[c.model_dump() for c in claim.citations],
        )
    ctx.conn.commit()
