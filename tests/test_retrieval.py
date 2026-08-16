"""Hybrid retrieval, collaboration and accessibility tests.

The accessibility tests compute real WCAG contrast ratios rather than asserting
that a stylesheet exists.
"""

from __future__ import annotations

import re

import pytest

from pas.analysis.retrieval import (
    BM25Index,
    HybridRetriever,
    content_hash,
    cosine,
    normalise_scores,
    pack_vector,
    tokenise,
    unpack_vector,
)
from pas.config import AppConfig
from pas.storage import voc_repo

# ---------------------------------------------------------------------------
# Vector plumbing
# ---------------------------------------------------------------------------


def test_vectors_round_trip_through_storage():
    original = [0.1, -0.5, 0.9, 0.0, 1.0]
    restored = unpack_vector(pack_vector(original))
    assert len(restored) == len(original)
    for a, b in zip(original, restored):
        assert a == pytest.approx(b, abs=1e-6)


def test_cosine_similarity_basics():
    assert cosine([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_handles_degenerate_input():
    assert cosine([], [1, 2]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0
    assert cosine([1, 2, 3], [1, 2]) == 0.0, "mismatched dimensions must not raise"


def test_content_hash_is_stable_across_formatting():
    assert content_hash("  Hello   World  ") == content_hash("hello world")
    assert content_hash("a") != content_hash("b")


def test_normalise_scores_maps_to_unit_range():
    assert normalise_scores([1.0, 3.0, 5.0]) == [0.0, 0.5, 1.0]
    assert normalise_scores([]) == []
    # A flat set must not divide by zero.
    assert normalise_scores([2.0, 2.0]) == [1.0, 1.0]
    assert normalise_scores([0.0, 0.0]) == [0.0, 0.0]


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


def test_tokenise_drops_stopwords_and_short_tokens():
    tokens = tokenise("The product is a very good SOC 2 platform")
    assert "the" not in tokens and "is" not in tokens and "very" not in tokens
    assert "product" in tokens and "soc" in tokens and "platform" in tokens


def test_bm25_ranks_the_matching_document_highest():
    corpus = [
        "Competitor pricing starts at forty nine dollars per month",
        "The onboarding flow requires six separate steps",
        "SOC 2 Type II certification was completed last year",
    ]
    index = BM25Index.build(corpus)
    scores = [index.score("what is competitor pricing", i) for i in range(len(corpus))]
    assert scores[0] == max(scores)
    assert scores[0] > 0


def test_bm25_rewards_rare_terms_over_common_ones():
    corpus = [
        "pricing pricing pricing pricing information",
        "pricing and SCIM provisioning support",
    ]
    index = BM25Index.build(corpus)
    # SCIM appears in one document only, so it discriminates.
    assert index.score("SCIM", 1) > index.score("SCIM", 0)


def test_bm25_returns_zero_for_no_overlap():
    index = BM25Index.build(["completely unrelated content here"])
    assert index.score("pricing competitors", 0) == 0.0


def test_bm25_handles_an_empty_corpus():
    index = BM25Index.build([])
    assert index.score("anything", 0) == 0.0


# ---------------------------------------------------------------------------
# Hybrid ranking
# ---------------------------------------------------------------------------


class _StubProvider:
    """Embeddings that encode a couple of topical axes deterministically."""

    name = "stub"

    def __init__(self):
        self.calls = 0

    def embed(self, *, model, texts):
        from pas.ai.provider import Usage

        self.calls += 1
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([
                float("pric" in lowered or "cost" in lowered or "expensive" in lowered),
                float("compet" in lowered or "rival" in lowered),
                float("onboard" in lowered or "setup" in lowered),
            ])
        return vectors, Usage(provider="stub", model=model, total_tokens=len(texts))


def _retriever(conn, workspace, enabled=True):
    return HybridRetriever(
        conn,
        config=AppConfig(api_key="k", embeddings_enabled=enabled),
        provider=_StubProvider(),
        workspace_id=workspace,
    )


def _evidence(claim, grade="strong_inference", confidence=0.8, ident=None):
    return {
        "id": ident or f"evd_{abs(hash(claim)) % 10000}",
        "claim": claim,
        "detail": "",
        "grade": grade,
        "confidence": confidence,
        "citations": [],
    }


def test_hybrid_ranks_the_relevant_claim_first(conn, workspace, analysis):
    items = [
        _evidence("Onboarding requires six manual steps"),
        _evidence("Competitor pricing starts at $49 per month"),
        _evidence("The logo was refreshed last quarter"),
    ]
    ranked = _retriever(conn, workspace).rank(
        "how does our pricing compare to competitors", items, analysis_id=analysis
    )
    assert ranked
    assert "pricing" in ranked[0].item["claim"].lower()


def test_verified_facts_outrank_hypotheses_at_equal_relevance(conn, workspace, analysis):
    items = [
        _evidence("Competitor pricing starts at $49", "ai_hypothesis", 0.8, "evd_guess"),
        _evidence("Competitor pricing starts at $49", "verified_fact", 0.8, "evd_fact"),
    ]
    ranked = _retriever(conn, workspace).rank(
        "competitor pricing", items, analysis_id=analysis
    )
    assert ranked[0].item["id"] == "evd_fact"


def test_embeddings_are_cached_across_queries(conn, workspace, analysis):
    """A claim must be embedded once, not once per question."""
    retriever = _retriever(conn, workspace)
    items = [_evidence("Competitor pricing starts at $49 per month")]

    retriever.rank("pricing", items, analysis_id=analysis)
    first_calls = retriever._provider.calls
    retriever.rank("pricing again", items, analysis_id=analysis)

    # The second query embeds only the new question, not the claim again.
    cached = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
    assert cached >= 2
    assert retriever._provider.calls > first_calls  # the new question
    stats = retriever.stats()
    assert stats["cached_vectors"] == cached


def test_retrieval_degrades_to_lexical_when_embeddings_fail(conn, workspace, analysis):
    class Exploding(_StubProvider):
        def embed(self, *, model, texts):
            raise RuntimeError("embedding service down")

    retriever = HybridRetriever(
        conn,
        config=AppConfig(api_key="k", embeddings_enabled=True),
        provider=Exploding(),
        workspace_id=workspace,
    )
    items = [
        _evidence("Competitor pricing starts at $49"),
        _evidence("Unrelated note about the logo"),
    ]
    ranked = retriever.rank("competitor pricing", items, analysis_id=analysis)

    assert ranked, "a failed embedding must not break search"
    assert "pricing" in ranked[0].item["claim"].lower()
    assert all(entry.semantic == 0.0 for entry in ranked)


def test_disabling_embeddings_uses_lexical_only(conn, workspace, analysis):
    retriever = _retriever(conn, workspace, enabled=False)
    items = [_evidence("Competitor pricing starts at $49")]
    ranked = retriever.rank("pricing", items, analysis_id=analysis)

    assert ranked
    assert retriever._provider.calls == 0
    assert ranked[0].semantic == 0.0


def test_ranking_an_empty_corpus_is_safe(conn, workspace, analysis):
    assert _retriever(conn, workspace).rank("anything", [], analysis_id=analysis) == []


def test_ranking_respects_the_limit(conn, workspace, analysis):
    items = [_evidence(f"Pricing observation number {i}", ident=f"evd_{i}") for i in range(30)]
    ranked = _retriever(conn, workspace).rank("pricing", items, limit=5, analysis_id=analysis)
    assert len(ranked) <= 5


# ---------------------------------------------------------------------------
# Mentions, assignment, ordering, activity (spec 32)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Hey @alice, thoughts?", ["alice"]),
        ("@alice and @bob.smith please review", ["alice", "bob.smith"]),
        ("email me at a@b.com", []),
        ("contact first.last@corp.io and @dave", ["dave"]),
        ("@alice. Also @carol-jones!", ["alice", "carol-jones"]),
        ("no mentions at all", []),
        ("@a", []),
    ],
)
def test_mention_extraction(body, expected):
    """An email address must never be read as a mention."""
    assert voc_repo.extract_mentions(body) == expected


def test_mentions_resolve_against_workspace_members(conn, workspace, product):
    from pas.auth.service import AuthService

    auth = AuthService(conn)
    alice = auth.create_user(
        email="alice@example.com", password="correct-horse-battery-staple",
        name="Alice Smith", workspace_id=workspace,
    )

    comment_id = voc_repo.add_comment(
        conn, workspace_id=workspace, product_id=product, user_id=None,
        author_label="Bob", target_type="recommendation", target_id="rec_1",
        body="@alice can you check this? @nobody too",
    )
    matched = voc_repo.record_mentions(
        conn, workspace_id=workspace, comment_id=comment_id,
        body="@alice can you check this? @nobody too",
    )

    assert matched == ["alice"], "unresolved handles must be ignored"
    mentions = voc_repo.list_mentions(conn, alice)
    assert len(mentions) == 1
    assert "check this" in mentions[0]["body"]

    voc_repo.mark_mentions_seen(conn, alice)
    assert voc_repo.list_mentions(conn, alice) == []


def test_mention_by_display_name(conn, workspace, product):
    from pas.auth.service import AuthService

    auth = AuthService(conn)
    user = auth.create_user(
        email="x@example.com", password="correct-horse-battery-staple",
        name="Dana Lee", workspace_id=workspace,
    )
    comment_id = voc_repo.add_comment(
        conn, workspace_id=workspace, product_id=product, user_id=None,
        author_label="Bob", target_type="roadmap_item", target_id="r1",
        body="@dana.lee please own this",
    )
    assert voc_repo.record_mentions(
        conn, workspace_id=workspace, comment_id=comment_id, body="@dana.lee please own this"
    ) == ["dana.lee"]
    assert len(voc_repo.list_mentions(conn, user)) == 1


def test_roadmap_reordering_swaps_adjacent_items(conn, workspace, product):
    from pas.storage import repositories as repo

    first = repo.add_roadmap_item(
        conn, workspace_id=workspace, product_id=product, title="First", horizon="now"
    )
    second = repo.add_roadmap_item(
        conn, workspace_id=workspace, product_id=product, title="Second", horizon="now"
    )

    order = [i["title"] for i in repo.list_roadmap(conn, product)]
    assert order == ["First", "Second"]

    voc_repo.reorder_roadmap_item(conn, second, -1)
    assert [i["title"] for i in repo.list_roadmap(conn, product)] == ["Second", "First"]


def test_reordering_at_the_boundary_is_a_no_op(conn, workspace, product):
    from pas.storage import repositories as repo

    only = repo.add_roadmap_item(
        conn, workspace_id=workspace, product_id=product, title="Only", horizon="now"
    )
    voc_repo.reorder_roadmap_item(conn, only, -1)
    voc_repo.reorder_roadmap_item(conn, only, 1)
    assert len(repo.list_roadmap(conn, product)) == 1


def test_reordering_only_affects_the_same_horizon(conn, workspace, product):
    from pas.storage import repositories as repo

    now_item = repo.add_roadmap_item(
        conn, workspace_id=workspace, product_id=product, title="Now item", horizon="now"
    )
    repo.add_roadmap_item(
        conn, workspace_id=workspace, product_id=product, title="Next item", horizon="next"
    )
    voc_repo.reorder_roadmap_item(conn, now_item, -1)

    grouped = {i["horizon"]: i["title"] for i in repo.list_roadmap(conn, product)}
    assert grouped["now"] == "Now item"
    assert grouped["next"] == "Next item"


def test_assignment_ignores_a_missing_user(conn, workspace, product):
    from pas.storage import repositories as repo

    item = repo.add_roadmap_item(
        conn, workspace_id=workspace, product_id=product, title="Task", horizon="now"
    )
    voc_repo.assign_roadmap_item(conn, item, "usr_does_not_exist", "Ghost")

    stored = repo.list_roadmap(conn, product)[0]
    assert stored["assignee_id"] is None
    assert stored["assignee_label"] == "Ghost"


def test_activity_feed_merges_audit_and_comments(conn, workspace, product):
    from pas.auth.service import AuthService

    auth = AuthService(conn)
    auth.audit(
        workspace_id=workspace, identity=None, action="product.created",
        target_type="product", target_id=product, detail="Test product",
    )
    voc_repo.add_comment(
        conn, workspace_id=workspace, product_id=product, user_id=None,
        author_label="Alice", target_type="recommendation", target_id="rec_1",
        body="Worth doing",
    )

    feed = voc_repo.activity_feed(conn, product)
    kinds = {entry["kind"] for entry in feed}
    assert "audit" in kinds and "comment" in kinds
    # Newest first.
    assert feed == sorted(feed, key=lambda e: e["at"], reverse=True)


# ---------------------------------------------------------------------------
# Accessibility (spec 53)
# ---------------------------------------------------------------------------


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance."""
    hex_colour = hex_colour.lstrip("#")
    if len(hex_colour) == 3:
        hex_colour = "".join(c * 2 for c in hex_colour)
    channels = []
    for offset in (0, 2, 4):
        value = int(hex_colour[offset : offset + 2], 16) / 255
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    a = _relative_luminance(foreground)
    b = _relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


#: The darkest surface any text sits on.
BACKGROUND = "#0b0c0e"


def test_contrast_helper_matches_known_values():
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.1)
    assert contrast_ratio("#000000", "#000000") == pytest.approx(1.0, abs=0.01)


def test_body_and_muted_text_meet_wcag_aa():
    from pas.ui.theme import PALETTE

    body = contrast_ratio(PALETTE["text"], BACKGROUND)
    muted = contrast_ratio(PALETTE["muted"], BACKGROUND)

    assert body >= 4.5, f"body text contrast {body:.2f} is below WCAG AA"
    # Muted text is secondary, so AA-large (3:1) is the applicable threshold.
    assert muted >= 3.0, f"muted text contrast {muted:.2f} is below WCAG AA-large"


def test_status_colours_are_distinguishable_against_the_background():
    from pas.ui.theme import PALETTE

    for key in ("success", "danger", "accent", "primary_2"):
        ratio = contrast_ratio(PALETTE[key], BACKGROUND)
        assert ratio >= 3.0, f"{key} contrast {ratio:.2f} is too low to read"


def test_evidence_grade_colours_are_readable():
    from pas.ui.theme import GRADE_STYLES

    for grade, (_label, colour) in GRADE_STYLES.items():
        ratio = contrast_ratio(colour, BACKGROUND)
        assert ratio >= 3.0, f"grade '{grade}' colour {colour} contrast {ratio:.2f} too low"


def test_verdict_and_threat_colours_are_readable():
    from pas.ui.theme import THREAT_STYLES, VERDICT_STYLES

    for verdict, (_label, colour) in VERDICT_STYLES.items():
        assert contrast_ratio(colour, BACKGROUND) >= 3.0, f"verdict {verdict}"
    for level, colour in THREAT_STYLES.items():
        assert contrast_ratio(colour, BACKGROUND) >= 3.0, f"threat {level}"


def test_stylesheet_defines_visible_focus_states():
    """Keyboard users must be able to see where they are."""
    from pas.ui.theme import _CSS

    assert ":focus-visible" in _CSS
    assert "outline" in _CSS
    # An outline of `none` anywhere in the focus rule would defeat the purpose.
    focus_block = _CSS[_CSS.index(":focus-visible") : _CSS.index(":focus-visible") + 400]
    assert "outline: none" not in focus_block


def test_stylesheet_does_not_force_unreadable_input_text():
    """The original build styled input text black on a dark panel."""
    from pas.ui.theme import _CSS

    assert "color: #000000" not in _CSS.replace(" ", " ")
    assert re.search(r"input[^}]*color:\s*var\(--text\)", _CSS) is not None


# ---------------------------------------------------------------------------
# Research providers (spec 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/plausible/analytics", ("plausible", "analytics")),
        ("https://github.com/foo/bar.git", ("foo", "bar")),
        ("http://www.github.com/a/b/tree/main", ("a", "b")),
        ("https://example.com/foo/bar", None),
        ("https://github.com/onlyowner", None),
        ("not a url", None),
        ("", None),
    ],
)
def test_github_url_parsing(url, expected):
    from pas.research.providers import parse_github_url

    repo = parse_github_url(url)
    assert (None if repo is None else (repo.owner, repo.name)) == expected


def test_github_summary_renders_as_prompt_text():
    from pas.research.providers import GitHubProvider

    text = GitHubProvider.as_text({
        "slug": "acme/tool", "url": "https://github.com/acme/tool",
        "description": "A tool", "stars": 1200, "forks": 30, "open_issues": 4,
        "language": "Python", "topics": ["cli"], "license": "MIT",
        "created_at": "2020-01-01", "pushed_at": "2026-08-01", "archived": False,
        "releases": [{"name": "v2.0", "published_at": "2026-07-01", "body": "Adds SSO"}],
    })
    assert "acme/tool" in text
    assert "1200" in text
    assert "Adds SSO" in text
    assert "ARCHIVED" not in text


def test_github_summary_flags_archived_repositories():
    from pas.research.providers import GitHubProvider

    text = GitHubProvider.as_text({
        "slug": "old/thing", "url": "u", "description": "", "stars": 1, "forks": 0,
        "open_issues": 0, "language": "", "topics": [], "license": "",
        "created_at": "2015-01-01", "pushed_at": "2018-01-01", "archived": True,
        "releases": [],
    })
    assert "ARCHIVED" in text, "an abandoned project is a material signal"


def test_providers_reject_unsafe_seeds():
    """Every provider must refuse an SSRF-unsafe seed."""
    from pas.research.providers import (
        ChangelogProvider,
        FeedProvider,
        SitemapProvider,
    )

    for provider in (SitemapProvider(), FeedProvider(), ChangelogProvider()):
        assert provider.discover("http://169.254.169.254/") == []
        assert provider.discover("file:///etc/passwd") == []
        assert provider.discover("") == []


def test_changelog_provider_offers_conventional_paths():
    from pas.research.providers import ChangelogProvider

    targets = ChangelogProvider().discover("https://example.com/product")
    urls = [t.url for t in targets]
    assert any(u.endswith("/changelog") for u in urls)
    assert all(u.startswith("https://example.com/") for u in urls)


def test_default_providers_respects_the_deep_flag():
    from pas.research.providers import default_providers

    shallow = default_providers("https://example.com", deep=False)
    deep = default_providers("https://example.com", deep=True)
    assert len(deep) > len(shallow)


# ---------------------------------------------------------------------------
# Text truncation (UI)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,limit,expected",
    [
        ("Short label", 40, "Short label"),
        ("", 20, ""),
        ("Dominance of Corn and Soybean Production", 34, "Dominance of Corn and Soybean…"),
        # Must not cut mid-word.
        ("Competitive pressure from incumbents", 20, "Competitive…"),
        # Trailing punctuation is trimmed before the ellipsis.
        ("One two three, four five", 15, "One two…"),
    ],
)
def test_truncate_respects_word_boundaries(text, limit, expected):
    """A hard slice produced labels like 'Soybea', which reads as a bug."""
    from pas.ui.components import truncate

    assert truncate(text, limit) == expected


def test_truncate_never_exceeds_the_limit():
    from pas.ui.components import truncate

    for length in range(5, 60):
        result = truncate("The quick brown fox jumps over the lazy dog", length)
        assert len(result) <= length, f"limit {length} produced {len(result)} chars"


def test_truncate_handles_a_single_long_word():
    from pas.ui.components import truncate

    result = truncate("Supercalifragilisticexpialidocious", 12)
    assert len(result) <= 12


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "$0.00"),
        (None, "$0.00"),
        # A real but tiny cost must not read as free.
        (0.00002, "<$0.0001"),
        (0.0001, "$0.0001"),
        (0.1224, "$0.1224"),
        (12.5, "$12.50"),
        (1234.5, "$1,234.50"),
    ],
)
def test_cost_formatting_never_shows_a_real_cost_as_zero(value, expected):
    from pas.ui.components import format_cost

    assert format_cost(value) == expected
