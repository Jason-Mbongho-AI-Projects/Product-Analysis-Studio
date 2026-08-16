"""Visual identity.

A cool slate dark system. Every colour is measured rather than chosen by eye:
the chart series clear the data-viz validator against this surface (lightness
band, chroma floor, colour-vision separation, contrast), every UI and status
colour clears WCAG AA at 4.5:1, and every chart mark clears the 3:1 graphical
floor.

The design decisions that matter:

* **A slate ground, not near-black.** Pure black reads flat and makes every
  border work to define anything; a blue-grey plane has presence, and panels
  above it separate by luminance alone. Surfaces step evenly, so a raised
  element nested inside a panel still reads as raised.
* **Hairline borders at low alpha, not solid rules.** Structure comes from
  luminance steps and spacing; visible boxes everywhere read as a form, not a
  dashboard.
* **Colour always means something.** Three uses, and no others: the workflow
  domain (where you are), status (evidence grade, severity, score band), and
  data series. There is no decorative colour anywhere.
* **Wayfinding takes the domain colour; controls keep the neutral accent.**
  The current section, its page rule and its tab indicator follow the domain,
  while buttons and toggles stay blue - so an orange section never grows an
  orange primary button that reads as a warning.
* **Tabular figures for numbers.** Stat values and table columns align
  vertically instead of shifting as digits change.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

PALETTE = {
    # Surfaces: a cool slate ramp. Near-black reads flat and forces every border
    # to work hard for definition; a blue-grey ground has presence and lets the
    # panels above it separate by luminance alone. Steps are even, so nesting a
    # raised element inside a panel still reads.
    "plane": "#1b2130",
    "bg_1": "#1b2130",
    "bg_2": "#1e2434",
    "surface": "#222939",
    "surface_raised": "#293143",
    "surface_hover": "#313a4e",
    "sidebar": "#171d29",
    "input": "#1a2030",
    # Borders are alpha so they sit correctly on any surface beneath them.
    "line": "rgba(255,255,255,0.075)",
    "line_strong": "rgba(255,255,255,0.14)",
    # Ink, stepped for this ground.
    "text": "#eef1f6",
    "text_secondary": "#aeb6c4",
    "muted": "#949cab",
    # One accent for controls.
    "primary": "#4b8bf5",
    "primary_hover": "#6b9ff7",
    "primary_soft": "rgba(75,139,245,0.16)",
    "primary_2": "#4b8bf5",
    # Status - reserved, never decorative. Stepped for the lifted surface so
    # each still clears WCAG AA at 4.5:1 rather than the 3:1 graphical floor.
    "success": "#3fb950",
    "accent": "#d9a441",
    "warning": "#d9a441",
    "serious": "#e0693a",
    "danger": "#f0605d",
    "violet": "#9d90f0",
}

#: Validated categorical slots for CHART MARKS, fixed order, never cycled.
#:
#: These are deliberately a shade deeper than the UI colours below. Chart marks
#: must sit inside a common lightness band so a series set reads as one family;
#: UI text and chips have no such constraint and are stepped lighter to clear
#: 4.5:1 on this surface. Marks only need the 3:1 graphical floor, which these
#: clear. Conflating the two would either wash out the charts or dim the text.
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]

#: Workflow domains. Colour here encodes *where you are* - it is navigation
#: feedback, not decoration. These three clear every gate on the all-pairs
#: list, which matters because they appear far apart on screen rather than
#: side by side. Blue and violet were the obvious first choice and were
#: rejected: ΔE 11.5 apart to normal vision, 3.0 under protanopia.
DOMAINS = {
    "Analyse": "#4b8bf5",
    "Strategise": "#e0693a",
    "Act": "#22b07f",
    "System": "#9096a1",
}
DEFAULT_DOMAIN = "#4b8bf5"

#: Evidence grade is a status ladder, so it borrows status-family colours:
#: verified reads as good, hypothesis reads as caution.
GRADE_STYLES = {
    "verified_fact": ("Verified", "#3fb950"),
    "strong_inference": ("Strong inference", "#4b8bf5"),
    "user_supplied": ("You told us", "#9d90f0"),
    "weak_inference": ("Weak inference", "#d9a441"),
    "ai_hypothesis": ("AI hypothesis", "#e0693a"),
}

VERDICT_STYLES = {
    "must_build": ("Must build", "#f0605d"),
    "should_build": ("Should build", "#d9a441"),
    "could_build": ("Could build", "#4b8bf5"),
    "do_not_build": ("Do not build", "#9096a1"),
    "investigate_first": ("Investigate first", "#9d90f0"),
}

THREAT_STYLES = {
    "critical": "#f0605d",
    "high": "#e0693a",
    "medium": "#d9a441",
    "low": "#3fb950",
}

_VARIABLES = "\n".join(
    f"    --{name}: {PALETTE[key]};"
    for name, key in [
        ("plane", "plane"),
        ("surface", "surface"),
        ("surface-raised", "surface_raised"),
        ("surface-hover", "surface_hover"),
        ("sidebar", "sidebar"),
        ("input", "input"),
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
    background: var(--sidebar);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

[data-testid="stSidebar"] .stButton button {
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
/* Streamlit centres the label in a flex div *inside* the button, so setting
   justify-content on the button alone does nothing. Left-aligning here lines
   the route names up with the group headings above them; centred items read as
   misaligned against a left-aligned "ANALYSE". */
[data-testid="stSidebar"] .stButton button > div {
    justify-content: flex-start;
    width: 100%;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: var(--surface-hover); color: var(--text); border-color: transparent;
}
/* Current route: a soft wash and an accent rule, not a saturated fill. */
[data-testid="stSidebar"] .stButton button[kind="primary"] {
    background: var(--domain-soft, var(--primary-soft));
    color: var(--text);
    border: 1px solid transparent;
    border-left: 2px solid var(--domain, var(--primary));
    border-radius: 3px var(--radius) var(--radius) 3px;
    font-weight: 600;
}
[data-testid="stSidebar"] .stButton button[kind="primary"]:hover {
    background: var(--domain-soft, var(--primary-soft));
}

/* The brand in the sidebar: same relief, smaller, so the two agree. */
.brand-mark {
    font-size: 1.06rem; font-weight: 700; letter-spacing: -0.025em;
    line-height: 1.2; margin: 0 0 0.15rem 0;
}
.brand-sub {
    color: var(--muted); font-size: 0.755rem; line-height: 1.4;
    margin: 0 0 0.2rem 0;
}

/* Group label, tinted by domain. */
.nav-group {
    font-size: 0.635rem; letter-spacing: 0.12em; text-transform: uppercase;
    font-weight: 680; margin: 1.15rem 0 0.4rem 0.15rem;
}
/* A route you cannot reach yet must recede, not advance. `border-color` has to
   be reset explicitly: the base rule's `border: 1px solid transparent` is
   overridden by Streamlit's own disabled styling, which drew a visible box. On
   the landing screen every product-scoped route is disabled, so the effect was
   backwards - the unavailable routes were the only boxed items in the sidebar
   and read as the primary navigation. */
[data-testid="stSidebar"] .stButton button:disabled {
    color: #626a79;
    background: transparent;
    border-color: transparent;
}

/* Raised-relief brand type. The face carries a top-lit gradient (bright at the
   cap line, cooling toward the baseline) and the depth comes from a stack of
   hard drop-shadows.

   Each drop-shadow in a filter chain is applied to the *output* of the previous
   one, so the offsets compound: uniform 1px steps build one solid 5px side face,
   whereas 1/2/3px would land at 1/3/6px and leave gaps that read as a blurred
   shadow. The ramp darkens down the stack so the extrusion turns away from the
   light, and it is navy rather than black so it sits in the slate palette
   instead of punching a hole through it. `color` is set first as the fallback:
   if background-clip:text is unsupported the name renders white, never invisible.
*/
.brand-3d {
    color: #ffffff;
    background: linear-gradient(180deg, #ffffff 0%, #edf2f9 40%, #c2cfe3 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    filter:
        drop-shadow(0 1px 0 #2b3242)
        drop-shadow(0 1px 0 #252c3a)
        drop-shadow(0 1px 0 #1f2532)
        drop-shadow(0 1px 0 #191e29)
        drop-shadow(0 1px 0 #141821)
        drop-shadow(0 5px 8px rgba(0, 0, 0, 0.42));
    padding-bottom: 0.14em;
}

/* The sidebar mark is a sixth of the hero's size, so it takes a proportionally
   shallower extrusion. Depth has to stay a roughly constant *fraction* of the
   cap height or it stops reading as the same object: the hero's 5px on ~35px is
   about a seventh, so 1px on ~12px here matches. Two steps at this size read as
   a ghosted second copy of the name rather than a side face. */
.brand-mark.brand-3d {
    filter:
        drop-shadow(0 1px 0 #1d2431)
        drop-shadow(0 1px 3px rgba(0, 0, 0, 0.34));
    padding-bottom: 0.08em;
}

/* ---- Page header ---- */
.hero { margin: 0 0 1.75rem 0; }
.hero .title {
    font-size: clamp(1.7rem, 2.6vw, 2.3rem);
    font-weight: 700;
    letter-spacing: -0.032em;
    color: var(--text);
    line-height: 1.15;
    margin: 0;
}
.hero .subtitle {
    color: var(--muted); margin-top: 0.45rem; font-size: 0.9rem;
    max-width: 70ch; line-height: 1.6;
}

.page-head { margin: 0 0 1.4rem 0; }
/* A short rule in the page's domain colour: enough to identify where you are
   at a glance, without tinting the content itself. */
.page-head::before {
    content: ""; display: block; width: 28px; height: 3px; border-radius: 2px;
    background: var(--domain, var(--primary)); margin-bottom: 0.7rem;
}
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
    border-left: 2px solid var(--domain-soft, var(--line-strong));
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
div[data-testid="stTextArea"] textarea::placeholder { color: #737b8a !important; }
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
/* The selected-tab underline. Streamlit renders this with react-aria, not
   baseweb - the obvious [data-baseweb="tab-highlight"] selector matches
   nothing, so the indicator stayed blue on every domain. */
.react-aria-SelectionIndicator {
    background: var(--domain, var(--primary)) !important;
}

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


def set_domain(colour: str) -> None:
    """Tint the current screen with its workflow domain colour.

    Applied as a CSS variable so the page header rule, the selected tab and
    focus states all follow the domain without every component needing to know
    about it.
    """
    st.markdown(
        f"<style>:root {{ --domain: {colour}; "
        f"--domain-soft: color-mix(in srgb, {colour} 15%, transparent); }}</style>",
        unsafe_allow_html=True,
    )


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
