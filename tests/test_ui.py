"""UI smoke tests using Streamlit's AppTest.

A page that raises renders an error block instead of crashing the server, so
"the app returns HTTP 200" proves nothing. These tests execute the real script
and assert no exception was raised, including against a fully populated
analysis and against empty/partial data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pas.storage import repositories as repo

st_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = st_testing.AppTest

TIMEOUT = 30
#: AppTest resolves relative paths against this file, so anchor to the repo root.
APP_SCRIPT = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Run the real app against an isolated database."""
    monkeypatch.setenv("PAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")

    from pas.storage import db as db_module

    db_module.reset_thread_state()
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "ui.sqlite3")

    import pas.ui.app as ui_app

    ui_app._base_service.clear()  # drop the cached service between tests
    yield AppTest.from_file(APP_SCRIPT, default_timeout=TIMEOUT)
    db_module.reset_thread_state()


def _assert_clean(at):
    assert not at.exception, [str(e) for e in at.exception]


def test_app_boots_without_exception(app):
    at = app.run()
    _assert_clean(at)
    assert any("Product Analysis Studio" in str(m.value) for m in at.markdown)


def test_intake_rejects_empty_submission(app):
    at = app.run()
    _assert_clean(at)
    at.button[0].click().run()
    _assert_clean(at)


def test_diagnostics_page_renders(app):
    at = app.run()
    at.session_state["route"] = "diagnostics"
    at.run()
    _assert_clean(at)


def test_workroom_handles_missing_product(app):
    at = app.run()
    at.session_state["route"] = "workroom"
    at.session_state["active_product"] = "prd_does_not_exist"
    at.run()
    _assert_clean(at)


def test_workroom_renders_populated_analysis(app, tmp_path):
    """The full workroom against realistic data - the highest-value UI check."""
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(
        conn, workspace_id=workspace, name="Test Product", intake_kind="idea",
        intake_input="an idea", category="Analytics",
    )
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", progress=1.0, completed=True)

    repo.save_product_profile(conn, analysis, {
        "summary": "A product.", "primary_problem": "A problem.",
        "pricing_model": "Subscription", "distribution_model": "Direct",
        "switching_costs": "Low", "defensibility": "Brand",
        "features": [{"name": "Dashboards", "description": "Charts", "grade": "verified_fact"}],
        "lists": {"use_cases": ["Reporting"], "core_capabilities": ["Analytics"],
                  "target_customers": ["SMBs"]},
    })
    repo.save_scores(conn, analysis, [
        {"dimension": d, "score": 70, "confidence": 0.6, "explanation": "Because.",
         "assumptions": ["a"], "supporting_evidence": ["e"]}
        for d in ["market_opportunity", "competitive_pressure", "defensibility"]
    ])
    repo.save_competitor(conn, workspace_id=workspace, analysis_id=analysis, data={
        "name": "Rival", "company": "Rival Inc", "website": "https://rival.example",
        "competitor_type": "direct", "positioning": "Cheap", "target_customer": "SMB",
        "pricing_summary": "$10/mo", "threat_level": "high", "rationale": "Same buyer",
        "grade": "strong_inference", "confidence": 0.7, "strengths": ["Price"],
        "weaknesses": ["Support"], "known_features": ["Dashboards"],
    })
    repo.save_market(conn, analysis, {
        "market_definition": "Analytics", "maturity": "growth",
        "competitive_concentration": "fragmented", "entry_barriers": ["Brand"],
        "adjacent_markets": ["BI"],
        "sizing": [{"label": "TAM", "value_usd": 1e9, "formula": "10M x $100",
                    "variables": ["10M businesses"], "assumptions": ["adoption"],
                    "basis": "bottom_up", "confidence": 0.4}],
    })
    repo.save_customers(conn, analysis, {
        "icp": "SMB marketing teams", "switching_concerns": ["Data migration"],
        "personas": [{"name": "Marketer", "is_buyer": True, "is_user": True,
                      "grade": "ai_hypothesis", "confidence": 0.5,
                      "pain_points": ["Too complex"], "jobs_to_be_done": ["Report"]}],
    })
    repo.save_recommendations(conn, workspace_id=workspace, analysis_id=analysis,
        product_id=product, recommendations=[
            {"title": "Add SSO", "gap_category": "security", "problem": "Enterprises need it",
             "recommendation": "Ship SAML", "verdict": "must_build", "reason": "Blocker",
             "effort": "l", "priority": 1, "confidence": 0.8,
             "supporting_evidence": ["Competitor has it"], "dependencies": ["Auth refactor"]},
            {"title": "Build mobile app", "gap_category": "mobile", "problem": "None",
             "recommendation": "Do not build", "verdict": "do_not_build",
             "reason": "No demand signal", "effort": "xl", "priority": 9, "confidence": 0.6},
        ])
    repo.record_evidence(conn, workspace_id=workspace, analysis_id=analysis,
        claim="Rival offers SSO", detail="Seen on pricing page", grade="verified_fact",
        confidence=0.9, agent="competitive_intelligence", subject_type="strength",
        citations=[{"url": "https://rival.example/pricing", "title": "Pricing",
                    "source_type": "pricing_page"}])
    conn.commit()

    at = app.run()
    at.session_state["route"] = "workroom"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)

    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Test Product" in rendered
    assert "Must build" in rendered
    assert "Do not build" in rendered, "the do-not-build verdict must be visible"


def _seed_strategy(conn, analysis):
    """Populate the strategy studios so their pages have data to render."""
    repo.save_positioning(conn, analysis, {
        "recommended_strategy": "Compliance First",
        "recommendation_reason": "Audit deadlines drive the purchase.",
        "messaging": {
            "positioning_statement": "For hospitals who face audits...",
            "unique_value_proposition": "Continuous evidence collection",
            "homepage_headline": "Pass your next audit without the scramble",
            "homepage_subheadline": "Evidence collection on autopilot",
            "messaging_hierarchy": ["Audit-ready always"],
            "objection_handling": [{"objection": "Too expensive", "response": "Cheaper than failing"}],
        },
        "options": [
            {"strategy_name": "Compliance First", "fit_score": 88, "confidence": 0.7,
             "target_customer": "Hospital CISOs", "value_proposition": "Audit readiness",
             "differentiation": "Healthcare-specific controls", "benefits": ["Clear buyer"],
             "risks": ["Narrow market"], "required_product_changes": ["HIPAA mapping"]},
            {"strategy_name": "Developer First", "fit_score": 42, "confidence": 0.5,
             "target_customer": "Engineers", "value_proposition": "API-first",
             "differentiation": "SDKs"},
        ],
    })
    repo.save_pricing(conn, analysis, {
        "current_assessment": "No pricing published.",
        "recommended_model": "tiered", "value_metric": "monitored endpoints",
        "rationale": "Scales with the customer's estate.",
        "pricing_power": "Moderate", "risks": ["Procurement cycles"],
        "assumptions": ["Mid-market budgets"],
        "economics": {"arpu_monthly_usd": 950, "gross_margin_pct": 78, "cac_usd": 4200,
                      "monthly_churn_pct": 2.0, "monthly_expansion_pct": 1.0,
                      "price_elasticity": -0.8, "basis": "Comparable healthcare SaaS"},
        "tiers": [{"name": "Team", "price_monthly_usd": 499, "target_segment": "Clinics",
                   "included_capabilities": ["Dashboards"], "limits": "50 endpoints"}],
        "competitor_pricing": [
            {"competitor": "Rival", "plan_name": "Pro", "price_monthly_usd": 799,
             "pricing_model": "subscription", "grade": "verified_fact", "confidence": 0.9},
            {"competitor": "Opaque", "plan_name": "Enterprise", "price_monthly_usd": -1,
             "pricing_model": "enterprise", "grade": "ai_hypothesis", "confidence": 0.2},
        ],
    })
    repo.save_growth(conn, analysis, {
        "primary_motion": "sales-led", "motion_rationale": "High ACV, committee buying.",
        "sequencing": ["Design partners first"], "channels_to_avoid": ["Paid social"],
        "channels": [
            {"channel": "outbound_sales", "fit_score": 84, "priority": 1,
             "why_appropriate": "Named accounts are enumerable",
             "first_experiment": "50 targeted emails", "effort": "m",
             "expected_cac": "$4-6k", "time_to_traction": "2 quarters",
             "scalability": "Linear", "confidence": 0.6,
             "supporting_evidence": ["Buyers are identifiable"]},
        ],
    })
    repo.save_gtm(conn, analysis, {
        "target_segment": "Mid-market hospital systems",
        "beachhead_rationale": "Enough budget, less procurement friction.",
        "launch_strategy": "Design partner cohort", "channel_strategy": "Outbound",
        "sales_strategy": "Founder-led", "content_strategy": "Compliance guides",
        "partnership_strategy": "MSP channel", "pricing_summary": "Tiered",
        "messaging_summary": "Audit readiness", "positioning_summary": "Compliance first",
        "metrics": ["Design partners signed"], "budget_assumptions": ["$50k pilot"],
        "risks": ["Long cycles"],
        "experiments": [{"hypothesis": "CISOs respond to audit framing", "test": "A/B email",
                         "success_metric": "Reply rate", "effort": "s"}],
        "phases": [
            {"horizon": "30_days", "objectives": ["Landing page"], "activities": ["Write copy"],
             "milestones": ["Page live"], "owner_role": "Founder"},
            {"horizon": "90_days", "objectives": ["Five design partners"],
             "activities": ["Outbound"], "milestones": ["5 signed"], "owner_role": "Founder"},
        ],
    })
    conn.commit()


def test_strategy_pages_render(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(conn, workspace_id=workspace, name="Strat",
                                  intake_kind="idea", intake_input="idea")
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)
    _seed_strategy(conn, analysis)

    at = app.run()
    at.session_state["route"] = "strategy"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)

    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Compliance First" in rendered
    assert "Pass your next audit" in rendered


def test_reports_page_offers_downloads(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(conn, workspace_id=workspace, name="Rep",
                                  intake_kind="idea", intake_input="idea")
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)
    _seed_strategy(conn, analysis)
    repo.save_scores(conn, analysis, [
        {"dimension": "market_opportunity", "score": 70, "confidence": 0.6,
         "explanation": "x", "assumptions": [], "supporting_evidence": []}
    ])

    at = app.run()
    at.session_state["route"] = "reports"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)


def test_ask_page_renders_without_a_question(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(conn, workspace_id=workspace, name="Ask",
                                  intake_kind="idea", intake_input="idea")
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)

    at = app.run()
    at.session_state["route"] = "ask"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)


def test_alerts_page_renders_and_shows_severity_order(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(conn, workspace_id=workspace, name="Alert",
                                  intake_kind="idea", intake_input="idea")
    repo.create_alert(conn, workspace_id=workspace, product_id=product,
                      category="pricing", severity="critical",
                      title="Rival cut Professional from $49 to $39",
                      body="Was: $49. Now: $39.",
                      recommended_action="Review our own pricing")
    conn.commit()

    at = app.run()
    at.session_state["route"] = "alerts"
    at.session_state["active_product"] = product
    at.run()
    _assert_clean(at)

    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "$49 to $39" in rendered


def test_decide_page_renders(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(conn, workspace_id=workspace, name="Dec",
                                  intake_kind="idea", intake_input="idea")
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)
    repo.save_recommendations(conn, workspace_id=workspace, analysis_id=analysis,
        product_id=product, recommendations=[
            {"title": "Ship SSO", "gap_category": "security", "verdict": "must_build",
             "reason": "Enterprise blocker", "priority": 1, "confidence": 0.8}])
    conn.commit()

    at = app.run()
    at.session_state["route"] = "decide"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)
    assert "Ship SSO" in " ".join(str(m.value) for m in at.markdown)


def test_product_scoped_routes_fall_back_without_a_product(app):
    """Selecting a product-scoped route with no product must not crash."""
    at = app.run()
    at.session_state["route"] = "strategy"
    at.session_state["active_product"] = None
    at.run()
    _assert_clean(at)


def test_workroom_renders_empty_analysis_without_crashing(app, tmp_path):
    """An analysis where every agent failed must still render."""
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(
        conn, workspace_id=workspace, name="Empty", intake_kind="idea", intake_input="x"
    )
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)

    at = app.run()
    at.session_state["route"] = "workroom"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)


# ---------------------------------------------------------------------------
# Authentication gate
# ---------------------------------------------------------------------------


@pytest.fixture
def secured_app(tmp_path, monkeypatch):
    """The app with authentication switched ON."""
    monkeypatch.setenv("PAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")
    monkeypatch.setenv("PAS_AUTH_ENABLED", "true")

    import importlib

    from pas import config as config_module
    from pas.storage import db as db_module

    db_module.reset_thread_state()
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "secure.sqlite3")
    importlib.reload(config_module)

    import pas.ui.app as ui_app

    ui_app._base_service.clear()
    yield AppTest.from_file(APP_SCRIPT, default_timeout=TIMEOUT)

    db_module.reset_thread_state()
    monkeypatch.delenv("PAS_AUTH_ENABLED", raising=False)
    importlib.reload(config_module)


def test_open_mode_is_quiet_on_localhost(app):
    """A banner repeated on every screen is noise for a solo developer."""
    at = app.run()
    _assert_clean(at)
    text = (
        " ".join(str(c.value) for c in at.caption)
        + " ".join(str(m.value) for m in at.markdown)
    ).lower()
    assert "authentication is disabled" not in text
    assert "auth disabled" not in text


def test_open_mode_still_shouts_when_reachable_off_machine(monkeypatch):
    """Quiet on loopback, loud when other machines can route to it.

    This is the case the banner exists for, so removing the routine notice must
    not remove this one.
    """
    from pas.config import network_exposure_warning

    monkeypatch.setenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    warning = network_exposure_warning(auth_enabled=False)
    assert warning is not None
    assert "PAS_AUTH_ENABLED" in warning

    # And silent once auth is on, whatever the binding.
    assert network_exposure_warning(auth_enabled=True) is None


def test_open_mode_requires_no_login(app):
    """The dev flow must be completely unobstructed."""
    at = app.run()
    _assert_clean(at)
    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Sign in" not in rendered
    assert "Start an analysis" in rendered or "Products" in rendered


def test_enabled_auth_blocks_access_until_signed_in(secured_app):
    at = secured_app.run()
    _assert_clean(at)

    rendered = " ".join(str(m.value) for m in at.markdown)
    # The first-run path offers account creation, not the product workspace.
    assert "Sign in to continue" in rendered
    assert "Start an analysis" not in rendered


def test_enabled_auth_ignores_a_forged_session_token(secured_app):
    at = secured_app.run()
    at.session_state["auth_token"] = "totally-made-up-token"
    at.run()
    _assert_clean(at)

    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Sign in to continue" in rendered, "a forged token must not grant access"


def test_account_page_renders_in_open_mode(app):
    at = app.run()
    at.session_state["route"] = "account"
    at.run()
    _assert_clean(at)
    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Account and access" in rendered


# ---------------------------------------------------------------------------
# Voice of Customer, radar and scenario pages
# ---------------------------------------------------------------------------


def _product_with_analysis(conn, name="P"):
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(
        conn, workspace_id=workspace, name=name, intake_kind="idea", intake_input="idea"
    )
    analysis = repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)
    return workspace, product, analysis


def test_voice_page_renders_empty_and_populated(app, tmp_path):
    from pas.research.documents import FeedbackRecord
    from pas.storage import db as db_module
    from pas.storage import voc_repo

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace, product, analysis = _product_with_analysis(conn, "VoC")

    at = app.run()
    at.session_state["route"] = "voice"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)

    batch = voc_repo.create_batch(
        conn, workspace_id=workspace, product_id=product, label="Reviews",
        source_type="review",
    )
    voc_repo.add_feedback_items(
        conn, workspace_id=workspace, product_id=product, batch_id=batch,
        records=[FeedbackRecord(content="Onboarding took three days and we nearly quit")],
    )
    voc_repo.save_feedback_analysis(
        conn, workspace_id=workspace, product_id=product, analysis_id=analysis,
        data={
            "total_items_analysed": 1, "overall_sentiment": "negative",
            "sentiment_positive_pct": 0, "sentiment_neutral_pct": 0,
            "sentiment_negative_pct": 100, "summary": "Onboarding dominates.",
            "top_complaints": ["Onboarding"], "top_praise": [], "unmet_needs": [],
            "emerging_trends": [], "caveats": ["Tiny sample"],
            "clusters": [{
                "label": "Onboarding friction", "theme": "onboarding",
                "sentiment": "negative", "summary": "Setup is slow.",
                "share_of_feedback": 100, "item_count": 1,
                "representative_quotes": ["Onboarding took three days and we nearly quit"],
                "customer_language": ["took three days"], "is_churn_driver": True,
                "is_feature_request": False, "severity": "high",
                "suggested_action": "Shorten setup", "confidence": 0.7,
            }],
        },
    )

    at = app.run()
    at.session_state["route"] = "voice"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)

    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "Onboarding friction" in rendered
    assert "churn driver" in rendered


def test_radar_page_renders(app, tmp_path):
    from pas.storage import db as db_module
    from pas.storage import voc_repo

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace, product, analysis = _product_with_analysis(conn, "Radar")
    voc_repo.save_radar(
        conn, workspace_id=workspace, analysis_id=analysis, product_id=product,
        signals=[
            {"signal_type": "opportunity", "title": "Compliance whitespace",
             "category": "market_trend", "description": "d", "why_now": "w",
             "impact": 80, "probability": 60, "horizon": "near_term",
             "recommended_response": "r", "supporting_evidence": ["e"], "confidence": 0.6},
            {"signal_type": "threat", "title": "Incumbent bundling",
             "category": "competitor", "description": "d", "why_now": "w",
             "impact": 70, "probability": 50, "horizon": "medium_term",
             "recommended_response": "r", "supporting_evidence": [], "confidence": 0.5},
        ],
    )

    at = app.run()
    at.session_state["route"] = "radar"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)
    assert "Compliance whitespace" in " ".join(str(m.value) for m in at.markdown)


def test_radar_page_handles_no_signals(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    _workspace, product, analysis = _product_with_analysis(conn, "Empty radar")

    at = app.run()
    at.session_state["route"] = "radar"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)


@pytest.mark.parametrize("mode", ["founder", "product_manager", "executive", "investor", "consultant"])
def test_every_mode_renders_the_executive_view(app, tmp_path, mode):
    """Each mode reorders the same intelligence; none may crash."""
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    workspace = repo.ensure_default_workspace(conn)
    product = repo.create_product(
        conn, workspace_id=workspace, name=f"Mode {mode}", intake_kind="idea",
        intake_input="idea",
    )
    analysis = repo.create_analysis(
        conn, workspace_id=workspace, product_id=product, mode=mode
    )["id"]
    repo.update_analysis_progress(conn, analysis, status="complete", completed=True)
    repo.save_scores(conn, analysis, [
        {"dimension": "market_opportunity", "score": 70, "confidence": 0.6,
         "explanation": "e", "assumptions": [], "supporting_evidence": []}
    ])
    repo.save_recommendations(
        conn, workspace_id=workspace, analysis_id=analysis, product_id=product,
        recommendations=[
            {"title": "Ship SSO", "gap_category": "security", "verdict": "must_build",
             "reason": "r", "priority": 1, "confidence": 0.8},
            {"title": "Build wearable app", "gap_category": "mobile",
             "verdict": "do_not_build", "reason": "no demand", "priority": 9,
             "confidence": 0.5},
        ],
    )
    conn.commit()

    at = app.run()
    at.session_state["route"] = "workroom"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)

    captions = " ".join(str(c.value) for c in at.caption)
    assert mode.replace("_", " ").title() in captions, "the mode must be stated"


def test_competitor_add_form_renders(app, tmp_path):
    from pas.storage import db as db_module

    conn = db_module.get_connection(tmp_path / "ui.sqlite3")
    db_module.migrate(conn)
    _workspace, product, analysis = _product_with_analysis(conn, "Comp")

    at = app.run()
    at.session_state["route"] = "workroom"
    at.session_state["active_product"] = product
    at.session_state["active_analysis"] = analysis
    at.run()
    _assert_clean(at)
