"""SSRF guard tests (spec 41).

These assert on the security boundary of the research engine. A regression here
would let a user-supplied URL reach internal infrastructure, so the cases are
enumerated explicitly rather than sampled.
"""

from __future__ import annotations

import pytest

from pas.research.safety import UnsafeURLError, is_safe, validate_url

BLOCKED_URLS = [
    # Loopback in every spelling
    "http://127.0.0.1/",
    "http://127.0.0.1:8501/admin",
    "http://localhost/",
    "http://LOCALHOST:80/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://127.1/",
    # Private ranges
    "http://10.0.0.1/",
    "http://172.16.5.4/",
    "http://192.168.1.1/",
    # Link-local and metadata
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://100.100.100.200/",
    "http://192.0.0.192/",
    # Unspecified / reserved
    "http://0.0.0.0/",
    # Dangerous schemes
    "file:///etc/passwd",
    "file://C:/Windows/win.ini",
    "gopher://127.0.0.1:11211/",
    "ftp://example.com/",
    "data:text/html,<script>alert(1)</script>",
    "javascript:alert(1)",
    # Credential smuggling
    "http://user:password@example.com/",
    "https://admin:secret@internal.example.com/",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_dangerous_urls_are_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)
    assert is_safe(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://.internal/",
        "http://foo.localhost/",
        "http://service.internal/",
    ],
)
def test_internal_suffixes_are_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_empty_and_oversized_urls_rejected():
    with pytest.raises(UnsafeURLError):
        validate_url("")
    with pytest.raises(UnsafeURLError):
        validate_url("https://example.com/" + "a" * 3000)


def test_public_ip_literal_is_allowed():
    result = validate_url("http://93.184.216.34/", resolve_dns=False)
    assert result.hostname == "93.184.216.34"


def test_scheme_is_normalised_and_fragment_stripped():
    result = validate_url("HTTPS://Example.COM/path#fragment", resolve_dns=False)
    assert result.scheme == "https"
    assert "#" not in result.url


def test_dns_failure_is_an_error_not_a_pass():
    """A name that will not resolve must fail closed."""
    with pytest.raises(UnsafeURLError):
        validate_url("https://this-domain-should-not-exist-pas-test-9x8y7z.invalid/")


def test_ipv4_mapped_ipv6_does_not_bypass_loopback_check():
    """::ffff:127.0.0.1 is not flagged loopback by ipaddress directly."""
    with pytest.raises(UnsafeURLError) as exc:
        validate_url("http://[::ffff:127.0.0.1]/")
    assert "loopback" in str(exc.value)
