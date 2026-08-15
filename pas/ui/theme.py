"""Visual identity.

The original product's dark "glass" look is preserved deliberately - it is the
one part of the previous build worth keeping. What changed:

* Input labels were forced to ``#000000`` against a dark panel, which is
  unreadable. Text colours now derive from the palette and meet contrast
  requirements (spec 53).
* Gradients are pulled back to accents so dense executive tables stay legible
  (spec 47).
* Focus states are visible, which they were not before.
"""

from __future__ import annotations

import streamlit as st

PALETTE = {
    "bg_1": "#040b16",
    "bg_2": "#0a1324",
    "panel": "rgba(15, 23, 42, 0.72)",
    "line": "rgba(148, 163, 184, 0.22)",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "primary": "#7c3aed",
    "primary_2": "#22d3ee",
    "accent": "#f59e0b",
    "success": "#34d399",
    "danger": "#f87171",
}

#: Grade -> (label, colour). Used everywhere a claim is rendered so the
#: epistemic status of a statement is always visible at a glance.
GRADE_STYLES = {
    "verified_fact": ("Verified", "#34d399"),
    "strong_inference": ("Strong inference", "#38bdf8"),
    "weak_inference": ("Weak inference", "#fbbf24"),
    "ai_hypothesis": ("AI hypothesis", "#f97316"),
    "user_supplied": ("You told us", "#a78bfa"),
}

VERDICT_STYLES = {
    "must_build": ("MUST BUILD", "#f87171"),
    "should_build": ("SHOULD BUILD", "#fbbf24"),
    "could_build": ("COULD BUILD", "#38bdf8"),
    "do_not_build": ("DO NOT BUILD", "#94a3b8"),
    "investigate_first": ("INVESTIGATE FIRST", "#a78bfa"),
}

THREAT_STYLES = {
    "critical": "#f87171",
    "high": "#fb923c",
    "medium": "#fbbf24",
    "low": "#34d399",
}

_CSS = """
<style>
:root {
    --bg-1: %(bg_1)s;
    --bg-2: %(bg_2)s;
    --panel: %(panel)s;
    --line: %(line)s;
    --text: %(text)s;
    --muted: %(muted)s;
    --primary: %(primary)s;
    --primary-2: %(primary_2)s;
    --accent: %(accent)s;
    --success: %(success)s;
    --danger: %(danger)s;
}

html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at top left, rgba(124, 58, 237, 0.18), transparent 30%%),
        radial-gradient(circle at bottom right, rgba(34, 211, 238, 0.12), transparent 30%%),
        linear-gradient(135deg, var(--bg-1), var(--bg-2));
    color: var(--text);
}

.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1400px; }

[data-testid="stSidebar"] {
    background: rgba(8, 15, 30, 0.92);
    border-right: 1px solid var(--line);
}

.hero {
    background: linear-gradient(135deg, rgba(124, 58, 237, 0.16), rgba(34, 211, 238, 0.07));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 1.5rem 1.6rem;
    margin-bottom: 1.4rem;
}
.hero .title {
    font-size: clamp(1.8rem, 3vw, 2.6rem);
    font-weight: 800;
    letter-spacing: -0.04em;
    background: linear-gradient(135deg, #f8fafc 0%%, #b4c1ff 40%%, #6ee7f9 100%%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    line-height: 1.1;
    margin: 0;
}
.hero .subtitle { color: var(--muted); margin-top: 0.45rem; font-size: 0.96rem; }

.panel {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.78), rgba(15, 23, 42, 0.6));
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 1.05rem 1.15rem;
    margin-bottom: 0.9rem;
}
.panel h4 { margin: 0 0 0.5rem 0; font-size: 0.78rem; letter-spacing: 0.14em;
            text-transform: uppercase; color: var(--muted); font-weight: 700; }

.kpi { display: flex; flex-direction: column; gap: 0.25rem; }
.kpi .value { font-size: 2rem; font-weight: 800; color: #f8fafc; line-height: 1; }
.kpi .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.12em;
              color: var(--muted); font-weight: 600; }
.kpi .note { font-size: 0.78rem; color: var(--muted); }

.chip {
    display: inline-block; padding: 0.14rem 0.55rem; border-radius: 999px;
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; border: 1px solid currentColor; white-space: nowrap;
}

.meter { height: 7px; border-radius: 999px; background: rgba(148,163,184,0.18);
         overflow: hidden; margin: 0.35rem 0; }
.meter > span { display: block; height: 100%%; border-radius: 999px; }

.claim { border-left: 3px solid var(--line); padding: 0.15rem 0 0.15rem 0.7rem;
         margin-bottom: 0.7rem; }
.claim .text { color: var(--text); font-size: 0.92rem; }
.claim .meta { color: var(--muted); font-size: 0.76rem; margin-top: 0.2rem; }
.claim a { color: var(--primary-2); }

.empty { border: 1px dashed var(--line); border-radius: 14px; padding: 1.6rem;
         text-align: center; color: var(--muted); }

/* Inputs: readable text on the dark panel. The previous build forced these to
   black, which was invisible against the background. */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input {
    background: rgba(2, 6, 23, 0.6) !important;
    color: var(--text) !important;
    border-radius: 10px;
}
div[data-testid="stTextInput"] input::placeholder,
div[data-testid="stTextArea"] textarea::placeholder { color: rgba(148,163,184,0.7) !important; }
label, .stMarkdown label { color: var(--text) !important; }

.stButton > button {
    border-radius: 10px; border: 1px solid var(--line);
    background: rgba(30, 41, 59, 0.7); color: var(--text);
    font-weight: 600; transition: border-color .15s ease, transform .15s ease;
}
.stButton > button:hover { border-color: var(--primary-2); transform: translateY(-1px); }
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--primary), var(--primary-2));
    border: none; color: #ffffff; font-weight: 700;
}

/* Visible focus ring - absent from the previous build. */
:focus-visible, .stButton > button:focus-visible, input:focus-visible,
textarea:focus-visible, [role="tab"]:focus-visible {
    outline: 2px solid var(--primary-2) !important;
    outline-offset: 2px !important;
}

[data-testid="stExpander"] {
    border: 1px solid var(--line); border-radius: 12px;
    background: rgba(15, 23, 42, 0.45);
}
[data-baseweb="tab-list"] { gap: 0.2rem; border-bottom: 1px solid var(--line); }
[data-baseweb="tab"] { color: var(--muted); }
[aria-selected="true"][role="tab"] { color: #f8fafc !important; }

.stMarkdown { line-height: 1.65; }
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 { color: #f8fafc; }
[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 12px; }

@media (max-width: 768px) {
    .block-container { padding-left: 0.7rem; padding-right: 0.7rem; }
    .kpi .value { font-size: 1.5rem; }
    .hero { padding: 1.1rem; }
}
</style>
""" % PALETTE


def inject() -> None:
    """Apply the stylesheet once per page render."""
    st.markdown(_CSS, unsafe_allow_html=True)


def score_colour(value: float) -> str:
    """Green/amber/red band for a 0-100 score."""
    if value >= 70:
        return PALETTE["success"]
    if value >= 45:
        return PALETTE["accent"]
    return PALETTE["danger"]


def confidence_label(value: float) -> tuple[str, str]:
    """Map a 0-1 confidence to a label and colour (spec 35)."""
    if value >= 0.75:
        return "High confidence", PALETTE["success"]
    if value >= 0.5:
        return "Medium confidence", PALETTE["accent"]
    if value > 0:
        return "Low confidence", PALETTE["danger"]
    return "Insufficient evidence", PALETTE["muted"]
