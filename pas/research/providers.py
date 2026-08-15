"""Additional research providers (spec 5).

Each provider here uses an access route the publisher explicitly offers:

* **GitHub** — the documented public REST API.
* **Feeds** — RSS/Atom, a format whose entire purpose is machine consumption.
* **Sitemap** — ``sitemap.xml``, published specifically to direct crawlers,
  discovered via ``robots.txt`` where possible.
* **Changelog** — conventional public changelog paths on the product's own site.

What is deliberately NOT here, and why:

* **App stores** (Apple, Google Play) publish no free review API, and their
  terms prohibit scraping the listing pages. Users can export their own reviews
  and upload them through Voice of Customer instead.
* **Review sites** (G2, Capterra, Trustpilot) prohibit automated collection in
  their terms. Same route: export and upload.
* **Search engines** require a paid API key; there is no free compliant route.

The spec asks for legally and technically appropriate access. Building a scraper
for a site that forbids it would be the wrong kind of "complete".
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests

from ..config import HTTP_TIMEOUT_SECONDS, HTTP_USER_AGENT
from ..domain.enums import SourceType
from .engine import ResearchTarget
from .safety import UnsafeURLError, validate_url

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

#: Conventional changelog and release-note locations on a product's own site.
CHANGELOG_PATHS = [
    ("/changelog", SourceType.CHANGELOG),
    ("/releases", SourceType.CHANGELOG),
    ("/whats-new", SourceType.CHANGELOG),
    ("/release-notes", SourceType.CHANGELOG),
    ("/blog", SourceType.BLOG),
    ("/news", SourceType.NEWS),
]

#: Conventional feed locations.
FEED_PATHS = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/blog/rss.xml"]


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": HTTP_USER_AGENT})
    return session


@dataclass
class GitHubRepo:
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_github_url(url: str) -> GitHubRepo | None:
    """Extract owner/repo from a GitHub URL, if it is one."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if "github.com" not in (parsed.netloc or "").lower():
        return None

    parts = [part for part in (parsed.path or "").split("/") if part]
    if len(parts) < 2:
        return None
    return GitHubRepo(owner=parts[0], name=re.sub(r"\.git$", "", parts[1]))


class GitHubProvider:
    """Reads public repository metadata through the documented API.

    Useful for open-source products and for competitors who develop in the
    open: stars, topics, language, release cadence and recent releases are all
    real signals about momentum and direction.
    """

    name = "github"

    def __init__(self, repo_url: str | None = None) -> None:
        self._repo_url = repo_url

    def discover(self, seed: str) -> list[ResearchTarget]:
        repo = parse_github_url(self._repo_url or seed)
        if repo is None:
            return []
        # The API endpoints are fetched directly rather than routed through the
        # generic fetcher, because their JSON needs structuring, not text
        # extraction. `fetch_repository` handles them.
        return []

    def fetch_repository(self, url: str) -> dict[str, object] | None:
        """Return a structured summary of a public repository, or None."""
        repo = parse_github_url(url)
        if repo is None:
            return None

        session = _session()
        session.headers.update({"Accept": "application/vnd.github+json"})

        try:
            validate_url(f"{GITHUB_API}/repos/{repo.slug}")
            response = session.get(
                f"{GITHUB_API}/repos/{repo.slug}", timeout=HTTP_TIMEOUT_SECONDS
            )
            if response.status_code == 404:
                return None
            if response.status_code == 403:
                logger.info("GitHub rate limit reached for %s", repo.slug)
                return None
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, UnsafeURLError, ValueError) as exc:
            logger.info("GitHub lookup failed for %s: %s", repo.slug, exc)
            return None

        releases: list[dict[str, str]] = []
        try:
            release_response = session.get(
                f"{GITHUB_API}/repos/{repo.slug}/releases",
                params={"per_page": 5},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if release_response.ok:
                releases = [
                    {
                        "name": item.get("name") or item.get("tag_name") or "",
                        "published_at": (item.get("published_at") or "")[:10],
                        "body": (item.get("body") or "")[:600],
                    }
                    for item in release_response.json()[:5]
                ]
        except (requests.RequestException, ValueError):
            pass
        finally:
            session.close()

        return {
            "slug": repo.slug,
            "url": data.get("html_url"),
            "description": data.get("description") or "",
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "language": data.get("language") or "",
            "topics": data.get("topics", []),
            "license": ((data.get("license") or {}) or {}).get("spdx_id") or "",
            "created_at": (data.get("created_at") or "")[:10],
            "pushed_at": (data.get("pushed_at") or "")[:10],
            "archived": bool(data.get("archived")),
            "releases": releases,
        }

    @staticmethod
    def as_text(summary: dict[str, object]) -> str:
        """Render the summary as prompt-ready text."""
        releases = summary.get("releases") or []
        release_lines = "\n".join(
            f"- {item['name']} ({item['published_at']}): {item['body'][:200]}"
            for item in releases  # type: ignore[union-attr]
        )
        return (
            f"GitHub repository {summary['slug']}\n"
            f"Description: {summary['description']}\n"
            f"Stars: {summary['stars']} | Forks: {summary['forks']} | "
            f"Open issues: {summary['open_issues']}\n"
            f"Primary language: {summary['language']} | "
            f"License: {summary['license']}\n"
            f"Topics: {', '.join(summary.get('topics') or [])}\n"  # type: ignore[arg-type]
            f"Created: {summary['created_at']} | Last pushed: {summary['pushed_at']}"
            f"{' | ARCHIVED' if summary.get('archived') else ''}\n"
            f"Recent releases:\n{release_lines or '- none published'}"
        )


class FeedProvider:
    """Discovers RSS/Atom feeds and turns entries into research targets.

    Feeds exist to be read by machines, which makes them the least ambiguous
    legitimate source for release notes, blog posts and announcements.
    """

    name = "feed"

    def __init__(self, max_entries: int = 8) -> None:
        self._max_entries = max_entries

    def discover(self, seed: str) -> list[ResearchTarget]:
        if not seed:
            return []
        try:
            safe = validate_url(seed, resolve_dns=False)
        except UnsafeURLError:
            return []

        parsed = urlparse(safe.url)
        root = f"{parsed.scheme}://{parsed.netloc}"

        feed_url = self._find_feed(root)
        if feed_url is None:
            return []

        entries = self._read_feed(feed_url)
        return [
            ResearchTarget(
                url=entry, source_type=SourceType.BLOG, label="Feed entry"
            )
            for entry in entries[: self._max_entries]
        ]

    def _find_feed(self, root: str) -> str | None:
        session = _session()
        try:
            # A <link rel="alternate"> declaration is authoritative; fall back to
            # conventional paths only if the page does not declare one.
            try:
                response = session.get(root, timeout=HTTP_TIMEOUT_SECONDS)
                if response.ok:
                    match = re.search(
                        r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>',
                        response.text,
                        re.I,
                    )
                    if match:
                        href = re.search(r'href=["\']([^"\']+)["\']', match.group(0), re.I)
                        if href:
                            return urljoin(root, href.group(1))
            except requests.RequestException:
                pass

            for path in FEED_PATHS:
                candidate = urljoin(root, path)
                try:
                    validate_url(candidate, resolve_dns=False)
                    head = session.get(candidate, timeout=HTTP_TIMEOUT_SECONDS)
                except (requests.RequestException, UnsafeURLError):
                    continue
                content_type = (head.headers.get("Content-Type") or "").lower()
                if head.ok and ("xml" in content_type or head.text.lstrip().startswith("<?xml")):
                    return candidate
        finally:
            session.close()
        return None

    def _read_feed(self, feed_url: str) -> list[str]:
        session = _session()
        try:
            response = session.get(feed_url, timeout=HTTP_TIMEOUT_SECONDS)
            if not response.ok:
                return []
            root = ElementTree.fromstring(response.content)
        except (requests.RequestException, ElementTree.ParseError) as exc:
            logger.info("Feed %s could not be read: %s", feed_url, exc)
            return []
        finally:
            session.close()

        links: list[str] = []
        # RSS
        for item in root.iter("item"):
            link = item.findtext("link")
            if link:
                links.append(link.strip())
        # Atom
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            link_element = entry.find("{http://www.w3.org/2005/Atom}link")
            if link_element is not None:
                href = link_element.get("href")
                if href:
                    links.append(href.strip())

        safe_links = []
        for link in links:
            try:
                safe_links.append(validate_url(link, resolve_dns=False).url)
            except UnsafeURLError:
                continue
        return list(dict.fromkeys(safe_links))


class SitemapProvider:
    """Uses sitemap.xml to find high-value pages rather than guessing paths.

    Sitemaps are published to direct crawlers, so this is the polite way to
    discover a site's structure. Only pages whose URL suggests product,
    pricing, security or documentation content are returned.
    """

    name = "sitemap"

    #: URL fragments worth fetching, in priority order.
    INTERESTING = [
        ("pricing", SourceType.PRICING_PAGE),
        ("plans", SourceType.PRICING_PAGE),
        ("security", SourceType.DOCUMENTATION),
        ("compliance", SourceType.DOCUMENTATION),
        ("integrations", SourceType.DOCUMENTATION),
        ("features", SourceType.PRODUCT_WEBSITE),
        ("product", SourceType.PRODUCT_WEBSITE),
        ("enterprise", SourceType.PRODUCT_WEBSITE),
        ("docs", SourceType.DOCUMENTATION),
        ("changelog", SourceType.CHANGELOG),
    ]

    def __init__(self, max_targets: int = 8) -> None:
        self._max_targets = max_targets

    def discover(self, seed: str) -> list[ResearchTarget]:
        if not seed:
            return []
        try:
            safe = validate_url(seed, resolve_dns=False)
        except UnsafeURLError:
            return []

        parsed = urlparse(safe.url)
        root = f"{parsed.scheme}://{parsed.netloc}"

        urls = self._sitemap_urls(root)
        if not urls:
            return []

        targets: list[ResearchTarget] = []
        seen: set[str] = set()
        for fragment, source_type in self.INTERESTING:
            for url in urls:
                if fragment in url.lower() and url not in seen:
                    seen.add(url)
                    targets.append(ResearchTarget(url=url, source_type=source_type))
                    break
            if len(targets) >= self._max_targets:
                break
        return targets

    def _sitemap_urls(self, root: str) -> list[str]:
        session = _session()
        candidates = [urljoin(root, "/sitemap.xml")]

        # robots.txt is the declared location for sitemaps.
        try:
            robots = session.get(urljoin(root, "/robots.txt"), timeout=HTTP_TIMEOUT_SECONDS)
            if robots.ok:
                for line in robots.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        candidates.insert(0, line.split(":", 1)[1].strip())
        except requests.RequestException:
            pass

        urls: list[str] = []
        for candidate in candidates[:3]:
            try:
                validate_url(candidate, resolve_dns=False)
                response = session.get(candidate, timeout=HTTP_TIMEOUT_SECONDS)
                if not response.ok:
                    continue
                tree = ElementTree.fromstring(response.content)
            except (requests.RequestException, UnsafeURLError, ElementTree.ParseError):
                continue

            namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            # A sitemap index points at further sitemaps; follow only the first.
            nested = [
                element.text.strip()
                for element in tree.iter(f"{namespace}sitemap")
                for element in element.iter(f"{namespace}loc")
                if element.text
            ]
            if nested:
                candidates.extend(nested[:2])

            urls.extend(
                element.text.strip()
                for element in tree.iter(f"{namespace}loc")
                if element.text
            )
            if urls:
                break

        session.close()

        safe_urls = []
        for url in urls[:2000]:
            try:
                safe_urls.append(validate_url(url, resolve_dns=False).url)
            except UnsafeURLError:
                continue
        return safe_urls


class ChangelogProvider:
    """Tries conventional changelog and news paths on the product's own site."""

    name = "changelog"

    def discover(self, seed: str) -> list[ResearchTarget]:
        if not seed:
            return []
        try:
            safe = validate_url(seed, resolve_dns=False)
        except UnsafeURLError:
            return []

        parsed = urlparse(safe.url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        return [
            ResearchTarget(url=urljoin(root, path), source_type=source_type)
            for path, source_type in CHANGELOG_PATHS
        ]


#: Providers that are safe to run against any product URL.
def default_providers(seed: str, deep: bool = False) -> list[object]:
    """Return the provider set for a research run.

    ``deep`` adds sitemap and feed discovery, which cost extra requests and are
    only worth it when the caller wants broader coverage.
    """
    from .engine import SiteProvider

    providers: list[object] = [SiteProvider()]
    if deep:
        providers.extend([SitemapProvider(), ChangelogProvider(), FeedProvider()])
    return providers
