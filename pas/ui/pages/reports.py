"""Report Studio (spec 30 / 56).

Reports are assembled from stored intelligence, so generating one costs nothing
and always matches what the UI displays.
"""

from __future__ import annotations

import streamlit as st

from ...analysis import reports as report_lib
from ...service import StudioService
from ..components import empty_state, esc, page_header
from ..theme import PALETTE


def render(service: StudioService, product: dict, analysis_id: str | None) -> None:
    page_header(
        "Reports",
        "Share the findings. Every report states how well-evidenced it is, so a "
        "reader can judge how much weight to put on it.",
    )

    if not analysis_id:
        empty_state("Run an analysis first", "Reports are built from analysis output.")
        return

    data = service.dashboard(analysis_id)
    quality = data["quality"]

    if quality.get("distinct_sources", 0) == 0:
        st.warning(
            "This analysis retrieved no external sources, so its reports will state "
            "that every finding is an AI hypothesis. Consider re-running with a "
            "product URL before sharing them.",
            icon=":material/warning:",
        )

    st.caption("Download as Markdown, or as HTML and print to PDF.")

    for report_id, (label, _builder) in report_lib.REPORTS.items():
        with st.container(border=True):
            st.markdown(f"**{esc(label)}**")

            available = _availability(report_id, data)
            if not available:
                st.caption("Not available — the underlying agents did not complete.")
                continue

            try:
                report = service.build_report(report_id, analysis_id)
            except ValueError as exc:
                st.error(str(exc))
                continue

            cols = st.columns([1, 1, 2])
            cols[0].download_button(
                "Markdown",
                data=report.markdown,
                file_name=report.filename,
                mime="text/markdown",
                key=f"md_{report_id}",
                width="stretch",
            )
            cols[1].download_button(
                "HTML",
                data=report.as_html(),
                file_name=report.filename.replace(".md", ".html"),
                mime="text/html",
                key=f"html_{report_id}",
                width="stretch",
            )
            with cols[2]:
                with st.expander("Preview"):
                    st.markdown(report.markdown)

    st.markdown("---")
    st.markdown("#### Evidence ledger")
    with st.container(border=True):
        evidence_report = service.build_evidence_report(analysis_id)
        cols = st.columns([1, 1, 2])
        cols[0].download_button(
            "Markdown",
            data=evidence_report.markdown,
            file_name=evidence_report.filename,
            mime="text/markdown",
            width="stretch",
        )
        cols[1].download_button(
            "HTML",
            data=evidence_report.as_html(),
            file_name=evidence_report.filename.replace(".md", ".html"),
            mime="text/html",
            width="stretch",
        )
        cols[2].caption(
            f"{quality.get('total', 0)} claims across "
            f"{quality.get('distinct_sources', 0)} sources."
        )

    st.markdown("#### Structured data")
    st.caption("For spreadsheets, BI tools, or feeding another system.")

    evidence = service.evidence(analysis_id, limit=1000)
    cols = st.columns(4)
    cols[0].download_button(
        "Scores CSV",
        data=report_lib.scores_csv(data["scores"]),
        file_name="scores.csv",
        mime="text/csv",
        disabled=not data["scores"],
        width="stretch",
    )
    cols[1].download_button(
        "Competitors CSV",
        data=report_lib.competitors_csv(data["competitors"]),
        file_name="competitors.csv",
        mime="text/csv",
        disabled=not data["competitors"],
        width="stretch",
    )
    cols[2].download_button(
        "Evidence CSV",
        data=report_lib.evidence_csv(evidence),
        file_name="evidence.csv",
        mime="text/csv",
        disabled=not evidence,
        width="stretch",
    )
    cols[3].download_button(
        "Full JSON",
        data=service.export_json(analysis_id),
        file_name=f"analysis-{analysis_id}.json",
        mime="application/json",
        width="stretch",
    )

    st.caption(
        f"Exports contain only this workspace's data for **{esc(product['name'])}**. "
        "Review before sharing externally — analyses may include confidential "
        "information you supplied."
    )


def _availability(report_id: str, data: dict) -> bool:
    """Only offer a report when the intelligence behind it exists."""
    return {
        "executive": bool(data["scores"] or data["recommendations"] or data["profile"]),
        "competitive": bool(data["competitors"]),
        "market": bool(data["market"]),
        "strategy": bool(
            data.get("positioning") or data.get("pricing")
            or data.get("growth") or data.get("gtm")
        ),
    }.get(report_id, True)
