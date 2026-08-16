"""Visual identity.

Rebuilt around a **validated** palette rather than a chosen-by-eye one. The
categorical chart slots were run through the data-viz validator against this
surface and clear every gate: lightness band, chroma floor, colour-vision
separation, normal-vision separation and contrast.

What changed from the previous look, and why:

* The purple/cyan gradient wash read as generic-AI-startup. The spec asks for
  "modern, clean, serious, executive" and explicitly warns off excessive
  gradients. Gradients are now confined to the hero, at low opacity.
* One accent (blue) instead of a purple/cyan duo. A single accent makes the
  status colours mean something; two decorative accents compete with them.
* Status colours are reserved. Green/amber/orange/red carry evidence grade and
  severity only, never decoration - so a red chip always means the same thing.
* The base plane is a near-black with a slight cool cast rather than saturated
  navy, so dense tables and charts sit on a neutral ground.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

PALETTE = {
    # Surfaces, darkest to lightest.
    "plane": "#0d0f13",
    "bg_1": "#0d0f13",
    "bg_2": "#111419",
    "surface": "#14171c",
    "surface_raised": "#1a1e25",
    "line": "#262b34",
    "line_strong": "#333a45",
    # Ink.
    "text": "#f0f2f5",
    "text_secondary": "#b4bcc8",
    "muted": "#7c8797",
    # One accent.
    "primary": "#3987e5",
    "primary_hover": "#5598e7",
    "primary_2": "#3987e5",
    # Status - reserved, never decorative.
    "success": "#2ea043",
    "accent": "#d7a02a",
    "warning": "#d7a02a",
    "serious": "#e07a4f",
    "danger": "#e0524f",
}

#: Validated categorical slots, in fixed order. Never cycled: a ninth series
#: folds into "Other" rather than inventing a hue.
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]

#: Evidence grade is a status ladder, not a set of identities, so it uses
#: status-family colours: verified reads as good, hypothesis reads as caution.
GRADE_STYLES = {
    "verified_fact": ("Verified", "#2ea043"),
    "strong_inference": ("Strong inference", "#3987e5"),
    "user_supplied": ("You told us", "#9085e9"),
    "weak_inference": ("Weak inference", "#d7a02a"),
    "ai_hypothesis": ("AI hypothesis", "#e07a4f"),
}

VERDICT_STYLES = {
    "must_build": ("MUST BUILD", "#e0524f"),
    "should_build": ("SHOULD BUILD", "#d7a02a"),
    "could_build": ("COULD BUILD", "#3987e5"),
    "do_not_build": ("DO NOT BUILD", "#8b95a5"),
    "investigate_first": ("INVESTIGATE FIRST", "#9085e9"),
}

THREAT_STYLES = {
    "critical": "#e0524f",
    "high": "#e07a4f",
    "medium": "#d7a02a",
    "low": "#2ea043",
}

#: CSS custom properties, generated from PALETTE so the palette has exactly one
#: definition. Built separately from the stylesheet because CSS contains literal
#: `%` values, which would collide with %-formatting.
_VARIABLES = "\n".join(
    f"    --{name}: {PALETTE[key]};"
    for name, key in [
        ("plane", "plane"),
        ("surface", "surface"),
        ("surface-raised", "surface_raised"),
        ("line", "line"),
        ("line-strong", "line_strong"),
        ("text", "text"),
        ("text-2", "text_secondary"),
        ("muted", "muted"),
        ("primary", "primary"),
        ("primary-hover", "primary_hover"),
        ("success", "success"),
        ("warning", "warning"),
        ("danger", "danger"),
    ]
)

_STYLES = """
<style>
:root {
/*VARS*/
}

html, body, [data-testid="stAppViewContainer"] {
    background: var(--plane);
    color: var(--text);
    font-feature-settings: "cv02", "cv03", "cv04";
}

/* Streamlit's toolbar is fixed to the top, so the first element needs
   clearance or it renders underneath it. */
.block-container { padding-top: 3.25rem; padding-bottom: 4rem; max-width: 1440px; }

[data-testid="stSidebar"] {
    background: #0a0c10;
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

/* ---- Hero: the one place a gradient is allowed, and kept subtle ---- */
.hero {
    background:
        linear-gradient(135deg, rgba(57,133,229,0.10), rgba(57,133,229,0.02) 60%),
        var(--surface);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 1.6rem 1.75rem;
    margin-bottom: 1.5rem;
}
.hero .title {
    font-size: clamp(1.6rem, 2.4vw, 2.1rem);
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--text);
    line-height: 1.15;
    margin: 0;
}
.hero .subtitle {
    color: var(--text-2);
    margin-top: 0.5rem;
    font-size: 0.95rem;
    max-width: 68ch;
    line-height: 1.55;
}

/* ---- Page header: what this screen is for ---- */
.page-head { margin: 0 0 1.1rem 0; }
.page-head .name {
    font-size: 1.3rem; font-weight: 650; letter-spacing: -0.02em; color: var(--text);
}
.page-head .purpose {
    color: var(--muted); font-size: 0.88rem; margin-top: 0.25rem;
    max-width: 74ch; line-height: 1.5;
}

/* ---- Explanatory lead-in above a tab's content ---- */
.lead {
    border-left: 2px solid var(--primary);
    padding: 0.1rem 0 0.1rem 0.75rem;
    margin: 0.2rem 0 1.1rem 0;
    color: var(--text-2);
    font-size: 0.88rem;
    line-height: 1.55;
    max-width: 82ch;
}

.panel {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 1rem 1.1rem;
    margin-bottom: 0.85rem;
}
.panel h4 {
    margin: 0 0 0.5rem 0; font-size: 0.72rem; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--muted); font-weight: 650;
}

/* ---- Stat tile ---- */
.kpi { display: flex; flex-direction: column; gap: 0.3rem; }
.kpi .value {
    font-size: 1.85rem; font-weight: 680; color: var(--text); line-height: 1.05;
    letter-spacing: -0.02em;
}
.kpi .label {
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--muted); font-weight: 650;
}
.kpi .note { font-size: 0.76rem; color: var(--muted); line-height: 1.4; }

.chip {
    display: inline-block; padding: 0.13rem 0.5rem; border-radius: 4px;
    font-size: 0.66rem; font-weight: 650; letter-spacing: 0.05em;
    text-transform: uppercase; border: 1px solid currentColor;
    white-space: nowrap; line-height: 1.5;
}

/* Thin marks, recessive ground. */
.meter {
    height: 5px; border-radius: 2px; background: rgba(255,255,255,0.07);
    overflow: hidden; margin: 0.4rem 0;
}
.meter > span { display: block; height: 100%; border-radius: 2px; }

.claim {
    border-left: 2px solid var(--line-strong);
    padding: 0.1rem 0 0.1rem 0.75rem; margin-bottom: 0.75rem;
}
.claim .text { color: var(--text); font-size: 0.9rem; line-height: 1.5; }
.claim .meta { color: var(--muted); font-size: 0.75rem; margin-top: 0.25rem; }
.claim a { color: var(--primary); text-decoration: none; }
.claim a:hover { text-decoration: underline; }

.empty {
    border: 1px dashed var(--line-strong); border-radius: 10px; padding: 2rem 1.5rem;
    text-align: center; color: var(--muted);
}

/* ---- Inputs ---- */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input {
    background: #0f1216 !important;
    color: var(--text) !important;
    border-radius: 7px;
    border: 1px solid var(--line) !important;
    font-size: 0.9rem !important;
}
div[data-testid="stTextInput"] input::placeholder,
div[data-testid="stTextArea"] textarea::placeholder { color: #626d7d !important; }
label, .stMarkdown label { color: var(--text-2) !important; font-size: 0.86rem; }

.stButton > button {
    border-radius: 7px; border: 1px solid var(--line-strong);
    background: var(--surface-raised); color: var(--text);
    font-weight: 550; font-size: 0.86rem;
    transition: border-color .12s ease, background .12s ease;
}
.stButton > button:hover {
    border-color: var(--primary); background: #1f242c;
}
.stButton > button[kind="primary"] {
    background: var(--primary); border-color: var(--primary);
    color: #ffffff; font-weight: 600;
}
.stButton > button[kind="primary"]:hover {
    background: var(--primary-hover); border-color: var(--primary-hover);
}

/* Visible focus ring for keyboard users. */
:focus-visible, .stButton > button:focus-visible, input:focus-visible,
textarea:focus-visible, [role="tab"]:focus-visible {
    outline: 2px solid var(--primary) !important;
    outline-offset: 2px !important;
}

[data-testid="stExpander"] {
    border: 1px solid var(--line); border-radius: 9px; background: var(--surface);
}
[data-testid="stExpander"] summary { font-size: 0.87rem; }

/* ---- Tabs: readable, with a clear selected state ---- */
[data-baseweb="tab-list"] {
    gap: 0.15rem; border-bottom: 1px solid var(--line); padding-bottom: 0;
}
[data-baseweb="tab"] {
    color: var(--muted); font-size: 0.87rem; font-weight: 550;
    padding: 0.5rem 0.85rem;
}
[data-baseweb="tab"]:hover { color: var(--text-2); }
[aria-selected="true"][role="tab"] { color: var(--text) !important; font-weight: 620; }

.stMarkdown { line-height: 1.6; }
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
    color: var(--text); letter-spacing: -0.015em; font-weight: 640;
}
.stMarkdown h4 { font-size: 1rem; margin-top: 1.4rem; }
.stMarkdown a { color: var(--primary); }

[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 9px; }
[data-testid="stMetric"] {
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 9px; padding: 0.75rem 0.9rem;
}
code { font-size: 0.85em; }
hr { border-color: var(--line); }

@media (max-width: 768px) {
    .block-container { padding-left: 0.75rem; padding-right: 0.75rem; }
    .kpi .value { font-size: 1.4rem; }
    .hero { padding: 1.1rem 1.2rem; }
    .hero .title { font-size: 1.4rem; }
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
