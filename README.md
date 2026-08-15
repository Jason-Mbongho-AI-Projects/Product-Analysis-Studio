# Product Analysis Studio

**Know your product. Understand your market. Anticipate your competition. Decide what to build next.**

An evidence-driven AI product intelligence and strategy platform. Give it a product
URL — or just an idea — and it researches, analyses, scores, and produces prioritised
recommendations you can accept, reject, or push onto a roadmap.

The organising principle is **evidence discipline**: every conclusion carries a claim,
a grade, a confidence level, and its sources. An AI guess is never rendered as a
verified fact.

---

## What it does

| Capability | Description |
|---|---|
| **Universal intake** | Product URL, plain description, or "I only have an idea" mode |
| **Research engine** | Fetches public product pages with SSRF protection and robots.txt compliance |
| **Product profile** | Structured capabilities, features, SWOT, commercial model |
| **Competitor discovery** | Direct, indirect, substitute, legacy, open-source and manual alternatives |
| **Market intelligence** | Drivers, inhibitors, trends, plus TAM/SAM/SOM that shows its arithmetic |
| **Customer intelligence** | ICP and personas, explicitly labelled as inferred unless research-backed |
| **Scoring engine** | 15 weighted dimensions; the composite is computed in code, not by the model |
| **Gap analysis** | Recommendations including explicit `DO NOT BUILD` verdicts |
| **Decision board** | Accept / reject / investigate / postpone, with decisions remembered |
| **Roadmap** | Now / Next / Later, fed by accepted recommendations |
| **Evidence ledger** | Every claim, its grade, confidence, agent and citations |
| **Version comparison** | Then-vs-now across analysis versions |
| **Cost & audit** | Measured spend, agent runs, latency, failures |

---

## Architecture

```
app.py                    Streamlit entry point (thin)
pas/
├── config.py             All environment access. Nothing else reads os.environ.
├── domain/
│   ├── enums.py          Controlled vocabularies + score weights
│   └── contracts.py      Pydantic agent output contracts
├── ai/
│   ├── schema.py         Pydantic → strict JSON Schema conversion
│   └── provider.py       LLMProvider ABC + OpenRouter implementation
├── research/
│   ├── safety.py         SSRF guard (the security boundary)
│   ├── fetcher.py        Polite, size-capped, redirect-revalidating fetcher
│   └── engine.py         Provider-based research orchestration
├── agents/
│   ├── base.py           Agent ABC: contracts, retry, observability, budget
│   ├── analysts.py       The eight specialist agents + composite scoring
│   └── orchestrator.py   Pipeline execution with progressive events
├── storage/
│   ├── db.py             sqlite connection + migration runner
│   ├── migrations/       Versioned SQL
│   └── repositories.py   Workspace-scoped data access
├── jobs/runner.py        Background thread pool for long analyses
├── service.py            Application facade — the only thing the UI calls
└── ui/                   Theme, components, pages
```

### Data flow

```
Intake → Research (SSRF-guarded fetch) → Agent pipeline → Storage → UI
                                              ↓
                              Evidence ledger (claim/grade/source/confidence)
```

### Agent pipeline

Agents run in dependency order; each reads what earlier agents persisted:

```
intake → product_analyst → competitive_intelligence → market_analyst
       → customer_intelligence → scoring → gap_analysis → chief_strategy
```

Each agent returns a **validated Pydantic contract**, not prose. A schema violation
is a retryable error carrying the validation message back to the model. There is no
single mega-prompt anywhere in the codebase.

If one agent fails, the analysis degrades to `partial` and the rest continue.

---

## Evidence model

Every claim is graded:

| Grade | Meaning |
|---|---|
| `verified_fact` | A retrieved source directly states it |
| `strong_inference` | Strongly implied by retrieved material |
| `weak_inference` | Plausible but thinly supported |
| `ai_hypothesis` | Model reasoning with no retrieved support |
| `user_supplied` | You asserted it |

When no sources are retrieved, agents are instructed that **every** claim must be
`ai_hypothesis` with empty citations. The UI then shows a warning banner, and
confidence drops accordingly. This is verified by the test suite.

The composite product score is weighted arithmetic over 15 dimensions
(`SCORE_WEIGHTS` in `domain/enums.py`, summing to 1.0). Three dimensions — competitive
pressure, acquisition difficulty, implementation complexity — are stored raw but
inverted before rolling up, so the headline always reads "higher is better".

---

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

cp .env.example .env            # then add your key
streamlit run app.py
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | *(required)* | API key. Server-side only, never sent to the browser. |
| `PAS_FAST_MODEL` | `openai/gpt-4.1-mini` | Model for mechanical tasks |
| `PAS_DEEP_MODEL` | `openai/gpt-4.1-mini` | Model for reasoning-heavy agents |
| `PAS_DATA_DIR` | `./data` | SQLite location |
| `PAS_MAX_LLM_CALLS` | `60` | Per-analysis call ceiling |
| `PAS_HTTP_TIMEOUT` | `12` | Research fetch timeout (seconds) |
| `PAS_MAX_PAGES_PER_DOMAIN` | `6` | Research politeness limit |

Set `PAS_DEEP_MODEL` to a stronger model (e.g. `openai/gpt-4.1`) for better
reasoning at higher cost. Task-based routing is already wired through
`Agent.deep`.

---

## Testing

```bash
python -m pytest
```

Coverage focuses on the paths where failure is expensive:

- **SSRF guard** — every blocked class enumerated (loopback, private ranges,
  metadata endpoints, dangerous schemes, credential smuggling, IPv4-mapped IPv6)
- **Schema contracts** — strict-mode compliance for all eight agent contracts
- **Scoring** — weights sum to 1.0, inversion behaves correctly, composite is reproducible
- **Strategy memory** — rejected recommendations are not resurfaced
- **Tenant isolation** — cross-workspace reads return nothing
- **Output escaping** — model output is escaped; only http(s) URLs become links

---

## Security

| Concern | Handling |
|---|---|
| **SSRF** | `research/safety.py` resolves DNS and validates every address before connecting. Redirects are followed manually so each hop is revalidated. |
| **Secrets** | Only `config.py` reads the environment. The key is never rendered or serialised into UI payloads. |
| **XSS** | All model output and fetched titles pass through `esc()` before reaching HTML. Only `http(s)` URLs become anchors, with `rel="noopener noreferrer nofollow"`. |
| **TLS** | Verification is always on; the OS trust store is used via `truststore` so corporate roots resolve. |
| **Resource limits** | Responses are size-capped and streamed; redirects bounded; per-analysis model-call ceiling. |
| **Site terms** | robots.txt is honoured. Sites that decline access are recorded as blocked and skipped — never worked around. |
| **Tenant isolation** | Every table carries `workspace_id`; every read is scoped. |
| **Deletion** | Deleting a product cascades to all derived intelligence via foreign keys. |

---

## Database

SQLite with foreign keys enforced, WAL enabled, and versioned migrations in
`pas/storage/migrations/`. Analyses are versioned and **never overwritten**, which is
what makes then-vs-now comparison possible.

Structured intelligence lives in columns so it stays queryable; JSON is reserved for
genuinely free-shaped metadata.

---

## Cost control

OpenRouter reports real spend per call, so cost tracking is **measured, not estimated**
from a price table that would drift. Every call records provider, model, tokens, cost
and latency against its agent run. See the Audit tab and Diagnostics page.

---

## Current limitations

Honest scope statement — see `AUDIT.md` for the full roadmap:

- Research covers the product's own site and user-supplied URLs. Review sites, app
  stores, news and job postings are designed for (`ResearchProvider` protocol) but not
  yet implemented.
- Competitor monitoring, change detection and alerts are not yet built; the schema
  supports them.
- Positioning, pricing simulation, GTM and Voice-of-Customer are not yet implemented.
- Report export (PDF/DOCX/XLSX) is not yet implemented.
- Single-user. Workspace scoping exists throughout, but there is no auth layer —
  do not expose this to untrusted networks as-is.

---

## License

MIT. See [LICENSE](LICENSE).
