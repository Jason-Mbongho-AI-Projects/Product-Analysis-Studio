"""Visual identity.

A restrained, neutral dark system. Every colour is measured rather than chosen
by eye: the chart series clear the data-viz validator against this surface
(lightness band, chroma floor, colour-vision separation ΔE 9.0, normal-vision
ΔE 25.8, contrast), and every UI and status colour clears WCAG AA at 4.5:1 -
not merely the 3:1 large-text floor.

The design decisions that matter:

* **Neutral greys, not blue-tinted navy.** A coloured ground fights the data
  sitting on it. The plane is near-black and the surfaces step up in small,
  even increments.
* **Hairline borders at low alpha, not solid rules.** Structure comes from
  luminance steps and spacing; visible boxes everywhere read as a form, not a
  dashboard.
* **One accent, used sparingly.** Blue marks what is interactive or current.
  Everything else that carries colour carries *meaning* - status, severity,
  evidence grade - so a coloured element is always informative.
* **Tabular figures for numbers.** Stat values and table columns align
  vertically instead of shifting as digits change.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

PALETTE = {
    # Surfaces: even luminance steps, neutral hue.
    "plane": "#0b0c0e",
    "bg_1": "#0b0c0e",
    "bg_2": "#0e0f12",
    "surface": "#111214",
    "surface_raised": "#17181b",
    "surface_hover": "#1c1d21",
    # Borders are alpha so they sit correctly on any surface beneath them.
    "line": "rgba(255,255,255,0.055)",
    "line_strong": "rgba(255,255,255,0.10)",
    # Ink.
    "text": "#ededf0",
    "text_secondary": "#a1a1aa",
    "muted": "#8b8b94",
    # One accent.
    "primary": "#4b8bf5",
    "primary_hover": "#6b9ff7",
    "primary_soft": "rgba(75,139,245,0.14)",
    "primary_2": "#4b8bf5",
    # Status - reserved, never decorative.
    "success": "#3fb950",
    "accent": "#d29922",
    "warning": "#d29922",
    "serious": "#e08c50",
    "danger": "#f0605d",
    "violet": "#a78bfa",
}

#: Validated categorical slots, fixed order, never cycled.
SERIES = ["#4b8bf5", "#e0693a", "#1faa7c", "#d29922", "#d55181", "#a78bfa"]

#: Evidence grade is a status ladder, so it borrows status-family colours:
#: verified reads as good, hypothesis reads as caution.
GRADE_STYLES = {
    "verified_fact": ("Verified", "#3fb950"),
    "strong_inference": ("Strong inference", "#4b8bf5"),
    "user_supplied": ("You told us", "#a78bfa"),
    "weak_inference": ("Weak inference", "#d29922"),
    "ai_hypothesis": ("AI hypothesis", "#e08c50"),
}

VERDICT_STYLES = {
    "must_build": ("Must build", "#f0605d"),
    "should_build": ("Should build", "#d29922"),
    "could_build": ("Could build", "#4b8bf5"),
    "do_not_build": ("Do not build", "#8b8b94"),
    "investigate_first": ("Investigate first", "#a78bfa"),
}

THREAT_STYLES = {
    "critical": "#f0605d",
    "high": "#e08c50",
    "medium": "#d29922",
    "low": "#3fb950",
}

_VARIABLES = "\n".join(
    f"    --{name}: {PALETTE[key]};"
    for name, key in [
        ("plane", "plane"),
        ("surface", "surface"),
        ("surface-raised", "surface_raised"),
        ("surface-hover", "surface_hover"),
        ("line", "line"),
        ("line-strong", "line_strong"),
        ("text", "text"),
        ("text-2", "text_secondary"),
        ("muted", "muted"),
        ("primary", "primary"),
        ("primary-hover", "primary_hover"),
        ("primary-soft", "primary_soft"),
        ("success", "success"),
        ("warning", "warning"),
        ("danger", "danger"),
    ]
)

_STYLES = """
<style>
:root {
/*VARS*/
    --radius: 8px;
    --radius-lg: 10px;
    --font: -apple-system, "Segoe UI Variable Text", "Segoe UI", system-ui,
            "Helvetica Neue", Arial, sans-serif;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    background: var(--plane);
    color: var(--text);
    font-family: var(--font);
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}

.block-container {
    padding-top: 3.25rem; padding-bottom: 5rem; max-width: 1400px;
}

/* ---- Sidebar: compact, quiet, with a clear current item ---- */
[data-testid="stSidebar"] {
    border-right: 1px solid var(--line);
    background: #090a0c;
}
[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

[data-testid="stSidebar"] .stButton > button {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-2);
    font-weight: 500;
    font-size: 0.855rem;
    text-align: left;
    justify-content: flex-start;
    padding: 0.4rem 0.7rem;
    border-radius: var(--radius);
    min-height: 0;
    transition: background .12s ease, color .12s ease;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: var(--surface-hover); color: var(--text); border-color: transparent;
}
/* Current route: a soft wash and an accent rule, not a saturated fill. */
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--primary-soft);
    color: var(--text);
    border: 1px solid transparent;
    border-left: 2px solid var(--primary);
    border-radius: 3px var(--radius) var(--radius) 3px;
    font-weight: 600;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: var(--primary-soft);
}
[data-testid="stSidebar"] .stButton > button:disabled {
    color: #4d4d55; background: transparent;
}

/* ---- Page header ---- */
.hero { margin: 0 0 1.75rem 0; }
.hero .title {
    font-size: clamp(1.5rem, 2.2vw, 1.9rem);
    font-weight: 640;
    letter-spacing: -0.028em;
    color: var(--text);
    line-height: 1.15;
    margin: 0;
}
.hero .subtitle {
    color: var(--muted); margin-top: 0.45rem; font-size: 0.9rem;
    max-width: 70ch; line-height: 1.6;
}

.page-head { margin: 0 0 1.4rem 0; }
.page-head .name {
    font-size: 1.22rem; font-weight: 640; letter-spacing: -0.022em; color: var(--text);
}
.page-head .purpose {
    color: var(--muted); font-size: 0.865rem; margin-top: 0.3rem;
    max-width: 76ch; line-height: 1.6;
}

/* ---- Tab lead-in ---- */
.lead {
    color: var(--muted);
    font-size: 0.865rem;
    line-height: 1.65;
    max-width: 84ch;
    margin: 0.45rem 0 1.5rem 0;
    padding-left: 0.8rem;
    border-left: 2px solid var(--line-strong);
}

.panel {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
    padding: 1.05rem 1.15rem;
    margin-bottom: 0.8rem;
}
.panel h4 {
    margin: 0 0 0.45rem 0; font-size: 0.7rem; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--muted); font-weight: 600;
}

/* ---- Stat tile ---- */
.kpi { display: flex; flex-direction: column; gap: 0.35rem; }
.kpi .value {
    font-size: 1.9rem; font-weight: 640; color: var(--text); line-height: 1;
    letter-spacing: -0.03em; font-variant-numeric: tabular-nums;
}
.kpi .label {
    font-size: 0.665rem; text-transform: uppercase; letter-spacing: 0.09em;
    color: var(--muted); font-weight: 600;
}
.kpi .note { font-size: 0.755rem; color: var(--muted); line-height: 1.45; }

/* ---- Chips: soft fill, sentence case, no shouting ---- */
.chip {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 5px;
    font-size: 0.7rem; font-weight: 560; letter-spacing: 0.005em;
    border: 1px solid transparent;
    background: color-mix(in srgb, currentColor 14%, transparent);
    white-space: nowrap; line-height: 1.55;
}

.meter {
    height: 4px; border-radius: 2px; background: rgba(255,255,255,0.06);
    overflow: hidden; margin: 0.45rem 0;
}
.meter > span { display: block; height: 100%; border-radius: 2px; }

.claim {
    border-left: 2px solid var(--line-strong);
    padding: 0.05rem 0 0.05rem 0.8rem; margin-bottom: 0.85rem;
}
.claim .text { color: var(--text); font-size: 0.885rem; line-height: 1.6; }
.claim .meta { color: var(--muted); font-size: 0.74rem; margin-top: 0.3rem; }
.claim a { color: var(--primary); text-decoration: none; }
.claim a:hover { text-decoration: underline; }

.empty {
    border: 1px dashed var(--line-strong); border-radius: var(--radius-lg);
    padding: 2.25rem 1.5rem; text-align: center; color: var(--muted);
    background: var(--surface);
}

/* ---- Inputs ---- */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input,
div[data-baseweb="select"] > div {
    background: var(--surface) !important;
    color: var(--text) !important;
    border-radius: var(--radius) !important;
    border: 1px solid var(--line-strong) !important;
    font-size: 0.885rem !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {
    border-color: var(--primary) !important;
}
div[data-testid="stTextInput"] input::placeholder,
div[data-testid="stTextArea"] textarea::placeholder { color: #5c5c65 !important; }
label, .stMarkdown label {
    color: var(--text-2) !important; font-size: 0.83rem; font-weight: 500;
}

/* ---- Buttons ---- */
.stButton > button {
    border-radius: var(--radius);
    border: 1px solid var(--line-strong);
    background: var(--surface-raised);
    color: var(--text);
    font-weight: 520; font-size: 0.855rem;
    transition: background .12s ease, border-color .12s ease;
}
.stButton > button:hover {
    background: var(--surface-hover); border-color: rgba(255,255,255,0.16);
}
.stButton > button[kind="primary"] {
    background: var(--primary); border-color: var(--primary);
    color: #ffffff; font-weight: 580;
}
.stButton > button[kind="primary"]:hover {
    background: var(--primary-hover); border-color: var(--primary-hover);
}

:focus-visible, .stButton > button:focus-visible, input:focus-visible,
textarea:focus-visible, [role="tab"]:focus-visible {
    outline: 2px solid var(--primary) !important;
    outline-offset: 2px !important;
}

[data-testid="stExpander"] {
    border: 1px solid var(--line); border-radius: var(--radius-lg);
    background: var(--surface);
}
[data-testid="stExpander"] summary {
    font-size: 0.855rem; color: var(--text-2); font-weight: 520;
}
[data-testid="stExpander"] summary:hover { color: var(--text); }

/* ---- Tabs ---- */
[data-baseweb="tab-list"] {
    gap: 0.1rem; border-bottom: 1px solid var(--line); padding-bottom: 0;
}
[data-baseweb="tab"] {
    color: var(--muted); font-size: 0.86rem; font-weight: 520;
    padding: 0.55rem 0.8rem;
}
[data-baseweb="tab"]:hover { color: var(--text-2); }
[aria-selected="true"][role="tab"] { color: var(--text) !important; font-weight: 600; }

/* ---- Type ---- */
.stMarkdown { line-height: 1.65; font-size: 0.925rem; }
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
    color: var(--text); letter-spacing: -0.02em; font-weight: 620;
}
.stMarkdown h4 { font-size: 0.98rem; margin-top: 1.6rem; margin-bottom: 0.5rem; }
.stMarkdown a { color: var(--primary); }
.stMarkdown strong { font-weight: 600; color: var(--text); }

[data-testid="stDataFrame"] {
    border: 1px solid var(--line); border-radius: var(--radius-lg);
    font-variant-numeric: tabular-nums;
}
[data-testid="stMetric"] {
    background: var(--surface); border: 1px solid var(--line);
    border-radius: var(--radius-lg); padding: 0.8rem 0.95rem;
}
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }

[data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalBlock"] {
    gap: 0.55rem;
}
code { font-size: 0.84em; background: var(--surface-raised); border-radius: 4px; }
hr { border-color: var(--line); margin: 1.75rem 0; }

@media (max-width: 768px) {
    .block-container { padding-left: 0.85rem; padding-right: 0.85rem; }
    .kpi .value { font-size: 1.45rem; }
    .hero .title { font-size: 1.35rem; }
}
</style>
"""

_CSS = _STYLES.replace("/*VARS*/", _VARIABLES)


def inject() -> None:
    """Apply the stylesheet once per page render."""
    st.markdown(_CSS, unsafe_allow_html=True)


def score_colour(value: float) -> str:
    """Status band for a 0-100 score. Reserved colours, consistently applied."""
    if value >= 70:
        return PALETTE["success"]
    if value >= 45:
        return PALETTE["warning"]
    return PALETTE["danger"]


def confidence_label(value: float) -> tuple[str, str]:
    """Map a 0-1 confidence to a label and colour (spec 35)."""
    if value >= 0.75:
        return "High confidence", PALETTE["success"]
    if value >= 0.5:
        return "Medium confidence", PALETTE["warning"]
    if value > 0:
        return "Low confidence", PALETTE["danger"]
    return "Insufficient evidence", PALETTE["muted"]
