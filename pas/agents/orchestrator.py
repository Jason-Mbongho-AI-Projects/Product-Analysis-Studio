"""Analysis orchestration (spec 48/50).

Runs research, then the agent pipeline, emitting progress as each stage lands
so the UI can show partial results rather than a single long spinner. A failing
agent degrades the analysis to ``partial``; it does not abort the run.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ai.provider import LLMProvider, OpenRouterProvider
from ..config import AppConfig, load_config
from ..domain.enums import AnalysisStatus
from ..research.engine import ResearchEngine, SiteProvider, UserSourceProvider
from ..storage import repositories as repo
from ..storage.db import get_connection
from .base import AnalysisContext, ResearchBundle
from .pipeline import execution_levels, pipeline_for

ProgressCallback = Callable[[str, str, dict[str, Any]], None]


@dataclass
class AnalysisRequest:
    workspace_id: str
    product_id: str
    analysis_id: str
    mode: str = "founder"
    research_enabled: bool = True
    depth: str = "full"
    deep_research: bool = False
    extra_urls: list[str] = field(default_factory=list)


class AnalysisOrchestrator:
    """Executes one analysis from research through executive synthesis."""

    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._config = config or load_config()
        self._provider = provider

    def _get_provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = OpenRouterProvider(self._config)
        return self._provider

    def run(
        self,
        request: AnalysisRequest,
        *,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        conn = get_connection()
        emit = on_progress or (lambda *_args, **_kwargs: None)

        def notify(event: str, message: str, payload: dict[str, Any] | None = None) -> None:
            emit(event, message, payload or {})

        product = repo.get_product(conn, request.product_id, request.workspace_id)
        if product is None:
            raise ValueError("Product not found in this workspace.")

        repo.update_analysis_progress(
            conn,
            request.analysis_id,
            status=AnalysisStatus.RUNNING.value,
            progress=0.02,
            stage="Starting",
        )

        research = ResearchBundle()
        failed_agents: list[str] = []

        try:
            # -- Stage 1: research ----------------------------------------
            if request.research_enabled:
                research = self._run_research(conn, request, product, notify)
            else:
                notify("research_skipped", "Research disabled for this run")

            repo.update_analysis_progress(
                conn, request.analysis_id, progress=0.15, stage="Analysing"
            )

            # -- Stage 2: agent pipeline ----------------------------------
            ctx = AnalysisContext(
                conn=conn,
                config=self._config,
                provider=self._get_provider(),
                workspace_id=request.workspace_id,
                analysis_id=request.analysis_id,
                product=dict(product),
                mode=request.mode,
                research=research,
                memory=repo.list_memory(conn, request.product_id),
                emit=lambda event, message, payload: notify(event, message, payload),
            )

            agents = pipeline_for(request.depth)
            levels = execution_levels(agents)
            total = len(agents)
            completed = 0

            for level in levels:
                if cancel_event is not None and cancel_event.is_set():
                    repo.update_analysis_progress(
                        conn,
                        request.analysis_id,
                        status=AnalysisStatus.CANCELLED.value,
                        stage="Cancelled",
                        completed=True,
                    )
                    notify("cancelled", "Analysis cancelled")
                    return {"status": AnalysisStatus.CANCELLED.value}

                instances = [agent_cls() for agent_cls in level]
                repo.update_analysis_progress(
                    conn,
                    request.analysis_id,
                    progress=0.15 + 0.8 * completed / total,
                    stage=" + ".join(a.title for a in instances[:3]),
                )

                for agent, result in self._run_level(ctx, instances):
                    completed += 1
                    if result is None:
                        failed_agents.append(agent.name)
                    else:
                        # Progressive disclosure: tell the UI this section is ready.
                        notify("section_ready", agent.title, {"agent": agent.name})

                repo.update_analysis_progress(
                    conn, request.analysis_id, progress=0.15 + 0.8 * completed / total
                )

            status = (
                AnalysisStatus.PARTIAL.value
                if failed_agents
                else AnalysisStatus.COMPLETE.value
            )
            repo.update_analysis_progress(
                conn,
                request.analysis_id,
                status=status,
                progress=1.0,
                stage="Complete" if not failed_agents else "Completed with gaps",
                error=(
                    "Agents that did not complete: " + ", ".join(failed_agents)
                    if failed_agents
                    else None
                ),
                completed=True,
            )
            notify("complete", "Analysis complete", {"failed_agents": failed_agents})
            return {"status": status, "failed_agents": failed_agents}

        except Exception as exc:  # pragma: no cover - defensive top level
            repo.update_analysis_progress(
                conn,
                request.analysis_id,
                status=AnalysisStatus.FAILED.value,
                stage="Failed",
                error=f"{type(exc).__name__}: {exc}"[:1000],
                completed=True,
            )
            notify("failed", f"Analysis failed: {exc}", {"trace": traceback.format_exc()[:2000]})
            raise

    def _run_level(self, ctx: AnalysisContext, agents: list[Any]):
        """Run one dependency level, concurrently when it holds more than one.

        Each worker gets its own sqlite connection - connections are thread-local
        and are not safe to share - and its own AnalysisContext view. Results are
        merged back into the shared context afterwards so later levels can read
        them, which is safe because merging happens on this thread only.
        """
        if len(agents) == 1:
            agent = agents[0]
            return [(agent, agent.run(ctx))]

        import copy
        from concurrent.futures import ThreadPoolExecutor

        def run_one(agent):
            # A per-thread connection; WAL mode allows the concurrent writes.
            worker_ctx = copy.copy(ctx)
            worker_ctx.conn = get_connection()
            worker_ctx.results = dict(ctx.results)
            return agent, agent.run(worker_ctx)

        with ThreadPoolExecutor(
            max_workers=min(len(agents), 4), thread_name_prefix="pas-agent"
        ) as pool:
            outcomes = list(pool.map(run_one, agents))

        for agent, result in outcomes:
            if result is not None:
                ctx.results[agent.name] = result
            # Model-call budget is shared across the level.
            ctx.llm_calls += 1
        return outcomes

    # -- research ----------------------------------------------------------

    def _run_research(
        self,
        conn,
        request: AnalysisRequest,
        product: dict[str, Any],
        notify: Callable[..., None],
    ) -> ResearchBundle:
        seed = product.get("source_url") or ""
        providers: list[Any] = []
        if seed:
            providers.append(SiteProvider())
            if request.deep_research:
                # Sitemap and feed discovery find pages that guessing the usual
                # paths misses - /security and /compliance in particular.
                from ..research.providers import (
                    ChangelogProvider,
                    FeedProvider,
                    SitemapProvider,
                )

                providers.extend(
                    [SitemapProvider(), ChangelogProvider(), FeedProvider()]
                )
        if request.extra_urls:
            providers.append(UserSourceProvider(request.extra_urls))

        if not providers:
            notify(
                "research_empty",
                "No URLs supplied - analysis will rely on model knowledge only",
            )
            return ResearchBundle()

        notify("research_started", "Gathering source material")
        engine = ResearchEngine(
            conn,
            workspace_id=request.workspace_id,
            analysis_id=request.analysis_id,
        )
        try:
            pages, failures = engine.gather(
                providers,
                seed,
                on_progress=lambda url: notify("research_fetch", f"Fetching {url}"),
            )
        finally:
            engine.close()

        github = self._fetch_github(conn, request, product, notify)
        if github:
            pages.append(github)

        notify(
            "research_done",
            f"{len(pages)} sources retrieved, {len(failures)} unavailable",
            {"pages": len(pages), "failures": len(failures)},
        )
        return ResearchBundle(pages=pages, failures=failures)

    def _fetch_github(
        self,
        conn,
        request: AnalysisRequest,
        product: dict[str, Any],
        notify: Callable[..., None],
    ) -> dict[str, Any] | None:
        """Enrich with public GitHub metadata when the product is open source."""
        from ..research.providers import GitHubProvider

        candidates = [product.get("source_url") or "", *request.extra_urls]
        for candidate in candidates:
            summary = GitHubProvider().fetch_repository(candidate)
            if summary is None:
                continue

            notify("research_github", f"Read GitHub repository {summary['slug']}")
            source_id = repo.upsert_source(
                conn,
                workspace_id=request.workspace_id,
                analysis_id=request.analysis_id,
                url=str(summary.get("url") or candidate),
                title=f"GitHub: {summary['slug']}",
                source_type="github",
                fetched_at=repo.utcnow(),
                status="active",
                reliability=0.9,
                excerpt=str(summary.get("description") or "")[:2000],
            )
            conn.commit()
            return {
                "source_id": source_id,
                "url": str(summary.get("url") or candidate),
                "title": f"GitHub: {summary['slug']}",
                "source_type": "github",
                "text": GitHubProvider.as_text(summary),
                "ok": True,
                "error": None,
            }
        return None
