"""Product intake and the product list (spec 1, 49).

Onboarding asks only what changes the analysis, and the "I only have an idea"
path is a first-class entry point rather than a degraded one.
"""

from __future__ import annotations

import streamlit as st

from ...domain.enums import AnalysisMode, IntakeKind
from ...service import StudioService
from ..components import empty_state, esc, hero
from ..theme import PALETTE

MODE_HELP = {
    "founder": "Is this worth building? What is the MVP? Who do I target first?",
    "product_manager": "Feature prioritisation, gaps, roadmap, impact vs effort.",
    "executive": "Strategic risks, competitive threats, where to invest.",
    "investor": "Due diligence: market, defensibility, execution risk.",
    "consultant": "Client-ready analysis and exportable findings.",
}


def render(service: StudioService) -> None:
    hero(
        "Product Analysis Studio",
        "Know your product. Understand your market. Anticipate your competition. "
        "Decide what to build next.",
    )

    if not service.config.is_configured:
        st.error(
            "No `OPENROUTER_API_KEY` found. Copy `.env.example` to `.env`, add your key, "
            "and restart. You can browse saved analyses without it, but cannot run new ones.",
            icon=":material/key_off:",
        )

    new_tab, library_tab = st.tabs(["Start an analysis", "Your products"])

    with new_tab:
        _render_new_analysis(service)

    with library_tab:
        _render_library(service)


def _render_new_analysis(service: StudioService) -> None:
    st.markdown("#### What are you analysing?")

    kind = st.radio(
        "Input type",
        options=[IntakeKind.IDEA.value, IntakeKind.URL.value, IntakeKind.DESCRIPTION.value],
        format_func=lambda value: {
            "idea": "I only have an idea",
            "url": "A product website",
            "description": "An existing product I'll describe",
        }[value],
        horizontal=True,
        label_visibility="collapsed",
    )

    with st.form("intake_form", clear_on_submit=False):
        source_url = ""
        name = ""

        if kind == IntakeKind.IDEA.value:
            description = st.text_area(
                "Describe your idea",
                placeholder=(
                    "I want to build an AI assistant that helps hospitals manage "
                    "cybersecurity compliance."
                ),
                height=120,
                help="One or two sentences is enough. The intake agent structures the rest.",
            )
            st.caption(
                "No URL needed. Findings will be labelled as hypotheses rather than "
                "verified facts, because there is nothing to verify against yet."
            )
        elif kind == IntakeKind.URL.value:
            source_url = st.text_input(
                "Product URL", placeholder="https://example.com", help="The product's own site."
            )
            description = st.text_area(
                "Anything the site won't tell us (optional)",
                placeholder="Positioning, target customer, what you're really trying to decide.",
                height=80,
            )
        else:
            name = st.text_input("Product name", placeholder="e.g. Acme Compliance Cloud")
            description = st.text_area(
                "Describe the product",
                placeholder="What it does, who it's for, how it makes money.",
                height=120,
            )

        col_a, col_b = st.columns(2)
        with col_a:
            mode = st.selectbox(
                "Analysis lens",
                options=[m.value for m in AnalysisMode],
                format_func=lambda value: AnalysisMode(value).label,
            )
            st.caption(MODE_HELP.get(mode, ""))
        with col_b:
            research_enabled = st.toggle(
                "Gather live evidence",
                value=True,
                help=(
                    "Fetches the product's public pages, honouring robots.txt. "
                    "Without this the analysis relies on model knowledge alone."
                ),
            )
            deep_research = st.toggle(
                "Deep research",
                value=False,
                help=(
                    "Also read the site's sitemap, changelog and RSS feed, and "
                    "public GitHub metadata if the product is open source. "
                    "Slower and costs more, but finds pages path-guessing misses."
                ),
            )
            extra = st.text_area(
                "Additional source URLs (one per line, optional)",
                placeholder="https://competitor.com/pricing",
                height=68,
            )

        submitted = st.form_submit_button(
            "Run analysis", type="primary", width="stretch"
        )

    if not submitted:
        return

    try:
        intake_input = description or source_url or name
        product_id = service.create_product(
            name=name or "",
            intake_kind=kind,
            intake_input=intake_input,
            source_url=source_url or None,
        )
        analysis_id, _job = service.start_analysis(
            product_id,
            mode=mode,
            research_enabled=research_enabled,
            deep_research=deep_research,
            extra_urls=[line for line in (extra or "").splitlines() if line.strip()],
        )
    except ValueError as exc:
        st.error(str(exc), icon=":material/error:")
        return

    st.session_state["active_product"] = product_id
    st.session_state["active_analysis"] = analysis_id
    st.session_state["route"] = "workroom"
    st.rerun()


def _render_library(service: StudioService) -> None:
    products = service.list_products()
    if not products:
        empty_state(
            "No products yet",
            "Start an analysis and it will appear here with every version you run.",
        )
        return

    for product in products:
        with st.container(border=True):
            head, actions = st.columns([4, 1])
            with head:
                st.markdown(
                    f"**{esc(product['name'])}**  \n"
                    f"<span style='color:{PALETTE['muted']};font-size:0.85rem'>"
                    f"{esc(product.get('one_liner') or product.get('intake_input', '')[:140])}"
                    f"</span>",
                    unsafe_allow_html=True,
                )
                meta = " · ".join(
                    filter(
                        None,
                        [
                            product.get("category"),
                            product.get("industry"),
                            f"{product.get('analysis_count', 0)} analyses",
                        ],
                    )
                )
                st.caption(meta)
            with actions:
                if st.button("Open", key=f"open_{product['id']}", width="stretch"):
                    latest = service.latest_analysis(product["id"])
                    st.session_state["active_product"] = product["id"]
                    st.session_state["active_analysis"] = latest["id"] if latest else None
                    st.session_state["route"] = "workroom"
                    st.rerun()
                if st.button(
                    "Delete", key=f"del_{product['id']}", width="stretch"
                ):
                    st.session_state[f"confirm_del_{product['id']}"] = True

            if st.session_state.get(f"confirm_del_{product['id']}"):
                st.warning(
                    f"Delete **{esc(product['name'])}** and every analysis, source and "
                    "recommendation derived from it? This cannot be undone."
                )
                yes, no = st.columns(2)
                if yes.button("Delete permanently", key=f"yes_{product['id']}", type="primary"):
                    service.delete_product(product["id"])
                    st.session_state.pop(f"confirm_del_{product['id']}", None)
                    if st.session_state.get("active_product") == product["id"]:
                        st.session_state["active_product"] = None
                        st.session_state["active_analysis"] = None
                    st.rerun()
                if no.button("Cancel", key=f"no_{product['id']}"):
                    st.session_state.pop(f"confirm_del_{product['id']}", None)
                    st.rerun()
