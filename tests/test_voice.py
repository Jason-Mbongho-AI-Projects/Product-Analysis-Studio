"""Voice of Customer, document parsing, radar and scenario tests.

The quote-verification tests are the important ones here: a fabricated customer
quote is the most damaging output this platform could produce, because the user
will go looking for it in their own data.
"""

from __future__ import annotations

import io
import json

import pytest

from pas.agents.voice import VoiceOfCustomerAgent, sample_feedback
from pas.domain.contracts import FeedbackAnalysis
from pas.research.documents import (
    MAX_UPLOAD_BYTES,
    DocumentError,
    FeedbackRecord,
    deduplicate,
    extension_of,
    parse_pasted_feedback,
    parse_structured,
    parse_tabular,
    parse_text,
    parse_upload,
)
from pas.storage import voc_repo

# ---------------------------------------------------------------------------
# Document parsing (spec 1 / 11)
# ---------------------------------------------------------------------------


def test_csv_detects_the_text_column():
    data = b"id,rating,review\n1,5,Great product overall\n2,2,Onboarding was painful\n"
    parsed = parse_tabular(data)
    assert len(parsed.records) == 2
    assert parsed.records[0].content == "Great product overall"
    assert parsed.records[0].rating == 5.0


def test_csv_recognises_alternative_column_names():
    for header in ("comment", "feedback", "body", "text"):
        data = f"id,{header}\n1,Something useful was said here\n".encode()
        parsed = parse_tabular(data)
        assert parsed.records[0].content == "Something useful was said here"


def test_csv_falls_back_to_the_widest_column():
    data = (
        b"col_a,col_b\n"
        + b"\n".join(
            f"x{i},This is a much longer piece of customer commentary number {i}".encode()
            for i in range(5)
        )
    )
    parsed = parse_tabular(data)
    assert "longer piece of customer commentary" in parsed.records[0].content
    assert any("Guessed" in w for w in parsed.warnings)


def test_tsv_is_parsed():
    data = b"id\treview\n1\tTab separated feedback here\n"
    parsed = parse_tabular(data, delimiter="\t")
    assert parsed.records[0].content == "Tab separated feedback here"


def test_csv_without_a_usable_text_column_is_rejected():
    with pytest.raises(DocumentError):
        parse_tabular(b"a,b\n1,2\n3,4\n")


def test_csv_with_only_a_header_and_no_rows_is_rejected():
    with pytest.raises(DocumentError, match="No usable rows"):
        parse_tabular(b"id,review\n")


def test_csv_with_only_whitespace_is_rejected():
    with pytest.raises(DocumentError):
        parse_tabular(b"\n\n   \n")


def test_rows_with_empty_text_are_skipped():
    data = b"id,review\n1,Good detailed feedback here\n2,\n3,  \n4,More useful feedback\n"
    parsed = parse_tabular(data)
    assert len(parsed.records) == 2


def test_json_array_and_jsonl_both_parse():
    array = json.dumps(
        [{"text": "First review here", "rating": 4}, {"text": "Second review here"}]
    ).encode()
    assert len(parse_structured(array).records) == 2

    lines = b'{"content": "Line one feedback"}\n{"content": "Line two feedback"}\n'
    assert len(parse_structured(lines).records) == 2


def test_malformed_json_lines_are_skipped_not_fatal():
    data = b'{"content": "Good line here"}\nnot json at all\n{"content": "Another good line"}\n'
    assert len(parse_structured(data).records) == 2


def test_invalid_json_array_is_rejected():
    with pytest.raises(DocumentError, match="Invalid JSON"):
        parse_structured(b"[{broken}]")


def test_pasted_text_splits_on_blank_lines_then_newlines():
    blocks = parse_pasted_feedback("First item here.\n\nSecond item here.\n\nThird item.")
    assert len(blocks.records) == 3

    lines = parse_pasted_feedback("Line one here\nLine two here\nLine three here")
    assert len(lines.records) == 3


def test_empty_paste_is_rejected():
    with pytest.raises(DocumentError):
        parse_pasted_feedback("   \n  \n ")


def test_oversized_upload_is_rejected():
    with pytest.raises(DocumentError, match="larger than"):
        parse_text(b"x" * (MAX_UPLOAD_BYTES + 1))


def test_empty_upload_is_rejected():
    with pytest.raises(DocumentError, match="empty"):
        parse_text(b"")


def test_undecodable_bytes_do_not_raise():
    """A single bad byte must not fail an entire upload."""
    parsed = parse_text(b"valid text \xff\xfe more text")
    assert "valid text" in parsed.text


def test_unsupported_extension_is_rejected():
    with pytest.raises(DocumentError, match="Unsupported"):
        parse_upload("malware.exe", b"data")


@pytest.mark.parametrize(
    "filename,expected",
    [("a.csv", ".csv"), ("A.CSV", ".csv"), ("x.tar.gz", ".gz"), ("noext", "")],
)
def test_extension_detection(filename, expected):
    assert extension_of(filename) == expected


def test_deduplication_ignores_whitespace_and_case():
    records = [
        FeedbackRecord(content="Onboarding is slow"),
        FeedbackRecord(content="  onboarding   IS SLOW  "),
        FeedbackRecord(content="Something else entirely"),
    ]
    kept, dropped = deduplicate(records)
    assert len(kept) == 2
    assert dropped == 1


def test_pdf_parsing_round_trips():
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    parsed = parse_upload("doc.pdf", buffer.getvalue())
    assert parsed.page_count == 1
    # A blank page yields no text, which must be reported rather than crash.
    assert any("No extractable text" in w for w in parsed.warnings)


# ---------------------------------------------------------------------------
# Feedback sampling
# ---------------------------------------------------------------------------


def _items(count: int, size: int = 50) -> list[dict]:
    return [{"content": f"item {i} " + "x" * size, "rating": None} for i in range(count)]


def test_small_feedback_sets_are_sent_whole():
    rendered, included = sample_feedback(_items(10), max_chars=50_000)
    assert included == 10
    assert "item 9" in rendered


def test_large_feedback_sets_are_sampled_across_the_whole_range():
    """Taking the first N rows would bias to whatever the export sorted by."""
    items = _items(2000, size=200)
    rendered, included = sample_feedback(items, max_chars=10_000)

    assert included < len(items)
    # The sample must reach into the tail, not stop at the head.
    assert "item 1900" in rendered or "item 1800" in rendered
    assert len(rendered) <= 11_000


def test_empty_feedback_sampling():
    rendered, included = sample_feedback([])
    assert rendered == "" and included == 0


# ---------------------------------------------------------------------------
# Quote verification - the anti-fabrication guard
# ---------------------------------------------------------------------------


def _analysis_with_quotes(quotes: list[str]) -> FeedbackAnalysis:
    return FeedbackAnalysis.model_validate(
        {
            "total_items_analysed": 3,
            "overall_sentiment": "mixed",
            "sentiment_positive_pct": 30,
            "sentiment_neutral_pct": 20,
            "sentiment_negative_pct": 50,
            "clusters": [
                {
                    "label": "Onboarding friction",
                    "theme": "onboarding",
                    "sentiment": "negative",
                    "summary": "Setup takes too long.",
                    "share_of_feedback": 60,
                    "item_count": 2,
                    "representative_quotes": quotes,
                    "customer_language": ["set up", "took days"],
                    "is_churn_driver": True,
                    "is_feature_request": False,
                    "suggested_action": "Shorten setup.",
                    "severity": "high",
                    "confidence": 0.8,
                }
            ],
            "top_complaints": ["Onboarding"],
            "top_praise": [],
            "unmet_needs": [],
            "emerging_trends": [],
            "summary": "Onboarding dominates.",
            "caveats": [],
        }
    )


CORPUS = [
    {"content": "The onboarding took three days and we nearly gave up entirely."},
    {"content": "Setup was painful but support helped us through it."},
    {"content": "Reporting is excellent once you get going."},
]


def test_fabricated_quotes_are_removed():
    """A quote the user cannot find in their own data destroys all trust."""
    agent = VoiceOfCustomerAgent(CORPUS)
    result = _analysis_with_quotes(
        [
            "The onboarding took three days and we nearly gave up entirely.",
            "This product completely ruined my business and I want a refund.",
        ]
    )
    verified = agent._verify_quotes(result)

    quotes = verified["clusters"][0]["representative_quotes"]
    assert len(quotes) == 1
    assert "three days" in quotes[0]
    assert verified["quotes_dropped"] == 1
    assert any("could not be matched" in c for c in verified["caveats"])


def test_verbatim_quotes_survive_whitespace_differences():
    agent = VoiceOfCustomerAgent(CORPUS)
    result = _analysis_with_quotes(["Setup   was painful\nbut support helped us through it."])
    verified = agent._verify_quotes(result)
    assert len(verified["clusters"][0]["representative_quotes"]) == 1


def test_quote_matching_is_case_insensitive():
    agent = VoiceOfCustomerAgent(CORPUS)
    result = _analysis_with_quotes(["REPORTING IS EXCELLENT ONCE YOU GET GOING."])
    verified = agent._verify_quotes(result)
    assert len(verified["clusters"][0]["representative_quotes"]) == 1


def test_trivially_short_quotes_are_not_accepted():
    """Short fragments match by chance and are not evidence."""
    agent = VoiceOfCustomerAgent(CORPUS)
    result = _analysis_with_quotes(["the", "setup was"])
    verified = agent._verify_quotes(result)
    assert verified["clusters"][0]["representative_quotes"] == []


def test_all_quotes_fabricated_leaves_an_empty_list_not_an_error():
    agent = VoiceOfCustomerAgent(CORPUS)
    result = _analysis_with_quotes(["Completely invented customer statement here."])
    verified = agent._verify_quotes(result)
    assert verified["clusters"][0]["representative_quotes"] == []
    assert verified["quotes_dropped"] == 1


# ---------------------------------------------------------------------------
# Storage round-trips
# ---------------------------------------------------------------------------


def test_feedback_deduplicates_across_batches(conn, workspace, product):
    """Re-importing an overlapping export must not inflate a theme's share."""
    first = voc_repo.create_batch(
        conn, workspace_id=workspace, product_id=product, label="Batch 1",
        source_type="review",
    )
    inserted, duplicates = voc_repo.add_feedback_items(
        conn, workspace_id=workspace, product_id=product, batch_id=first,
        records=[FeedbackRecord(content="Onboarding is slow"),
                 FeedbackRecord(content="Pricing is too high")],
    )
    assert (inserted, duplicates) == (2, 0)

    second = voc_repo.create_batch(
        conn, workspace_id=workspace, product_id=product, label="Batch 2",
        source_type="review",
    )
    inserted, duplicates = voc_repo.add_feedback_items(
        conn, workspace_id=workspace, product_id=product, batch_id=second,
        records=[FeedbackRecord(content="Onboarding is slow"),
                 FeedbackRecord(content="Support is responsive")],
    )
    assert inserted == 1
    assert duplicates == 1
    assert voc_repo.feedback_item_count(conn, product) == 3


def test_feedback_analysis_round_trip(conn, workspace, product, analysis):
    record_id = voc_repo.save_feedback_analysis(
        conn, workspace_id=workspace, product_id=product, analysis_id=analysis,
        data={
            "total_items_analysed": 120,
            "overall_sentiment": "negative",
            "sentiment_positive_pct": 20,
            "sentiment_neutral_pct": 25,
            "sentiment_negative_pct": 55,
            "summary": "Pricing dominates complaints.",
            "top_complaints": ["Pricing"],
            "top_praise": ["Support"],
            "unmet_needs": ["Mobile"],
            "emerging_trends": ["Security questions rising"],
            "caveats": ["Small sample"],
            "clusters": [
                {"label": "Too expensive", "theme": "pricing", "sentiment": "negative",
                 "summary": "s", "share_of_feedback": 40, "item_count": 48,
                 "representative_quotes": ["way too expensive for what it does"],
                 "customer_language": ["expensive"], "is_churn_driver": True,
                 "is_feature_request": False, "severity": "high",
                 "suggested_action": "Review pricing", "confidence": 0.8},
            ],
        },
    )
    assert record_id

    stored = voc_repo.latest_feedback_analysis(conn, product)
    assert stored["items_analysed"] == 120
    assert stored["top_complaints"] == ["Pricing"]
    assert stored["clusters"][0]["is_churn_driver"] == 1
    assert stored["clusters"][0]["quotes"] == ["way too expensive for what it does"]


def test_deleting_a_batch_removes_its_feedback(conn, workspace, product):
    batch = voc_repo.create_batch(
        conn, workspace_id=workspace, product_id=product, label="B", source_type="review"
    )
    voc_repo.add_feedback_items(
        conn, workspace_id=workspace, product_id=product, batch_id=batch,
        records=[FeedbackRecord(content="Something a customer said")],
    )
    assert voc_repo.feedback_item_count(conn, product) == 1

    voc_repo.delete_batch(conn, batch)
    assert voc_repo.feedback_item_count(conn, product) == 0


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------


def test_radar_priority_is_expected_value(conn, workspace, product, analysis):
    """An unlikely catastrophe must not outrank a near-certain moderate issue."""
    voc_repo.save_radar(
        conn, workspace_id=workspace, analysis_id=analysis, product_id=product,
        signals=[
            {"signal_type": "threat", "title": "Unlikely catastrophe",
             "impact": 100, "probability": 5, "horizon": "long_term"},
            {"signal_type": "threat", "title": "Near-certain moderate problem",
             "impact": 55, "probability": 90, "horizon": "immediate"},
        ],
    )
    threats = voc_repo.list_radar(conn, analysis, "threat")

    assert threats[0]["title"] == "Near-certain moderate problem"
    assert threats[0]["priority_score"] == pytest.approx(49.5)
    assert threats[1]["priority_score"] == pytest.approx(5.0)


def test_radar_separates_opportunities_from_threats(conn, workspace, product, analysis):
    voc_repo.save_radar(
        conn, workspace_id=workspace, analysis_id=analysis, product_id=product,
        signals=[
            {"signal_type": "opportunity", "title": "Whitespace", "impact": 70,
             "probability": 60, "supporting_evidence": ["gap found"]},
            {"signal_type": "threat", "title": "New entrant", "impact": 60,
             "probability": 40},
        ],
    )
    assert len(voc_repo.list_radar(conn, analysis, "opportunity")) == 1
    assert len(voc_repo.list_radar(conn, analysis, "threat")) == 1
    assert len(voc_repo.list_radar(conn, analysis)) == 2
    assert voc_repo.list_radar(conn, analysis, "opportunity")[0]["supporting_evidence"] == [
        "gap found"
    ]


def test_radar_is_replaced_not_appended(conn, workspace, product, analysis):
    for _ in range(2):
        voc_repo.save_radar(
            conn, workspace_id=workspace, analysis_id=analysis, product_id=product,
            signals=[{"signal_type": "threat", "title": "T", "impact": 10, "probability": 10}],
        )
    assert len(voc_repo.list_radar(conn, analysis)) == 1


# ---------------------------------------------------------------------------
# Scenarios and comments
# ---------------------------------------------------------------------------


def test_scenario_round_trip(conn, workspace, product, analysis):
    voc_repo.save_scenario(
        conn, workspace_id=workspace, product_id=product, analysis_id=analysis,
        data={
            "question": "What if we raise prices 30%?",
            "recommendation": "Test on new customers first.",
            "reversibility": "Easy to reverse for new signups.",
            "assumptions": ["Elasticity around -1.2"],
            "outcomes": [{"case": "base", "probability": 50, "narrative": "n"}],
            "leading_indicators": ["Trial conversion"],
            "risks": ["Churn spike"],
            "confidence": 0.55,
        },
    )
    runs = voc_repo.list_scenario_runs(conn, product)
    assert len(runs) == 1
    assert runs[0]["outcomes"][0]["case"] == "base"
    assert runs[0]["assumptions"] == ["Elasticity around -1.2"]


def test_comments_round_trip_and_count(conn, workspace, product):
    voc_repo.add_comment(
        conn, workspace_id=workspace, product_id=product, user_id=None,
        author_label="Alice", target_type="recommendation", target_id="rec_1",
        body="Do we have data for this?",
    )
    comments = voc_repo.list_comments(conn, "recommendation", "rec_1")
    assert len(comments) == 1
    assert comments[0]["author_label"] == "Alice"
    assert voc_repo.comment_counts(conn, product) == {"rec_1": 1}

    voc_repo.resolve_comment(conn, comments[0]["id"])
    assert voc_repo.comment_counts(conn, product) == {}


def test_comment_with_a_nonexistent_user_does_not_break(conn, workspace, product):
    """A session can outlive a deleted account."""
    comment_id = voc_repo.add_comment(
        conn, workspace_id=workspace, product_id=product, user_id="usr_gone",
        author_label="Ghost", target_type="roadmap", target_id="rdm_1", body="Note",
    )
    assert comment_id
    assert voc_repo.list_comments(conn, "roadmap", "rdm_1")[0]["user_id"] is None
