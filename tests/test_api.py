"""HTTP API tests (spec 57) and rate limiting (spec 41).

Driven through Starlette's TestClient, so these exercise the real routing,
authentication and scope enforcement rather than calling handlers directly.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from pas.api import keys as key_store
from pas.api.ratelimit import Bucket, RateLimiter

# ---------------------------------------------------------------------------
# Key issuing and verification
# ---------------------------------------------------------------------------


def test_issued_key_verifies(conn, workspace):
    issued = key_store.issue_key(conn, workspace_id=workspace, name="Test")
    record = key_store.resolve_key(conn, issued.secret)
    assert record is not None
    assert record["workspace_id"] == workspace
    assert record["scope_set"] == {"read"}


def test_secret_is_never_stored_in_the_clear(conn, workspace):
    issued = key_store.issue_key(conn, workspace_id=workspace, name="Test")
    dumped = str([dict(r) for r in conn.execute("SELECT * FROM api_keys").fetchall()])
    assert issued.secret not in dumped
    assert key_store.hash_key(issued.secret) in dumped


def test_listing_keys_never_returns_a_secret(conn, workspace):
    issued = key_store.issue_key(conn, workspace_id=workspace, name="Test")
    listed = key_store.list_keys(conn, workspace)
    assert len(listed) == 1
    assert issued.secret not in str(listed)
    assert "key_hash" not in listed[0]
    assert listed[0]["key_prefix"] in issued.secret


def test_generated_keys_are_unique_and_high_entropy():
    secrets_seen = {key_store.generate_key() for _ in range(200)}
    assert len(secrets_seen) == 200
    assert all(len(s) > 40 for s in secrets_seen)
    assert all(s.startswith("pas_") for s in secrets_seen)


def test_unknown_and_malformed_keys_are_rejected(conn, workspace):
    key_store.issue_key(conn, workspace_id=workspace, name="Test")
    assert key_store.resolve_key(conn, "") is None
    assert key_store.resolve_key(conn, "not-a-key") is None
    assert key_store.resolve_key(conn, "pas_totally_made_up_value") is None


def test_revoked_key_stops_working(conn, workspace):
    issued = key_store.issue_key(conn, workspace_id=workspace, name="Test")
    key_store.revoke_key(conn, issued.id)
    assert key_store.resolve_key(conn, issued.secret) is None


def test_expired_key_stops_working(conn, workspace):
    issued = key_store.issue_key(
        conn, workspace_id=workspace, name="Test", expires_in_days=1
    )
    assert key_store.resolve_key(conn, issued.secret) is not None

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn.execute("UPDATE api_keys SET expires_at = ?", (past,))
    conn.commit()
    assert key_store.resolve_key(conn, issued.secret) is None


def test_write_scope_is_parsed(conn, workspace):
    issued = key_store.issue_key(
        conn, workspace_id=workspace, name="RW", scopes="read,write"
    )
    record = key_store.resolve_key(conn, issued.secret)
    assert record["scope_set"] == {"read", "write"}


def test_unknown_scope_is_rejected(conn, workspace):
    with pytest.raises(key_store.ApiKeyError, match="Unknown scope"):
        key_store.issue_key(conn, workspace_id=workspace, name="X", scopes="admin")


def test_key_creator_reference_survives_a_missing_user(conn, workspace):
    issued = key_store.issue_key(
        conn, workspace_id=workspace, name="X", created_by="usr_gone"
    )
    assert key_store.resolve_key(conn, issued.secret) is not None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_bucket_allows_up_to_capacity_then_refuses():
    bucket = Bucket(capacity=3, tokens=3, refill_per_second=0)
    assert [bucket.consume()[0] for _ in range(4)] == [True, True, True, False]


def test_bucket_refills_over_time():
    bucket = Bucket(capacity=2, tokens=0, refill_per_second=100)
    time.sleep(0.05)
    allowed, _ = bucket.consume()
    assert allowed


def test_refused_bucket_reports_a_retry_delay():
    bucket = Bucket(capacity=1, tokens=0, refill_per_second=1)
    allowed, retry_after = bucket.consume()
    assert not allowed
    assert retry_after > 0


def test_limiter_is_per_key():
    limiter = RateLimiter(burst_multiplier=1.0)
    for _ in range(60):
        limiter.check("key_a", 60)

    allowed_a, _ = limiter.check("key_a", 60)
    allowed_b, _ = limiter.check("key_b", 60)
    assert not allowed_a, "the exhausted key must be limited"
    assert allowed_b, "a different key must be unaffected"


def test_limiter_prunes_unbounded_growth():
    limiter = RateLimiter()
    for index in range(50):
        limiter.check(f"key_{index}", 60)
    assert limiter.prune(max_buckets=10) == 40


def test_limiter_reset():
    limiter = RateLimiter(burst_multiplier=1.0)
    for _ in range(61):
        limiter.check("k", 60)
    assert not limiter.check("k", 60)[0]
    limiter.reset("k")
    assert limiter.check("k", 60)[0]


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A TestClient wired to an isolated database, plus a read and write key."""
    starlette_testclient = pytest.importorskip("starlette.testclient")

    from pas.storage import db as db_module
    from pas.storage import repositories as repo

    db_module.reset_thread_state()
    db_path = tmp_path / "api.sqlite3"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PAS_DATA_DIR", str(tmp_path))

    conn = db_module.get_connection(db_path)
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(
        conn, workspace_id=workspace, name="API product", intake_kind="idea",
        intake_input="an idea", category="Analytics",
    )
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)
    repo.save_scores(conn, analysis, [
        {"dimension": "market_opportunity", "score": 72, "confidence": 0.6,
         "explanation": "e", "assumptions": [], "supporting_evidence": []}
    ])
    repo.save_competitor(conn, workspace_id=workspace, analysis_id=analysis, data={
        "name": "Rival", "competitor_type": "direct", "threat_level": "high",
    })
    conn.commit()

    read_key = key_store.issue_key(conn, workspace_id=workspace, name="read")
    write_key = key_store.issue_key(
        conn, workspace_id=workspace, name="write", scopes="read,write"
    )

    from pas.api.app import create_app
    from pas.api.ratelimit import limiter

    limiter.reset()
    client = starlette_testclient.TestClient(create_app())

    yield {
        "client": client,
        "read": read_key.secret,
        "write": write_key.secret,
        "product": product,
        "workspace": workspace,
        "conn": conn,
    }
    db_module.reset_thread_state()


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def test_health_needs_no_key(api):
    response = api["client"].get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_endpoints_require_a_key(api):
    for path in ("/v1/products", f"/v1/products/{api['product']}/score"):
        assert api["client"].get(path).status_code == 401


def test_malformed_authorization_header_is_rejected(api):
    client = api["client"]
    assert client.get("/v1/products", headers={"Authorization": "Basic xyz"}).status_code == 401
    assert client.get("/v1/products", headers={"Authorization": "Bearer "}).status_code == 401
    assert client.get(
        "/v1/products", headers={"Authorization": "Bearer pas_fake"}
    ).status_code == 401


def test_read_key_can_list_products(api):
    response = api["client"].get("/v1/products", headers=_auth(api["read"]))
    assert response.status_code == 200
    products = response.json()["products"]
    assert len(products) == 1
    assert products[0]["name"] == "API product"


def test_score_endpoint_returns_dimensions(api):
    response = api["client"].get(
        f"/v1/products/{api['product']}/score", headers=_auth(api["read"])
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["composite"]["score"] > 0
    assert payload["dimensions"][0]["dimension"] == "market_opportunity"


def test_competitors_endpoint(api):
    response = api["client"].get(
        f"/v1/products/{api['product']}/competitors", headers=_auth(api["read"])
    )
    assert response.status_code == 200
    assert response.json()["competitors"][0]["name"] == "Rival"


def test_unknown_product_returns_404(api):
    response = api["client"].get(
        "/v1/products/prd_nope/analysis", headers=_auth(api["read"])
    )
    assert response.status_code == 404


def test_read_key_cannot_start_an_analysis(api):
    """A read key must never be able to spend against the model provider."""
    response = api["client"].post(
        "/v1/products",
        headers=_auth(api["read"]),
        json={"name": "New", "description": "an idea"},
    )
    assert response.status_code == 403
    assert "read-only" in response.json()["error"]


def test_read_key_cannot_ask(api):
    response = api["client"].post(
        f"/v1/products/{api['product']}/ask",
        headers=_auth(api["read"]),
        json={"question": "what should I build?"},
    )
    assert response.status_code == 403


def test_write_key_can_simulate(api):
    """The simulator is deterministic, so this costs nothing."""
    response = api["client"].post(
        "/v1/simulate",
        headers=_auth(api["write"]),
        json={"arpu_monthly": 100, "gross_margin_pct": 80, "cac": 600,
              "monthly_churn_pct": 5, "customers": 100, "elasticity": -1.2},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_economics"]["ltv"] == pytest.approx(1600.0)
    assert payload["unit_economics"]["cac_payback_months"] == pytest.approx(7.5)
    assert "disclaimer" in payload
    # Raising price must reduce customer count.
    rise = next(s for s in payload["price_sensitivity"] if s["price_change_pct"] == 30)
    assert rise["new_customers"] < 100


def test_invalid_json_body_is_a_400(api):
    response = api["client"].post(
        "/v1/simulate", headers=_auth(api["write"]), content=b"{not json"
    )
    assert response.status_code == 400


def test_rate_limit_returns_429_with_retry_after(api):
    from pas.api.ratelimit import limiter

    limiter.reset()
    conn = api["conn"]
    conn.execute("UPDATE api_keys SET rate_per_minute = 2")
    conn.commit()

    statuses = [
        api["client"].get("/v1/products", headers=_auth(api["read"])).status_code
        for _ in range(12)
    ]
    assert 429 in statuses, "the limiter must eventually refuse"

    limited = api["client"].get("/v1/products", headers=_auth(api["read"]))
    if limited.status_code == 429:
        assert "Retry-After" in limited.headers
        assert limited.json()["retry_after_seconds"] > 0
    limiter.reset()


def test_requests_are_logged_for_diagnostics(api):
    from pas.api.ratelimit import limiter

    limiter.reset()
    api["client"].get("/v1/products", headers=_auth(api["read"]))
    usage = key_store.usage_summary(api["conn"], api["workspace"])
    assert usage["requests"] >= 1


def test_key_usage_counter_increments(api):
    from pas.api.ratelimit import limiter

    limiter.reset()
    api["client"].get("/v1/products", headers=_auth(api["read"]))
    keys = key_store.list_keys(api["conn"], api["workspace"])
    read_key = next(k for k in keys if k["name"] == "read")
    assert read_key["request_count"] >= 1
    assert read_key["last_used_at"] is not None


def test_api_is_disabled_by_default():
    from pas.config import AppConfig

    assert AppConfig(api_key="k").api_enabled is False
