"""Voice of Customer, radar and scenario agents (spec 11 / 20 / 27 / 28).

The Voice of Customer agent is the only place in the platform that reads real
customer words. That makes its output the strongest evidence available - and
makes fabricated quotes the worst thing it could do, so the prompt and the
persistence layer both guard against it.
"""

from __future__ import annotations

import re
from typing import Any

from ..domain.contracts import FeedbackAnalysis, RadarReport, ScenarioAnalysis
from ..domain.enums import EvidenceGrade, SourceType
from ..storage import repositories as repo
from .base import Agent, AnalysisContext

#: How much raw feedback to send in one pass. Large exports are sampled rather
#: than truncated blindly, so the sample spans the whole file.
MAX_FEEDBACK_CHARS = 45_000


def sample_feedback(items: list[dict[str, Any]], max_chars: int = MAX_FEEDBACK_CHARS) -> tuple[str, int]:
    """Render feedback for the prompt, evenly sampling when it will not all fit.

    Returns ``(rendered, count_included)``. Sampling evenly across the list
    matters: taking the first N rows of a review export biases towards whatever
    the export happened to sort by.
    """
    if not items:
        return "", 0

    rendered: list[str] = []
    used = 0
    step = 1
    estimated = sum(len(item["content"]) + 40 for item in items)
    if estimated > max_chars:
        step = max(1, round(estimated / max_chars))

    included = 0
    for index in range(0, len(items), step):
        item = items[index]
        rating = f" [rating {item['rating']}]" if item.get("rating") is not None else ""
        date = f" [{item['occurred_at']}]" if item.get("occurred_at") else ""
        line = f"#{index + 1}{rating}{date}: {item['content']}"
        if used + len(line) > max_chars:
            break
        rendered.append(line)
        used += len(line)
        included += 1

    return "\n".join(rendered), included


class VoiceOfCustomerAgent(Agent[FeedbackAnalysis]):
    """Clusters real customer feedback into themes (spec 11).

    Not part of the standard pipeline - it runs only when the user has supplied
    feedback, and is invoked directly by the service.
    """

    name = "voice_of_customer"
    title = "Voice of customer"
    contract = FeedbackAnalysis
    deep = True
    max_tokens = 10_000

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self._included = 0

    def build_prompt(self, ctx: AnalysisContext) -> str:
        rendered, included = sample_feedback(self._items)
        self._included = included
        total = len(self._items)

        sampling_note = ""
        if included < total:
            sampling_note = (
                f"\nNOTE: {total} items were supplied; {included} are shown here, "
                "sampled evenly across the whole set. Base percentages on what you "
                "can see and say so in caveats.\n"
            )

        return (
            f"{ctx.product_context()}\n"
            f"You are analysing {total} pieces of real customer feedback about this "
            f"product.{sampling_note}\n"
            f"FEEDBACK:\n{rendered}\n\n"
            "Cluster this feedback into recurring themes.\n\n"
            "Rules that matter:\n"
            "- Every quote in representative_quotes must be a VERBATIM excerpt from "
            "the feedback above. Copy the words exactly. Never invent, paraphrase or "
            "'clean up' a quote - a fabricated customer quote is the single most "
            "damaging thing you could produce here.\n"
            "- share_of_feedback must reflect the actual proportion you observe. The "
            "shares should roughly total 100 across clusters.\n"
            "- customer_language should capture the words customers actually use, "
            "which is what marketing copy should echo back.\n"
            "- Mark is_churn_driver only where customers signal leaving, not merely "
            "annoyance.\n"
            "- Report praise as well as complaints. A theme list that is all "
            "negative is usually a reading failure, not a product failure.\n"
            "- In caveats, be honest about sample size and any obvious bias."
        )

    def persist(self, ctx: AnalysisContext, result: FeedbackAnalysis) -> None:
        from ..storage import voc_repo

        verified = self._verify_quotes(result)
        analysis_id = voc_repo.save_feedback_analysis(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            product_id=ctx.product["id"],
            analysis_id=ctx.analysis_id,
            data=verified,
        )

        # Customer feedback is user-supplied evidence, which is the strongest
        # grade available short of a retrieved source.
        for cluster in verified["clusters"][:12]:
            repo.record_evidence(
                ctx.conn,
                workspace_id=ctx.workspace_id,
                analysis_id=ctx.analysis_id,
                claim=f"Customers report: {cluster['label']}",
                detail=cluster["summary"],
                grade=EvidenceGrade.USER_SUPPLIED.value,
                confidence=cluster["confidence"],
                agent=self.name,
                subject_type="customer_feedback",
                subject_id=analysis_id,
                citations=[
                    {
                        "url": None,
                        "title": f"Customer feedback ({cluster['item_count']} items)",
                        "source_type": SourceType.USER_UPLOAD.value,
                        "published_date": None,
                    }
                ],
            )
        ctx.conn.commit()

    def _verify_quotes(self, result: FeedbackAnalysis) -> dict[str, Any]:
        """Drop any quote that does not appear in the supplied feedback.

        The prompt forbids invented quotes; this enforces it. A quote the user
        cannot find in their own data destroys trust in everything else.
        """
        corpus = " ".join(_normalise(item["content"]) for item in self._items)
        payload = result.model_dump(mode="json")
        dropped = 0

        for cluster in payload["clusters"]:
            kept = []
            for quote in cluster.get("representative_quotes", []):
                normalised = _normalise(quote)
                # Short fragments match too easily to be meaningful evidence.
                if len(normalised) >= 12 and normalised in corpus:
                    kept.append(quote)
                else:
                    dropped += 1
            cluster["representative_quotes"] = kept

        if dropped:
            payload.setdefault("caveats", []).append(
                f"{dropped} quote(s) could not be matched against the supplied "
                "feedback and were removed."
            )
        payload["quotes_dropped"] = dropped
        return payload


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


class RadarAgent(Agent[RadarReport]):
    """Ranks opportunities and threats across every axis (spec 27 / 28)."""

    name = "radar"
    title = "Opportunity & threat radar"
    contract = RadarReport
    deep = True
    max_tokens = 9000
    requires = (
        "scoring",
        "gap_analysis",
        "competitive_intelligence",
        "market_analyst",
    )

    def build_prompt(self, ctx: AnalysisContext) -> str:
        conn, analysis_id = ctx.conn, ctx.analysis_id

        competitors = repo.list_competitors(conn, analysis_id)
        competitor_block = "\n".join(
            f"- {c['name']} ({c['competitor_type']}, threat {c['threat_level']}): "
            f"{c['positioning']} | weaknesses: {', '.join(c['weaknesses'][:3]) or 'unknown'}"
            for c in competitors[:12]
        ) or "No competitors identified."

        market = repo.get_market(conn, analysis_id)
        market_block = ""
        if market:
            market_block = (
                f"Market: {market['market_definition']} "
                f"(maturity {market['maturity']}, {market['competitive_concentration']})\n"
                f"Entry barriers: {', '.join(market['entry_barriers'][:6])}\n"
            )

        scores = repo.get_scores(conn, analysis_id)
        weak = sorted(scores, key=lambda s: s["score"])[:5]
        weak_block = "\n".join(
            f"- {s['dimension']}: {s['score']:.0f}/100 - {s['explanation'][:120]}"
            for s in weak
        ) or "No scores available."

        recommendations = repo.list_recommendations(conn, analysis_id)
        gaps = "\n".join(f"- {r['title']}: {r['problem'][:100]}" for r in recommendations[:10])

        changes = repo.list_changes(conn, ctx.product["id"], limit=10)
        change_block = "\n".join(
            f"- {c['summary']} (severity {c['severity']}, {c['detected_at'][:10]})"
            for c in changes
        ) or "No competitor changes detected."

        from ..storage import voc_repo

        feedback = voc_repo.latest_feedback_analysis(conn, ctx.product["id"])
        feedback_block = "No customer feedback has been analysed."
        if feedback:
            feedback_block = "Customer themes: " + "; ".join(
                f"{c['label']} ({c['share_pct']:.0f}%)" for c in feedback["clusters"][:8]
            )

        return (
            f"{ctx.product_context()}\n"
            f"{market_block}\n"
            f"COMPETITORS:\n{competitor_block}\n\n"
            f"WEAKEST SCORES:\n{weak_block}\n\n"
            f"IDENTIFIED GAPS:\n{gaps}\n\n"
            f"RECENT COMPETITOR CHANGES:\n{change_block}\n\n"
            f"{feedback_block}\n\n"
            "Build an opportunity and threat radar.\n\n"
            "For OPPORTUNITIES, look across: unmet customer pain, competitor "
            "weakness, market trends, product gaps, new technology, pricing gaps, "
            "geographic expansion, integrations, partnerships, underserved segments, "
            "distribution, and regulatory change.\n\n"
            "For THREATS, look across: competitors, market shifts, technology "
            "disruption, pricing pressure, regulation, churn signals, new entrants, "
            "substitutes, platform dependencies, security and reputation.\n\n"
            "Score impact and probability independently and honestly - a "
            "catastrophic but unlikely threat is not the same as a moderate but "
            "certain one, and the radar must let the reader tell them apart. "
            "`why_now` must explain what makes this current; if it is a perennial "
            "truth rather than a live signal, leave it out."
        )

    def persist(self, ctx: AnalysisContext, result: RadarReport) -> None:
        from ..storage import voc_repo

        voc_repo.save_radar(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            analysis_id=ctx.analysis_id,
            product_id=ctx.product["id"],
            signals=[s.model_dump(mode="json") for s in result.opportunities]
            + [s.model_dump(mode="json") for s in result.threats],
        )


class ScenarioAgent(Agent[ScenarioAnalysis]):
    """Answers open-ended what-if questions (spec 20)."""

    name = "scenario"
    title = "Scenario analysis"
    contract = ScenarioAnalysis
    deep = True
    max_tokens = 7000

    def __init__(self, question: str) -> None:
        self._question = question

    def build_prompt(self, ctx: AnalysisContext) -> str:
        conn, analysis_id = ctx.conn, ctx.analysis_id

        profile = repo.get_product_profile(conn, analysis_id)
        pricing = repo.get_pricing(conn, analysis_id)
        competitors = repo.list_competitors(conn, analysis_id)

        pricing_block = ""
        if pricing:
            economics = pricing.get("economics", {})
            pricing_block = (
                f"Pricing model: {pricing['recommended_model']} | "
                f"ARPU est ${economics.get('arpu_monthly_usd', 0):,.0f}/mo | "
                f"churn est {economics.get('monthly_churn_pct', 0)}%/mo | "
                f"CAC est ${economics.get('cac_usd', 0):,.0f} | "
                f"elasticity est {economics.get('price_elasticity', -1)}\n"
            )

        return (
            f"{ctx.product_context()}\n"
            f"Summary: {(profile or {}).get('summary', 'unknown')}\n"
            f"{pricing_block}"
            f"Competitors: {', '.join(c['name'] for c in competitors[:10]) or 'none identified'}\n\n"
            f"SCENARIO TO MODEL:\n{self._question}\n\n"
            "Model this scenario across best, base and worst cases.\n\n"
            "Requirements:\n"
            "- List every assumption the projection depends on. If the scenario is "
            "underspecified, state the interpretation you adopted.\n"
            "- Probabilities across the three cases should total roughly 100.\n"
            "- Leading indicators must be things the team could actually observe "
            "within weeks, not lagging outcomes.\n"
            "- Say plainly how reversible this decision is. A cheap reversible "
            "experiment deserves different advice from a one-way door.\n"
            "- These are projections under assumptions, not predictions. Keep "
            "confidence honest; for a novel scenario with thin data, that is low."
        )

    def persist(self, ctx: AnalysisContext, result: ScenarioAnalysis) -> None:
        from ..storage import voc_repo

        voc_repo.save_scenario(
            ctx.conn,
            workspace_id=ctx.workspace_id,
            product_id=ctx.product["id"],
            analysis_id=ctx.analysis_id,
            data=result.model_dump(mode="json"),
        )
