"""Tests for change detection, retrieval/citation verification and reports.

All deterministic - no model calls. The citation-verification tests are the
important ones: they are what stops a fabricated source reaching the user.
"""

from __future__ import annotations

import json

import pytest

from pas.analysis.ask import AskEngine, RetrievedContext, score_evidence
from pas.analysis.monitoring import (
    MIN_CHANGE_RATIO,
    assess_change,
    build_diff,
    change_ratio,
    extract_prices,
    normalise_content,
)
from pas.analysis.reports import (
    competitors_csv,
    evidence_csv,
    full_export_json,
    markdown_to_html,
    scores_csv,
)
from pas.storage import repositories as repo

# ---------------------------------------------------------------------------
# Change detection (spec 8)
# ---------------------------------------------------------------------------


def test_identical_content_has_no_change():
    text = "Plans start at $49 per month for the Professional tier."
    assert change_ratio(text, text) == 0.0


def test_volatile_noise_is_normalised_away():
    """Dates and times change constantly and are not product decisions."""
    before = "Updated 12 March 2024. Professional plan $49/month."
    after = "Updated 4 August 2026. Professional plan $49/month."
    assert change_ratio(before, after) < MIN_CHANGE_RATIO


def test_timestamps_do_not_register_as_change():
    assert change_ratio("Synced at 14:32 today", "Synced at 09:05 today") < MIN_CHANGE_RATIO


def test_case_and_whitespace_are_ignored():
    assert change_ratio("Pro Plan   $49", "pro plan $49") == 0.0


def test_price_change_on_a_long_page_is_always_significant():
    """The regression that matters most.

    A single price edit is a tiny fraction of a long pricing page, so a bulk
    ratio threshold alone silently discards it - which would defeat the entire
    feature. Price tokens must escalate regardless of ratio.
    """
    filler = " ".join(f"Feature {i} is included in this plan." for i in range(400))
    before = f"Professional plan costs $49 per month. {filler}"
    after = f"Professional plan costs $39 per month. {filler}"

    assessment = assess_change(before, after)
    assert assessment.ratio < MIN_CHANGE_RATIO, "bulk ratio alone would miss this"
    assert assessment.price_changed
    assert assessment.is_significant, "a price change must always escalate"
    assert "$39" in assessment.prices_added
    assert "$49" in assessment.prices_removed


def test_price_change_reasons_are_explicit():
    assessment = assess_change("Pro tier $49/mo", "Pro tier $39/mo")
    reasons = " ".join(assessment.reasons())
    assert "Pricing changed" in reasons
    assert "$49" in reasons and "$39" in reasons


def test_new_capability_on_a_long_page_is_significant():
    filler = " ".join(f"Paragraph {i} of marketing copy." for i in range(400))
    before = f"Analytics and dashboards. {filler}"
    after = f"Analytics, dashboards, and SAML single sign-on. {filler}"

    assessment = assess_change(before, after)
    assert assessment.ratio < MIN_CHANGE_RATIO
    assert "saml" in assessment.signals_added
    assert assessment.is_significant


def test_removed_capability_is_significant():
    assessment = assess_change(
        "We offer a free tier and SSO.", "We offer SSO."
    )
    assert "free tier" in assessment.signals_removed
    assert assessment.is_significant


def test_cosmetic_copy_change_is_not_significant():
    filler = " ".join(f"Sentence {i} about the product." for i in range(400))
    before = f"Welcome to our website. {filler}"
    after = f"Welcome to our site. {filler}"

    assessment = assess_change(before, after)
    assert not assessment.is_significant, "copy tweaks must not trigger a model call"


def test_date_only_change_is_not_significant():
    assessment = assess_change(
        "Updated 12 March 2024. Professional plan $49/month.",
        "Updated 4 August 2026. Professional plan $49/month.",
    )
    assert not assessment.is_significant


def test_large_rewrite_is_significant_without_price_or_signal_change():
    assessment = assess_change(
        "We build analytics software for small teams.",
        "A completely different paragraph about unrelated consulting services.",
    )
    assert assessment.ratio >= MIN_CHANGE_RATIO
    assert assessment.is_significant


def test_price_extraction_handles_formats():
    prices = extract_prices("Plans: $49, £1,200.50 per year, and 99 USD monthly.")
    assert "$49" in prices
    assert any("1,200.50" in p for p in prices)
    assert any("99usd" in p.replace(" ", "") for p in prices)


def test_empty_to_content_is_a_total_change():
    assert change_ratio("", "Now with enterprise SSO") == 1.0
    assert change_ratio("", "") == 0.0


def test_normalise_strips_cache_busting_query_strings():
    assert "v=12345" not in normalise_content("script.js?v=12345 loaded")


def test_diff_contains_both_sides_of_a_change():
    diff = build_diff(
        "Professional plan costs $49 per month. Includes dashboards.",
        "Professional plan costs $39 per month. Includes dashboards.",
    )
    assert diff
    assert any(line.startswith("-") for line in diff.splitlines())
    assert any(line.startswith("+") for line in diff.splitlines())
    assert "39" in diff


def test_diff_is_budget_capped():
    diff = build_diff("alpha. " * 4000, "beta. " * 4000, max_chars=1200)
    assert len(diff) <= 1400
    assert "truncated" in diff


def test_identical_text_produces_no_diff():
    assert build_diff("Same content here.", "Same content here.") == ""


# ---------------------------------------------------------------------------
# Retrieval ranking (spec 25 / 40)
# ---------------------------------------------------------------------------


def _evidence(claim, grade="verified_fact", confidence=0.9, detail=""):
    return {"id": "evd_1", "claim": claim, "detail": detail, "grade": grade,
            "confidence": confidence, "citations": []}


def test_relevant_evidence_outranks_irrelevant():
    question = "Is my pricing competitive?"
    relevant = score_evidence(question, _evidence("Competitor pricing starts at $49"))
    irrelevant = score_evidence(question, _evidence("The onboarding flow has six steps"))
    assert relevant > irrelevant


def test_verified_evidence_outranks_hypothesis_at_equal_relevance():
    question = "What is the pricing model?"
    verified = score_evidence(question, _evidence("Pricing model is per seat", "verified_fact"))
    guessed = score_evidence(question, _evidence("Pricing model is per seat", "ai_hypothesis"))
    assert verified > guessed


def test_confidence_affects_ranking():
    question = "What are the integrations?"
    high = score_evidence(question, _evidence("Integrations include Slack", confidence=0.95))
    low = score_evidence(question, _evidence("Integrations include Slack", confidence=0.2))
    assert high > low


def test_stopwords_alone_do_not_match():
    assert score_evidence("what is the", _evidence("Something entirely unrelated")) == 0.0


def test_no_overlap_scores_zero():
    assert score_evidence("pricing", _evidence("Accessibility audit is incomplete")) == 0.0


# ---------------------------------------------------------------------------
# Citation verification - the anti-fabrication guard
# ---------------------------------------------------------------------------


def test_fabricated_citation_ids_are_dropped():
    """A model-invented evidence ID must never reach the user."""
    context = RetrievedContext(
        evidence=[
            {"id": "evd_real", "claim": "Real claim", "grade": "verified_fact",
             "confidence": 0.9, "citations": [{"url": "https://x.com", "title": "X"}]}
        ]
    )
    citations, dropped = AskEngine._verify_citations(
        ["evd_real", "evd_totally_made_up", "evd_also_fake"], context
    )
    assert len(citations) == 1
    assert citations[0]["id"] == "evd_real"
    assert dropped == 2


def test_all_fabricated_citations_yield_none():
    context = RetrievedContext(evidence=[])
    citations, dropped = AskEngine._verify_citations(["evd_a", "evd_b"], context)
    assert citations == []
    assert dropped == 2


def test_citation_whitespace_is_tolerated():
    context = RetrievedContext(
        evidence=[{"id": "evd_1", "claim": "c", "grade": "verified_fact",
                   "confidence": 0.8, "citations": []}]
    )
    citations, dropped = AskEngine._verify_citations([" evd_1 "], context)
    assert len(citations) == 1 and dropped == 0


def test_verified_citations_carry_grade_and_sources():
    context = RetrievedContext(
        evidence=[{"id": "evd_1", "claim": "Competitor offers SSO", "grade": "verified_fact",
                   "confidence": 0.85,
                   "citations": [{"url": "https://rival.com/pricing", "title": "Pricing"}]}]
    )
    citations, _ = AskEngine._verify_citations(["evd_1"], context)
    assert citations[0]["grade"] == "verified_fact"
    assert citations[0]["sources"][0]["url"] == "https://rival.com/pricing"


# ---------------------------------------------------------------------------
# Reports (spec 30)
# ---------------------------------------------------------------------------


def test_report_html_escapes_injected_markup():
    """Report content includes model output and fetched page titles."""
    html = markdown_to_html("# <script>alert(1)</script>\n\nBody & text", "T")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_report_html_escapes_the_title():
    html = markdown_to_html("# Hi", '"><script>bad()</script>')
    assert "<script>bad()</script>" not in html


def test_report_html_renders_tables_and_lists():
    html = markdown_to_html(
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n", "T"
    )
    assert "<table>" in html and "<th>A</th>" in html and "<td>1</td>" in html
    assert "<ul>" in html and "<li>one</li>" in html


def test_report_html_is_self_contained():
    html = markdown_to_html("# Title", "T")
    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert "http://" not in html and "https://" not in html, "must not fetch external assets"


def test_scores_csv_has_a_row_per_score():
    csv_text = scores_csv([
        {"dimension": "market_opportunity", "score": 80.0, "inverted": 0, "weight": 0.12,
         "confidence": 0.7, "explanation": "Because", "assumptions": ["a", "b"]},
        {"dimension": "competitive_pressure", "score": 60.0, "inverted": 1, "weight": 0.07,
         "confidence": 0.5, "explanation": "Crowded", "assumptions": []},
    ])
    lines = csv_text.strip().split("\n")
    assert len(lines) == 3
    assert "Market Opportunity" in csv_text
    assert "yes" in csv_text  # the inverted flag


def test_csv_exports_handle_empty_input():
    assert scores_csv([]).strip().count("\n") == 0
    assert competitors_csv([]).strip().count("\n") == 0
    assert evidence_csv([]).strip().count("\n") == 0


def test_full_export_is_valid_json_with_evidence():
    payload = json.loads(
        full_export_json(
            {"analysis": {"id": "a"}, "composite": {"score": 70}, "scores": [],
             "quality": {"total": 1}},
            {"id": "p", "name": "Test"},
            [{"id": "evd_1", "claim": "c", "grade": "verified_fact", "confidence": 0.9}],
        )
    )
    assert payload["product"]["name"] == "Test"
    assert payload["evidence"][0]["claim"] == "c"
    assert "generator" in payload


def test_reports_state_their_evidence_basis(conn, workspace, product, analysis):
    """Every report must disclose how well-evidenced it is."""
    from pas.analysis.reports import executive_report

    data = {
        "composite": {"score": 50, "confidence": 0.4, "coverage": 1.0},
        "scores": [], "profile": None, "recommendations": [], "competitors": [],
        "quality": {"total": 10, "evidence_backed_ratio": 0.0, "distinct_sources": 0},
    }
    report = executive_report(data, {"name": "Test", "one_liner": ""})
    assert "No external sources were retrieved" in report.markdown
    assert "hypotheses, not verified facts" in report.markdown


def test_report_filenames_are_filesystem_safe():
    from pas.analysis.reports import executive_report

    data = {"composite": {"score": 0, "confidence": 0, "coverage": 0}, "scores": [],
            "profile": None, "recommendations": [], "competitors": [],
            "quality": {"total": 0}}
    report = executive_report(data, {"name": "My Product: v2/beta <test>", "one_liner": ""})
    assert not any(c in report.filename for c in '<>:"/\\|?*')


# ---------------------------------------------------------------------------
# Strategy storage round-trips
# ---------------------------------------------------------------------------


def test_positioning_round_trip_marks_recommended(conn, analysis):
    repo.save_positioning(conn, analysis, {
        "recommended_strategy": "Compliance First",
        "recommendation_reason": "Buyers are driven by audit deadlines.",
        "messaging": {"positioning_statement": "For hospitals...",
                      "homepage_headline": "Pass your audit"},
        "options": [
            {"strategy_name": "Compliance First", "fit_score": 88, "confidence": 0.7,
             "target_customer": "Hospital CISOs", "benefits": ["Clear buyer"]},
            {"strategy_name": "Developer First", "fit_score": 41, "confidence": 0.5,
             "target_customer": "Engineers", "risks": ["Wrong buyer"]},
        ],
    })
    stored = repo.get_positioning(conn, analysis)
    assert stored["recommended_strategy"] == "Compliance First"
    assert stored["options"][0]["is_recommended"] == 1
    assert stored["options"][0]["strategy_name"] == "Compliance First"
    assert stored["messaging"]["homepage_headline"] == "Pass your audit"
    assert stored["options"][0]["detail"]["benefits"] == ["Clear buyer"]


def test_pricing_round_trip_preserves_unknown_prices(conn, analysis):
    """-1 means 'unknown' and must survive the round trip as such."""
    repo.save_pricing(conn, analysis, {
        "recommended_model": "tiered", "value_metric": "monitored endpoints",
        "economics": {"arpu_monthly_usd": 250, "cac_usd": 1200},
        "tiers": [{"name": "Team", "price_monthly_usd": 99,
                   "included_capabilities": ["Dashboards"]}],
        "competitor_pricing": [
            {"competitor": "Rival", "plan_name": "Pro", "price_monthly_usd": 49,
             "grade": "verified_fact", "confidence": 0.9},
            {"competitor": "Opaque Inc", "plan_name": "Enterprise",
             "price_monthly_usd": -1, "grade": "ai_hypothesis", "confidence": 0.2},
        ],
    })
    stored = repo.get_pricing(conn, analysis)
    assert stored["economics"]["arpu_monthly_usd"] == 250
    assert stored["tiers"][0]["included_capabilities"] == ["Dashboards"]
    unknown = [p for p in stored["competitor_pricing"] if p["price_monthly_usd"] == -1]
    assert len(unknown) == 1
    assert unknown[0]["competitor"] == "Opaque Inc"


def test_growth_and_gtm_round_trip(conn, analysis):
    repo.save_growth(conn, analysis, {
        "primary_motion": "product-led", "motion_rationale": "Low price point",
        "sequencing": ["SEO first"], "channels_to_avoid": ["Paid social"],
        "channels": [{"channel": "seo", "fit_score": 82, "priority": 1,
                      "supporting_evidence": ["Buyers search first"]}],
    })
    growth = repo.get_growth(conn, analysis)
    assert growth["channels"][0]["channel"] == "seo"
    assert growth["channels_to_avoid"] == ["Paid social"]

    repo.save_gtm(conn, analysis, {
        "target_segment": "Mid-market hospitals", "metrics": ["Activated accounts"],
        "phases": [
            {"horizon": "90_days", "objectives": ["Ten design partners"]},
            {"horizon": "30_days", "objectives": ["Ship landing page"]},
        ],
    })
    gtm = repo.get_gtm(conn, analysis)
    # Phases must render chronologically regardless of emitted order.
    assert [p["horizon"] for p in gtm["phases"]] == ["30_days", "90_days"]


def test_alerts_sort_critical_first(conn, workspace, product):
    for severity, title in [
        ("low", "Minor copy change"),
        ("critical", "Competitor halved their price"),
        ("medium", "New integration listed"),
    ]:
        repo.create_alert(conn, workspace_id=workspace, product_id=product,
                          category="competitor", severity=severity, title=title)
    conn.commit()

    alerts = repo.list_alerts(conn, product)
    assert alerts[0]["severity"] == "critical"
    assert repo.unread_alert_count(conn, product) == 3

    repo.set_alert_status(conn, alerts[0]["id"], "read")
    assert repo.unread_alert_count(conn, product) == 2


def test_snapshots_are_pruned_to_a_bounded_history(conn, workspace, product):
    for index in range(9):
        repo.save_snapshot(conn, workspace_id=workspace, product_id=product,
                           url="https://rival.com/pricing", title="Pricing",
                           content=f"version {index}", content_hash=f"hash{index}")
    repo.prune_snapshots(conn, product, "https://rival.com/pricing", keep=5)

    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM competitor_snapshots WHERE url = ?",
        ("https://rival.com/pricing",),
    ).fetchone()["n"]
    assert remaining == 5
    # The newest capture must survive pruning.
    assert repo.latest_snapshot(conn, product, "https://rival.com/pricing")["content"] == "version 8"


def test_due_monitors_respects_interval(conn, workspace, product):
    never_run = repo.create_monitor(conn, workspace_id=workspace, product_id=product,
                                    label="Fresh", urls=["https://a.com"], interval_hours=168)
    recent = repo.create_monitor(conn, workspace_id=workspace, product_id=product,
                                 label="Recent", urls=["https://b.com"], interval_hours=168)
    repo.update_monitor_run(conn, recent, status="ok")

    due = {m["id"] for m in repo.due_monitors(conn, workspace)}
    assert never_run in due, "a monitor that never ran is due"
    assert recent not in due, "a monitor that just ran is not due"


def test_disabled_monitors_are_never_due(conn, workspace, product):
    monitor = repo.create_monitor(conn, workspace_id=workspace, product_id=product,
                                  label="Off", urls=["https://a.com"])
    repo.set_monitor_enabled(conn, monitor, False)
    assert monitor not in {m["id"] for m in repo.due_monitors(conn, workspace)}


# ---------------------------------------------------------------------------
# Price sentinel rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (-1, "Custom"),
        (-99, "Custom"),
        (0, "Free"),
        (49, "$49"),
        (1250.4, "$1,250"),
        (None, "Unknown"),
    ],
)
def test_price_sentinels_render_as_words(value, expected):
    """-1 (contact sales) and 0 (free) must never render as "$-1" or "$0"."""
    from pas.analysis.reports import format_price
    from pas.ui.components import format_price as ui_format_price

    assert format_price(value) == expected
    assert ui_format_price(value) == expected


def test_price_suffix_only_applied_to_real_amounts():
    from pas.ui.components import format_price

    assert format_price(49, "/mo") == "$49/mo"
    assert format_price(-1, "/mo") == "Custom"
    assert format_price(0, "/mo") == "Free"


def test_strategy_report_renders_custom_tier_pricing(conn, analysis):
    """A contact-sales tier must not appear as $-1 in a downloadable report."""
    from pas.analysis.reports import strategy_report

    repo.save_pricing(conn, analysis, {
        "recommended_model": "tiered", "value_metric": "seats",
        "tiers": [
            {"name": "Starter", "price_monthly_usd": 0, "target_segment": "Solo"},
            {"name": "Pro", "price_monthly_usd": 99, "target_segment": "Teams"},
            {"name": "Enterprise", "price_monthly_usd": -1, "target_segment": "Large"},
        ],
    })
    report = strategy_report(
        {"pricing": repo.get_pricing(conn, analysis), "quality": {"total": 0}},
        {"name": "Test"},
    )
    assert "$-1" not in report.markdown
    assert "Custom" in report.markdown
    assert "Free" in report.markdown
    assert "$99" in report.markdown


# ---------------------------------------------------------------------------
# Monitor scheduler (spec 33)
# ---------------------------------------------------------------------------


def test_scheduler_dispatches_due_monitors():
    from pas.jobs.scheduler import MonitorScheduler

    dispatched = []
    scheduler = MonitorScheduler(
        due_provider=lambda: [{"id": "mon_1"}, {"id": "mon_2"}],
        dispatch=dispatched.append,
    )
    assert scheduler.tick() == 2
    assert dispatched == ["mon_1", "mon_2"]
    assert scheduler.state.dispatched == 2


def test_scheduler_caps_dispatches_per_tick():
    """A backlog after a long shutdown must not stampede the provider."""
    from pas.jobs.scheduler import MonitorScheduler

    dispatched = []
    scheduler = MonitorScheduler(
        due_provider=lambda: [{"id": f"mon_{i}"} for i in range(50)],
        dispatch=dispatched.append,
        max_per_tick=3,
    )
    assert scheduler.tick() == 3
    assert len(dispatched) == 3


def test_scheduler_survives_a_failing_dispatch():
    """One broken monitor must not stop the others or kill the scheduler."""
    from pas.jobs.scheduler import MonitorScheduler

    dispatched = []

    def dispatch(monitor_id):
        if monitor_id == "mon_bad":
            raise RuntimeError("provider exploded")
        dispatched.append(monitor_id)

    scheduler = MonitorScheduler(
        due_provider=lambda: [{"id": "mon_bad"}, {"id": "mon_good"}],
        dispatch=dispatch,
    )
    assert scheduler.tick() == 1
    assert dispatched == ["mon_good"]
    assert scheduler.state.errors == 1
    assert "provider exploded" in scheduler.state.last_error


def test_scheduler_survives_a_failing_query():
    from pas.jobs.scheduler import MonitorScheduler

    def explode():
        raise RuntimeError("database gone")

    scheduler = MonitorScheduler(due_provider=explode, dispatch=lambda _: None)
    assert scheduler.tick() == 0
    assert scheduler.state.errors == 1


def test_scheduler_does_nothing_when_nothing_is_due():
    from pas.jobs.scheduler import MonitorScheduler

    scheduler = MonitorScheduler(due_provider=list, dispatch=lambda _: None)
    assert scheduler.tick() == 0
    assert scheduler.state.errors == 0


def test_scheduler_thread_starts_and_stops_cleanly():
    from pas.jobs.scheduler import MonitorScheduler

    scheduler = MonitorScheduler(
        due_provider=list, dispatch=lambda _: None, tick_seconds=0.05
    )
    scheduler.start()
    assert scheduler.state.running
    scheduler.stop()
    assert not scheduler.state.running


def test_scheduler_is_off_by_default():
    """Spending money on a timer must be a deliberate choice."""
    from pas.config import AppConfig

    assert AppConfig(api_key="k").scheduler_enabled is False
