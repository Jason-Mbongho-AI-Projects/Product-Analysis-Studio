# Product Analysis Studio

A modern AI-powered Streamlit dashboard for generating product analysis reports from a product name or concept.

## Features
- Enter a product name or idea
- Generate a structured market and business analysis
- Get actionable recommendations for positioning, revenue, and launch planning
- Modern dark glass-style interface

## Tech Stack
- Python
- Streamlit
- OpenAI-compatible API via OpenRouter
- python-dotenv

## Project Structure

```text
Product-Analysis-Studio/
├── app.py                 # Entry point for the app
├── src/
│   ├── __init__.py
│   └── product_analysis_app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── LICENSE
└── .venv/
```

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a local `.env` file in the project root with your OpenRouter key:
   ```env
   OPENROUTER_API_KEY=your_key_here
   ```

4. Run the app:
   ```bash
   streamlit run app.py
   ```

## Notes
- Do not commit your `.env` file.
- The app expects a valid OpenRouter API key in `OPENROUTER_API_KEY`.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
