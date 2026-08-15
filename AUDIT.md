# Repository Audit & Implementation Plan

Audit date: 2026-08-15. Baseline commit: `d367e91` ("Restore single-file app").

---

## 1. What existed before this work

The repository contained **13 tracked files**, three of them empty `__init__.py`.

| File | Assessment |
|---|---|
| `app.py` (292 lines) | Streamlit UI + one hardcoded prompt + one LLM call. All logic in one file. |
| `src/product_analysis_app.py` | **Byte-identical duplicate of `app.py`.** Dead code, imported by nothing. |
| `services/openrouter_service.py` | **Orphan.** The same prompt a third time. `app.py` never imported it. |
| `config/settings.py` | Only consumed by the orphan service. `app.py` re-read `os.environ` itself. |

### Defects found

1. **The single analysis prompt was triplicated** across three files — any edit had to be made three times or the copies would drift.
2. **`src/` was entirely dead code**, while the README documented it as the app structure.
3. **`app.py` bypassed its own config layer**, so `config/settings.py`'s missing-key validation never ran on the real code path.
4. **Accessibility defect**: CSS forced input labels and text to `#000000` against a dark panel — unreadable.
5. **No persistence.** Every analysis was lost on rerun.

### What was healthy

- `.env` correctly gitignored and untracked. **No secrets committed.**
- OpenRouter integration functional (verified with a live call).
- The dark "glass" visual identity was usable and worth preserving.

---

## 2. Implementation matrix

Verified against the specification. Nothing in the spec was implemented at baseline.

| # | Capability | Before | Now | Notes |
|---|---|---|---|---|
| 1 | Universal intake | Name only | **Partial** | URL / description / Idea Mode. Files, GitHub, app stores not yet. |
| 2 | Product intelligence profile | Prose | **Done** | Structured columns + features table |
| 3 | Scoring engine | None | **Done** | 15 weighted dimensions, composite computed in code, fully drillable |
| 4 | Evidence engine | None | **Done** | Claim→grade→source→confidence→date. The spine of the platform. |
| 5 | Research engine | None | **Partial** | Own-site + user URLs. Provider protocol ready for more. |
| 6 | Competitor discovery | Prose | **Done** | 8 classification types incl. manual/open-source alternatives |
| 7 | Comparison matrix | None | **Partial** | Matrix + detail. Pin/reorder/export not yet. |
| 8 | Change detection | None | **Done** | Hash → price/signal → diff → agent. Price changes always escalate. |
| 9 | Gap engine | None | **Done** | Incl. `DO_NOT_BUILD` verdicts — verified in live runs |
| 10 | Customer intelligence | Prose | **Done** | Personas explicitly graded as inferred |
| 11 | Voice of Customer | None | **Missing** | |
| 12 | Market intelligence | Prose | **Done** | Drivers, inhibitors, trends, regulatory — all evidenced |
| 13 | TAM/SAM/SOM | None | **Done** | Formula + variables + assumptions + confidence required |
| 14 | Positioning studio | None | **Done** | 3+ distinct strategies, fit-scored, full messaging |
| 15 | Pricing studio | None | **Done** | Tiers, value metric, graded competitor pricing |
| 16 | Growth engine | None | **Done** | Channels scored per product; names channels to avoid |
| 17 | GTM studio | None | **Done** | Beachhead + 30/60/90/6mo/12mo phases |
| 18 | Roadmap generator | None | **Partial** | Now/Next/Later, move, delete. No drag-drop (Streamlit limitation). |
| 19 | AI product board | None | **Done** | Accept/reject/investigate/postpone; decisions remembered |
| 20 | Simulation lab | None | **Partial** | Pricing/growth simulation with elasticity. No what-if scenario agent. |
| 21 | Digital twin | None | **Partial** | Structured profile + memory serve this role |
| 22 | Strategy memory | None | **Done** | Rejected recs not resurfaced — test-covered |
| 23 | Multi-agent architecture | None | **Done** | 12 specialist agents, dependency-ordered |
| 24 | Agent contracts | None | **Done** | Pydantic → strict JSON Schema, validated + retried |
| 25 | Ask the platform | None | **Done** | Retrieval + citations verified against the ledger |
| 26 | Executive war room | None | **Partial** | KPIs, priorities, score profile, alert centre. |
| 27/28 | Opportunity / Threat radar | None | **Partial** | Synthesis ranks both; no dedicated visual |
| 29 | Strategy graph | None | **Partial** | Relational FKs model the relationships |
| 30 | Report studio | None | **Done** | MD/HTML/CSV/JSON; every report states its evidence basis |
| 31 | Workspaces | None | **Partial** | Schema + scoping throughout; single default workspace |
| 32 | Collaboration | None | **Missing** | Correctly deferred — product is single-user |
| 33 | Continuous intelligence | None | **Partial** | Monitors + due-detection. No OS-level scheduler. |
| 34 | Alert center | None | **Done** | Severity-ranked, read/archive, alert→roadmap, ask AI |
| 35 | Data quality indicators | None | **Done** | Banners, grade chips, confidence everywhere |
| 36 | Source management | None | **Done** | Library, statuses, failure reasons, disable |
| 37 | Analysis versioning | None | **Done** | Never overwritten; then-vs-now comparison |
| 38 | AI cost control | None | **Done** | Measured cost, dedup, call ceiling, model routing |
| 39 | Provider abstraction | None | **Done** | `LLMProvider` ABC |
| 40 | Retrieval | None | **Partial** | Grade/confidence-weighted keyword ranking. No embeddings. |
| 41 | Security | None | **Done** | SSRF, XSS, TLS, limits, isolation — test-covered |
| 42 | Privacy | None | **Done** | Cascade deletion, workspace scoping |
| 43 | Auditability | None | **Done** | Agent, model, timestamp, evidence per finding |
| 44 | Observability | None | **Done** | Runs, latency, failures, structured events |
| 45 | Background jobs | None | **Done** | Thread pool, progress, cancel |
| 46 | Database design | None | **Done** | 33 tables, FKs, indexes, 2 migrations |
| 47 | UX | Basic | **Done** | Executive cards, tabs, drilldowns, progressive disclosure |
| 48/50 | Progressive analysis | None | **Done** | Section-ready events, live progress |
| 49 | Onboarding | None | **Done** | Minimal, mode-aware |
| 51 | Admin diagnostics | None | **Done** | Provider, spend, failures, config |
| 52 | Testing | None | **Done** | 181 tests on security + correctness paths |
| 53 | Accessibility | Broken | **Partial** | Contrast fixed, focus rings added. No full audit. |
| 54 | Performance | N/A | **Partial** | Indexed, capped, paginated reads |
| 55 | Mobile | None | **Partial** | Responsive breakpoints |
| 56 | Export / sharing | None | **Done** | Download + structured export |
| 57 | Public API | None | **Missing** | Service layer is API-ready; not exposed |
| 58–62 | Modes | None | **Partial** | Mode selected and steers synthesis; no per-mode surfaces |

---

## 3. Verification performed

Not claimed — executed:

| Check | Result |
|---|---|
| Live OpenRouter call | Pass |
| Strict structured output, all 14 contracts | Pass (one `$ref`-sibling bug found and fixed) |
| SSRF guard, 23 attack vectors | All blocked |
| Full pipeline, Idea Mode | 8/8 agents succeeded, $0.0151 |
| Full pipeline, URL + research | 8/8 agents, 3 sources, $0.0284 |
| Evidence discipline (no sources) | **0 verified facts, 0% backed** — correct |
| Evidence discipline (with sources) | **16 verified facts, 87.5% backed**, all citing genuinely fetched URLs |
| `DO_NOT_BUILD` capability | Produced in live run |
| Test suite | 181 passed |
| Full 12-agent pipeline (live) | 12/12 succeeded, $0.0401, 95% evidence-backed |
| Monitoring: unchanged content | **0 model calls** — hash check short-circuits |
| Monitoring: real change | Detected, classified `pricing`, alert raised, 1 model call |
| Ask with citations | 0 fabricated citations across live questions |

The evidence contrast between those two runs is the central proof: the platform
does not manufacture verified facts when it has nothing to verify against.

---

## 4. Architectural decisions

**Stayed on Python + Streamlit + SQLite.** The spec directs against introducing
unnecessary technologies and against enterprise complexity for a single-user
product. FastAPI/React/Postgres/Celery would have been a rewrite, not an upgrade.

**SQLite over an ORM.** The data model is relational and modest; SQLAlchemy would
have added a dependency without removing real work.

**Workspace scoping from day one.** Every table carries `workspace_id` even though
there is one workspace today — retrofitting tenant isolation means rewriting every
query.

**Composite score computed in code.** The model scores individual dimensions; the
headline number is weighted arithmetic. A model-generated composite could not be
reproduced or explained.

**Deleted rather than kept:** `src/product_analysis_app.py`, `services/`, `config/`.
All three were dead or duplicated. Their only unique content — the prompt — is
superseded by eight specialised agents.

---

## 5. Remaining roadmap

Phases 2-4 of the original plan are now built. What remains:

**Voice of Customer (§11)** — review/feedback ingestion, theme clustering,
sentiment. The largest single remaining capability.

**Scenario simulation agent (§20)** — the financial simulator exists; the
open-ended "what if Competitor X launches Feature Y" agent does not.

**Per-mode surfaces (§58-62)** — mode steers synthesis but Investor / PM /
Executive / Consultant do not yet get distinct views.

**Semantic retrieval (§40)** — ranking is grade- and confidence-weighted keyword
overlap. Embeddings would improve recall on paraphrased questions.

**Richer research providers (§5)** — review sites, app stores, job postings,
news. The `ResearchProvider` protocol is ready for them.

**Opportunity / Threat radar visuals (§27-28)** — ranked in synthesis, no
dedicated visual surface.

**Public API (§57)** — the service layer is clean enough to expose; not done.

**Scheduling (§33)** — monitors know when they are due, but nothing wakes the
process. Needs an OS scheduler or a long-running worker.

**Cross-cutting, required before any multi-user deployment**
Authentication and RBAC. The app has **no auth layer** and must not be exposed
to untrusted networks. Collaboration (§32) depends on this landing first.

---

## 6. Defects found and fixed by testing

Each of these was caught by writing a test or reading live output, not by
inspection. They are recorded because they were all silent failures — the
system looked like it was working.

| Defect | Impact | Fix |
|---|---|---|
| `$ref` carried sibling keywords | Every structured agent call 400'd | Strip siblings in `ai/schema.py` |
| TLS verification failed on system CA | All research broke in this environment | Use OS trust store via `truststore`; verification stays **on** |
| Change ratio computed character-wise | A `$49`→`$39` price cut scored **below** threshold and was silently dropped — defeating the whole monitoring feature | Word-level ratio **plus** price/capability token extraction that always escalates |
| Confidence returned as `95` not `0.95` | Repository clamped to `1.0`, reporting **false maximum certainty** — the worst possible failure for an evidence-graded product | `Confidence` type rescales rather than clamps |
| `-1` price sentinel rendered literally | Contact-sales tiers displayed as **"$-1/mo"** | `format_price` renders Custom / Free; applied across UI, reports and prompts |
| Date regex missed `12 March 2024` | Date-only edits registered as content change | Handle both date orderings |
| Price regex captured trailing comma | `"$49,"` ≠ `"$49"`, causing phantom price changes | Explicit thousands-group matching |
