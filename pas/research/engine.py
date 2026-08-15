"""Research orchestration (spec 5).

Gathers source material before the analysis agents run. Providers are modular
so additional legitimate sources (official APIs, licensed feeds, user uploads)
can be added without touching the agents.

What this module deliberately does NOT do: crawl aggressively, ignore
robots.txt, or scrape sites that disallow it. Sources that decline access are
recorded as such and the analysis proceeds with less evidence and lower
confidence, which is the honest outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urljoin, urlparse

from ..config import RESEARCH_MAX_PAGES_PER_DOMAIN
from ..domain.enums import SourceType
from ..storage import repositories as repo
from .fetcher import Fetcher, FetchResult
from .safety import UnsafeURLError, validate_url

#: Paths worth trying on a product's own site. Ordered by intelligence value.
HIGH_VALUE_PATHS: list[tuple[str, SourceType]] = [
    ("/", SourceType.PRODUCT_WEBSITE),
    ("/pricing", SourceType.PRICING_PAGE),
    ("/product", SourceType.PRODUCT_WEBSITE),
    ("/features", SourceType.PRODUCT_WEBSITE),
    ("/docs", SourceType.DOCUMENTATION),
    ("/about", SourceType.PRODUCT_WEBSITE),
    ("/changelog", SourceType.CHANGELOG),
    ("/security", SourceType.DOCUMENTATION),
]


@dataclass
class ResearchTarget:
    url: str
    source_type: SourceType = SourceType.OTHER
    label: str = ""


class ResearchProvider(Protocol):
    """Contract for a source of research targets."""

    name: str

    def discover(self, seed: str) -> list[ResearchTarget]:
        """Return candidate URLs to fetch for ``seed``."""


class SiteProvider:
    """Explores a product's own website - the highest-signal legitimate source."""

    name = "site"

    def __init__(self, max_pages: int = RESEARCH_MAX_PAGES_PER_DOMAIN) -> None:
        self._max_pages = max_pages

    def discover(self, seed: str) -> list[ResearchTarget]:
        if not seed:
            return []
        try:
            safe = validate_url(seed, resolve_dns=False)
        except UnsafeURLError:
            return []

        parsed = urlparse(safe.url)
        root = f"{parsed.scheme}://{parsed.netloc}"

        targets = [ResearchTarget(url=safe.url, source_type=SourceType.PRODUCT_WEBSITE)]
        seen = {safe.url.rstrip("/")}
        for path, source_type in HIGH_VALUE_PATHS:
            candidate = urljoin(root, path)
            if candidate.rstrip("/") in seen:
                continue
            seen.add(candidate.rstrip("/"))
            targets.append(ResearchTarget(url=candidate, source_type=source_type))
        return targets[: self._max_pages]


class UserSourceProvider:
    """URLs the user supplied explicitly."""

    name = "user"

    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    def discover(self, seed: str) -> list[ResearchTarget]:
        return [
            ResearchTarget(url=url, source_type=SourceType.OTHER, label="User supplied")
            for url in self._urls
            if url.strip()
        ]


class ResearchEngine:
    """Runs providers, fetches safely, and records every source and failure."""

    def __init__(
        self,
        conn,
        *,
        workspace_id: str,
        analysis_id: str,
        fetcher: Fetcher | None = None,
    ) -> None:
        self._conn = conn
        self._workspace_id = workspace_id
        self._analysis_id = analysis_id
        self._fetcher = fetcher or Fetcher()

    def gather(
        self,
        providers: list[ResearchProvider],
        seed: str,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Fetch from every provider. Returns ``(pages, failures)``."""
        targets: list[ResearchTarget] = []
        seen: set[str] = set()
        for provider in providers:
            for target in provider.discover(seed):
                key = target.url.rstrip("/")
                if key not in seen:
                    seen.add(key)
                    targets.append(target)

        pages: list[dict] = []
        failures: list[dict] = []

        for target in targets:
            if on_progress:
                on_progress(target.url)
            result = self._fetcher.fetch(target.url)
            record = self._record(target, result)
            (pages if result.ok else failures).append(record)

        self._conn.commit()
        return pages, failures

    def _record(self, target: ResearchTarget, result: FetchResult) -> dict:
        status = "active" if result.ok else ("blocked" if result.blocked_by_robots else "failed")
        source_id = repo.upsert_source(
            self._conn,
            workspace_id=self._workspace_id,
            analysis_id=self._analysis_id,
            url=result.url,
            title=result.title or target.url,
            source_type=target.source_type.value,
            fetched_at=repo.utcnow(),
            status=status,
            reliability=0.8 if result.ok else 0.0,
            content_hash=result.content_hash,
            excerpt=result.excerpt,
            failure_reason=result.error,
        )
        return {
            "source_id": source_id,
            "url": result.url,
            "title": result.title,
            "source_type": target.source_type.value,
            "text": result.text,
            "ok": result.ok,
            "error": result.error,
        }

    def close(self) -> None:
        self._fetcher.close()
