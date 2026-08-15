"""Data access for Voice of Customer, radar, scenarios and comments."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Sequence

from .repositories import _row, _rows, loads, new_id, utcnow


# ---------------------------------------------------------------------------
# Feedback ingestion (spec 11)
# ---------------------------------------------------------------------------


def create_batch(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    label: str,
    source_type: str,
    filename: str = "",
) -> str:
    batch_id = new_id("fbb")
    conn.execute(
        "INSERT INTO feedback_batches (id, workspace_id, product_id, label,"
        " source_type, filename, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (batch_id, workspace_id, product_id, label, source_type, filename, "ready", utcnow()),
    )
    conn.commit()
    return batch_id


def add_feedback_items(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    batch_id: str,
    records: Sequence[Any],
    source_type: str = "upload",
) -> tuple[int, int]:
    """Insert feedback, skipping items already stored for this product.

    Returns ``(inserted, duplicates)``. Deduplication is enforced by a unique
    index, so re-uploading an overlapping export cannot inflate a theme's share.
    """
    inserted = 0
    duplicates = 0

    for record in records:
        try:
            conn.execute(
                """
                INSERT INTO feedback_items (id, workspace_id, batch_id, product_id,
                    content, content_hash, author, rating, occurred_at, source_type,
                    created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("fbi"),
                    workspace_id,
                    batch_id,
                    product_id,
                    record.content,
                    record.content_hash,
                    record.author,
                    record.rating,
                    record.occurred_at,
                    source_type,
                    utcnow(),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            duplicates += 1

    conn.execute(
        "UPDATE feedback_batches SET item_count = ? WHERE id = ?", (inserted, batch_id)
    )
    conn.commit()
    return inserted, duplicates


def list_feedback_items(
    conn: sqlite3.Connection, product_id: str, limit: int = 5000
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM feedback_items WHERE product_id = ? ORDER BY created_at LIMIT ?",
            (product_id, limit),
        )
    )


def feedback_item_count(conn: sqlite3.Connection, product_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM feedback_items WHERE product_id = ?", (product_id,)
    ).fetchone()["n"]


def list_batches(conn: sqlite3.Connection, product_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM feedback_batches WHERE product_id = ? ORDER BY created_at DESC",
            (product_id,),
        )
    )


def delete_batch(conn: sqlite3.Connection, batch_id: str) -> None:
    conn.execute("DELETE FROM feedback_batches WHERE id = ?", (batch_id,))
    conn.commit()


def save_feedback_analysis(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    analysis_id: str | None,
    data: dict[str, Any],
) -> str:
    record_id = new_id("fba")
    conn.execute(
        """
        INSERT INTO feedback_analyses (id, workspace_id, product_id, analysis_id,
            items_analysed, overall_sentiment, positive_pct, neutral_pct, negative_pct,
            summary, complaints_json, praise_json, unmet_needs_json, trends_json,
            caveats_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record_id,
            workspace_id,
            product_id,
            analysis_id,
            int(data.get("total_items_analysed", 0) or 0),
            data.get("overall_sentiment", "neutral"),
            float(data.get("sentiment_positive_pct", 0) or 0),
            float(data.get("sentiment_neutral_pct", 0) or 0),
            float(data.get("sentiment_negative_pct", 0) or 0),
            data.get("summary", ""),
            json.dumps(data.get("top_complaints", [])),
            json.dumps(data.get("top_praise", [])),
            json.dumps(data.get("unmet_needs", [])),
            json.dumps(data.get("emerging_trends", [])),
            json.dumps(data.get("caveats", [])),
            utcnow(),
        ),
    )

    for position, cluster in enumerate(data.get("clusters", [])):
        conn.execute(
            """
            INSERT INTO feedback_clusters (id, feedback_analysis_id, label, theme,
                sentiment, summary, share_pct, item_count, is_churn_driver,
                is_feature_request, severity, suggested_action, quotes_json,
                language_json, confidence, position)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("fbc"),
                record_id,
                cluster.get("label", ""),
                cluster.get("theme", "other"),
                cluster.get("sentiment", "neutral"),
                cluster.get("summary", ""),
                float(cluster.get("share_of_feedback", 0) or 0),
                int(cluster.get("item_count", 0) or 0),
                1 if cluster.get("is_churn_driver") else 0,
                1 if cluster.get("is_feature_request") else 0,
                cluster.get("severity", "low"),
                cluster.get("suggested_action", ""),
                json.dumps(cluster.get("representative_quotes", [])),
                json.dumps(cluster.get("customer_language", [])),
                float(cluster.get("confidence", 0.5) or 0.5),
                position,
            ),
        )
    conn.commit()
    return record_id


def latest_feedback_analysis(
    conn: sqlite3.Connection, product_id: str
) -> dict[str, Any] | None:
    record = _row(
        conn.execute(
            "SELECT * FROM feedback_analyses WHERE product_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (product_id,),
        )
    )
    if not record:
        return None
    for key, target in (
        ("complaints_json", "top_complaints"),
        ("praise_json", "top_praise"),
        ("unmet_needs_json", "unmet_needs"),
        ("trends_json", "emerging_trends"),
        ("caveats_json", "caveats"),
    ):
        record[target] = loads(record.pop(key, "[]"), [])

    clusters = _rows(
        conn.execute(
            "SELECT * FROM feedback_clusters WHERE feedback_analysis_id = ?"
            " ORDER BY position",
            (record["id"],),
        )
    )
    for cluster in clusters:
        cluster["quotes"] = loads(cluster.pop("quotes_json", "[]"), [])
        cluster["customer_language"] = loads(cluster.pop("language_json", "[]"), [])
    record["clusters"] = clusters
    return record


def list_feedback_analyses(
    conn: sqlite3.Connection, product_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT id, created_at, items_analysed, overall_sentiment FROM feedback_analyses"
            " WHERE product_id = ? ORDER BY created_at DESC LIMIT ?",
            (product_id, limit),
        )
    )


# ---------------------------------------------------------------------------
# Radar (spec 27 / 28)
# ---------------------------------------------------------------------------


def save_radar(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    analysis_id: str,
    product_id: str,
    signals: Sequence[dict[str, Any]],
) -> None:
    conn.execute("DELETE FROM radar_signals WHERE analysis_id = ?", (analysis_id,))
    for signal in signals:
        impact = float(signal.get("impact", 0) or 0)
        probability = float(signal.get("probability", 0) or 0)
        conn.execute(
            """
            INSERT INTO radar_signals (id, workspace_id, analysis_id, product_id,
                signal_type, title, category, description, why_now, impact, probability,
                priority_score, horizon, recommended_response, evidence_json,
                confidence, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("rdr"),
                workspace_id,
                analysis_id,
                product_id,
                signal.get("signal_type", "opportunity"),
                signal.get("title", ""),
                signal.get("category", ""),
                signal.get("description", ""),
                signal.get("why_now", ""),
                impact,
                probability,
                # Expected value, so an unlikely catastrophe does not outrank a
                # certain moderate problem.
                round(impact * probability / 100.0, 2),
                signal.get("horizon", "near_term"),
                signal.get("recommended_response", ""),
                json.dumps(signal.get("supporting_evidence", [])),
                float(signal.get("confidence", 0.5) or 0.5),
                utcnow(),
            ),
        )
    conn.commit()


def list_radar(
    conn: sqlite3.Connection, analysis_id: str, signal_type: str | None = None
) -> list[dict[str, Any]]:
    clause = ""
    params: list[Any] = [analysis_id]
    if signal_type:
        clause = " AND signal_type = ?"
        params.append(signal_type)
    signals = _rows(
        conn.execute(
            f"SELECT * FROM radar_signals WHERE analysis_id = ?{clause}"
            " ORDER BY priority_score DESC",
            params,
        )
    )
    for signal in signals:
        signal["supporting_evidence"] = loads(signal.pop("evidence_json", "[]"), [])
    return signals


# ---------------------------------------------------------------------------
# Scenarios (spec 20)
# ---------------------------------------------------------------------------


def save_scenario(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    analysis_id: str | None,
    data: dict[str, Any],
) -> str:
    scenario_id = new_id("sce")
    conn.execute(
        """
        INSERT INTO scenarios (id, workspace_id, product_id, analysis_id, question,
            recommendation, reversibility, assumptions_json, outcomes_json,
            indicators_json, risks_json, confidence, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            scenario_id,
            workspace_id,
            product_id,
            analysis_id,
            data.get("question", ""),
            data.get("recommendation", ""),
            data.get("reversibility", ""),
            json.dumps(data.get("assumptions", [])),
            json.dumps(data.get("outcomes", [])),
            json.dumps(data.get("leading_indicators", [])),
            json.dumps(data.get("risks", [])),
            float(data.get("confidence", 0.5) or 0.5),
            utcnow(),
        ),
    )
    conn.commit()
    return scenario_id


def list_scenario_runs(
    conn: sqlite3.Connection, product_id: str, limit: int = 25
) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            "SELECT * FROM scenarios WHERE product_id = ? ORDER BY created_at DESC LIMIT ?",
            (product_id, limit),
        )
    )
    for row in rows:
        row["assumptions"] = loads(row.pop("assumptions_json", "[]"), [])
        row["outcomes"] = loads(row.pop("outcomes_json", "[]"), [])
        row["leading_indicators"] = loads(row.pop("indicators_json", "[]"), [])
        row["risks"] = loads(row.pop("risks_json", "[]"), [])
    return rows


def delete_scenario_run(conn: sqlite3.Connection, scenario_id: str) -> None:
    conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Comments (spec 32)
# ---------------------------------------------------------------------------


def add_comment(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    user_id: str | None,
    author_label: str,
    target_type: str,
    target_id: str,
    body: str,
) -> str:
    comment_id = new_id("cmt")
    # A session can outlive a deleted account, so only reference a real user row.
    if user_id and not conn.execute(
        "SELECT 1 FROM users WHERE id = ? LIMIT 1", (user_id,)
    ).fetchone():
        user_id = None

    conn.execute(
        "INSERT INTO comments (id, workspace_id, product_id, user_id, author_label,"
        " target_type, target_id, body, resolved, created_at) VALUES (?,?,?,?,?,?,?,?,0,?)",
        (
            comment_id,
            workspace_id,
            product_id,
            user_id,
            author_label,
            target_type,
            target_id,
            body[:4000],
            utcnow(),
        ),
    )
    conn.commit()
    return comment_id


def list_comments(
    conn: sqlite3.Connection, target_type: str, target_id: str
) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            "SELECT * FROM comments WHERE target_type = ? AND target_id = ?"
            " ORDER BY created_at",
            (target_type, target_id),
        )
    )


def comment_counts(conn: sqlite3.Connection, product_id: str) -> dict[str, int]:
    rows = _rows(
        conn.execute(
            "SELECT target_id, COUNT(*) AS n FROM comments WHERE product_id = ?"
            " AND resolved = 0 GROUP BY target_id",
            (product_id,),
        )
    )
    return {row["target_id"]: row["n"] for row in rows}


def resolve_comment(conn: sqlite3.Connection, comment_id: str, resolved: bool = True) -> None:
    conn.execute(
        "UPDATE comments SET resolved = ? WHERE id = ?", (1 if resolved else 0, comment_id)
    )
    conn.commit()


def delete_comment(conn: sqlite3.Connection, comment_id: str) -> None:
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
