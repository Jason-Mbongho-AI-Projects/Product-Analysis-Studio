from datetime import datetime

from openai import OpenAI

from config.settings import MODEL, OPENROUTER_BASE_URL, get_api_key


def create_client():
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=get_api_key(),
    )


def generate_product_report(product_name):
    client = create_client()
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
