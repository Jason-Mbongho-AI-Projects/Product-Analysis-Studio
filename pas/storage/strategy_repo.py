"""Data access for the strategy studios, monitoring and conversations.

Split from ``repositories.py`` to keep each module readable; both share the same
connection, id and timestamp helpers.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Sequence

from ..domain.enums import AlertSeverity, AlertStatus
from .repositories import _row, _rows, loads, new_id, utcnow


# ---------------------------------------------------------------------------
# Positioning
# ---------------------------------------------------------------------------


def save_positioning(conn: sqlite3.Connection, analysis_id: str, data: dict[str, Any]) -> None:
    conn.execute("DELETE FROM positioning_studies WHERE analysis_id = ?", (analysis_id,))
    conn.execute("DELETE FROM positioning_options WHERE analysis_id = ?", (analysis_id,))
    conn.execute(
        "INSERT INTO positioning_studies (id, analysis_id, recommended_strategy,"
        " recommendation_reason, messaging_json, created_at) VALUES (?,?,?,?,?,?)",
        (
            new_id("pos"),
            analysis_id,
            data.get("recommended_strategy", ""),
            data.get("recommendation_reason", ""),
            json.dumps(data.get("messaging", {})),
            utcnow(),
        ),
    )
    recommended = (data.get("recommended_strategy") or "").strip().lower()
    for option in data.get("options", []):
        detail = {
            key: option.get(key, [])
            for key in (
                "supporting_evidence",
                "benefits",
                "risks",
                "required_product_changes",
            )
        }
        conn.execute(
            """
            INSERT INTO positioning_options (id, analysis_id, strategy_name, target_customer,
                value_proposition, differentiation, pricing_implications, gtm_implications,
                competitive_reaction_risk, fit_score, confidence, is_recommended,
                detail_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("pop"),
                analysis_id,
                option.get("strategy_name", ""),
                option.get("target_customer", ""),
                option.get("value_proposition", ""),
                option.get("differentiation", ""),
                option.get("pricing_implications", ""),
                option.get("gtm_implications", ""),
                option.get("competitive_reaction_risk", ""),
                float(option.get("fit_score", 0)),
                float(option.get("confidence", 0.5)),
                1 if option.get("strategy_name", "").strip().lower() == recommended else 0,
                json.dumps(detail),
                utcnow(),
            ),
        )
    conn.commit()


def get_positioning(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    study = _row(
        conn.execute("SELECT * FROM positioning_studies WHERE analysis_id = ?", (analysis_id,))
    )
    if not study:
        return None
    study["messaging"] = loads(study.pop("messaging_json", "{}"), {})
    options = _rows(
        conn.execute(
            "SELECT * FROM positioning_options WHERE analysis_id = ?"
            " ORDER BY is_recommended DESC, fit_score DESC",
            (analysis_id,),
        )
    )
    for option in options:
        option["detail"] = loads(option.pop("detail_json", "{}"), {})
    study["options"] = options
    return study


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def save_pricing(conn: sqlite3.Connection, analysis_id: str, data: dict[str, Any]) -> None:
    for table in ("pricing_studies", "pricing_tiers", "competitor_pricing"):
        conn.execute(f"DELETE FROM {table} WHERE analysis_id = ?", (analysis_id,))

    conn.execute(
        """
        INSERT INTO pricing_studies (id, analysis_id, current_assessment, recommended_model,
            value_metric, rationale, pricing_power, risks_json, assumptions_json,
            economics_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            new_id("prc"),
            analysis_id,
            data.get("current_assessment", ""),
            data.get("recommended_model", "subscription"),
            data.get("value_metric", ""),
            data.get("rationale", ""),
            data.get("pricing_power", ""),
            json.dumps(data.get("risks", [])),
            json.dumps(data.get("assumptions", [])),
            json.dumps(data.get("economics", {})),
            utcnow(),
        ),
    )
    for position, tier in enumerate(data.get("tiers", [])):
        conn.execute(
            "INSERT INTO pricing_tiers (id, analysis_id, name, price_monthly_usd,"
            " target_segment, limits, rationale, capabilities_json, position)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                new_id("tier"),
                analysis_id,
                tier.get("name", ""),
                float(tier.get("price_monthly_usd", 0) or 0),
                tier.get("target_segment", ""),
                tier.get("limits", ""),
                tier.get("rationale", ""),
                json.dumps(tier.get("included_capabilities", [])),
                position,
            ),
        )
    for point in data.get("competitor_pricing", []):
        conn.execute(
            "INSERT INTO competitor_pricing (id, analysis_id, competitor, plan_name,"
            " price_monthly_usd, pricing_model, notes, grade, confidence)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                new_id("cpp"),
                analysis_id,
                point.get("competitor", ""),
                point.get("plan_name", ""),
                float(point.get("price_monthly_usd", -1) or -1),
                point.get("pricing_model", "subscription"),
                point.get("notes", ""),
                point.get("grade", "ai_hypothesis"),
                float(point.get("confidence", 0.5)),
            ),
        )
    conn.commit()


def get_pricing(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    study = _row(
        conn.execute("SELECT * FROM pricing_studies WHERE analysis_id = ?", (analysis_id,))
    )
    if not study:
        return None
    study["risks"] = loads(study.pop("risks_json", "[]"), [])
    study["assumptions"] = loads(study.pop("assumptions_json", "[]"), [])
    study["economics"] = loads(study.pop("economics_json", "{}"), {})
    tiers = _rows(
        conn.execute(
            "SELECT * FROM pricing_tiers WHERE analysis_id = ? ORDER BY position",
            (analysis_id,),
        )
    )
    for tier in tiers:
        tier["included_capabilities"] = loads(tier.pop("capabilities_json", "[]"), [])
    study["tiers"] = tiers
    study["competitor_pricing"] = _rows(
        conn.execute(
            "SELECT * FROM competitor_pricing WHERE analysis_id = ? ORDER BY price_monthly_usd",
            (analysis_id,),
        )
    )
    return study


def save_scenario(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    analysis_id: str | None,
    label: str,
    inputs: dict[str, Any],
    results: dict[str, Any],
) -> str:
    scenario_id = new_id("scn")
    conn.execute(
        "INSERT INTO pricing_scenarios (id, workspace_id, product_id, analysis_id, label,"
        " inputs_json, results_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            scenario_id,
            workspace_id,
            product_id,
            analysis_id,
            label,
            json.dumps(inputs),
            json.dumps(results),
            utcnow(),
        ),
    )
    conn.commit()
    return scenario_id


def list_scenarios(conn: sqlite3.Connection, product_id: str, limit: int = 25) -> list[dict]:
    rows = _rows(
        conn.execute(
            "SELECT * FROM pricing_scenarios WHERE product_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (product_id, limit),
        )
    )
    for row in rows:
        row["inputs"] = loads(row.pop("inputs_json", "{}"), {})
        row["results"] = loads(row.pop("results_json", "{}"), {})
    return rows


def delete_scenario(conn: sqlite3.Connection, scenario_id: str) -> None:
    conn.execute("DELETE FROM pricing_scenarios WHERE id = ?", (scenario_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------


def save_growth(conn: sqlite3.Connection, analysis_id: str, data: dict[str, Any]) -> None:
    conn.execute("DELETE FROM growth_strategies WHERE analysis_id = ?", (analysis_id,))
    conn.execute("DELETE FROM growth_channels WHERE analysis_id = ?", (analysis_id,))
    conn.execute(
        "INSERT INTO growth_strategies (id, analysis_id, primary_motion, motion_rationale,"
        " sequencing_json, avoid_json, created_at) VALUES (?,?,?,?,?,?,?)",
        (
            new_id("grw"),
            analysis_id,
            data.get("primary_motion", ""),
            data.get("motion_rationale", ""),
            json.dumps(data.get("sequencing", [])),
            json.dumps(data.get("channels_to_avoid", [])),
            utcnow(),
        ),
    )
    for channel in data.get("channels", []):
        conn.execute(
            """
            INSERT INTO growth_channels (id, analysis_id, channel, fit_score, why_appropriate,
                expected_cac, time_to_traction, scalability, effort, first_experiment,
                evidence_json, confidence, priority)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("chn"),
                analysis_id,
                channel.get("channel", "seo"),
                float(channel.get("fit_score", 0)),
                channel.get("why_appropriate", ""),
                channel.get("expected_cac", ""),
                channel.get("time_to_traction", ""),
                channel.get("scalability", ""),
                channel.get("effort", "m"),
                channel.get("first_experiment", ""),
                json.dumps(channel.get("supporting_evidence", [])),
                float(channel.get("confidence", 0.5)),
                int(channel.get("priority", 99)),
            ),
        )
    conn.commit()


def get_growth(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    strategy = _row(
        conn.execute("SELECT * FROM growth_strategies WHERE analysis_id = ?", (analysis_id,))
    )
    if not strategy:
        return None
    strategy["sequencing"] = loads(strategy.pop("sequencing_json", "[]"), [])
    strategy["channels_to_avoid"] = loads(strategy.pop("avoid_json", "[]"), [])
    channels = _rows(
        conn.execute(
            "SELECT * FROM growth_channels WHERE analysis_id = ?"
            " ORDER BY priority, fit_score DESC",
            (analysis_id,),
        )
    )
    for channel in channels:
        channel["supporting_evidence"] = loads(channel.pop("evidence_json", "[]"), [])
    strategy["channels"] = channels
    return strategy


# ---------------------------------------------------------------------------
# Go-to-market
# ---------------------------------------------------------------------------


def save_gtm(conn: sqlite3.Connection, analysis_id: str, data: dict[str, Any]) -> None:
    conn.execute("DELETE FROM gtm_plans WHERE analysis_id = ?", (analysis_id,))
    conn.execute("DELETE FROM gtm_phases WHERE analysis_id = ?", (analysis_id,))
    conn.execute(
        """
        INSERT INTO gtm_plans (id, analysis_id, target_segment, beachhead_rationale,
            positioning_summary, messaging_summary, pricing_summary, channel_strategy,
            sales_strategy, launch_strategy, content_strategy, partnership_strategy,
            metrics_json, budget_json, risks_json, experiments_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            new_id("gtm"),
            analysis_id,
            data.get("target_segment", ""),
            data.get("beachhead_rationale", ""),
            data.get("positioning_summary", ""),
            data.get("messaging_summary", ""),
            data.get("pricing_summary", ""),
            data.get("channel_strategy", ""),
            data.get("sales_strategy", ""),
            data.get("launch_strategy", ""),
            data.get("content_strategy", ""),
            data.get("partnership_strategy", ""),
            json.dumps(data.get("metrics", [])),
            json.dumps(data.get("budget_assumptions", [])),
            json.dumps(data.get("risks", [])),
            json.dumps(data.get("experiments", [])),
            utcnow(),
        ),
    )
    #: Canonical ordering so phases render chronologically regardless of
    #: the order the model emitted them in.
    order = {"30_days": 0, "60_days": 1, "90_days": 2, "6_months": 3, "12_months": 4}
    for phase in data.get("phases", []):
        horizon = phase.get("horizon", "30_days")
        conn.execute(
            "INSERT INTO gtm_phases (id, analysis_id, horizon, owner_role, objectives_json,"
            " activities_json, milestones_json, position) VALUES (?,?,?,?,?,?,?,?)",
            (
                new_id("phs"),
                analysis_id,
                horizon,
                phase.get("owner_role", ""),
                json.dumps(phase.get("objectives", [])),
                json.dumps(phase.get("activities", [])),
                json.dumps(phase.get("milestones", [])),
                order.get(horizon, 99),
            ),
        )
    conn.commit()


def get_gtm(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    plan = _row(conn.execute("SELECT * FROM gtm_plans WHERE analysis_id = ?", (analysis_id,)))
    if not plan:
        return None
    plan["metrics"] = loads(plan.pop("metrics_json", "[]"), [])
    plan["budget_assumptions"] = loads(plan.pop("budget_json", "[]"), [])
    plan["risks"] = loads(plan.pop("risks_json", "[]"), [])
    plan["experiments"] = loads(plan.pop("experiments_json", "[]"), [])
    phases = _rows(
        conn.execute(
            "SELECT * FROM gtm_phases WHERE analysis_id = ? ORDER BY position", (analysis_id,)
        )
    )
    for phase in phases:
        phase["objectives"] = loads(phase.pop("objectives_json", "[]"), [])
        phase["activities"] = loads(phase.pop("activities_json", "[]"), [])
        phase["milestones"] = loads(phase.pop("milestones_json", "[]"), [])
    plan["phases"] = phases
    return plan


# ---------------------------------------------------------------------------
# Monitoring, snapshots and change detection
# ---------------------------------------------------------------------------


def save_snapshot(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    url: str,
    title: str,
    content: str,
    content_hash: str,
    competitor_id: str | None = None,
) -> str:
    snapshot_id = new_id("snp")
    conn.execute(
        "INSERT INTO competitor_snapshots (id, workspace_id, product_id, competitor_id,"
        " url, title, content_hash, content, captured_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            snapshot_id,
            workspace_id,
            product_id,
            competitor_id,
            url,
            title,
            content_hash,
            content[:100_000],
            utcnow(),
        ),
    )
    conn.commit()
    return snapshot_id


def latest_snapshot(
    conn: sqlite3.Connection, product_id: str, url: str
) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT * FROM competitor_snapshots WHERE product_id = ? AND url = ?"
            " ORDER BY captured_at DESC LIMIT 1",
            (product_id, url),
        )
    )


def prune_snapshots(conn: sqlite3.Connection, product_id: str, url: str, keep: int = 5) -> int:
    """Retain only the most recent snapshots per URL.

    Snapshots store full page text; without pruning a weekly monitor would grow
    the database without bound.
    """
    cursor = conn.execute(
        """
        DELETE FROM competitor_snapshots
        WHERE id IN (
            SELECT id FROM competitor_snapshots
            WHERE product_id = ? AND url = ?
            ORDER BY captured_at DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (product_id, url, keep),
    )
    conn.commit()
    return cursor.rowcount


def record_change(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    snapshot_id: str | None,
    competitor_id: str | None,
    data: dict[str, Any],
    source_url: str | None = None,
) -> str:
    change_id = new_id("chg")
    conn.execute(
        """
        INSERT INTO competitor_changes (id, workspace_id, product_id, competitor_id,
            snapshot_id, change_type, summary, previous_state, current_state, evidence,
            estimated_impact, recommended_action, severity, confidence, source_url, detected_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            change_id,
            workspace_id,
            product_id,
            competitor_id,
            snapshot_id,
            data.get("change_type", "other"),
            data.get("summary", ""),
            data.get("previous_state", ""),
            data.get("current_state", ""),
            data.get("evidence", ""),
            data.get("estimated_impact", ""),
            data.get("recommended_action", ""),
            data.get("severity", "low"),
            float(data.get("confidence", 0.5)),
            source_url,
            utcnow(),
        ),
    )
    return change_id


def list_changes(conn: sqlite3.Connection, product_id: str, limit: int = 100) -> list[dict]:
    return _rows(
        conn.execute(
            "SELECT * FROM competitor_changes WHERE product_id = ?"
            " ORDER BY detected_at DESC LIMIT ?",
            (product_id, limit),
        )
    )


def create_alert(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    category: str,
    severity: str,
    title: str,
    body: str = "",
    recommended_action: str = "",
    change_id: str | None = None,
    source_url: str | None = None,
) -> str:
    alert_id = new_id("alt")
    conn.execute(
        """
        INSERT INTO alerts (id, workspace_id, product_id, category, severity, title, body,
            recommended_action, change_id, source_url, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            alert_id,
            workspace_id,
            product_id,
            category,
            severity,
            title,
            body,
            recommended_action,
            change_id,
            source_url,
            AlertStatus.UNREAD.value,
            utcnow(),
        ),
    )
    return alert_id


def list_alerts(
    conn: sqlite3.Connection,
    product_id: str,
    *,
    statuses: Iterable[str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    statuses = list(statuses or [])
    clause = ""
    params: list[Any] = [product_id]
    if statuses:
        clause = f" AND status IN ({','.join('?' * len(statuses))})"
        params.extend(statuses)
    params.append(limit)
    alerts = _rows(
        conn.execute(
            f"SELECT * FROM alerts WHERE product_id = ?{clause}"
            " ORDER BY created_at DESC LIMIT ?",
            params,
        )
    )
    # Sort by severity first so a critical alert never sits below chatter.
    alerts.sort(
        key=lambda a: (-AlertSeverity(a["severity"]).rank, a["created_at"]), reverse=False
    )
    return alerts


def unread_alert_count(conn: sqlite3.Connection, product_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM alerts WHERE product_id = ? AND status = ?",
        (product_id, AlertStatus.UNREAD.value),
    ).fetchone()["n"]


def set_alert_status(
    conn: sqlite3.Connection, alert_id: str, status: str, snoozed_until: str | None = None
) -> None:
    conn.execute(
        "UPDATE alerts SET status = ?, snoozed_until = ? WHERE id = ?",
        (status, snoozed_until, alert_id),
    )
    conn.commit()


def get_alert(conn: sqlite3.Connection, alert_id: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)))


def create_monitor(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    label: str,
    urls: Sequence[str],
    interval_hours: int = 168,
) -> str:
    monitor_id = new_id("mon")
    conn.execute(
        "INSERT INTO monitoring_jobs (id, workspace_id, product_id, label, urls_json,"
        " interval_hours, enabled, created_at) VALUES (?,?,?,?,?,?,1,?)",
        (
            monitor_id,
            workspace_id,
            product_id,
            label,
            json.dumps(list(urls)),
            int(interval_hours),
            utcnow(),
        ),
    )
    conn.commit()
    return monitor_id


def list_monitors(conn: sqlite3.Connection, product_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            "SELECT * FROM monitoring_jobs WHERE product_id = ? ORDER BY created_at",
            (product_id,),
        )
    )
    for row in rows:
        row["urls"] = loads(row.pop("urls_json", "[]"), [])
    return rows


def get_monitor(conn: sqlite3.Connection, monitor_id: str) -> dict[str, Any] | None:
    row = _row(conn.execute("SELECT * FROM monitoring_jobs WHERE id = ?", (monitor_id,)))
    if row:
        row["urls"] = loads(row.pop("urls_json", "[]"), [])
    return row


def update_monitor_run(
    conn: sqlite3.Connection,
    monitor_id: str,
    *,
    status: str,
    error: str | None = None,
    changes_found: int = 0,
) -> None:
    conn.execute(
        "UPDATE monitoring_jobs SET last_run_at = ?, last_status = ?, last_error = ?,"
        " changes_found = changes_found + ? WHERE id = ?",
        (utcnow(), status, error, changes_found, monitor_id),
    )
    conn.commit()


def set_monitor_enabled(conn: sqlite3.Connection, monitor_id: str, enabled: bool) -> None:
    conn.execute(
        "UPDATE monitoring_jobs SET enabled = ? WHERE id = ?", (1 if enabled else 0, monitor_id)
    )
    conn.commit()


def delete_monitor(conn: sqlite3.Connection, monitor_id: str) -> None:
    conn.execute("DELETE FROM monitoring_jobs WHERE id = ?", (monitor_id,))
    conn.commit()


def due_monitors(conn: sqlite3.Connection, workspace_id: str) -> list[dict[str, Any]]:
    """Monitors whose interval has elapsed.

    Comparison is done in SQL against an ISO timestamp, which sorts
    lexicographically for UTC values.
    """
    rows = _rows(
        conn.execute(
            """
            SELECT * FROM monitoring_jobs
            WHERE workspace_id = ? AND enabled = 1
              AND (last_run_at IS NULL
                   OR datetime(last_run_at) <= datetime('now', '-' || interval_hours || ' hours'))
            """,
            (workspace_id,),
        )
    )
    for row in rows:
        row["urls"] = loads(row.pop("urls_json", "[]"), [])
    return rows


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def save_conversation(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    product_id: str,
    analysis_id: str | None,
    question: str,
    answer: str,
    confidence: float,
    caveats: Sequence[str],
    citations: Sequence[dict[str, Any]],
) -> str:
    conversation_id = new_id("cnv")
    conn.execute(
        "INSERT INTO conversations (id, workspace_id, product_id, analysis_id, question,"
        " answer, confidence, caveats_json, citations_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            conversation_id,
            workspace_id,
            product_id,
            analysis_id,
            question,
            answer,
            float(confidence),
            json.dumps(list(caveats)),
            json.dumps(list(citations)),
            utcnow(),
        ),
    )
    conn.commit()
    return conversation_id


def list_conversations(
    conn: sqlite3.Connection, product_id: str, limit: int = 30
) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            "SELECT * FROM conversations WHERE product_id = ? ORDER BY created_at DESC LIMIT ?",
            (product_id, limit),
        )
    )
    for row in rows:
        row["caveats"] = loads(row.pop("caveats_json", "[]"), [])
        row["citations"] = loads(row.pop("citations_json", "[]"), [])
    return rows
