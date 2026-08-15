"""Storage, versioning, tenant isolation and strategy memory tests."""

from __future__ import annotations

import sqlite3

import pytest

from pas.domain.enums import DecisionState
from pas.storage import repositories as repo


def test_migrations_are_idempotent(conn):
    from pas.storage.db import migrate

    assert migrate(conn) == []  # already applied by the fixture


def test_foreign_keys_are_enforced(conn):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO analyses (id, workspace_id, product_id, version, started_at)"
            " VALUES ('a', 'nope', 'nope', 1, 'now')"
        )


def test_analysis_versions_increment_and_never_overwrite(conn, workspace, product):
    first = repo.create_analysis(conn, workspace_id=workspace, product_id=product)
    second = repo.create_analysis(conn, workspace_id=workspace, product_id=product)
    third = repo.create_analysis(conn, workspace_id=workspace, product_id=product)

    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]
    assert len(repo.list_analyses(conn, product)) == 3


def test_deleting_a_product_cascades_to_derived_intelligence(conn, workspace, product, analysis):
    repo.record_evidence(
        conn,
        workspace_id=workspace,
        analysis_id=analysis,
        claim="c",
        detail="d",
        grade="ai_hypothesis",
        confidence=0.5,
        agent="test",
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"] == 1

    repo.delete_product(conn, product, workspace)
    assert conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM analyses").fetchone()["c"] == 0


def test_workspace_isolation_on_reads(conn, workspace, product):
    other = "ws_other"
    conn.execute(
        "INSERT INTO workspaces (id, name, created_at) VALUES (?, 'Other', 'now')", (other,)
    )
    conn.commit()

    assert repo.get_product(conn, product, other) is None
    assert repo.get_product(conn, product, workspace) is not None
    assert repo.list_products(conn, other) == []


def test_evidence_citations_deduplicate_sources(conn, workspace, analysis):
    citation = {"url": "https://example.com/pricing", "title": "Pricing", "source_type": "pricing_page"}
    repo.record_evidence(
        conn, workspace_id=workspace, analysis_id=analysis, claim="a", detail="",
        grade="verified_fact", confidence=0.9, agent="t", citations=[citation],
    )
    repo.record_evidence(
        conn, workspace_id=workspace, analysis_id=analysis, claim="b", detail="",
        grade="verified_fact", confidence=0.9, agent="t", citations=[citation],
    )
    conn.commit()

    sources = repo.list_sources(conn, analysis)
    assert len(sources) == 1, "the same URL must reuse one source row"
    assert sources[0]["citation_count"] == 2


def test_evidence_quality_summary_counts_backed_claims(conn, workspace, analysis):
    for grade in ["verified_fact", "strong_inference", "ai_hypothesis", "ai_hypothesis"]:
        repo.record_evidence(
            conn, workspace_id=workspace, analysis_id=analysis, claim=grade, detail="",
            grade=grade, confidence=0.5, agent="t",
        )
    conn.commit()

    summary = repo.evidence_quality_summary(conn, analysis)
    assert summary["total"] == 4
    assert summary["evidence_backed"] == 2
    assert summary["evidence_backed_ratio"] == 0.5


def test_confidence_is_clamped(conn, workspace, analysis):
    repo.record_evidence(
        conn, workspace_id=workspace, analysis_id=analysis, claim="x", detail="",
        grade="ai_hypothesis", confidence=5.0, agent="t",
    )
    conn.commit()
    assert repo.list_evidence(conn, analysis)[0]["confidence"] == 1.0


def test_rejected_recommendations_are_not_resurfaced(conn, workspace, product):
    """Spec 19/22: a rejected recommendation stays rejected across versions."""
    first = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.save_recommendations(
        conn, workspace_id=workspace, analysis_id=first, product_id=product,
        recommendations=[{"title": "Add SSO support", "gap_category": "security"}],
    )
    rec = repo.list_recommendations(conn, first)[0]
    repo.decide_recommendation(conn, rec["id"], state=DecisionState.REJECTED.value, note="Too early")

    second = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.save_recommendations(
        conn, workspace_id=workspace, analysis_id=second, product_id=product,
        recommendations=[{"title": "add sso support", "gap_category": "Security"}],
    )
    reissued = repo.list_recommendations(conn, second)[0]

    assert reissued["decision_state"] == DecisionState.REJECTED.value
    assert reissued["decision_note"] == "Too early"


def test_fingerprint_is_stable_across_wording_noise():
    a = repo.fingerprint_recommendation("Add SSO support", "security")
    b = repo.fingerprint_recommendation("add  SSO   support!", "Security")
    c = repo.fingerprint_recommendation("Add SAML support", "security")
    assert a == b
    assert a != c


def test_decisions_are_written_to_strategy_memory(conn, workspace, product):
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.save_recommendations(
        conn, workspace_id=workspace, analysis_id=analysis, product_id=product,
        recommendations=[{"title": "Build mobile app", "gap_category": "mobile"}],
    )
    rec = repo.list_recommendations(conn, analysis)[0]
    repo.decide_recommendation(conn, rec["id"], state=DecisionState.REJECTED.value, note="No demand")

    memory = repo.list_memory(conn, product)
    assert any(m["kind"] == "decision_rejected" and "mobile" in m["summary"].lower() for m in memory)


def test_usage_summary_aggregates_cost(conn, workspace, analysis):
    for model, cost in [("fast", 0.001), ("fast", 0.002), ("deep", 0.01)]:
        repo.record_usage(
            conn, workspace_id=workspace, analysis_id=analysis, agent_run_id=None,
            provider="openrouter", model=model, prompt_tokens=10, completion_tokens=5,
            total_tokens=15, cost_usd=cost, latency_ms=100,
        )
    summary = repo.usage_summary(conn, workspace, analysis)
    assert summary["calls"] == 3
    assert summary["cost"] == pytest.approx(0.013)
    assert len(summary["by_model"]) == 2


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


def test_statement_splitter_handles_comments_and_literals():
    from pas.storage.db import split_statements

    script = """
    -- a leading comment
    CREATE TABLE t (a TEXT);
    INSERT INTO t (a) VALUES ('has ; a semicolon');
    -- trailing comment
    CREATE INDEX ix ON t(a);
    """
    statements = split_statements(script)
    assert len(statements) == 3
    assert "has ; a semicolon" in statements[1]
    assert statements[2].startswith("CREATE INDEX")


def test_failed_migration_rolls_back_completely(tmp_path, monkeypatch):
    """A migration that fails part-way must leave NOTHING behind.

    `executescript` issues an implicit COMMIT, which previously let a failing
    migration half-apply and then be unable to re-run.
    """
    from pas.storage import db as db_module

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_ok.sql").write_text(
        "CREATE TABLE alpha (id TEXT PRIMARY KEY);", encoding="utf-8"
    )
    # The second statement is invalid, so the whole file must roll back.
    (migrations / "002_broken.sql").write_text(
        "CREATE TABLE beta (id TEXT PRIMARY KEY);\n"
        "CREATE INDEX ix_dupe ON nonexistent_table(id);",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations)

    db_module.reset_thread_state()
    conn = db_module.get_connection(tmp_path / "m.sqlite3")

    with pytest.raises(sqlite3.OperationalError):
        db_module.migrate(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "alpha" in tables, "the successful migration should have applied"
    assert "beta" not in tables, "the failed migration must leave nothing behind"

    applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    assert applied == {"001_ok.sql"}
    db_module.reset_thread_state()


def test_index_names_are_unique_across_migrations():
    """SQLite index names are global, so a collision breaks migration."""
    import re
    from pas.storage.db import MIGRATIONS_DIR

    seen: dict[str, str] = {}
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        for name in re.findall(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(\w+)", sql_file.read_text(encoding="utf-8"), re.I
        ):
            assert name not in seen, (
                f"index '{name}' declared in both {seen[name]} and {sql_file.name}"
            )
            seen[name] = sql_file.name


def test_all_migrations_apply_to_a_fresh_database(tmp_path):
    from pas.storage import db as db_module

    db_module.reset_thread_state()
    conn = db_module.get_connection(tmp_path / "fresh.sqlite3")
    applied = db_module.migrate(conn)
    assert len(applied) >= 4
    assert db_module.migrate(conn) == [], "re-running must be a no-op"
    db_module.reset_thread_state()
