"""Ask Product Analysis Studio (spec 25).

A question-answering layer over everything the platform knows about one product.
Two properties matter:

1. **It answers from stored intelligence, not model priors.** Context is
   assembled from the database and the model is told to say so when the answer
   is not in there.
2. **Citations are verified after the fact.** The model returns the evidence IDs
   it used; those are resolved against the database and any ID that does not
   exist is dropped. A fabricated citation therefore cannot reach the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..ai.provider import LLMProvider
from ..config import AppConfig
from ..domain.contracts import CitedAnswer
from ..domain.enums import ScoreDimension
from ..storage import repositories as repo

#: Words too common to discriminate between evidence records.
_STOPWORDS = frozenset(
    """the a an and or but of to in for on with is are was were be been am i my we our you your
    it its this that these those what which who whom how why when where should would could can
    do does did have has had will shall me us them they he she at by from as if then than so
    about into over under again more most other some such no nor not only own same too very""".split()
)


def _tokenise(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


@dataclass
class RetrievedContext:
    """Everything assembled for one question."""

    evidence: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n\n".join(self.blocks) if self.blocks else "No intelligence is available."


@dataclass
class Answer:
    text: str
    confidence: float
    caveats: list[str]
    citations: list[dict[str, Any]]
    followups: list[str]
    dropped_citations: int = 0


def score_evidence(question: str, item: dict[str, Any]) -> float:
    """Rank an evidence record against the question.

    Keyword overlap weighted by the record's own confidence and grade. Semantic
    embeddings would rank better, but this keeps retrieval dependency-free and
    is adequate over the few hundred records one analysis produces.
    """
    question_terms = _tokenise(question)
    if not question_terms:
        return 0.0

    haystack = _tokenise(f"{item.get('claim', '')} {item.get('detail', '')}")
    overlap = len(question_terms & haystack)
    if overlap == 0:
        return 0.0

    base = overlap / len(question_terms)
    grade_weight = {
        "verified_fact": 1.3,
        "strong_inference": 1.15,
        "user_supplied": 1.2,
        "weak_inference": 0.9,
        "ai_hypothesis": 0.8,
    }.get(item.get("grade", ""), 1.0)
    return base * grade_weight * (0.5 + float(item.get("confidence", 0.5)))


class AskEngine:
    """Assembles context, asks the model, and verifies the citations."""

    def __init__(self, conn, *, config: AppConfig, provider: LLMProvider, workspace_id: str):
        self._conn = conn
        self._config = config
        self._provider = provider
        self._workspace_id = workspace_id

    # -- retrieval ---------------------------------------------------------

    def build_context(
        self, product: dict[str, Any], analysis_id: str, question: str, max_evidence: int = 24
    ) -> RetrievedContext:
        conn = self._conn
        context = RetrievedContext()

        context.blocks.append(
            f"PRODUCT: {product['name']}\n"
            f"{product.get('one_liner', '')}\n"
            f"Category: {product.get('category')} | Industry: {product.get('industry')} | "
            f"Model: {product.get('business_model')} | Maturity: {product.get('maturity')}"
        )

        profile = repo.get_product_profile(conn, analysis_id)
        if profile:
            lists = profile.get("lists", {})
            context.blocks.append(
                f"PRODUCT PROFILE\n{profile['summary']}\n"
                f"Primary problem: {profile['primary_problem']}\n"
                f"Capabilities: {', '.join(lists.get('core_capabilities', [])[:15])}\n"
                f"Pricing model: {profile['pricing_model']} | "
                f"Defensibility: {profile['defensibility']}"
            )

        scores = repo.get_scores(conn, analysis_id)
        if scores:
            from ..agents.analysts import composite_score

            composite = composite_score(scores)
            lines = "\n".join(
                f"- {ScoreDimension(s['dimension']).label}: {s['score']:.0f}/100 "
                f"({s['confidence']:.0%} confidence) - {s['explanation'][:160]}"
                for s in scores
            )
            context.blocks.append(
                f"SCORES (composite {composite['score']:.0f}/100)\n{lines}"
            )

        competitors = repo.list_competitors(conn, analysis_id)
        if competitors:
            lines = "\n".join(
                f"- {c['name']} ({c['competitor_type']}, threat {c['threat_level']}): "
                f"{c['positioning']} | pricing: {c['pricing_summary']} | "
                f"strengths: {', '.join(c['strengths'][:3])}"
                for c in competitors[:15]
            )
            context.blocks.append(f"COMPETITORS\n{lines}")

        market = repo.get_market(conn, analysis_id)
        if market:
            sizing = "; ".join(
                f"{m['label']} ${m['value_usd']:,.0f} ({m['confidence']:.0%})"
                for m in market["sizing"]
            )
            context.blocks.append(
                f"MARKET\n{market['market_definition']}\n"
                f"Maturity: {market['maturity']} | "
                f"Concentration: {market['competitive_concentration']}\nSizing: {sizing}"
            )

        customers = repo.get_customers(conn, analysis_id)
        if customers:
            personas = "; ".join(p["name"] for p in customers["personas"][:8])
            context.blocks.append(f"CUSTOMERS\nICP: {customers['icp']}\nPersonas: {personas}")

        recommendations = repo.list_recommendations(conn, analysis_id)
        if recommendations:
            lines = "\n".join(
                f"- [{r['verdict'].upper()}] [{r['decision_state']}] {r['title']}: "
                f"{r['reason'][:150]}"
                for r in recommendations[:20]
            )
            context.blocks.append(f"RECOMMENDATIONS\n{lines}")

        for label, getter in (
            ("POSITIONING", repo.get_positioning),
            ("PRICING", repo.get_pricing),
            ("GROWTH", repo.get_growth),
            ("GO-TO-MARKET", repo.get_gtm),
        ):
            block = self._strategy_block(label, getter(conn, analysis_id))
            if block:
                context.blocks.append(block)

        changes = repo.list_changes(conn, product["id"], limit=15)
        if changes:
            lines = "\n".join(
                f"- [{c['detected_at'][:10]}] {c['summary']} (severity {c['severity']})"
                for c in changes
            )
            context.blocks.append(f"RECENT COMPETITOR CHANGES\n{lines}")

        # Evidence is ranked against the question rather than dumped wholesale.
        all_evidence = repo.list_evidence(conn, analysis_id, limit=400)
        ranked = sorted(
            ((score_evidence(question, item), item) for item in all_evidence),
            key=lambda pair: pair[0],
            reverse=True,
        )
        selected = [item for score, item in ranked if score > 0][:max_evidence]
        if not selected:
            # Nothing matched the wording; fall back to the strongest evidence.
            selected = sorted(
                all_evidence,
                key=lambda e: (e["grade"] == "verified_fact", e["confidence"]),
                reverse=True,
            )[:12]

        context.evidence = selected
        if selected:
            lines = "\n".join(
                f"[{item['id']}] ({item['grade']}, {item['confidence']:.0%}) {item['claim']}"
                + (
                    f"  SOURCES: {', '.join(c['url'] for c in item['citations'] if c.get('url'))}"
                    if item.get("citations")
                    else ""
                )
                for item in selected
            )
            context.blocks.append(
                "EVIDENCE LEDGER (cite these IDs in used_evidence_ids)\n" + lines
            )

        return context

    @staticmethod
    def _strategy_block(label: str, data: dict[str, Any] | None) -> str:
        if not data:
            return ""
        if label == "POSITIONING":
            messaging = data.get("messaging", {})
            return (
                f"POSITIONING\nRecommended: {data['recommended_strategy']}\n"
                f"Statement: {messaging.get('positioning_statement', '')}\n"
                f"UVP: {messaging.get('unique_value_proposition', '')}"
            )
        if label == "PRICING":
            from .reports import format_price

            tiers = "; ".join(
                f"{t['name']} {format_price(t['price_monthly_usd'], '/mo')}"
                for t in data.get("tiers", [])
            )
            return (
                f"PRICING\nModel: {data['recommended_model']} | "
                f"Value metric: {data['value_metric']}\nTiers: {tiers}"
            )
        if label == "GROWTH":
            channels = "; ".join(
                f"{c['channel']} (fit {c['fit_score']:.0f})" for c in data.get("channels", [])[:8]
            )
            return f"GROWTH\nMotion: {data['primary_motion']}\nChannels: {channels}"
        phases = "; ".join(p["horizon"] for p in data.get("phases", []))
        return (
            f"GO-TO-MARKET\nSegment: {data['target_segment']}\n"
            f"Launch: {data['launch_strategy'][:200]}\nPhases: {phases}"
        )

    # -- answering ---------------------------------------------------------

    def ask(
        self,
        product: dict[str, Any],
        analysis_id: str,
        question: str,
        *,
        mode: str = "founder",
    ) -> Answer:
        context = self.build_context(product, analysis_id, question)

        system = (
            "You answer questions about a product using ONLY the intelligence "
            "provided below.\n\n"
            "Rules:\n"
            "1. If the answer is not in the provided intelligence, say so plainly. "
            "Do not fill the gap from general knowledge.\n"
            "2. Cite the evidence IDs you actually relied on in used_evidence_ids. "
            "Use the exact IDs shown in square brackets. Never invent an ID.\n"
            "3. Distinguish what is verified from what the platform inferred. Much "
            "of this intelligence is AI-inferred; do not present it as established fact.\n"
            "4. Answer the question directly first, then explain.\n"
            "5. Be specific and decision-useful. No consulting filler.\n"
            f"6. The reader is operating in {mode.replace('_', ' ')} mode."
        )
        user = f"INTELLIGENCE AVAILABLE:\n\n{context.render()}\n\nQUESTION: {question}"

        completion = self._provider.complete_structured(
            model=self._config.deep_model,
            system=system,
            user=user,
            schema=CitedAnswer,
            max_tokens=4000,
        )
        result: CitedAnswer = completion.data

        usage = completion.usage
        repo.record_usage(
            self._conn,
            workspace_id=self._workspace_id,
            analysis_id=analysis_id,
            agent_run_id=None,
            provider=usage.provider,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
        )

        citations, dropped = self._verify_citations(result.used_evidence_ids, context)
        return Answer(
            text=result.answer,
            confidence=result.confidence,
            caveats=result.caveats,
            citations=citations,
            followups=result.followup_questions,
            dropped_citations=dropped,
        )

    @staticmethod
    def _verify_citations(
        claimed_ids: list[str], context: RetrievedContext
    ) -> tuple[list[dict[str, Any]], int]:
        """Resolve claimed evidence IDs against what was actually retrieved.

        Anything the model cites that was not in its context is discarded - this
        is the guard against fabricated citations reaching the user.
        """
        available = {item["id"]: item for item in context.evidence}
        resolved: list[dict[str, Any]] = []
        dropped = 0

        for evidence_id in claimed_ids:
            item = available.get(evidence_id.strip())
            if item is None:
                dropped += 1
                continue
            resolved.append(
                {
                    "id": item["id"],
                    "claim": item["claim"],
                    "grade": item["grade"],
                    "confidence": item["confidence"],
                    "sources": [
                        {"url": c.get("url"), "title": c.get("title")}
                        for c in item.get("citations", [])
                    ],
                }
            )
        return resolved, dropped


SUGGESTED_QUESTIONS = [
    "Who is my biggest competitor, and why?",
    "What should I build next?",
    "What should I stop building?",
    "Is my pricing competitive?",
    "What are my top five risks?",
    "What is my biggest opportunity?",
    "Which market segment should I target first?",
    "What would make this fail?",
    "Create a board summary.",
    "How should I spend a $50,000 marketing budget?",
]
