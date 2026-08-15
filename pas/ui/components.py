"""Reusable UI building blocks.

Small components rather than large page functions, so the pages stay readable
and evidence rendering is consistent everywhere it appears (spec 68).
"""

from __future__ import annotations

import html
from typing import Any, Iterable, Sequence

import streamlit as st

from .theme import (
    GRADE_STYLES,
    PALETTE,
    THREAT_STYLES,
    VERDICT_STYLES,
    confidence_label,
    score_colour,
)


def esc(value: Any) -> str:
    """Escape user/model text before it reaches an HTML block.

    Model output and fetched page titles both end up in markup here, so this is
    the XSS boundary for the whole UI (spec 41).
    """
    return html.escape(str(value if value is not None else ""), quote=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="hero"><div class="title">{esc(title)}</div>'
        f'<div class="subtitle">{esc(subtitle)}</div></div>',
        unsafe_allow_html=True,
    )


def chip(label: str, colour: str) -> str:
    return f'<span class="chip" style="color:{colour}">{esc(label)}</span>'


def grade_chip(grade: str) -> str:
    label, colour = GRADE_STYLES.get(grade, ("Unknown", PALETTE["muted"]))
    return chip(label, colour)


def verdict_chip(verdict: str) -> str:
    label, colour = VERDICT_STYLES.get(verdict, (verdict.upper(), PALETTE["muted"]))
    return chip(label, colour)


def kpi(label: str, value: str, note: str = "", colour: str | None = None) -> None:
    colour = colour or "#f8fafc"
    st.markdown(
        f'<div class="panel kpi"><div class="label">{esc(label)}</div>'
        f'<div class="value" style="color:{colour}">{esc(value)}</div>'
        f'<div class="note">{esc(note)}</div></div>',
        unsafe_allow_html=True,
    )


def meter(value: float, maximum: float = 100.0, colour: str | None = None) -> str:
    pct = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum)) * 100
    colour = colour or score_colour(value)
    return f'<div class="meter"><span style="width:{pct:.1f}%;background:{colour}"></span></div>'


def empty_state(message: str, hint: str = "") -> None:
    body = f"<strong>{esc(message)}</strong>"
    if hint:
        body += f"<br><span style='font-size:0.85rem'>{esc(hint)}</span>"
    st.markdown(f'<div class="empty">{body}</div>', unsafe_allow_html=True)


def citation_links(citations: Sequence[dict[str, Any]]) -> str:
    """Render citations as safe links.

    Only http(s) URLs become anchors; anything else is shown as plain text so a
    ``javascript:`` URL from model output cannot become a clickable link.
    """
    if not citations:
        return "<em>No source</em>"
    parts = []
    for citation in citations[:6]:
        url = (citation.get("url") or "").strip()
        title = citation.get("title") or url or "Source"
        if url.lower().startswith(("http://", "https://")):
            parts.append(
                f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer nofollow">'
                f"{esc(title[:60])}</a>"
            )
        else:
            parts.append(esc(title[:60]))
    return " · ".join(parts)


def claim_block(claim: dict[str, Any]) -> None:
    """Render one evidenced claim with its grade, confidence and sources."""
    grade = claim.get("grade", "ai_hypothesis")
    _, colour = GRADE_STYLES.get(grade, ("Unknown", PALETTE["muted"]))
    confidence = float(claim.get("confidence", 0) or 0)
    st.markdown(
        f'<div class="claim" style="border-left-color:{colour}">'
        f'<div class="text">{esc(claim.get("claim", ""))}</div>'
        f'<div class="meta">{grade_chip(grade)} &nbsp; {confidence:.0%} confidence '
        f'&nbsp;·&nbsp; {citation_links(claim.get("citations", []))}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    detail = claim.get("detail")
    if detail:
        st.caption(detail)


def claim_list(claims: Iterable[dict[str, Any]], empty_message: str = "Nothing recorded.") -> None:
    claims = list(claims)
    if not claims:
        st.caption(empty_message)
        return
    for claim in claims:
        claim_block(claim)


def confidence_banner(quality: dict[str, Any]) -> None:
    """Top-of-page honesty banner about the evidence base (spec 35)."""
    total = quality.get("total", 0)
    ratio = quality.get("evidence_backed_ratio", 0.0)
    sources = quality.get("distinct_sources", 0)

    if total == 0:
        st.warning(
            "No evidence has been recorded for this analysis yet.", icon=":material/help:"
        )
        return

    if sources == 0:
        st.warning(
            f"**No external sources were retrieved.** All {total} claims come from model "
            "knowledge alone and are labelled as hypotheses. Add a product URL and "
            "re-run to ground this analysis in real evidence.",
            icon=":material/warning:",
        )
    elif ratio < 0.35:
        st.warning(
            f"**Thin evidence base.** Only {ratio:.0%} of {total} claims are backed by "
            f"a retrieved source ({sources} sources). Treat conclusions as directional.",
            icon=":material/warning:",
        )
    else:
        st.info(
            f"{total} claims recorded · {ratio:.0%} evidence-backed · "
            f"{sources} distinct sources.",
            icon=":material/verified:",
        )


def score_row(score: dict[str, Any], dimension_label: str) -> None:
    value = float(score["score"])
    inverted = bool(score.get("inverted"))
    display = 100 - value if inverted else value
    colour = score_colour(display)

    left, right = st.columns([3, 1])
    with left:
        suffix = " (inverted: lower pressure is better)" if inverted else ""
        st.markdown(
            f"**{esc(dimension_label)}**<span style='color:{PALETTE['muted']};"
            f"font-size:0.78rem'>{esc(suffix)}</span>"
            f"{meter(display, colour=colour)}",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"<div style='text-align:right;font-size:1.35rem;font-weight:800;"
            f"color:{colour}'>{value:.0f}</div>"
            f"<div style='text-align:right;font-size:0.7rem;color:{PALETTE['muted']}'>"
            f"{float(score.get('confidence', 0)):.0%} confidence</div>",
            unsafe_allow_html=True,
        )

    with st.expander("Why this score", expanded=False):
        st.write(score.get("explanation") or "No explanation recorded.")
        assumptions = score.get("assumptions") or []
        evidence = score.get("supporting_evidence") or []
        if evidence:
            st.markdown("**Supporting evidence**")
            for item in evidence:
                st.markdown(f"- {esc(item)}", unsafe_allow_html=True)
        if assumptions:
            st.markdown("**Assumptions**")
            for item in assumptions:
                st.markdown(f"- {esc(item)}", unsafe_allow_html=True)
        st.caption(
            f"Weight in composite: {float(score.get('weight', 0)):.0%} · "
            f"Calculated {str(score.get('calculated_at', ''))[:19].replace('T', ' ')}"
        )


def threat_chip(level: str) -> str:
    return chip(level.upper(), THREAT_STYLES.get(level, PALETTE["muted"]))


def confidence_chip(value: float) -> str:
    label, colour = confidence_label(value)
    return chip(label, colour)
