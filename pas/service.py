"""Application service layer.

The UI calls only into this module. Keeping Streamlit out of the domain (and
domain logic out of Streamlit) is what would let a future API expose the same
capabilities without duplicating logic (spec 57).
"""

from __future__ import annotations

import threading
from typing import Any

from .agents.analysts import composite_score
from .agents.orchestrator import AnalysisOrchestrator, AnalysisRequest
from .config import AppConfig, load_config
from .domain.enums import AnalysisStatus, DecisionState, IntakeKind, RoadmapHorizon
from .jobs.runner import JobState, get_runner
from .research.safety import UnsafeURLError, validate_url
from .storage import repositories as repo
from .storage.db import get_connection, migrate


class StudioService:
    """Facade over storage, research and the agent pipeline."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.conn = get_connection()
        migrate(self.conn)
        self.workspace_id = repo.ensure_default_workspace(self.conn)

    # -- intake ------------------------------------------------------------

    def create_product(
        self,
        *,
        name: str,
        intake_kind: str,
        intake_input: str,
        source_url: str | None = None,
    ) -> str:
        """Create a product from any intake type.

        A supplied URL is validated here, at the boundary, so an unsafe URL is
        rejected before it is ever persisted or fetched.
        """
        name = (name or "").strip()
        intake_input = (intake_input or "").strip()
        if not intake_input:
            raise ValueError("Describe the product or provide a URL to analyse.")

        if source_url:
            source_url = source_url.strip()
            try:
                source_url = validate_url(source_url).url
            except UnsafeURLError as exc:
                raise ValueError(f"That URL cannot be analysed. {exc}") from exc

        if not name:
            name = source_url or intake_input[:60]

        return repo.create_product(
            self.conn,
            workspace_id=self.workspace_id,
            name=name[:120],
            intake_kind=intake_kind,
            intake_input=intake_input[:8000],
            source_url=source_url,
        )

    def list_products(self) -> list[dict[str, Any]]:
        return repo.list_products(self.conn, self.workspace_id)

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        return repo.get_product(self.conn, product_id, self.workspace_id)

    def delete_product(self, product_id: str) -> None:
        repo.delete_product(self.conn, product_id, self.workspace_id)

    # -- analyses ----------------------------------------------------------

    def start_analysis(
        self,
        product_id: str,
        *,
        mode: str = "founder",
        research_enabled: bool = True,
        extra_urls: list[str] | None = None,
    ) -> tuple[str, JobState]:
        """Create an analysis version and run it on a background worker."""
        if not self.config.is_configured:
            raise ValueError(
                "No OPENROUTER_API_KEY configured. Add it to .env and restart."
            )
        product = self.get_product(product_id)
        if product is None:
            raise ValueError("Product not found.")

        safe_urls: list[str] = []
        for url in extra_urls or []:
            if not url.strip():
                continue
            try:
                safe_urls.append(validate_url(url).url)
            except UnsafeURLError as exc:
                raise ValueError(f"Source URL rejected: {exc}") from exc

        analysis = repo.create_analysis(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            mode=mode,
            research_enabled=research_enabled,
        )
        analysis_id = analysis["id"]

        request = AnalysisRequest(
            workspace_id=self.workspace_id,
            product_id=product_id,
            analysis_id=analysis_id,
            mode=mode,
            research_enabled=research_enabled,
            extra_urls=safe_urls,
        )

        def work(emit, cancel_event: threading.Event):
            # A fresh orchestrator per job keeps provider state per-thread.
            orchestrator = AnalysisOrchestrator(config=self.config)
            return orchestrator.run(request, on_progress=emit, cancel_event=cancel_event)

        job = get_runner().submit(analysis_id, analysis_id, work)
        return analysis_id, job

    def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        return repo.get_analysis(self.conn, analysis_id, self.workspace_id)

    def list_analyses(self, product_id: str) -> list[dict[str, Any]]:
        return repo.list_analyses(self.conn, product_id)

    def latest_analysis(self, product_id: str) -> dict[str, Any] | None:
        return repo.latest_analysis(self.conn, product_id)

    def job_for(self, analysis_id: str) -> JobState | None:
        return get_runner().get(analysis_id)

    def cancel_analysis(self, analysis_id: str) -> bool:
        return get_runner().cancel(analysis_id)

    # -- intelligence reads ------------------------------------------------

    def dashboard(self, analysis_id: str) -> dict[str, Any]:
        """Everything the executive view needs, in one call."""
        conn = self.conn
        scores = repo.get_scores(conn, analysis_id)
        return {
            "analysis": repo.get_analysis(conn, analysis_id, self.workspace_id),
            "profile": repo.get_product_profile(conn, analysis_id),
            "scores": scores,
            "composite": composite_score(scores),
            "competitors": repo.list_competitors(conn, analysis_id),
            "market": repo.get_market(conn, analysis_id),
            "customers": repo.get_customers(conn, analysis_id),
            "recommendations": repo.list_recommendations(conn, analysis_id),
            "quality": repo.evidence_quality_summary(conn, analysis_id),
            "sources": repo.list_sources(conn, analysis_id),
            "usage": repo.usage_summary(conn, self.workspace_id, analysis_id),
            "runs": repo.list_agent_runs(conn, analysis_id),
        }

    def evidence(self, analysis_id: str, **filters: Any) -> list[dict[str, Any]]:
        return repo.list_evidence(self.conn, analysis_id, **filters)

    def sources(self, analysis_id: str) -> list[dict[str, Any]]:
        return repo.list_sources(self.conn, analysis_id)

    def disable_source(self, source_id: str) -> None:
        repo.set_source_status(self.conn, source_id, "disabled")

    # -- decisions and roadmap --------------------------------------------

    def decide(self, recommendation_id: str, state: str, note: str = "") -> None:
        if state not in {member.value for member in DecisionState}:
            raise ValueError(f"Unknown decision state: {state}")
        repo.decide_recommendation(self.conn, recommendation_id, state=state, note=note)

    def accept_to_roadmap(
        self, recommendation_id: str, horizon: str = RoadmapHorizon.NEXT.value
    ) -> str:
        """Accept a recommendation and materialise it as a roadmap item (spec 19)."""
        rec = repo.decide_recommendation(
            self.conn, recommendation_id, state=DecisionState.ACCEPTED.value
        )
        if rec is None:
            raise ValueError("Recommendation not found.")
        return repo.add_roadmap_item(
            self.conn,
            workspace_id=rec["workspace_id"],
            product_id=rec["product_id"],
            recommendation_id=recommendation_id,
            title=rec["title"],
            detail=rec["recommendation"],
            horizon=horizon,
            effort=rec["effort"],
        )

    def roadmap(self, product_id: str) -> dict[str, list[dict[str, Any]]]:
        items = repo.list_roadmap(self.conn, product_id)
        grouped: dict[str, list[dict[str, Any]]] = {
            horizon.value: [] for horizon in RoadmapHorizon
        }
        for item in items:
            grouped.setdefault(item["horizon"], []).append(item)
        return grouped

    def move_roadmap_item(self, item_id: str, horizon: str) -> None:
        repo.move_roadmap_item(self.conn, item_id, horizon)

    def delete_roadmap_item(self, item_id: str) -> None:
        repo.delete_roadmap_item(self.conn, item_id)

    def add_roadmap_item(
        self, product_id: str, title: str, detail: str = "", horizon: str = "next"
    ) -> str:
        if not title.strip():
            raise ValueError("A roadmap item needs a title.")
        return repo.add_roadmap_item(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            title=title.strip(),
            detail=detail.strip(),
            horizon=horizon,
        )

    # -- comparison (spec 37) ---------------------------------------------

    def compare_versions(self, product_id: str, older_id: str, newer_id: str) -> dict[str, Any]:
        """Then-vs-now comparison across two analysis versions."""
        conn = self.conn
        older_scores = {s["dimension"]: s for s in repo.get_scores(conn, older_id)}
        newer_scores = {s["dimension"]: s for s in repo.get_scores(conn, newer_id)}

        deltas = []
        for dimension, new in newer_scores.items():
            old = older_scores.get(dimension)
            if old is None:
                continue
            deltas.append(
                {
                    "dimension": dimension,
                    "before": old["score"],
                    "after": new["score"],
                    "delta": round(new["score"] - old["score"], 1),
                    "explanation": new["explanation"],
                }
            )
        deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)

        old_names = {c["name"].lower() for c in repo.list_competitors(conn, older_id)}
        new_competitors = repo.list_competitors(conn, newer_id)

        return {
            "score_deltas": deltas,
            "composite_before": composite_score(list(older_scores.values())),
            "composite_after": composite_score(list(newer_scores.values())),
            "new_competitors": [
                c for c in new_competitors if c["name"].lower() not in old_names
            ],
        }

    # -- diagnostics (spec 51) --------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        conn = self.conn
        usage = repo.usage_summary(conn, self.workspace_id)
        failed_runs = conn.execute(
            "SELECT COUNT(*) AS n FROM agent_runs WHERE status = 'failed'"
        ).fetchone()["n"]
        failed_sources = conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE status IN ('failed', 'blocked')"
        ).fetchone()["n"]
        return {
            "provider_configured": self.config.is_configured,
            "fast_model": self.config.fast_model,
            "deep_model": self.config.deep_model,
            "database": str(self.config.db_path),
            "usage": usage,
            "failed_agent_runs": failed_runs,
            "failed_sources": failed_sources,
            "active_jobs": len(get_runner().active_jobs()),
        }
