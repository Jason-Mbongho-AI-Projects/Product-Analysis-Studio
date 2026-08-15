"""Service-layer tests: intake validation, orchestration and UI escaping."""

from __future__ import annotations

import pytest

from pas.domain.enums import AnalysisStatus
from pas.research.fetcher import _Extractor
from pas.storage import repositories as repo


@pytest.fixture
def service(tmp_path, monkeypatch):
    from pas.config import AppConfig
    from pas.service import StudioService
    from pas.storage import db as db_module

    db_module.reset_thread_state()
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "svc.sqlite3")
    yield StudioService(AppConfig(api_key="test", db_path=tmp_path / "svc.sqlite3"))
    db_module.reset_thread_state()


def test_intake_requires_content(service):
    with pytest.raises(ValueError, match="Describe the product"):
        service.create_product(name="x", intake_kind="idea", intake_input="   ")


def test_intake_rejects_unsafe_url_before_persisting(service):
    with pytest.raises(ValueError, match="cannot be analysed"):
        service.create_product(
            name="Evil",
            intake_kind="url",
            intake_input="internal",
            source_url="http://169.254.169.254/latest/meta-data/",
        )
    assert service.list_products() == []


def test_idea_mode_creates_a_product(service):
    product_id = service.create_product(
        name="",
        intake_kind="idea",
        intake_input="An AI assistant that helps hospitals manage cybersecurity compliance",
    )
    product = service.get_product(product_id)
    assert product is not None
    assert product["intake_kind"] == "idea"
    assert product["name"], "a name must be derived when none was given"


def test_analysis_requires_configured_provider(tmp_path, monkeypatch):
    from pas.config import AppConfig
    from pas.service import StudioService
    from pas.storage import db as db_module

    db_module.reset_thread_state()
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "nokey.sqlite3")
    service = StudioService(AppConfig(api_key=None, db_path=tmp_path / "nokey.sqlite3"))
    product_id = service.create_product(name="X", intake_kind="idea", intake_input="an idea")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        service.start_analysis(product_id)
    db_module.reset_thread_state()


def test_extra_source_urls_are_validated(service):
    product_id = service.create_product(name="X", intake_kind="idea", intake_input="an idea")
    with pytest.raises(ValueError, match="rejected"):
        service.start_analysis(product_id, extra_urls=["http://127.0.0.1:9000/"])


def test_decide_rejects_unknown_state(service):
    with pytest.raises(ValueError, match="Unknown decision state"):
        service.decide("rec_x", "maybe")


def test_accept_creates_roadmap_item(service):
    product_id = service.create_product(name="X", intake_kind="idea", intake_input="an idea")
    analysis = repo.create_analysis(
        service.conn, workspace_id=service.workspace_id, product_id=product_id
    )["id"]
    repo.save_recommendations(
        service.conn,
        workspace_id=service.workspace_id,
        analysis_id=analysis,
        product_id=product_id,
        recommendations=[{"title": "Ship audit logging", "gap_category": "security", "effort": "l"}],
    )
    rec = repo.list_recommendations(service.conn, analysis)[0]

    service.accept_to_roadmap(rec["id"], horizon="now")

    roadmap = service.roadmap(product_id)
    assert len(roadmap["now"]) == 1
    assert roadmap["now"][0]["title"] == "Ship audit logging"
    assert roadmap["now"][0]["effort"] == "l"
    assert repo.list_recommendations(service.conn, analysis)[0]["decision_state"] == "accepted"


def test_roadmap_item_requires_title(service):
    product_id = service.create_product(name="X", intake_kind="idea", intake_input="idea")
    with pytest.raises(ValueError, match="needs a title"):
        service.add_roadmap_item(product_id, "   ")


def test_compare_versions_reports_deltas(service):
    product_id = service.create_product(name="X", intake_kind="idea", intake_input="idea")
    first = repo.create_analysis(
        service.conn, workspace_id=service.workspace_id, product_id=product_id
    )["id"]
    second = repo.create_analysis(
        service.conn, workspace_id=service.workspace_id, product_id=product_id
    )["id"]

    repo.save_scores(service.conn, first, [
        {"dimension": "market_opportunity", "score": 74, "confidence": 0.6, "explanation": "then"}
    ])
    repo.save_scores(service.conn, second, [
        {"dimension": "market_opportunity", "score": 86, "confidence": 0.7, "explanation": "now"}
    ])

    diff = service.compare_versions(product_id, first, second)
    assert diff["score_deltas"][0]["delta"] == 12.0
    assert diff["composite_after"]["score"] > diff["composite_before"]["score"]


def test_diagnostics_never_exposes_the_api_key(tmp_path, monkeypatch):
    """The diagnostics payload reaches the browser, so it must carry no secret."""
    from pas.config import AppConfig
    from pas.service import StudioService
    from pas.storage import db as db_module

    secret = "sk-or-v1-super-secret-key-value"
    db_module.reset_thread_state()
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "diag.sqlite3")
    service = StudioService(AppConfig(api_key=secret, db_path=tmp_path / "diag.sqlite3"))

    diagnostics = service.diagnostics()
    assert diagnostics["provider_configured"] is True
    assert "api_key" not in diagnostics
    assert secret not in repr(diagnostics)
    db_module.reset_thread_state()


def test_dashboard_is_safe_on_an_empty_analysis(service):
    """An analysis with no agent output must render, not crash."""
    product_id = service.create_product(name="X", intake_kind="idea", intake_input="idea")
    analysis = repo.create_analysis(
        service.conn, workspace_id=service.workspace_id, product_id=product_id
    )["id"]

    data = service.dashboard(analysis)
    assert data["profile"] is None
    assert data["scores"] == []
    assert data["composite"]["score"] == 0.0
    assert data["recommendations"] == []


# ---------------------------------------------------------------------------
# Output escaping (spec 41)
# ---------------------------------------------------------------------------


def test_ui_escapes_model_output():
    from pas.ui.components import esc

    assert esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert esc('" onerror="x') == "&quot; onerror=&quot;x"
    assert esc(None) == ""


def test_citation_links_only_linkify_http_urls():
    from pas.ui.components import citation_links

    rendered = citation_links([{"url": "javascript:alert(1)", "title": "Bad"}])
    assert "<a " not in rendered

    rendered = citation_links([{"url": "https://example.com", "title": "Good"}])
    assert 'href="https://example.com"' in rendered
    assert 'rel="noopener noreferrer nofollow"' in rendered


def test_html_extractor_drops_scripts():
    parser = _Extractor()
    parser.feed(
        "<html><head><title>T</title></head><body>"
        "<script>steal()</script><p>Real content</p></body></html>"
    )
    assert parser.title == "T"
    assert "steal" not in parser.text
    assert "Real content" in parser.text
