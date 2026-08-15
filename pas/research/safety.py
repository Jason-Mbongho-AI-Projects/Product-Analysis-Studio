"""URL safety checks for the research engine (spec 41).

The platform fetches user-supplied URLs, which is a textbook SSRF sink. The
guard here resolves DNS and validates *every* resolved address before any
socket is opened, because a hostname that looks public can resolve to
169.254.169.254 or 127.0.0.1.

Blocked by design:
  * non-http(s) schemes (file://, gopher://, ftp://, data:)
  * loopback, link-local, private, reserved, multicast and unspecified ranges
  * cloud instance-metadata endpoints
  * credentials embedded in the URL
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Hostnames that must never be fetched regardless of DNS resolution.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

#: Cloud metadata addresses. These resolve to link-local ranges too, but are
#: listed explicitly so the failure message is unambiguous.
BLOCKED_ADDRESSES = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP / OpenStack IMDS
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",      # Oracle Cloud
        "fd00:ec2::254",    # AWS IMDS over IPv6
    }
)

MAX_URL_LENGTH = 2048


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched."""


@dataclass(frozen=True)
class SafeURL:
    url: str
    hostname: str
    scheme: str
    addresses: tuple[str, ...]


def _address_is_blocked(raw: str) -> str | None:
    """Return a rejection reason for an IP literal, or None if it is allowed."""
    if raw in BLOCKED_ADDRESSES:
        return f"{raw} is a cloud metadata endpoint"
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return f"{raw} is not a valid IP address"

    if address.is_loopback:
        return f"{raw} is a loopback address"
    if address.is_private:
        return f"{raw} is in a private network range"
    if address.is_link_local:
        return f"{raw} is a link-local address"
    if address.is_reserved:
        return f"{raw} is in a reserved range"
    if address.is_multicast:
        return f"{raw} is a multicast address"
    if address.is_unspecified:
        return f"{raw} is the unspecified address"
    # IPv4-mapped IPv6 (::ffff:127.0.0.1) would otherwise slip past the checks
    # above, since the mapped form is not itself flagged as loopback.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        return _address_is_blocked(str(mapped))
    return None


def _resolve(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{hostname}': {exc}") from exc
    return sorted({info[4][0] for info in infos})


def validate_url(raw_url: str, *, resolve_dns: bool = True) -> SafeURL:
    """Validate a URL for outbound fetching.

    Raises :class:`UnsafeURLError` with a specific reason on rejection.
    """
    if not raw_url or not raw_url.strip():
        raise UnsafeURLError("URL is empty.")
    raw_url = raw_url.strip()
    if len(raw_url) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL exceeds the maximum permitted length.")

    parsed = urlparse(raw_url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Scheme '{parsed.scheme or 'none'}' is not permitted; use http or https."
        )
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs containing credentials are not permitted.")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise UnsafeURLError("URL has no host component.")
    if hostname in BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"Host '{hostname}' is blocked.")
    if hostname.endswith(".localhost") or hostname.endswith(".internal"):
        raise UnsafeURLError(f"Host '{hostname}' is blocked.")

    # A bare IP literal is checked directly; a name is checked after resolution.
    try:
        ipaddress.ip_address(hostname)
        candidates = [hostname]
    except ValueError:
        candidates = _resolve(hostname) if resolve_dns else []

    for candidate in candidates:
        reason = _address_is_blocked(candidate)
        if reason:
            raise UnsafeURLError(f"Blocked: {reason}.")

    normalised = urlunparse(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return SafeURL(
        url=normalised,
        hostname=hostname,
        scheme=parsed.scheme.lower(),
        addresses=tuple(candidates),
    )


def is_safe(raw_url: str) -> bool:
    try:
        validate_url(raw_url)
        return True
    except UnsafeURLError:
        return False
