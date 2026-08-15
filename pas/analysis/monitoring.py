"""Competitor monitoring and change detection (spec 8 / 33 / 34).

Design intent: **do not burn model calls on noise.** A monitored page is fetched
and hashed first. If the hash is unchanged, nothing else happens - no LLM call,
no alert. Only when the content actually differs is a diff computed and handed
to the change-detection agent, and only changes it marks as meaningful become
alerts.

That ordering is what makes weekly monitoring affordable.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ai.provider import LLMProvider, ProviderError
from ..config import AppConfig
from ..domain.contracts import ChangeReport
from ..domain.enums import AlertCategory, AlertSeverity
from ..research.fetcher import Fetcher
from ..research.safety import UnsafeURLError, validate_url
from ..storage import repositories as repo

#: Below this ratio of changed content, a page is treated as unchanged.
#: Marketing sites shuffle timestamps, testimonials and nav copy constantly.
#:
#: A bulk ratio alone is NOT sufficient: changing "$49" to "$39" on a long
#: pricing page is a tiny fraction of the text but is exactly the event this
#: feature exists to catch. High-signal tokens are therefore compared
#: separately and always escalate, regardless of ratio.
MIN_CHANGE_RATIO = 0.02

#: Cap the diff handed to the model so a rewritten page cannot blow the budget.
MAX_DIFF_CHARS = 6000

#: Currency amounts. Any change here is significant by definition.
#: Thousands groups are matched explicitly so a trailing comma in prose
#: ("plans are $49, $99 and $199") is not captured as part of the amount.
_AMOUNT = r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
PRICE_PATTERN = re.compile(
    rf"(?:[$£€]\s?(?:{_AMOUNT}))|(?:\b(?:{_AMOUNT})\s?(?:usd|eur|gbp)\b)"
)

#: Capability and trust markers whose appearance or removal is a strategic
#: signal even when the surrounding copy barely moves.
SIGNAL_TERMS = frozenset(
    {
        "sso", "saml", "scim", "oauth", "ldap",
        "soc 2", "soc2", "iso 27001", "hipaa", "gdpr", "fedramp", "pci dss",
        "enterprise", "on-premise", "on premise", "self-hosted", "private cloud",
        "free tier", "free trial", "freemium", "open source",
        "sla", "uptime guarantee", "dedicated support", "audit log",
        "api", "webhook", "integration", "mobile app", "white label",
        "per seat", "per user", "usage based", "unlimited",
    }
)


@dataclass
class MonitorResult:
    url: str
    checked: bool = False
    changed: bool = False
    change_ratio: float = 0.0
    changes_recorded: int = 0
    alerts_created: int = 0
    skipped_reason: str | None = None
    error: str | None = None
    assessment: "ChangeAssessment | None" = None


@dataclass
class MonitorRun:
    monitor_id: str
    results: list[MonitorResult] = field(default_factory=list)
    error: str | None = None

    @property
    def changes_found(self) -> int:
        return sum(r.changes_recorded for r in self.results)

    @property
    def alerts_created(self) -> int:
        return sum(r.alerts_created for r in self.results)

    @property
    def status(self) -> str:
        if self.error:
            return "failed"
        if any(r.error for r in self.results):
            return "partial"
        return "ok"


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def normalise_content(text: str) -> str:
    """Strip volatile noise before comparing two captures.

    Dates, times and cache-busting query strings change on every request for
    reasons that have nothing to do with product decisions.
    """
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    text = re.sub(r"\b\d{1,2}[:/]\d{2}(?::\d{2})?\b", "<time>", text)
    # Both orderings: "March 12, 2024" and "12 March 2024".
    text = re.sub(rf"\b(?:{_MONTHS})[a-z]*\s+\d{{1,2}},?\s+\d{{4}}\b", "<date>", text)
    text = re.sub(rf"\b\d{{1,2}}\s+(?:{_MONTHS})[a-z]*,?\s+\d{{4}}\b", "<date>", text)
    text = re.sub(rf"\b(?:{_MONTHS})[a-z]*\s+\d{{4}}\b", "<date>", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", text)
    text = re.sub(r"\?[a-z0-9_\-]*=[a-z0-9_\-]+", "", text)
    return text


def extract_prices(text: str) -> set[str]:
    """Currency amounts mentioned in the content."""
    return {
        match.group(0).replace(" ", "")
        for match in PRICE_PATTERN.finditer(normalise_content(text))
    }


def extract_signals(text: str) -> set[str]:
    """High-signal capability and trust terms present in the content."""
    normalised = normalise_content(text)
    return {term for term in SIGNAL_TERMS if term in normalised}


def change_ratio(before: str, after: str) -> float:
    """Fraction of the content that differs, 0.0-1.0.

    Compared at word level rather than character level: substituting one word
    for another is a far stronger signal than the handful of characters it
    touches, and character-level comparison drowns it in page length.
    """
    before_n, after_n = normalise_content(before), normalise_content(after)
    if not before_n and not after_n:
        return 0.0
    if not before_n or not after_n:
        return 1.0
    if before_n == after_n:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, before_n.split(), after_n.split()).ratio()


@dataclass
class ChangeAssessment:
    """Whether two captures differ enough to spend a model call on."""

    ratio: float
    prices_added: set[str] = field(default_factory=set)
    prices_removed: set[str] = field(default_factory=set)
    signals_added: set[str] = field(default_factory=set)
    signals_removed: set[str] = field(default_factory=set)

    @property
    def price_changed(self) -> bool:
        return bool(self.prices_added or self.prices_removed)

    @property
    def signals_changed(self) -> bool:
        return bool(self.signals_added or self.signals_removed)

    @property
    def is_significant(self) -> bool:
        """A price or capability change always escalates, however small."""
        return self.price_changed or self.signals_changed or self.ratio >= MIN_CHANGE_RATIO

    def reasons(self) -> list[str]:
        notes: list[str] = []
        if self.price_changed:
            notes.append(
                "Pricing changed: "
                f"{sorted(self.prices_removed) or 'none'} -> "
                f"{sorted(self.prices_added) or 'none'}"
            )
        if self.signals_added:
            notes.append(f"Capabilities appeared: {', '.join(sorted(self.signals_added))}")
        if self.signals_removed:
            notes.append(f"Capabilities disappeared: {', '.join(sorted(self.signals_removed))}")
        if self.ratio >= MIN_CHANGE_RATIO:
            notes.append(f"{self.ratio:.1%} of the page content changed")
        return notes


def assess_change(before: str, after: str) -> ChangeAssessment:
    """Decide whether a difference is worth analysing."""
    before_prices, after_prices = extract_prices(before), extract_prices(after)
    before_signals, after_signals = extract_signals(before), extract_signals(after)

    return ChangeAssessment(
        ratio=change_ratio(before, after),
        prices_added=after_prices - before_prices,
        prices_removed=before_prices - after_prices,
        signals_added=after_signals - before_signals,
        signals_removed=before_signals - after_signals,
    )


def build_diff(before: str, after: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """A unified diff of the changed lines only, budgeted for a prompt."""
    before_lines = [line for line in normalise_content(before).split(". ") if line]
    after_lines = [line for line in normalise_content(after).split(". ") if line]

    diff = [
        line
        for line in difflib.unified_diff(before_lines, after_lines, lineterm="", n=1)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    if not diff:
        return ""

    rendered = "\n".join(diff)
    if len(rendered) <= max_chars:
        return rendered
    # Keep both ends: additions cluster differently from removals.
    half = max_chars // 2
    return f"{rendered[:half]}\n...[diff truncated]...\n{rendered[-half:]}"


class ChangeDetector:
    """Fetches monitored pages, detects real changes, and raises alerts."""

    def __init__(
        self,
        conn,
        *,
        config: AppConfig,
        provider: LLMProvider,
        workspace_id: str,
        fetcher: Fetcher | None = None,
    ) -> None:
        self._conn = conn
        self._config = config
        self._provider = provider
        self._workspace_id = workspace_id
        self._fetcher = fetcher or Fetcher()

    def run_monitor(
        self,
        monitor: dict[str, Any],
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> MonitorRun:
        run = MonitorRun(monitor_id=monitor["id"])
        product_id = monitor["product_id"]

        for url in monitor.get("urls", []):
            if on_progress:
                on_progress(url)
            run.results.append(self._check_url(product_id, url))

        repo.update_monitor_run(
            self._conn,
            monitor["id"],
            status=run.status,
            error=run.error,
            changes_found=run.changes_found,
        )
        return run

    # -- internals ---------------------------------------------------------

    def _check_url(self, product_id: str, url: str) -> MonitorResult:
        try:
            safe = validate_url(url)
        except UnsafeURLError as exc:
            return MonitorResult(url=url, error=str(exc))

        fetched = self._fetcher.fetch(safe.url)
        if not fetched.ok:
            return MonitorResult(url=safe.url, error=fetched.error or "Fetch failed")

        previous = repo.latest_snapshot(self._conn, product_id, safe.url)

        snapshot_id = repo.save_snapshot(
            self._conn,
            workspace_id=self._workspace_id,
            product_id=product_id,
            url=safe.url,
            title=fetched.title,
            content=fetched.text,
            content_hash=fetched.content_hash,
        )
        repo.prune_snapshots(self._conn, product_id, safe.url)

        result = MonitorResult(url=safe.url, checked=True)

        if previous is None:
            result.skipped_reason = "First capture - baseline established."
            return result

        # Cheapest possible check first: identical bytes means stop here.
        if previous["content_hash"] == fetched.content_hash:
            result.skipped_reason = "No change (identical content hash)."
            return result

        assessment = assess_change(previous["content"], fetched.text)
        result.change_ratio = assessment.ratio
        result.assessment = assessment

        if not assessment.is_significant:
            result.skipped_reason = f"Change below threshold ({assessment.ratio:.1%})."
            return result

        diff = build_diff(previous["content"], fetched.text)
        if not diff:
            result.skipped_reason = "No substantive textual difference."
            return result

        result.changed = True
        try:
            report = self._analyse(safe.url, fetched.title, diff, assessment)
        except ProviderError as exc:
            result.error = f"Change analysis failed: {exc}"
            return result

        for change in report.changes:
            if not change.is_meaningful:
                continue
            change_id = repo.record_change(
                self._conn,
                workspace_id=self._workspace_id,
                product_id=product_id,
                snapshot_id=snapshot_id,
                competitor_id=None,
                data=change.model_dump(mode="json"),
                source_url=safe.url,
            )
            result.changes_recorded += 1

            # Only changes that matter enough to act on become alerts.
            if AlertSeverity(change.severity.value).rank >= AlertSeverity.MEDIUM.rank:
                repo.create_alert(
                    self._conn,
                    workspace_id=self._workspace_id,
                    product_id=product_id,
                    category=(
                        AlertCategory.PRICING.value
                        if change.change_type.value == "pricing"
                        else AlertCategory.COMPETITOR.value
                    ),
                    severity=change.severity.value,
                    title=change.summary,
                    body=(
                        f"Was: {change.previous_state}\n\n"
                        f"Now: {change.current_state}\n\n"
                        f"Impact: {change.estimated_impact}"
                    ),
                    recommended_action=change.recommended_action,
                    change_id=change_id,
                    source_url=safe.url,
                )
                result.alerts_created += 1

        self._conn.commit()
        return result

    def _analyse(
        self, url: str, title: str, diff: str, assessment: ChangeAssessment
    ) -> ChangeReport:
        system = (
            "You analyse changes to competitor web pages for a product strategy "
            "platform. You are strict about what counts as meaningful.\n\n"
            "Meaningful: pricing changes, new or removed features, new integrations, "
            "positioning shifts, new security or compliance claims, enterprise "
            "capabilities, new market or geography claims.\n\n"
            "NOT meaningful: copy tweaks, testimonial rotation, blog listings, nav "
            "changes, styling, dates, typo fixes. Mark these is_meaningful=false.\n\n"
            "Base every claim on the diff. Do not speculate about what the change "
            "implies commercially beyond what the text supports. If the diff is "
            "ambiguous, say so and lower confidence."
        )
        # Pre-computed signals are handed over so the model does not have to
        # spot a single changed digit buried in a long diff.
        detected = assessment.reasons()
        signal_note = (
            "AUTOMATICALLY DETECTED SIGNALS (these are reliable - account for them):\n"
            + "\n".join(f"- {reason}" for reason in detected)
            if detected
            else ""
        )
        user = (
            f"Page: {title}\nURL: {url}\n\n"
            f"{signal_note}\n\n"
            f"Lines prefixed '-' were removed, '+' were added.\n\n"
            f"DIFF:\n{diff}\n\n"
            "Identify what actually changed. Return an empty changes list if "
            "nothing meaningful did."
        )
        completion = self._provider.complete_structured(
            model=self._config.fast_model,
            system=system,
            user=user,
            schema=ChangeReport,
            max_tokens=4000,
        )
        usage = completion.usage
        repo.record_usage(
            self._conn,
            workspace_id=self._workspace_id,
            analysis_id=None,
            agent_run_id=None,
            provider=usage.provider,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
        )
        return completion.data

    def close(self) -> None:
        self._fetcher.close()
