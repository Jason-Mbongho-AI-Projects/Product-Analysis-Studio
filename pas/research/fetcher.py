"""Polite, SSRF-guarded page fetching.

Behaviour that is deliberate rather than incidental:

* robots.txt is honoured before every fetch (spec 5)
* redirects are followed manually so each hop is re-validated - otherwise a
  safe URL could redirect straight to 127.0.0.1
* responses are size-capped and streamed, so a hostile server cannot exhaust
  memory
* only HTML/text is parsed; binary types are recorded and skipped
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

from ..config import (
    HTTP_MAX_BYTES,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
)
from .safety import UnsafeURLError, validate_url

MAX_REDIRECTS = 4
TEXTUAL_TYPES = ("text/html", "text/plain", "application/xhtml", "application/json")


def _use_system_trust_store() -> bool:
    """Verify TLS against the OS trust store when possible.

    The bundled CA list misses roots that many corporate and Windows
    environments depend on, which surfaces as CERTIFICATE_VERIFY_FAILED on
    perfectly legitimate sites. Deferring to the OS fixes that while keeping
    verification fully enabled - certificate checks are never disabled here.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


_SYSTEM_TRUST = _use_system_trust_store()


@dataclass
class FetchResult:
    url: str
    ok: bool
    status_code: int | None = None
    title: str = ""
    text: str = ""
    content_hash: str = ""
    fetched_at: float = field(default_factory=time.time)
    error: str | None = None
    blocked_by_robots: bool = False

    @property
    def excerpt(self) -> str:
        return self.text[:2000]


class _Extractor(HTMLParser):
    """Minimal HTML-to-text extraction.

    A dedicated parser library would be nicer, but stdlib keeps the dependency
    surface small and this only needs to feed an LLM, not render a page.
    """

    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            attributes = dict(attrs)
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            if name in {"description", "og:description"} and not self._description:
                self._description = attributes.get("content") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        elif not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self._chunks.append(stripped)

    @property
    def text(self) -> str:
        body = " ".join(self._chunks)
        if self._description:
            body = f"{self._description}\n\n{body}"
        return re.sub(r"\s+", " ", body).strip()


class Fetcher:
    """Fetches pages with safety, politeness and caching.

    One instance per analysis: it memoises robots.txt per host and dedupes
    repeat fetches of the same URL within the run.
    """

    def __init__(self, *, timeout: float = HTTP_TIMEOUT_SECONDS, respect_robots: bool = True):
        self._timeout = timeout
        self._respect_robots = respect_robots
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._cache: dict[str, FetchResult] = {}
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": HTTP_USER_AGENT})

    # -- robots ------------------------------------------------------------

    def _robots_for(self, scheme: str, host: str) -> robotparser.RobotFileParser | None:
        key = f"{scheme}://{host}"
        if key in self._robots:
            return self._robots[key]

        parser: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        robots_url = f"{key}/robots.txt"
        try:
            validate_url(robots_url)
            response = self._session.get(robots_url, timeout=self._timeout)
            if response.status_code >= 400:
                # No usable robots.txt means no stated restriction.
                parser = None
            else:
                assert parser is not None
                parser.parse(response.text.splitlines())
        except (requests.RequestException, UnsafeURLError):
            parser = None

        self._robots[key] = parser
        return parser

    def allowed_by_robots(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        parsed = urlparse(url)
        parser = self._robots_for(parsed.scheme, parsed.netloc)
        if parser is None:
            return True
        return parser.can_fetch(HTTP_USER_AGENT, url)

    # -- fetching ----------------------------------------------------------

    def fetch(self, raw_url: str) -> FetchResult:
        if raw_url in self._cache:
            return self._cache[raw_url]
        result = self._fetch_uncached(raw_url)
        self._cache[raw_url] = result
        return result

    def _fetch_uncached(self, raw_url: str) -> FetchResult:
        current = raw_url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                safe = validate_url(current)
            except UnsafeURLError as exc:
                return FetchResult(url=current, ok=False, error=str(exc))

            if not self.allowed_by_robots(safe.url):
                return FetchResult(
                    url=safe.url,
                    ok=False,
                    error="Disallowed by the site's robots.txt.",
                    blocked_by_robots=True,
                )

            try:
                # allow_redirects=False so every hop is revalidated above.
                response = self._session.get(
                    safe.url, timeout=self._timeout, stream=True, allow_redirects=False
                )
            except requests.RequestException as exc:
                return FetchResult(url=safe.url, ok=False, error=f"Request failed: {exc}")

            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    return FetchResult(
                        url=safe.url,
                        ok=False,
                        status_code=response.status_code,
                        error="Redirect without a Location header.",
                    )
                current = urljoin(safe.url, location)
                continue

            return self._read(response, safe.url)

        return FetchResult(url=raw_url, ok=False, error="Too many redirects.")

    def _read(self, response: requests.Response, url: str) -> FetchResult:
        try:
            if response.status_code >= 400:
                return FetchResult(
                    url=url,
                    ok=False,
                    status_code=response.status_code,
                    error=f"HTTP {response.status_code}",
                )

            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not any(t in content_type for t in TEXTUAL_TYPES):
                return FetchResult(
                    url=url,
                    ok=False,
                    status_code=response.status_code,
                    error=f"Unsupported content type: {content_type.split(';')[0]}",
                )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=16384):
                chunks.append(chunk)
                total += len(chunk)
                if total >= HTTP_MAX_BYTES:
                    break
            body = b"".join(chunks)
        finally:
            response.close()

        encoding = response.encoding or "utf-8"
        try:
            decoded = body.decode(encoding, errors="replace")
        except LookupError:
            decoded = body.decode("utf-8", errors="replace")

        parser = _Extractor()
        try:
            parser.feed(decoded)
        except Exception:  # malformed markup should degrade, not fail the run
            pass

        text = parser.text or re.sub(r"\s+", " ", decoded).strip()
        return FetchResult(
            url=url,
            ok=bool(text),
            status_code=response.status_code,
            title=parser.title or urlparse(url).netloc,
            text=text[:60000],
            content_hash=hashlib.sha256(body).hexdigest(),
            error=None if text else "No extractable text content.",
        )

    def close(self) -> None:
        self._session.close()
