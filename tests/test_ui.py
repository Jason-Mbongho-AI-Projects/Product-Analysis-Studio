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

    ui_app._service.clear()  # drop the cached service between tests
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
    assert "MUST BUILD" in rendered
    assert "DO NOT BUILD" in rendered, "the do-not-build verdict must be visible"


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
