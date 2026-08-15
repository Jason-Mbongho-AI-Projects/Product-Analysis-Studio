"""Data access for Product Analysis Studio.

Every read is workspace-scoped. Callers pass ``workspace_id`` explicitly rather
than relying on ambient state, which is what keeps one workspace's intelligence
out of another's (spec 42).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from ..domain.enums import (
    SCORE_WEIGHTS,
    AnalysisStatus,
    DecisionState,
    EvidenceGrade,
    ScoreDimension,
)

DEFAULT_WORKSPACE_ID = "ws_default"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _row(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row else None


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


# ---------------------------------------------------------------------------
# Workspaces and products
# ---------------------------------------------------------------------------


def ensure_default_workspace(conn: sqlite3.Connection) -> str:
    existing = conn.execute(
        "SELECT id FROM workspaces WHERE id = ?", (DEFAULT_WORKSPACE_ID,)
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO workspaces (id, name, created_at) VALUES (?, ?, ?)",
            (DEFAULT_WORKSPACE_ID, "My Workspace", utcnow()),
        )
        conn.commit()
    return DEFAULT_WORKSPACE_ID


def create_product(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    name: str,
    intake_kind: str,
    intake_input: str,
    source_url: str | None = None,
    one_liner: str = "",
    **fields: Any,
) -> str:
    product_id = new_id("prd")
    now = utcnow()
    conn.execute(
        """
        INSERT INTO products (
            id, workspace_id, name, one_liner, intake_kind, intake_input, source_url,
            category, subcategory, industry, business_model, market_segment,
            maturity, revenue_model, metadata_json, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            product_id,
            workspace_id,
            name,
            one_liner,
            intake_kind,
            intake_input,
            source_url,
            fields.get("category", ""),
            fields.get("subcategory", ""),
            fields.get("industry", ""),
            fields.get("business_model", "other"),
            fields.get("market_segment", "b2b"),
            fields.get("maturity", "idea"),
            fields.get("revenue_model", ""),
            json.dumps(fields.get("metadata", {})),
            now,
            now,
        ),
    )
    conn.commit()
    return product_id


def update_product_classification(
    conn: sqlite3.Connection, product_id: str, **fields: Any
) -> None:
    allowed = {
        "name",
        "one_liner",
        "category",
        "subcategory",
        "industry",
        "business_model",
        "market_segment",
        "maturity",
        "revenue_model",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE products SET {assignments}, updated_at = ? WHERE id = ?",
        (*updates.values(), utcnow(), product_id),
    )
    conn.commit()


def list_products(conn: sqlite3.Connection, workspace_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT p.*,
                   (SELECT COUNT(*) FROM analyses a WHERE a.product_id = p.id) AS analysis_count,
                   (SELECT MAX(version) FROM analyses a WHERE a.product_id = p.id) AS latest_version
            FROM products p
            WHERE p.workspace_id = ?
            ORDER BY p.updated_at DESC
            """,
            (workspace_id,),
        )
    )


def get_product(
    conn: sqlite3.Connection, product_id: str, workspace_id: str
) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM products WHERE id = ? AND workspace_id = ?",
            (product_id, workspace_id),
        )
    )


def delete_product(conn: sqlite3.Connection, product_id: str, workspace_id: str) -> None:
    """Delete a product and everything derived from it (spec 42)."""
    conn.execute(
        "DELETE FROM products WHERE id = ? AND workspace_id = ?",
        (product_id, workspace_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Analyses (versioned, never overwritten)
# ---------------------------------------------------------------------------


def create_analysis(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    mode: str = "founder",
    research_enabled: bool = True,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM analyses WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    version = int(row["v"]) + 1

    analysis_id = new_id("anl")
    conn.execute(
        """
        INSERT INTO analyses (id, workspace_id, product_id, version, mode, status,
                              research_enabled, started_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            analysis_id,
            workspace_id,
            product_id,
            version,
            mode,
            AnalysisStatus.PENDING.value,
            1 if research_enabled else 0,
            utcnow(),
        ),
    )
    conn.commit()
    return {"id": analysis_id, "version": version}


def update_analysis_progress(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    stage: str | None = None,
    error: str | None = None,
    completed: bool = False,
) -> None:
    updates: dict[str, Any] = {}
    if status is not None:
        updates["status"] = status
    if progress is not None:
        updates["progress"] = max(0.0, min(1.0, progress))
    if stage is not None:
        updates["stage"] = stage
    if error is not None:
        updates["error"] = error
    if completed:
        updates["completed_at"] = utcnow()
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE analyses SET {assignments} WHERE id = ?",
        (*updates.values(), analysis_id),
    )
    conn.commit()


def get_analysis(
    conn: sqlite3.Connection, analysis_id: str, workspace_id: str
) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM analyses WHERE id = ? AND workspace_id = ?",
            (analysis_id, workspace_id),
        )
    )


def list_analyses(conn: sqlite3.Connection, product_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM analyses WHERE product_id = ? ORDER BY version DESC",
            (product_id,),
        )
    )


def latest_analysis(
    conn: sqlite3.Connection, product_id: str, only_usable: bool = True
) -> dict[str, Any] | None:
    clause = ""
    params: list[Any] = [product_id]
    if only_usable:
        clause = " AND status IN (?, ?, ?)"
        params += [
            AnalysisStatus.COMPLETE.value,
            AnalysisStatus.PARTIAL.value,
            AnalysisStatus.RUNNING.value,
        ]
    return _row(
        conn.execute(
            f"SELECT * FROM analyses WHERE product_id = ?{clause} ORDER BY version DESC LIMIT 1",
            params,
        )
    )


# ---------------------------------------------------------------------------
# Sources and evidence
# ---------------------------------------------------------------------------


def upsert_source(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    analysis_id: str | None,
    url: str | None,
    title: str,
    source_type: str,
    published_date: str | None = None,
    fetched_at: str | None = None,
    status: str = "active",
    reliability: float = 0.5,
    content_hash: str | None = None,
    excerpt: str = "",
    failure_reason: str | None = None,
) -> str:
    """Insert a source, reusing an existing row for the same URL in the analysis.

    Deduplication matters: the same pricing page cited by four agents should be
    one row with four citations, not four rows (spec 38).
    """
    if url:
        existing = conn.execute(
            "SELECT id FROM sources WHERE workspace_id = ? AND url = ?"
            " AND (analysis_id IS ? OR analysis_id = ?)",
            (workspace_id, url, analysis_id, analysis_id),
        ).fetchone()
        if existing:
            return existing["id"]

    source_id = new_id("src")
    conn.execute(
        """
        INSERT INTO sources (id, workspace_id, analysis_id, url, title, source_type,
                             published_date, fetched_at, status, reliability,
                             content_hash, excerpt, failure_reason, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            source_id,
            workspace_id,
            analysis_id,
            url,
            title,
            source_type,
            published_date,
            fetched_at,
            status,
            reliability,
            content_hash,
            excerpt[:4000],
            failure_reason,
            utcnow(),
        ),
    )
    return source_id


def set_source_status(conn: sqlite3.Connection, source_id: str, status: str) -> None:
    conn.execute("UPDATE sources SET status = ? WHERE id = ?", (status, source_id))
    conn.commit()


def list_sources(conn: sqlite3.Connection, analysis_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM evidence_sources es WHERE es.source_id = s.id)
                       AS citation_count
            FROM sources s WHERE s.analysis_id = ?
            ORDER BY s.created_at
            """,
            (analysis_id,),
        )
    )


def record_evidence(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    analysis_id: str,
    claim: str,
    detail: str,
    grade: str,
    confidence: float,
    agent: str,
    subject_type: str = "",
    subject_id: str | None = None,
    citations: Sequence[dict[str, Any]] = (),
) -> str:
    evidence_id = new_id("evd")
    conn.execute(
        """
        INSERT INTO evidence (id, workspace_id, analysis_id, claim, detail, grade,
                              confidence, agent, subject_type, subject_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            evidence_id,
            workspace_id,
            analysis_id,
            claim,
            detail,
            grade,
            max(0.0, min(1.0, confidence)),
            agent,
            subject_type,
            subject_id,
            utcnow(),
        ),
    )

    for citation in citations:
        source_id = upsert_source(
            conn,
            workspace_id=workspace_id,
            analysis_id=analysis_id,
            url=citation.get("url"),
            title=citation.get("title") or "Untitled source",
            source_type=citation.get("source_type") or "other",
            published_date=citation.get("published_date"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO evidence_sources (evidence_id, source_id) VALUES (?, ?)",
            (evidence_id, source_id),
        )
    return evidence_id


def list_evidence(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    grades: Iterable[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses = ["e.analysis_id = ?"]
    params: list[Any] = [analysis_id]
    if subject_type:
        clauses.append("e.subject_type = ?")
        params.append(subject_type)
    if subject_id:
        clauses.append("e.subject_id = ?")
        params.append(subject_id)
    grades = list(grades or [])
    if grades:
        clauses.append(f"e.grade IN ({','.join('?' * len(grades))})")
        params.extend(grades)
    params.append(limit)

    evidence = _rows(
        conn.execute(
            f"""
            SELECT * FROM evidence e
            WHERE {' AND '.join(clauses)}
            ORDER BY e.confidence DESC, e.created_at
            LIMIT ?
            """,
            params,
        )
    )
    if not evidence:
        return []

    ids = [item["id"] for item in evidence]
    citations = _rows(
        conn.execute(
            f"""
            SELECT es.evidence_id, s.id, s.url, s.title, s.source_type, s.published_date
            FROM evidence_sources es
            JOIN sources s ON s.id = es.source_id
            WHERE es.evidence_id IN ({','.join('?' * len(ids))})
            """,
            ids,
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for citation in citations:
        grouped.setdefault(citation["evidence_id"], []).append(citation)
    for item in evidence:
        item["citations"] = grouped.get(item["id"], [])
    return evidence


def evidence_quality_summary(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any]:
    """Aggregate counts per grade, for the data-quality banner (spec 35)."""
    rows = _rows(
        conn.execute(
            "SELECT grade, COUNT(*) AS n, AVG(confidence) AS avg_conf"
            " FROM evidence WHERE analysis_id = ? GROUP BY grade",
            (analysis_id,),
        )
    )
    by_grade = {row["grade"]: row for row in rows}
    total = sum(row["n"] for row in rows) or 0
    backed = sum(
        row["n"]
        for row in rows
        if EvidenceGrade(row["grade"]).is_evidence_backed
    )
    sourced = conn.execute(
        "SELECT COUNT(DISTINCT source_id) AS n FROM evidence_sources es"
        " JOIN evidence e ON e.id = es.evidence_id WHERE e.analysis_id = ?",
        (analysis_id,),
    ).fetchone()["n"]
    return {
        "total": total,
        "by_grade": by_grade,
        "evidence_backed": backed,
        "evidence_backed_ratio": (backed / total) if total else 0.0,
        "distinct_sources": sourced,
    }


# ---------------------------------------------------------------------------
# Profile, features, scores
# ---------------------------------------------------------------------------


def save_product_profile(
    conn: sqlite3.Connection, analysis_id: str, profile: dict[str, Any]
) -> None:
    conn.execute("DELETE FROM product_profiles WHERE analysis_id = ?", (analysis_id,))
    conn.execute("DELETE FROM product_features WHERE analysis_id = ?", (analysis_id,))
    conn.execute(
        """
        INSERT INTO product_profiles (id, analysis_id, summary, primary_problem,
            pricing_model, distribution_model, switching_costs, defensibility,
            lists_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            new_id("pfl"),
            analysis_id,
            profile.get("summary", ""),
            profile.get("primary_problem", ""),
            profile.get("pricing_model", ""),
            profile.get("distribution_model", ""),
            profile.get("switching_costs", ""),
            profile.get("defensibility", ""),
            json.dumps(profile.get("lists", {})),
            utcnow(),
        ),
    )
    for feature in profile.get("features", []):
        conn.execute(
            "INSERT INTO product_features (id, analysis_id, name, description, grade)"
            " VALUES (?,?,?,?,?)",
            (
                new_id("ftr"),
                analysis_id,
                feature.get("name", ""),
                feature.get("description", ""),
                feature.get("grade", EvidenceGrade.AI_HYPOTHESIS.value),
            ),
        )
    conn.commit()


def get_product_profile(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    profile = _row(
        conn.execute("SELECT * FROM product_profiles WHERE analysis_id = ?", (analysis_id,))
    )
    if not profile:
        return None
    profile["lists"] = loads(profile.pop("lists_json", "{}"), {})
    profile["features"] = _rows(
        conn.execute(
            "SELECT name, description, grade FROM product_features WHERE analysis_id = ?",
            (analysis_id,),
        )
    )
    return profile


def save_scores(
    conn: sqlite3.Connection, analysis_id: str, scores: Sequence[dict[str, Any]]
) -> None:
    conn.execute("DELETE FROM product_scores WHERE analysis_id = ?", (analysis_id,))
    now = utcnow()
    for entry in scores:
        dimension = ScoreDimension(entry["dimension"])
        conn.execute(
            """
            INSERT INTO product_scores (id, analysis_id, dimension, score, weight,
                inverted, explanation, confidence, assumptions_json, evidence_json,
                calculated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("scr"),
                analysis_id,
                dimension.value,
                max(0.0, min(100.0, float(entry.get("score", 0)))),
                SCORE_WEIGHTS.get(dimension, 0.0),
                1 if dimension.is_inverted else 0,
                entry.get("explanation", ""),
                float(entry.get("confidence", 0.5)),
                json.dumps(entry.get("assumptions", [])),
                json.dumps(entry.get("supporting_evidence", [])),
                now,
            ),
        )
    conn.commit()


def get_scores(conn: sqlite3.Connection, analysis_id: str) -> list[dict[str, Any]]:
    scores = _rows(
        conn.execute(
            "SELECT * FROM product_scores WHERE analysis_id = ? ORDER BY weight DESC",
            (analysis_id,),
        )
    )
    for score in scores:
        score["assumptions"] = loads(score.pop("assumptions_json", "[]"), [])
        score["supporting_evidence"] = loads(score.pop("evidence_json", "[]"), [])
    return scores


# ---------------------------------------------------------------------------
# Competitors
# ---------------------------------------------------------------------------


def save_competitor(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    analysis_id: str,
    data: dict[str, Any],
    is_user_added: bool = False,
    position: int = 0,
) -> str:
    competitor_id = new_id("cmp")
    conn.execute(
        """
        INSERT INTO competitors (id, workspace_id, analysis_id, name, company, website,
            competitor_type, positioning, target_customer, pricing_summary, threat_level,
            rationale, grade, confidence, strengths_json, weaknesses_json, is_user_added,
            pinned, position, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            competitor_id,
            workspace_id,
            analysis_id,
            data.get("name", ""),
            data.get("company", ""),
            data.get("website"),
            data.get("competitor_type", "direct"),
            data.get("positioning", ""),
            data.get("target_customer", ""),
            data.get("pricing_summary", ""),
            data.get("threat_level", "medium"),
            data.get("rationale", ""),
            data.get("grade", EvidenceGrade.AI_HYPOTHESIS.value),
            float(data.get("confidence", 0.5)),
            json.dumps(data.get("strengths", [])),
            json.dumps(data.get("weaknesses", [])),
            1 if is_user_added else 0,
            0,
            position,
            utcnow(),
        ),
    )
    for feature in data.get("known_features", []):
        conn.execute(
            "INSERT INTO competitor_features (id, competitor_id, name) VALUES (?,?,?)",
            (new_id("cft"), competitor_id, feature),
        )
    conn.commit()
    return competitor_id


def list_competitors(conn: sqlite3.Connection, analysis_id: str) -> list[dict[str, Any]]:
    competitors = _rows(
        conn.execute(
            "SELECT * FROM competitors WHERE analysis_id = ?"
            " ORDER BY pinned DESC, position, created_at",
            (analysis_id,),
        )
    )
    if not competitors:
        return []
    ids = [c["id"] for c in competitors]
    features = _rows(
        conn.execute(
            f"SELECT competitor_id, name FROM competitor_features"
            f" WHERE competitor_id IN ({','.join('?' * len(ids))})",
            ids,
        )
    )
    grouped: dict[str, list[str]] = {}
    for feature in features:
        grouped.setdefault(feature["competitor_id"], []).append(feature["name"])
    for competitor in competitors:
        competitor["strengths"] = loads(competitor.pop("strengths_json", "[]"), [])
        competitor["weaknesses"] = loads(competitor.pop("weaknesses_json", "[]"), [])
        competitor["features"] = grouped.get(competitor["id"], [])
    return competitors


def set_competitor_pinned(conn: sqlite3.Connection, competitor_id: str, pinned: bool) -> None:
    conn.execute(
        "UPDATE competitors SET pinned = ? WHERE id = ?", (1 if pinned else 0, competitor_id)
    )
    conn.commit()


def delete_competitor(conn: sqlite3.Connection, competitor_id: str) -> None:
    conn.execute("DELETE FROM competitors WHERE id = ?", (competitor_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Market and customers
# ---------------------------------------------------------------------------


def save_market(conn: sqlite3.Connection, analysis_id: str, data: dict[str, Any]) -> None:
    conn.execute("DELETE FROM market_analyses WHERE analysis_id = ?", (analysis_id,))
    conn.execute("DELETE FROM market_models WHERE analysis_id = ?", (analysis_id,))
    conn.execute(
        """
        INSERT INTO market_analyses (id, analysis_id, market_definition, maturity,
            competitive_concentration, entry_barriers_json, adjacent_markets_json, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            new_id("mkt"),
            analysis_id,
            data.get("market_definition", ""),
            data.get("maturity", ""),
            data.get("competitive_concentration", ""),
            json.dumps(data.get("entry_barriers", [])),
            json.dumps(data.get("adjacent_markets", [])),
            utcnow(),
        ),
    )
    for model in data.get("sizing", []):
        conn.execute(
            """
            INSERT INTO market_models (id, analysis_id, label, value_usd, formula,
                variables_json, assumptions_json, basis, confidence, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("msm"),
                analysis_id,
                model.get("label", ""),
                float(model.get("value_usd", 0) or 0),
                model.get("formula", ""),
                json.dumps(model.get("variables", [])),
                json.dumps(model.get("assumptions", [])),
                model.get("basis", "top_down"),
                float(model.get("confidence", 0.4)),
                utcnow(),
            ),
        )
    conn.commit()


def get_market(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    market = _row(
        conn.execute("SELECT * FROM market_analyses WHERE analysis_id = ?", (analysis_id,))
    )
    if not market:
        return None
    market["entry_barriers"] = loads(market.pop("entry_barriers_json", "[]"), [])
    market["adjacent_markets"] = loads(market.pop("adjacent_markets_json", "[]"), [])
    models = _rows(
        conn.execute(
            "SELECT * FROM market_models WHERE analysis_id = ? ORDER BY value_usd DESC",
            (analysis_id,),
        )
    )
    for model in models:
        model["variables"] = loads(model.pop("variables_json", "[]"), [])
        model["assumptions"] = loads(model.pop("assumptions_json", "[]"), [])
    market["sizing"] = models
    return market


def save_customers(conn: sqlite3.Connection, analysis_id: str, data: dict[str, Any]) -> None:
    conn.execute("DELETE FROM customer_profiles WHERE analysis_id = ?", (analysis_id,))
    conn.execute("DELETE FROM personas WHERE analysis_id = ?", (analysis_id,))
    conn.execute(
        "INSERT INTO customer_profiles (id, analysis_id, icp, switching_concerns_json,"
        " created_at) VALUES (?,?,?,?,?)",
        (
            new_id("cst"),
            analysis_id,
            data.get("icp", ""),
            json.dumps(data.get("switching_concerns", [])),
            utcnow(),
        ),
    )
    for persona in data.get("personas", []):
        detail = {
            key: persona.get(key, [])
            for key in (
                "jobs_to_be_done",
                "pain_points",
                "desired_outcomes",
                "buying_triggers",
                "objections",
                "decision_criteria",
                "current_alternatives",
            )
        }
        conn.execute(
            """
            INSERT INTO personas (id, analysis_id, name, is_buyer, is_user, grade,
                confidence, detail_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("psn"),
                analysis_id,
                persona.get("name", ""),
                1 if persona.get("is_buyer") else 0,
                1 if persona.get("is_user") else 0,
                persona.get("grade", EvidenceGrade.AI_HYPOTHESIS.value),
                float(persona.get("confidence", 0.5)),
                json.dumps(detail),
                utcnow(),
            ),
        )
    conn.commit()


def get_customers(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    profile = _row(
        conn.execute("SELECT * FROM customer_profiles WHERE analysis_id = ?", (analysis_id,))
    )
    if not profile:
        return None
    profile["switching_concerns"] = loads(profile.pop("switching_concerns_json", "[]"), [])
    personas = _rows(
        conn.execute(
            "SELECT * FROM personas WHERE analysis_id = ? ORDER BY confidence DESC",
            (analysis_id,),
        )
    )
    for persona in personas:
        persona["detail"] = loads(persona.pop("detail_json", "{}"), {})
    profile["personas"] = personas
    return profile


# ---------------------------------------------------------------------------
# Recommendations, decisions, roadmap
# ---------------------------------------------------------------------------


def fingerprint_recommendation(title: str, category: str) -> str:
    """Stable identity for "have we recommended this before?" (spec 19/22)."""
    import hashlib
    import re

    normalised = re.sub(r"[^a-z0-9 ]", "", f"{category} {title}".lower())
    normalised = " ".join(sorted(normalised.split()))
    return hashlib.sha256(normalised.encode()).hexdigest()[:24]


def save_recommendations(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    analysis_id: str,
    product_id: str,
    recommendations: Sequence[dict[str, Any]],
) -> list[str]:
    """Persist recommendations, inheriting prior decisions on repeat suggestions.

    If the user previously rejected an equivalent recommendation, the new row is
    created already-rejected rather than resurfacing as pending noise.
    """
    prior = {
        row["fingerprint"]: row
        for row in _rows(
            conn.execute(
                "SELECT fingerprint, decision_state, decision_note FROM recommendations"
                " WHERE product_id = ? AND decision_state != ?",
                (product_id, DecisionState.PENDING.value),
            )
        )
    }

    ids: list[str] = []
    for entry in recommendations:
        fingerprint = fingerprint_recommendation(
            entry.get("title", ""), entry.get("gap_category", "")
        )
        previous = prior.get(fingerprint)
        rec_id = new_id("rec")
        conn.execute(
            """
            INSERT INTO recommendations (id, workspace_id, analysis_id, product_id, title,
                gap_category, problem, recommendation, verdict, reason, customer_impact,
                competitive_impact, effort, risk, expected_outcome, dependencies_json,
                evidence_json, priority, confidence, decision_state, decision_note,
                decided_at, fingerprint, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rec_id,
                workspace_id,
                analysis_id,
                product_id,
                entry.get("title", ""),
                entry.get("gap_category", ""),
                entry.get("problem", ""),
                entry.get("recommendation", ""),
                entry.get("verdict", "should_build"),
                entry.get("reason", ""),
                entry.get("customer_impact", ""),
                entry.get("competitive_impact", ""),
                entry.get("effort", "m"),
                entry.get("risk", ""),
                entry.get("expected_outcome", ""),
                json.dumps(entry.get("dependencies", [])),
                json.dumps(entry.get("supporting_evidence", [])),
                int(entry.get("priority", 99)),
                float(entry.get("confidence", 0.5)),
                previous["decision_state"] if previous else DecisionState.PENDING.value,
                previous["decision_note"] if previous else "",
                utcnow() if previous else None,
                fingerprint,
                utcnow(),
            ),
        )
        ids.append(rec_id)
    conn.commit()
    return ids


def list_recommendations(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    decision_state: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["analysis_id = ?"]
    params: list[Any] = [analysis_id]
    if decision_state:
        clauses.append("decision_state = ?")
        params.append(decision_state)
    rows = _rows(
        conn.execute(
            f"SELECT * FROM recommendations WHERE {' AND '.join(clauses)}"
            " ORDER BY priority, confidence DESC",
            params,
        )
    )
    for row in rows:
        row["dependencies"] = loads(row.pop("dependencies_json", "[]"), [])
        row["supporting_evidence"] = loads(row.pop("evidence_json", "[]"), [])
    return rows


def decide_recommendation(
    conn: sqlite3.Connection,
    recommendation_id: str,
    *,
    state: str,
    note: str = "",
) -> dict[str, Any] | None:
    conn.execute(
        "UPDATE recommendations SET decision_state = ?, decision_note = ?, decided_at = ?"
        " WHERE id = ?",
        (state, note, utcnow(), recommendation_id),
    )
    conn.commit()
    rec = _row(
        conn.execute("SELECT * FROM recommendations WHERE id = ?", (recommendation_id,))
    )
    if rec:
        record_memory(
            conn,
            workspace_id=rec["workspace_id"],
            product_id=rec["product_id"],
            kind=f"decision_{state}",
            summary=rec["title"],
            detail=note or rec["reason"],
            payload={"fingerprint": rec["fingerprint"], "verdict": rec["verdict"]},
        )
    return rec


def add_roadmap_item(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    title: str,
    detail: str = "",
    horizon: str = "next",
    effort: str = "m",
    recommendation_id: str | None = None,
) -> str:
    position_row = conn.execute(
        "SELECT COALESCE(MAX(position), 0) AS p FROM roadmap_items"
        " WHERE product_id = ? AND horizon = ?",
        (product_id, horizon),
    ).fetchone()
    item_id = new_id("rdm")
    conn.execute(
        """
        INSERT INTO roadmap_items (id, workspace_id, product_id, recommendation_id, title,
            detail, horizon, status, owner, due_date, effort, position, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            item_id,
            workspace_id,
            product_id,
            recommendation_id,
            title,
            detail,
            horizon,
            "planned",
            "",
            None,
            effort,
            int(position_row["p"]) + 1,
            utcnow(),
        ),
    )
    conn.commit()
    return item_id


def list_roadmap(conn: sqlite3.Connection, product_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM roadmap_items WHERE product_id = ? ORDER BY horizon, position",
            (product_id,),
        )
    )


def move_roadmap_item(
    conn: sqlite3.Connection, item_id: str, horizon: str, status: str | None = None
) -> None:
    if status:
        conn.execute(
            "UPDATE roadmap_items SET horizon = ?, status = ? WHERE id = ?",
            (horizon, status, item_id),
        )
    else:
        conn.execute("UPDATE roadmap_items SET horizon = ? WHERE id = ?", (horizon, item_id))
    conn.commit()


def delete_roadmap_item(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute("DELETE FROM roadmap_items WHERE id = ?", (item_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Strategy memory and observability
# ---------------------------------------------------------------------------


def record_memory(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    kind: str,
    summary: str,
    detail: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    memory_id = new_id("mem")
    conn.execute(
        "INSERT INTO strategy_memory (id, workspace_id, product_id, kind, summary,"
        " detail, payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            memory_id,
            workspace_id,
            product_id,
            kind,
            summary,
            detail,
            json.dumps(payload or {}),
            utcnow(),
        ),
    )
    conn.commit()
    return memory_id


def list_memory(
    conn: sqlite3.Connection, product_id: str, kinds: Iterable[str] | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    kinds = list(kinds or [])
    clause = ""
    params: list[Any] = [product_id]
    if kinds:
        clause = f" AND kind IN ({','.join('?' * len(kinds))})"
        params.extend(kinds)
    params.append(limit)
    rows = _rows(
        conn.execute(
            f"SELECT * FROM strategy_memory WHERE product_id = ?{clause}"
            " ORDER BY created_at DESC LIMIT ?",
            params,
        )
    )
    for row in rows:
        row["payload"] = loads(row.pop("payload_json", "{}"), {})
    return rows


def start_agent_run(
    conn: sqlite3.Connection, analysis_id: str, agent: str, model: str
) -> str:
    run_id = new_id("run")
    conn.execute(
        "INSERT INTO agent_runs (id, analysis_id, agent, status, model, started_at)"
        " VALUES (?,?,?,?,?,?)",
        (run_id, analysis_id, agent, "running", model, utcnow()),
    )
    conn.commit()
    return run_id


def finish_agent_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    duration_ms: int,
    attempts: int = 1,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE agent_runs SET status = ?, duration_ms = ?, attempts = ?, error = ?,"
        " finished_at = ? WHERE id = ?",
        (status, duration_ms, attempts, error, utcnow(), run_id),
    )
    conn.commit()


def list_agent_runs(conn: sqlite3.Connection, analysis_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM agent_runs WHERE analysis_id = ? ORDER BY started_at",
            (analysis_id,),
        )
    )


def record_usage(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    analysis_id: str | None,
    agent_run_id: str | None,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost_usd: float,
    latency_ms: int,
) -> None:
    conn.execute(
        """
        INSERT INTO ai_usage (id, workspace_id, analysis_id, agent_run_id, provider, model,
            prompt_tokens, completion_tokens, total_tokens, cost_usd, latency_ms, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            new_id("usg"),
            workspace_id,
            analysis_id,
            agent_run_id,
            provider,
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cost_usd,
            latency_ms,
            utcnow(),
        ),
    )
    conn.commit()


def usage_summary(
    conn: sqlite3.Connection, workspace_id: str, analysis_id: str | None = None
) -> dict[str, Any]:
    clause = "workspace_id = ?"
    params: list[Any] = [workspace_id]
    if analysis_id:
        clause += " AND analysis_id = ?"
        params.append(analysis_id)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens,
               COALESCE(SUM(cost_usd), 0) AS cost, COALESCE(AVG(latency_ms), 0) AS avg_latency
        FROM ai_usage WHERE {clause}
        """,
        params,
    ).fetchone()
    by_model = _rows(
        conn.execute(
            f"SELECT model, COUNT(*) AS calls, SUM(total_tokens) AS tokens,"
            f" SUM(cost_usd) AS cost FROM ai_usage WHERE {clause} GROUP BY model",
            params,
        )
    )
    return {**dict(row), "by_model": by_model}
