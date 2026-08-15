import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

MODEL = "openai/gpt-4.1-mini"


def analyze_product(product_name):
    current_date = datetime.now().strftime("%b %Y")

    system_prompt = (
        "You are a senior product and business analyst. You write clear, practical, "
        "well-structured product analysis reports for founders and business teams."
    )

    user_prompt = f"""
Write a detailed product analysis report for: {product_name}.

Current month is {current_date}.

Cover the following in one flowing, well-organized report (use markdown headings and bullet points where helpful):
- Market Overview: provide size, growth trends, and key players.
- Product Features: describe the key features and differentiators.
- Competitive Analysis: compare the product with competitors using SWOT.
- Target Audience: define demographics, preferences, and pain points.
- Market Potential: assess growth opportunities, revenue streams, and scalability.
- Marketing Strategy: suggest effective strategies (at least 5 points).
- Technology and Manufacturing Feasibility: discuss the stack, requirements, and production considerations (at least 5 points).
- Business Model: explain scalability and revenue streams (at least 5 points).
- Concise business plan, goals, roadmap, and launch timeline.
- Conclusion: summarize findings and provide actionable recommendations.

Keep it insightful, practical, and actionable. Use clear and concise language, and provide specific examples where possible.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.choices[0].message.content


def main():
    st.set_page_config(
        page_title="Product Analysis Studio",
        page_icon="📊",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        :root {
            --bg-1: #040b16;
            --bg-2: #0a1324;
            --panel: rgba(15, 23, 42, 0.72);
            --panel-strong: rgba(16, 24, 39, 0.9);
            --line: rgba(148, 163, 184, 0.22);
            --text: #e2e8f0;
            --muted: #a5b4cf;
            --primary: #7c3aed;
            --primary-2: #22d3ee;
            --accent: #f59e0b;
            --success: #34d399;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background: radial-gradient(circle at top left, rgba(124, 58, 237, 0.22), transparent 25%),
                        radial-gradient(circle at bottom right, rgba(34, 211, 238, 0.18), transparent 25%),
                        linear-gradient(135deg, var(--bg-1), var(--bg-2));
            color: var(--text);
        }

        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 2rem;
            max-width: 1280px;
        }

        .hero {
            background: linear-gradient(135deg, rgba(124, 58, 237, 0.15), rgba(34, 211, 238, 0.08));
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 24px;
            padding: 1.8rem 1.5rem 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.35), inset 0 1px 0 rgba(255,255,255,0.14);
        }

        .title {
            font-size: clamp(2.3rem, 4vw, 3.8rem);
            font-weight: 800;
            letter-spacing: -0.06em;
            background: linear-gradient(135deg, #f8fafc 0%, #b4c1ff 30%, #6ee7f9 100%);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            margin: 0;
            line-height: 1.05;
        }

        .subtitle {
            font-size: 1rem;
            color: var(--muted);
            margin-top: 0.6rem;
            letter-spacing: 0.02em;
        }

        .glass-card {
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.8), rgba(15, 23, 42, 0.62));
            border: 1px solid var(--line);
            border-radius: 22px;
            padding: 1.2rem 1.1rem;
            box-shadow: 0 16px 30px rgba(2, 6, 23, 0.35), inset 0 1px 0 rgba(255,255,255,0.08);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }

        .metric-box {
            background: linear-gradient(145deg, rgba(124, 58, 237, 0.18), rgba(34, 211, 238, 0.08));
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 18px;
            padding: 1rem;
            margin-bottom: 0.8rem;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
        }

        .metric-number {
            font-size: 1.7rem;
            font-weight: 800;
            color: #f8fafc;
        }

        .metric-label {
            font-size: 0.8rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }

        div[data-testid="stTextInput"] > div {
            background: rgba(15, 23, 42, 0.7);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 16px;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
        }

        div[data-testid="stTextInput"] label,
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextInput"] textarea,
        div[data-testid="stTextInput"] p,
        div[data-testid="stTextInput"] div {
            color: #000000 !important;
        }

        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stTextInput"] textarea::placeholder {
            color: rgba(15, 23, 42, 0.6) !important;
        }

        div[data-baseweb="base-input"] > div {
            background: transparent;
            border-radius: 16px;
        }

        input {
            background: transparent !important;
            color: #000000 !important;
            font-size: 1rem !important;
        }

        .stButton > button {
            width: 100%;
            border: none;
            border-radius: 16px;
            background: linear-gradient(135deg, var(--primary), var(--primary-2));
            color: white;
            font-weight: 700;
            font-size: 1rem;
            padding: 0.8rem 1rem;
            box-shadow: 0 12px 25px rgba(124, 58, 237, 0.42), inset 0 1px 0 rgba(255,255,255,0.2);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 18px 30px rgba(34, 211, 238, 0.22), 0 10px 25px rgba(124, 58, 237, 0.38);
        }

        [data-testid="stExpander"] {
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 18px;
            background: rgba(15, 23, 42, 0.5);
            box-shadow: 0 12px 30px rgba(2, 6, 23, 0.2);
        }

        .stMarkdown {
            color: var(--text);
            line-height: 1.7;
        }

        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
            color: #f8fafc;
        }

        .stError, .stInfo {
            border-radius: 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="hero">
            <div class="title">Product Analysis Studio</div>
            <div class="subtitle">AI-powered market research, positioning, and growth strategy</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([2.1, 1])

    with left_col:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        product_name = st.text_input(
            "Product name",
            placeholder="e.g. AI fitness coaching app",
            label_visibility="collapsed",
        )
        if st.button("Analyze Product", use_container_width=True):
            if not product_name:
                st.error("Please enter a product name before starting the analysis.")
            else:
                loading_placeholder = st.empty()
                loading_placeholder.info(f"Starting analysis for '{product_name}'... Please wait.")

                try:
                    with st.spinner("Analyzing product... This may take a few moments."):
                        report = analyze_product(product_name)

                    loading_placeholder.empty()
                    st.subheader("Analysis Results")

                    with st.expander(f"Report: {product_name}", expanded=True):
                        st.markdown(report)

                except Exception as e:
                    loading_placeholder.empty()
                    st.error(f"An error occurred: {str(e)}")
        st.markdown('</div>', unsafe_allow_html=True)

    with right_col:
        st.markdown(
            """
            <div class="glass-card">
                <div class="metric-box">
                    <div class="metric-label">Focus</div>
                    <div class="metric-number">Market</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Output</div>
                    <div class="metric-number">Strategy</div>
                </div>
                <div class="metric-box">
                    <div class="metric-label">Format</div>
                    <div class="metric-number">Insights</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
