"""Voice of Customer: ingestion, themes and drilldown (spec 11)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ...domain.enums import FeedbackSource, FeedbackTheme, Sentiment
from ...research.documents import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    DocumentError,
)
from ...service import StudioService
from ..components import chip, empty_state, esc, kpi
from ..theme import PALETTE

SENTIMENT_COLOURS = {
    "positive": PALETTE["success"],
    "neutral": PALETTE["muted"],
    "negative": PALETTE["danger"],
    "mixed": PALETTE["accent"],
}

SEVERITY_COLOURS = {
    "critical": "#f87171",
    "high": "#fb923c",
    "medium": "#fbbf24",
    "low": "#38bdf8",
    "informational": "#94a3b8",
}


def render(service: StudioService, product: dict, analysis_id: str | None) -> None:
    st.markdown("### Voice of customer")
    st.caption(
        "Analyses feedback you supply — reviews, interviews, tickets, survey "
        "responses. This is the only place the platform reads real customer words, "
        "which makes it the strongest evidence available."
    )

    tabs = st.tabs(["Themes", "Add feedback", "Sources"])
    with tabs[0]:
        _themes(service, product, analysis_id)
    with tabs[1]:
        _ingest(service, product)
    with tabs[2]:
        _sources(service, product)


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


def _themes(service: StudioService, product: dict, analysis_id: str | None) -> None:
    stored = service.feedback_count(product["id"])
    analysis = service.feedback_analysis(product["id"])

    if stored == 0:
        empty_state(
            "No customer feedback yet",
            "Add reviews, interview notes or support tickets under 'Add feedback'.",
        )
        return

    header, action = st.columns([3, 1])
    with header:
        st.markdown(f"**{stored:,}** feedback items stored")
        if analysis:
            st.caption(
                f"Last analysed {str(analysis['created_at'])[:16].replace('T', ' ')} "
                f"· {analysis['items_analysed']:,} items"
            )
    with action:
        if st.button(
            "Analyse feedback" if not analysis else "Re-analyse",
            type="primary",
            use_container_width=True,
        ):
            try:
                with st.spinner("Clustering feedback into themes..."):
                    service.analyse_feedback(product["id"], analysis_id)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc), icon=":material/error:")

    if not analysis:
        st.info(
            "Feedback is stored but not yet analysed. Run the analysis to cluster "
            "it into themes.",
            icon=":material/info:",
        )
        return

    st.markdown("---")

    cols = st.columns(4)
    with cols[0]:
        kpi("Items analysed", f"{analysis['items_analysed']:,}")
    with cols[1]:
        sentiment = analysis["overall_sentiment"]
        kpi(
            "Overall sentiment",
            sentiment.title(),
            colour=SENTIMENT_COLOURS.get(sentiment),
        )
    with cols[2]:
        kpi("Negative", f"{analysis['negative_pct']:.0f}%", colour=PALETTE["danger"])
    with cols[3]:
        churn = [c for c in analysis["clusters"] if c["is_churn_driver"]]
        kpi("Churn drivers", str(len(churn)), colour=PALETTE["danger"] if churn else None)

    for caveat in analysis.get("caveats", []):
        st.warning(caveat, icon=":material/info:")

    if analysis["summary"]:
        st.markdown(f"**{esc(analysis['summary'])}**")

    clusters = analysis["clusters"]
    if clusters:
        st.markdown("#### Theme distribution")
        chart = pd.DataFrame(
            [{"Theme": c["label"][:40], "Share %": c["share_pct"]} for c in clusters]
        ).set_index("Theme")
        st.bar_chart(chart, height=max(240, 34 * len(clusters)), horizontal=True,
                     color=PALETTE["primary_2"])

        st.markdown("#### Themes")
        for cluster in clusters:
            _cluster_card(service, product, cluster)

    cols = st.columns(3)
    for column, (label, key) in zip(
        cols,
        [
            ("Top complaints", "top_complaints"),
            ("Top praise", "top_praise"),
            ("Unmet needs", "unmet_needs"),
        ],
    ):
        with column:
            st.markdown(f"**{label}**")
            items = analysis.get(key) or []
            if not items:
                st.caption("None identified.")
            for item in items:
                st.markdown(f"- {esc(item)}")

    trends = analysis.get("emerging_trends") or []
    if trends:
        st.markdown("**Emerging trends**")
        for trend in trends:
            st.markdown(f"- {esc(trend)}")


def _cluster_card(service: StudioService, product: dict, cluster: dict[str, Any]) -> None:
    sentiment = cluster["sentiment"]
    with st.container(border=True):
        head, share = st.columns([4, 1])
        with head:
            badges = [chip(sentiment, SENTIMENT_COLOURS.get(sentiment, PALETTE["muted"]))]
            try:
                badges.append(chip(FeedbackTheme(cluster["theme"]).label, PALETTE["primary_2"]))
            except ValueError:
                pass
            if cluster["is_churn_driver"]:
                badges.append(chip("churn driver", PALETTE["danger"]))
            if cluster["is_feature_request"]:
                badges.append(chip("feature request", PALETTE["accent"]))
            badges.append(
                chip(cluster["severity"], SEVERITY_COLOURS.get(cluster["severity"], PALETTE["muted"]))
            )
            st.markdown(
                f"**{esc(cluster['label'])}**<br>{' '.join(badges)}",
                unsafe_allow_html=True,
            )
        with share:
            st.markdown(
                f"<div style='text-align:right;font-size:1.5rem;font-weight:800'>"
                f"{cluster['share_pct']:.0f}%</div>"
                f"<div style='text-align:right;font-size:0.7rem;color:{PALETTE['muted']}'>"
                f"{cluster['item_count']} items</div>",
                unsafe_allow_html=True,
            )

        st.write(cluster["summary"])
        if cluster["suggested_action"]:
            st.markdown(f"**Suggested action:** {esc(cluster['suggested_action'])}")

        quotes = cluster.get("quotes") or []
        language = cluster.get("customer_language") or []

        with st.expander(f"Evidence ({len(quotes)} verbatim quotes)"):
            if quotes:
                for quote in quotes:
                    st.markdown(
                        f"<div style='border-left:3px solid {PALETTE['primary']};"
                        f"padding-left:0.7rem;margin-bottom:0.6rem;color:{PALETTE['text']};"
                        f"font-style:italic'>“{esc(quote)}”</div>",
                        unsafe_allow_html=True,
                    )
                st.caption(
                    "Quotes are checked against your uploaded feedback before being "
                    "stored. Anything the model could not match was discarded."
                )
            else:
                st.caption(
                    "No verbatim quotes were retained for this theme — either none "
                    "were quotable, or the model's quotes did not match your data."
                )
            if language:
                st.markdown(
                    "**Language customers use:** " + ", ".join(f"`{esc(w)}`" for w in language)
                )
            st.caption(f"Confidence {float(cluster['confidence']):.0%}")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _ingest(service: StudioService, product: dict) -> None:
    st.caption(
        "Only upload feedback you are permitted to process. Content stays in your "
        "local database and is sent to the model provider only when you run an analysis."
    )

    source = st.selectbox(
        "What kind of feedback is this?",
        [s.value for s in FeedbackSource],
        format_func=lambda v: FeedbackSource(v).label,
    )

    upload_tab, paste_tab = st.tabs(["Upload a file", "Paste text"])

    with upload_tab:
        uploaded = st.file_uploader(
            "Feedback export",
            type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTENSIONS)],
            help=(
                "CSV/TSV and JSON exports are split by row; the text column is "
                "detected automatically. TXT and PDF are split on blank lines. "
                f"Max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
            ),
        )
        label = st.text_input("Label this batch", placeholder="e.g. G2 reviews, Q3 2026")
        if uploaded is not None and st.button("Import file", type="primary"):
            try:
                result = service.ingest_feedback_file(
                    product["id"], label, uploaded.name, uploaded.getvalue(), source
                )
            except (DocumentError, ValueError) as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                _report_import(result)

    with paste_tab:
        pasted = st.text_area(
            "Paste feedback",
            height=220,
            placeholder=(
                "One item per line, or separate longer items with a blank line.\n\n"
                "Onboarding took three days and we nearly gave up.\n\n"
                "Love the reporting, but the mobile app is unusable."
            ),
        )
        paste_label = st.text_input(
            "Label this batch", key="paste_label", placeholder="e.g. Interview notes"
        )
        if st.button("Import text", type="primary"):
            try:
                result = service.ingest_feedback_text(
                    product["id"], paste_label, pasted, source
                )
            except (DocumentError, ValueError) as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                _report_import(result)


def _report_import(result: dict[str, Any]) -> None:
    message = f"Imported {result['inserted']:,} items."
    if result["duplicates"]:
        message += (
            f" {result['duplicates']:,} duplicate(s) skipped — re-importing an "
            "overlapping export cannot inflate a theme."
        )
    st.success(message)
    for warning in result.get("warnings", []):
        st.warning(warning, icon=":material/info:")


def _sources(service: StudioService, product: dict) -> None:
    batches = service.feedback_batches(product["id"])
    if not batches:
        empty_state("No feedback imported yet")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Batch": b["label"],
                    "Type": FeedbackSource(b["source_type"]).label
                    if b["source_type"] in {s.value for s in FeedbackSource}
                    else b["source_type"],
                    "Items": b["item_count"],
                    "File": b["filename"] or "—",
                    "Imported": str(b["created_at"])[:16].replace("T", " "),
                }
                for b in batches
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("**Remove a batch**")
    choice = st.selectbox(
        "Batch",
        [b["id"] for b in batches],
        format_func=lambda bid: next(b["label"] for b in batches if b["id"] == bid),
        label_visibility="collapsed",
    )
    if st.button("Delete batch and its feedback"):
        service.delete_feedback_batch(choice)
        st.rerun()
