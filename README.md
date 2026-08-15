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
| **Positioning studio** | Several genuinely different strategies, scored for fit, plus full messaging |
| **Pricing studio** | Value metric, tiers, competitor pricing graded by evidence |
| **Simulation lab** | LTV, CAC payback, break-even and price elasticity — computed in Python |
| **Growth engine** | Channels scored against *this* product's price point and buyer |
| **GTM studio** | Beachhead segment and a phased 30/60/90/6mo/12mo launch plan |
| **Decision board** | Accept / reject / investigate / postpone, with decisions remembered |
| **Roadmap** | Now / Next / Later, fed by accepted recommendations |
| **Voice of Customer** | Reviews, interviews and tickets clustered into themes, with verbatim quotes checked against your own data |
| **Opportunity & threat radar** | Signals ranked by expected value (impact x probability) |
| **Scenario lab** | Open-ended what-ifs across best / base / worst cases |
| **Ask** | Hybrid BM25 + embedding retrieval over the evidence ledger, with verified citations |
| **Monitoring & alerts** | Competitor change detection with a severity-ranked alert centre |
| **Report studio** | Markdown / HTML / CSV / JSON exports that carry their evidence basis |
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
│   ├── documents.py      Upload parsing (CSV/TSV/JSON/TXT/PDF)
│   ├── providers.py      GitHub API, RSS/Atom, sitemap, changelog
│   └── engine.py         Provider-based research orchestration
├── agents/
│   ├── base.py           Agent ABC: contracts, retry, observability, budget
│   ├── analysts.py       Intelligence agents — "what is true"
│   ├── strategists.py    Strategy agents — "what to do about it"
│   ├── voice.py          Voice of Customer, radar and scenario agents
│   ├── pipeline.py       Execution order (the dependency chain)
│   └── orchestrator.py   Pipeline execution with progressive events
├── analysis/
│   ├── finance.py        Deterministic unit economics + elasticity model
│   ├── monitoring.py     Change detection and alert generation
│   ├── ask.py            Question answering + citation verification
│   ├── retrieval.py      Hybrid BM25 + embedding ranking
│   └── reports.py        Report builders and format conversion
├── storage/
│   ├── db.py             sqlite connection + migration runner
│   ├── migrations/       Versioned SQL
│   ├── repositories.py   Workspace-scoped data access
│   └── strategy_repo.py  Strategy, monitoring and conversation access
├── auth/                 Passwords, roles, sessions, membership
├── jobs/
│   ├── runner.py         Background thread pool for long analyses
│   └── scheduler.py      Periodic monitor dispatch
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

Twelve agents run in dependency order; each reads what earlier agents persisted:

```
Intelligence   intake → product_analyst → competitive_intelligence
               → market_analyst → customer_intelligence → scoring → gap_analysis
Strategy       → positioning → pricing → growth → gtm
Synthesis      → radar → chief_strategy
```

Two agents run outside the pipeline, on demand: **voice_of_customer** (only when
you have supplied feedback) and **scenario** (one what-if at a time).

Each agent returns a **validated Pydantic contract**, not prose. A schema violation
is a retryable error carrying the validation message back to the model. There is no
single mega-prompt anywhere in the codebase.

If one agent fails, the analysis degrades to `partial` and the rest continue.

### What the model does not compute

Numbers that must be reproducible are calculated in Python from model-supplied
*inputs*, never generated by the model:

| Derived figure | Where |
|---|---|
| Composite product score | `agents/analysts.py::composite_score` |
| LTV, LTV:CAC, CAC payback | `analysis/finance.py::unit_economics` |
| Price/revenue scenarios | `analysis/finance.py::simulate_price_change` |
| Break-even and projections | `analysis/finance.py` |

The pricing agent estimates ARPU, churn, CAC and elasticity — and must state where
each came from. The simulator does the arithmetic. Raising price reduces customer
count through a constant-elasticity demand curve, so revenue can fall when price
rises; assuming constant demand would hide exactly the outcome worth knowing.

### Monitoring economics

A monitored page is fetched and hashed before anything else happens. Unchanged
hash means no model call. When content does differ, prices and capability terms
(SSO, SAML, SOC 2, free tier, …) are extracted and compared directly — a `$49` →
`$39` edit on a long pricing page is a tiny fraction of the text but always
escalates, because that is precisely the event monitoring exists to catch. Only
then is a diff sent to the change-detection agent, and only changes it marks
meaningful become alerts.

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
| `PAS_AUTH_ENABLED` | `false` | **Authentication. Off by default for local development.** |
| `PAS_ALLOW_SIGNUP` | `true` | Whether strangers may create their own accounts. |
| `PAS_DEFAULT_ROLE` | `viewer` | Role for accounts after the first (which becomes owner). |
| `PAS_SCHEDULER` | `false` | Run due monitors automatically while the app is open. |
| `PAS_SCHEDULER_TICK` | `300` | Seconds between scheduler checks. |
| `PAS_EMBEDDINGS` | `true` | Semantic retrieval for Ask. Cached per claim. |
| `PAS_EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Embedding model. |
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
| **Authentication** | scrypt password hashing (n=2^15), session tokens stored only as hashes, temporary lockout after 5 failed attempts, and identical response and timing for unknown-account vs wrong-password so login is not a user-enumeration oracle. |
| **Authorisation** | Six roles over a declarative permission matrix, enforced at the service boundary — not in the UI, which only hides what it already cannot reach. |
| **Tenant isolation** | Every table carries `workspace_id`; every read is scoped. A valid session grants nothing in a workspace the user is not a member of. |
| **Audit** | Every state change records actor, action, target and time. Audit writes are best-effort and can never roll back the operation they describe. |
| **Deletion** | Deleting a product cascades to all derived intelligence via foreign keys. |

---

## Retrieval

Ask ranks evidence with two complementary signals:

* **BM25** over claim text, which catches exact terminology — product names,
  "SOC 2", "SAML" — that embeddings blur together.
* **Cosine similarity** over embeddings, which catches paraphrase. Asking "who
  might eat our lunch" retrieves competitive-threat claims sharing no keywords
  with the question.

Scores are normalised, blended, then weighted by evidence grade and confidence,
so a verified fact outranks a hypothesis of equal textual relevance. Embeddings
are cached by content hash — a claim is embedded once regardless of how many
questions reference it — and a provider failure degrades to lexical-only rather
than breaking search.

---

## Research sources

Each source uses an access route the publisher offers deliberately:

| Source | Route |
|---|---|
| Product site | Direct fetch, robots.txt honoured |
| Site structure | `sitemap.xml`, discovered via `robots.txt` |
| Release notes | RSS/Atom feeds and conventional changelog paths |
| Open-source repos | The documented public GitHub REST API |
| Your own documents | Upload |

Enable the extra sources with the **Deep research** toggle on intake.

**Not included, deliberately:** app stores and review sites publish no free
review API and their terms prohibit scraping. Export your own data and upload it
through Voice of Customer. Building a scraper would have satisfied the feature
list while creating exactly the legal risk the spec says to avoid.

---

## Voice of Customer

Upload reviews, interview notes, support tickets or survey exports — CSV, TSV,
JSON/JSONL, TXT or PDF — or paste text directly. The text column is detected
automatically; feedback is deduplicated by normalised content hash, so
re-importing an overlapping export cannot inflate a theme's share.

**Quotes are verified after the fact.** The agent is told never to invent a
quote, and every quote it returns is then checked against your uploaded text.
Anything that does not match is discarded and reported in the caveats. A quote
you cannot find in your own data would destroy trust in every other finding, so
this is enforced in code rather than left to the prompt.

---

## Authentication

**Authentication is off by default** so `streamlit run app.py` works immediately
with no setup. While it is off, the app runs as a "development user" holding
owner rights and shows a permanent banner saying so.

To turn it on:

```bash
# .env
PAS_AUTH_ENABLED=true
```

Restart, and the first account you create becomes the **workspace owner**.
Subsequent accounts get `PAS_DEFAULT_ROLE` (default `viewer`).

### Roles

| Role | Can |
|---|---|
| **Owner** | Everything, including workspace deletion |
| **Admin** | Manage members, delete products, view diagnostics |
| **Analyst** | Run analyses, manage research sources and monitors |
| **Product manager** | Decide on recommendations, own the roadmap |
| **Executive** | Read everything, ask questions, export |
| **Viewer** | Read only |

Analyst and Product Manager are deliberately *not* nested: an analyst gathers
evidence but does not decide the roadmap, and a product manager decides without
managing research plumbing.

### Why the permission checks run even when auth is off

The development identity holds every permission rather than bypassing the
checks. `service.require(Permission.X)` executes on every call in both modes, so
switching authentication on does not activate a pile of code that has never run.
The test suite exercises the matrix with real per-role identities.

### Safety rail

An open app is one missing environment variable away from an unauthenticated
deployment, so `network_exposure_warning()` escalates from a quiet caption to a
prominent error when authentication is off **and** the server is bound to
anything other than loopback.

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
- **Authentication ships disabled** (`PAS_AUTH_ENABLED=false`) so local
  development is unobstructed. Turn it on before anyone else can reach the app.
- Sessions live in Streamlit's server-side state, so a server restart signs
  everyone out.
- No email-based password reset. An owner or admin sets a member's password
  directly from the Members tab; doing so revokes that account's sessions.
- The scheduler runs only while the app process is alive. For unattended
  monitoring, point cron at `StudioService.run_due_monitors()`.
- **No public API.** The service layer is the API surface — UI-free and
  permission-checked — but nothing is exposed over HTTP. The spec scoped that
  out of this phase.
- **App stores and review sites are not scraped.** They offer no free review
  API and prohibit automated collection. Export your reviews and upload them
  through Voice of Customer instead.
- Search-based competitor discovery needs a paid search API key.
- No drag-and-drop roadmap; Streamlit has none. Ordering is explicit buttons.
- Contrast and focus states are test-verified, but no screen-reader pass has
  been done.

---

## License

MIT. See [LICENSE](LICENSE).
