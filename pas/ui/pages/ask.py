"""Ask Product Analysis Studio (spec 25).

Answers come from stored intelligence and carry verified citations. When the
model cites evidence that was not in its context, the citation is dropped and
the fact is surfaced here rather than hidden.
"""

from __future__ import annotations

import streamlit as st

from ...analysis.ask import SUGGESTED_QUESTIONS
from ...service import StudioService
from ..components import citation_links, empty_state, esc, grade_chip, page_header
from ..theme import PALETTE, confidence_label


def render(service: StudioService, product: dict, analysis_id: str | None) -> None:
    page_header(
        "Ask",
        "Question everything the platform has established about your product. "
        "Answers come only from stored intelligence and cite the evidence they used.",
    )

    if not analysis_id:
        empty_state(
            "Run an analysis first",
            "Answers are drawn from stored intelligence, so there must be some.",
        )
        return

    st.caption(
        "Answers use only what this platform has established about your product. "
        "Where the intelligence does not cover a question, it will say so."
    )

    pending = st.session_state.pop("ask_prefill", "")

    with st.form("ask_form", clear_on_submit=False):
        question = st.text_area(
            "Your question",
            value=pending,
            placeholder="Who is my biggest competitor, and why?",
            height=90,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Ask", type="primary", width="stretch")

    st.markdown("**Try one of these**")
    suggestion_cols = st.columns(2)
    for index, suggestion in enumerate(SUGGESTED_QUESTIONS):
        with suggestion_cols[index % 2]:
            if st.button(suggestion, key=f"sug_{index}", width="stretch"):
                st.session_state["ask_prefill"] = suggestion
                st.rerun()

    if submitted and question.strip():
        try:
            with st.spinner("Consulting the evidence ledger..."):
                answer = service.ask(product["id"], analysis_id, question)
        except ValueError as exc:
            st.error(str(exc), icon=":material/error:")
        else:
            _render_answer(question, answer)

    history = service.conversations(product["id"])
    if history:
        st.markdown("---")
        st.markdown("#### Earlier questions")
        for entry in history[: 20 if submitted else 10]:
            with st.expander(entry["question"][:110], expanded=False):
                st.markdown(entry["answer"])
                if entry["caveats"]:
                    st.caption("Caveats: " + "; ".join(entry["caveats"]))
                _render_citations(entry["citations"])
                st.caption(
                    f"{float(entry['confidence']):.0%} confidence · "
                    f"{str(entry['created_at'])[:16].replace('T', ' ')}"
                )


def _render_answer(question: str, answer) -> None:
    with st.container(border=True):
        st.markdown(f"**{esc(question)}**")
        st.markdown("---")
        st.markdown(answer.text)

        label, colour = confidence_label(answer.confidence)
        st.markdown(
            f"<span class='chip' style='color:{colour}'>{esc(label)}</span> "
            f"<span style='color:{PALETTE['muted']};font-size:0.8rem'>"
            f"{answer.confidence:.0%} confidence</span>",
            unsafe_allow_html=True,
        )

        if answer.caveats:
            st.markdown("**What this answer could not establish**")
            for caveat in answer.caveats:
                st.markdown(f"- {esc(caveat)}")

        _render_citations(answer.citations)

        if answer.dropped_citations:
            # Surfaced rather than hidden: the user should know the model
            # reached for sources that did not exist.
            st.warning(
                f"{answer.dropped_citations} citation(s) referenced evidence that does "
                "not exist and were discarded. Treat this answer with extra caution.",
                icon=":material/link_off:",
            )

        if answer.followups:
            st.markdown("**Worth asking next**")
            for index, followup in enumerate(answer.followups):
                if st.button(followup, key=f"fu_{index}", width="stretch"):
                    st.session_state["ask_prefill"] = followup
                    st.rerun()


def _render_citations(citations: list[dict]) -> None:
    if not citations:
        st.caption("No evidence records were cited for this answer.")
        return
    st.markdown(f"**Evidence cited ({len(citations)})**")
    for citation in citations:
        st.markdown(
            f"{grade_chip(citation['grade'])} {esc(citation['claim'])}  \n"
            f"<span style='color:{PALETTE['muted']};font-size:0.76rem'>"
            f"{float(citation.get('confidence', 0)):.0%} confidence · "
            f"{citation_links(citation.get('sources', []))}</span>",
            unsafe_allow_html=True,
        )
