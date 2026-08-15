"""Application service layer.

The UI calls only into this module. Keeping Streamlit out of the domain (and
domain logic out of Streamlit) is what would let a future API expose the same
capabilities without duplicating logic (spec 57).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from .agents.analysts import composite_score
from .agents.orchestrator import AnalysisOrchestrator, AnalysisRequest
from .config import AppConfig, load_config
from .domain.enums import (
    AlertStatus,
    AnalysisStatus,
    DecisionState,
    IntakeKind,
    RoadmapHorizon,
)
from .jobs.runner import JobState, get_runner
from .research.safety import UnsafeURLError, validate_url
from .storage import repositories as repo
from .storage.db import get_connection, migrate

from .auth.models import Permission

if TYPE_CHECKING:  # imported lazily at runtime to keep UI startup fast
    from .analysis.ask import Answer
    from .analysis.finance import Economics
    from .analysis.reports import Report
    from .auth.models import Identity


class StudioService:
    """Facade over storage, research and the agent pipeline."""

    def __init__(
        self,
        config: AppConfig | None = None,
        identity: "Identity | None" = None,
    ) -> None:
        self.config = config or load_config()
        self.conn = get_connection()
        migrate(self.conn)
        self.workspace_id = repo.ensure_default_workspace(self.conn)
        self._llm = None

        from .auth.models import Role
        from .auth.service import AuthService

        try:
            default_role = Role(self.config.default_role)
        except ValueError:
            default_role = Role.VIEWER
        self.auth = AuthService(self.conn, default_role=default_role)

        # When authentication is disabled the identity is the development user,
        # which holds every permission. The authorisation code path still runs,
        # so enabling auth later does not switch on untested code.
        self.identity = identity or self.auth.open_identity(self.workspace_id)
        self.workspace_id = self.identity.workspace_id

    # -- authorisation -----------------------------------------------------

    def require(self, permission: "Permission") -> None:
        """Assert the current identity may perform an action."""
        self.identity.require(permission)

    def can(self, permission: "Permission") -> bool:
        return self.identity.can(permission)

    def _audit(
        self, action: str, *, target_type: str = "", target_id: str | None = None,
        detail: str = "",
    ) -> None:
        self.auth.audit(
            workspace_id=self.workspace_id,
            identity=self.identity,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )

    def _provider(self):
        """Lazily construct the model provider for foreground work.

        Background jobs build their own so provider state stays per-thread.
        """
        if self._llm is None:
            from .ai.provider import OpenRouterProvider

            self._llm = OpenRouterProvider(self.config)
        return self._llm

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
        self.require(Permission.CREATE_PRODUCT)
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

        product_id = repo.create_product(
            self.conn,
            workspace_id=self.workspace_id,
            name=name[:120],
            intake_kind=intake_kind,
            intake_input=intake_input[:8000],
            source_url=source_url,
        )
        self._audit("product.created", target_type="product", target_id=product_id,
                    detail=name[:120])
        return product_id

    def list_products(self) -> list[dict[str, Any]]:
        self.require(Permission.VIEW)
        return repo.list_products(self.conn, self.workspace_id)

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        return repo.get_product(self.conn, product_id, self.workspace_id)

    def delete_product(self, product_id: str) -> None:
        self.require(Permission.DELETE_PRODUCT)
        product = self.get_product(product_id)
        repo.delete_product(self.conn, product_id, self.workspace_id)
        self._audit("product.deleted", target_type="product", target_id=product_id,
                    detail=(product or {}).get("name", ""))

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
        self.require(Permission.RUN_ANALYSIS)
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
        self._audit("analysis.started", target_type="analysis", target_id=analysis_id,
                    detail=f"mode={mode} research={research_enabled}")
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
        self.require(Permission.RUN_ANALYSIS)
        self._audit("analysis.cancelled", target_type="analysis", target_id=analysis_id)
        return get_runner().cancel(analysis_id)

    # -- intelligence reads ------------------------------------------------

    def dashboard(self, analysis_id: str) -> dict[str, Any]:
        """Everything the executive view needs, in one call."""
        self.require(Permission.VIEW)
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
            "positioning": repo.get_positioning(conn, analysis_id),
            "pricing": repo.get_pricing(conn, analysis_id),
            "growth": repo.get_growth(conn, analysis_id),
            "gtm": repo.get_gtm(conn, analysis_id),
            "quality": repo.evidence_quality_summary(conn, analysis_id),
            "sources": repo.list_sources(conn, analysis_id),
            "usage": repo.usage_summary(conn, self.workspace_id, analysis_id),
            "runs": repo.list_agent_runs(conn, analysis_id),
            "radar": self.radar(analysis_id),
        }

    def evidence(self, analysis_id: str, **filters: Any) -> list[dict[str, Any]]:
        return repo.list_evidence(self.conn, analysis_id, **filters)

    def sources(self, analysis_id: str) -> list[dict[str, Any]]:
        return repo.list_sources(self.conn, analysis_id)

    def disable_source(self, source_id: str) -> None:
        self.require(Permission.MANAGE_SOURCES)
        repo.set_source_status(self.conn, source_id, "disabled")
        self._audit("source.disabled", target_type="source", target_id=source_id)

    # -- decisions and roadmap --------------------------------------------

    def decide(self, recommendation_id: str, state: str, note: str = "") -> None:
        self.require(Permission.DECIDE)
        if state not in {member.value for member in DecisionState}:
            raise ValueError(f"Unknown decision state: {state}")
        repo.decide_recommendation(self.conn, recommendation_id, state=state, note=note)
        self._audit(f"recommendation.{state}", target_type="recommendation",
                    target_id=recommendation_id, detail=note)

    def accept_to_roadmap(
        self, recommendation_id: str, horizon: str = RoadmapHorizon.NEXT.value
    ) -> str:
        """Accept a recommendation and materialise it as a roadmap item (spec 19)."""
        self.require(Permission.DECIDE)
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
        self.require(Permission.MANAGE_ROADMAP)
        repo.move_roadmap_item(self.conn, item_id, horizon)

    def delete_roadmap_item(self, item_id: str) -> None:
        self.require(Permission.MANAGE_ROADMAP)
        repo.delete_roadmap_item(self.conn, item_id)

    def add_roadmap_item(
        self, product_id: str, title: str, detail: str = "", horizon: str = "next"
    ) -> str:
        self.require(Permission.MANAGE_ROADMAP)
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

    # -- pricing simulation (spec 15 / 20) --------------------------------

    def economics_for(self, analysis_id: str, customers: int = 100) -> "Economics":
        """Seed the simulator from the pricing agent's estimates.

        Falls back to neutral placeholder assumptions when no pricing analysis
        exists, so the simulator is always usable and the UI can say which is
        which.
        """
        from .analysis.finance import Economics

        pricing = repo.get_pricing(self.conn, analysis_id) if analysis_id else None
        economics = (pricing or {}).get("economics", {})
        return Economics(
            arpu_monthly=float(economics.get("arpu_monthly_usd", 100) or 100),
            gross_margin_pct=float(economics.get("gross_margin_pct", 75) or 75),
            cac=float(economics.get("cac_usd", 500) or 500),
            monthly_churn_pct=float(economics.get("monthly_churn_pct", 4) or 4),
            monthly_expansion_pct=float(economics.get("monthly_expansion_pct", 0) or 0),
            customers=customers,
        )

    def simulate(
        self,
        economics: "Economics",
        *,
        elasticity: float = -1.0,
        fixed_costs: float = 0.0,
        new_customers_per_month: float = 0.0,
        months: int = 24,
    ) -> dict[str, Any]:
        """Run the deterministic pricing and growth simulation."""
        from .analysis import finance

        curve = finance.price_sensitivity_curve(economics, elasticity)
        return {
            "unit_economics": finance.unit_economics(economics),
            "curve": curve,
            "optimum": finance.revenue_maximising_change(curve),
            "break_even": finance.break_even(
                economics, fixed_costs, new_customers_per_month
            ),
            "projection": finance.project(
                economics, months, new_customers_per_month, fixed_costs
            ),
        }

    def save_scenario(
        self, product_id: str, analysis_id: str | None, label: str, inputs: dict, results: dict
    ) -> str:
        return repo.save_scenario(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            analysis_id=analysis_id,
            label=label or "Untitled scenario",
            inputs=inputs,
            results=results,
        )

    def list_scenarios(self, product_id: str) -> list[dict[str, Any]]:
        return repo.list_scenarios(self.conn, product_id)

    def delete_scenario(self, scenario_id: str) -> None:
        repo.delete_scenario(self.conn, scenario_id)

    # -- Ask (spec 25) -----------------------------------------------------

    def ask(self, product_id: str, analysis_id: str, question: str) -> "Answer":
        """Answer a question from stored intelligence, with verified citations."""
        self.require(Permission.ASK)
        question = (question or "").strip()
        if not question:
            raise ValueError("Ask a question first.")
        if len(question) > 2000:
            raise ValueError("That question is too long.")
        if not self.config.is_configured:
            raise ValueError("No OPENROUTER_API_KEY configured.")

        product = self.get_product(product_id)
        if product is None:
            raise ValueError("Product not found.")
        analysis = self.get_analysis(analysis_id) if analysis_id else None
        if analysis is None:
            raise ValueError("Run an analysis before asking questions about it.")

        from .analysis.ask import AskEngine

        engine = AskEngine(
            self.conn,
            config=self.config,
            provider=self._provider(),
            workspace_id=self.workspace_id,
        )
        answer = engine.ask(product, analysis_id, question, mode=analysis.get("mode", "founder"))

        repo.save_conversation(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            analysis_id=analysis_id,
            question=question,
            answer=answer.text,
            confidence=answer.confidence,
            caveats=answer.caveats,
            citations=answer.citations,
        )
        return answer

    def conversations(self, product_id: str) -> list[dict[str, Any]]:
        return repo.list_conversations(self.conn, product_id)

    # -- monitoring and alerts (spec 8 / 33 / 34) -------------------------

    def create_monitor(
        self, product_id: str, label: str, urls: list[str], interval_hours: int = 168
    ) -> str:
        self.require(Permission.MANAGE_MONITORS)
        safe_urls: list[str] = []
        for url in urls:
            if not url.strip():
                continue
            try:
                safe_urls.append(validate_url(url).url)
            except UnsafeURLError as exc:
                raise ValueError(f"Cannot monitor that URL: {exc}") from exc
        if not safe_urls:
            raise ValueError("Add at least one URL to monitor.")

        return repo.create_monitor(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            label=label.strip() or "Untitled monitor",
            urls=safe_urls,
            interval_hours=max(1, int(interval_hours)),
        )

    def monitors(self, product_id: str) -> list[dict[str, Any]]:
        return repo.list_monitors(self.conn, product_id)

    def set_monitor_enabled(self, monitor_id: str, enabled: bool) -> None:
        self.require(Permission.MANAGE_MONITORS)
        repo.set_monitor_enabled(self.conn, monitor_id, enabled)

    def delete_monitor(self, monitor_id: str) -> None:
        self.require(Permission.MANAGE_MONITORS)
        repo.delete_monitor(self.conn, monitor_id)

    def run_monitor(self, monitor_id: str) -> tuple[str, JobState]:
        """Run a monitor in the background; results land in the alert centre."""
        self.require(Permission.MANAGE_MONITORS)
        if not self.config.is_configured:
            raise ValueError("No OPENROUTER_API_KEY configured.")
        monitor = repo.get_monitor(self.conn, monitor_id)
        if monitor is None:
            raise ValueError("Monitor not found.")

        config, workspace_id = self.config, self.workspace_id

        def work(emit, cancel_event: threading.Event):
            from .analysis.monitoring import ChangeDetector
            from .ai.provider import OpenRouterProvider
            from .storage.db import get_connection

            conn = get_connection()
            detector = ChangeDetector(
                conn,
                config=config,
                provider=OpenRouterProvider(config),
                workspace_id=workspace_id,
            )
            try:
                emit("monitor_started", f"Checking {len(monitor['urls'])} page(s)", {})
                run = detector.run_monitor(
                    monitor,
                    on_progress=lambda url: emit("monitor_fetch", f"Checking {url}", {}),
                )
                emit(
                    "monitor_done",
                    f"{run.changes_found} change(s) detected, "
                    f"{run.alerts_created} alert(s) raised",
                    {"changes": run.changes_found},
                )
                return run
            finally:
                detector.close()

        job = get_runner().submit(f"mon_{monitor_id}", monitor_id, work)
        return monitor_id, job

    def due_monitors(self) -> list[dict[str, Any]]:
        return repo.due_monitors(self.conn, self.workspace_id)

    def alerts(self, product_id: str, statuses: list[str] | None = None) -> list[dict[str, Any]]:
        return repo.list_alerts(self.conn, product_id, statuses=statuses)

    def unread_alerts(self, product_id: str) -> int:
        return repo.unread_alert_count(self.conn, product_id)

    def set_alert_status(self, alert_id: str, status: str) -> None:
        self.require(Permission.MANAGE_ALERTS)
        if status not in {member.value for member in AlertStatus}:
            raise ValueError(f"Unknown alert status: {status}")
        repo.set_alert_status(self.conn, alert_id, status)

    def alert_to_roadmap(self, alert_id: str, horizon: str = "next") -> str:
        """Turn an alert into a tracked roadmap item (spec 34)."""
        self.require(Permission.MANAGE_ROADMAP)
        alert = repo.get_alert(self.conn, alert_id)
        if alert is None:
            raise ValueError("Alert not found.")
        item_id = repo.add_roadmap_item(
            self.conn,
            workspace_id=alert["workspace_id"],
            product_id=alert["product_id"],
            title=alert["title"][:120],
            detail=alert.get("recommended_action") or alert.get("body", ""),
            horizon=horizon,
        )
        repo.set_alert_status(self.conn, alert_id, AlertStatus.ARCHIVED.value)
        return item_id

    def changes(self, product_id: str) -> list[dict[str, Any]]:
        return repo.list_changes(self.conn, product_id)

    # -- reports (spec 30 / 56) -------------------------------------------

    def build_report(self, report_id: str, analysis_id: str) -> "Report":
        self.require(Permission.EXPORT)
        from .analysis import reports

        entry = reports.REPORTS.get(report_id)
        if entry is None:
            raise ValueError(f"Unknown report: {report_id}")

        data = self.dashboard(analysis_id)
        product = self.get_product(data["analysis"]["product_id"])
        if product is None:
            raise ValueError("Product not found.")
        return entry[1](data, product)

    def build_evidence_report(self, analysis_id: str) -> "Report":
        self.require(Permission.EXPORT)
        from .analysis import reports

        data = self.dashboard(analysis_id)
        product = self.get_product(data["analysis"]["product_id"])
        if product is None:
            raise ValueError("Product not found.")
        return reports.evidence_report(data, product, self.evidence(analysis_id, limit=1000))

    def export_json(self, analysis_id: str) -> str:
        self.require(Permission.EXPORT)
        self._audit("analysis.exported", target_type="analysis", target_id=analysis_id)
        from .analysis import reports

        data = self.dashboard(analysis_id)
        product = self.get_product(data["analysis"]["product_id"])
        if product is None:
            raise ValueError("Product not found.")
        return reports.full_export_json(data, product, self.evidence(analysis_id, limit=1000))

    # -- Voice of Customer (spec 11) --------------------------------------

    def ingest_feedback_text(
        self, product_id: str, label: str, text: str, source_type: str = "upload"
    ) -> dict[str, Any]:
        """Store pasted feedback, splitting it into individual items."""
        self.require(Permission.MANAGE_SOURCES)
        from .research.documents import deduplicate, parse_pasted_feedback

        parsed = parse_pasted_feedback(text)
        return self._store_feedback(product_id, label, parsed, source_type, "")

    def ingest_feedback_file(
        self, product_id: str, label: str, filename: str, data: bytes,
        source_type: str = "upload",
    ) -> dict[str, Any]:
        """Store feedback from an uploaded CSV/JSON/TXT/PDF export."""
        self.require(Permission.MANAGE_SOURCES)
        from .research.documents import parse_upload

        parsed = parse_upload(filename, data, as_feedback=True)
        return self._store_feedback(product_id, label, parsed, source_type, filename)

    def _store_feedback(
        self, product_id: str, label: str, parsed, source_type: str, filename: str
    ) -> dict[str, Any]:
        from .research.documents import deduplicate
        from .storage import voc_repo

        records, in_batch_duplicates = deduplicate(parsed.records)
        batch_id = voc_repo.create_batch(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            label=label or filename or "Pasted feedback",
            source_type=source_type,
            filename=filename,
        )
        inserted, duplicates = voc_repo.add_feedback_items(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            batch_id=batch_id,
            records=records,
            source_type=source_type,
        )
        self._audit("feedback.ingested", target_type="feedback_batch",
                    target_id=batch_id, detail=f"{inserted} items")
        return {
            "batch_id": batch_id,
            "inserted": inserted,
            "duplicates": duplicates + in_batch_duplicates,
            "warnings": parsed.warnings,
        }

    def feedback_batches(self, product_id: str) -> list[dict[str, Any]]:
        from .storage import voc_repo

        return voc_repo.list_batches(self.conn, product_id)

    def feedback_count(self, product_id: str) -> int:
        from .storage import voc_repo

        return voc_repo.feedback_item_count(self.conn, product_id)

    def delete_feedback_batch(self, batch_id: str) -> None:
        self.require(Permission.MANAGE_SOURCES)
        from .storage import voc_repo

        voc_repo.delete_batch(self.conn, batch_id)

    def analyse_feedback(self, product_id: str, analysis_id: str | None = None):
        """Cluster stored feedback into themes. Returns the stored analysis."""
        self.require(Permission.RUN_ANALYSIS)
        if not self.config.is_configured:
            raise ValueError("No OPENROUTER_API_KEY configured.")

        from .agents.base import AnalysisContext
        from .agents.voice import VoiceOfCustomerAgent
        from .storage import voc_repo

        product = self.get_product(product_id)
        if product is None:
            raise ValueError("Product not found.")

        items = voc_repo.list_feedback_items(self.conn, product_id)
        if not items:
            raise ValueError("Add some customer feedback before analysing it.")

        analysis_id = analysis_id or (self.latest_analysis(product_id) or {}).get("id")
        if analysis_id is None:
            raise ValueError("Run a product analysis first.")

        ctx = AnalysisContext(
            conn=self.conn,
            config=self.config,
            provider=self._provider(),
            workspace_id=self.workspace_id,
            analysis_id=analysis_id,
            product=dict(product),
        )
        agent = VoiceOfCustomerAgent(items)
        result = agent.run(ctx)
        if result is None:
            raise ValueError("Feedback analysis did not complete. See the audit tab.")

        self._audit("feedback.analysed", target_type="product", target_id=product_id,
                    detail=f"{len(items)} items")
        return voc_repo.latest_feedback_analysis(self.conn, product_id)

    def feedback_analysis(self, product_id: str) -> dict[str, Any] | None:
        from .storage import voc_repo

        return voc_repo.latest_feedback_analysis(self.conn, product_id)

    # -- radar (spec 27 / 28) ---------------------------------------------

    def radar(self, analysis_id: str) -> dict[str, list[dict[str, Any]]]:
        self.require(Permission.VIEW)
        from .storage import voc_repo

        return {
            "opportunities": voc_repo.list_radar(self.conn, analysis_id, "opportunity"),
            "threats": voc_repo.list_radar(self.conn, analysis_id, "threat"),
        }

    # -- scenarios (spec 20) ----------------------------------------------

    def run_scenario(self, product_id: str, analysis_id: str, question: str):
        """Model an open-ended what-if question."""
        self.require(Permission.RUN_ANALYSIS)
        question = (question or "").strip()
        if not question:
            raise ValueError("Describe the scenario you want to model.")
        if len(question) > 2000:
            raise ValueError("That scenario description is too long.")
        if not self.config.is_configured:
            raise ValueError("No OPENROUTER_API_KEY configured.")

        from .agents.base import AnalysisContext
        from .agents.voice import ScenarioAgent

        product = self.get_product(product_id)
        if product is None:
            raise ValueError("Product not found.")

        ctx = AnalysisContext(
            conn=self.conn,
            config=self.config,
            provider=self._provider(),
            workspace_id=self.workspace_id,
            analysis_id=analysis_id,
            product=dict(product),
        )
        result = ScenarioAgent(question).run(ctx)
        if result is None:
            raise ValueError("Scenario analysis did not complete.")
        self._audit("scenario.run", target_type="product", target_id=product_id,
                    detail=question[:200])
        return result

    def scenario_runs(self, product_id: str) -> list[dict[str, Any]]:
        from .storage import voc_repo

        return voc_repo.list_scenario_runs(self.conn, product_id)

    def delete_scenario_run(self, scenario_id: str) -> None:
        from .storage import voc_repo

        voc_repo.delete_scenario_run(self.conn, scenario_id)

    # -- comments (spec 32) ------------------------------------------------

    def add_comment(self, product_id: str, target_type: str, target_id: str, body: str) -> str:
        self.require(Permission.VIEW)
        body = (body or "").strip()
        if not body:
            raise ValueError("Write something first.")
        from .storage import voc_repo

        return voc_repo.add_comment(
            self.conn,
            workspace_id=self.workspace_id,
            product_id=product_id,
            user_id=None if self.identity.is_dev else self.identity.user_id,
            author_label=self.identity.label,
            target_type=target_type,
            target_id=target_id,
            body=body,
        )

    def comments(self, target_type: str, target_id: str) -> list[dict[str, Any]]:
        from .storage import voc_repo

        return voc_repo.list_comments(self.conn, target_type, target_id)

    def comment_counts(self, product_id: str) -> dict[str, int]:
        from .storage import voc_repo

        return voc_repo.comment_counts(self.conn, product_id)

    def resolve_comment(self, comment_id: str) -> None:
        self.require(Permission.VIEW)
        from .storage import voc_repo

        voc_repo.resolve_comment(self.conn, comment_id)

    # -- competitor management (spec 7) -----------------------------------

    def add_competitor(self, analysis_id: str, data: dict[str, Any]) -> str:
        """Add a competitor the discovery agent missed."""
        self.require(Permission.RUN_ANALYSIS)
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("A competitor needs a name.")

        website = (data.get("website") or "").strip() or None
        if website:
            try:
                website = validate_url(website).url
            except UnsafeURLError as exc:
                raise ValueError(f"That website cannot be used: {exc}") from exc

        payload = {
            **data,
            "name": name[:120],
            "website": website,
            # User-supplied competitors are exactly that, and should never be
            # presented with the same grade as a researched finding.
            "grade": "user_supplied",
            "confidence": 1.0,
        }
        competitor_id = repo.save_competitor(
            self.conn,
            workspace_id=self.workspace_id,
            analysis_id=analysis_id,
            data=payload,
            is_user_added=True,
            position=999,
        )
        self._audit("competitor.added", target_type="competitor",
                    target_id=competitor_id, detail=name)
        return competitor_id

    def pin_competitor(self, competitor_id: str, pinned: bool) -> None:
        self.require(Permission.RUN_ANALYSIS)
        repo.set_competitor_pinned(self.conn, competitor_id, pinned)

    def remove_competitor(self, competitor_id: str) -> None:
        self.require(Permission.RUN_ANALYSIS)
        repo.delete_competitor(self.conn, competitor_id)
        self._audit("competitor.removed", target_type="competitor", target_id=competitor_id)

    # -- scheduler (spec 33) ----------------------------------------------

    def start_scheduler(self):
        """Start the in-process monitor scheduler if it is enabled."""
        if not self.config.scheduler_enabled or not self.config.is_configured:
            return None

        from .config import SCHEDULER_TICK_SECONDS
        from .jobs.scheduler import start_scheduler

        return start_scheduler(
            self.due_monitors,
            lambda monitor_id: self.run_monitor(monitor_id),
            tick_seconds=SCHEDULER_TICK_SECONDS,
        )

    def scheduler_state(self):
        from .jobs.scheduler import get_scheduler

        scheduler = get_scheduler()
        return scheduler.state if scheduler else None

    def run_due_monitors(self) -> int:
        """Run every monitor whose interval has elapsed. The cron entry point."""
        self.require(Permission.MANAGE_MONITORS)
        dispatched = 0
        for monitor in self.due_monitors():
            self.run_monitor(monitor["id"])
            dispatched += 1
        return dispatched

    # -- account recovery --------------------------------------------------

    def reset_member_password(self, user_id: str, new_password: str) -> None:
        """Set another member's password (spec 41).

        There is no email-based reset flow, so recovery is an owner or admin
        setting a new password directly. Every existing session for that account
        is revoked as a side effect.
        """
        self.require(Permission.MANAGE_MEMBERS)
        self.auth.set_password(user_id, new_password)
        self._audit("user.password_reset", target_type="user", target_id=user_id)

    # -- diagnostics (spec 51) --------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        self.require(Permission.VIEW_DIAGNOSTICS)
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
