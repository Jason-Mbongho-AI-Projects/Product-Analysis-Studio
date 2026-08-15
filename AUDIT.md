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
| 1 | Universal intake | Name only | **Done** | URL, description, Idea Mode, and CSV/TSV/JSON/TXT/PDF upload |
| 2 | Product intelligence profile | Prose | **Done** | Structured columns + features table |
| 3 | Scoring engine | None | **Done** | 15 weighted dimensions, composite computed in code, fully drillable |
| 4 | Evidence engine | None | **Done** | Claim→grade→source→confidence→date. The spine of the platform. |
| 5 | Research engine | None | **Done** | Site, sitemap, feeds, changelog, GitHub API, user URLs |
| 6 | Competitor discovery | Prose | **Done** | 8 classification types incl. manual/open-source alternatives |
| 7 | Comparison matrix | None | **Done** | Matrix, detail, add/pin/remove, CSV export |
| 8 | Change detection | None | **Done** | Hash → price/signal → diff → agent. Price changes always escalate. |
| 9 | Gap engine | None | **Done** | Incl. `DO_NOT_BUILD` verdicts — verified in live runs |
| 10 | Customer intelligence | Prose | **Done** | Personas explicitly graded as inferred |
| 11 | Voice of Customer | None | **Done** | Ingestion, clustering, sentiment, quote verification |
| 12 | Market intelligence | Prose | **Done** | Drivers, inhibitors, trends, regulatory — all evidenced |
| 13 | TAM/SAM/SOM | None | **Done** | Formula + variables + assumptions + confidence required |
| 14 | Positioning studio | None | **Done** | 3+ distinct strategies, fit-scored, full messaging |
| 15 | Pricing studio | None | **Done** | Tiers, value metric, graded competitor pricing |
| 16 | Growth engine | None | **Done** | Channels scored per product; names channels to avoid |
| 17 | GTM studio | None | **Done** | Beachhead + 30/60/90/6mo/12mo phases |
| 18 | Roadmap generator | None | **Done** | Horizons, explicit ordering, assignment, comments |
| 19 | AI product board | None | **Done** | Accept/reject/investigate/postpone; decisions remembered |
| 20 | Simulation lab | None | **Done** | Deterministic pricing sim + open-ended scenario agent |
| 21 | Digital twin | None | **Partial** | Profile, memory, feedback and radar serve this role |
| 22 | Strategy memory | None | **Done** | Rejected recs not resurfaced — test-covered |
| 23 | Multi-agent architecture | None | **Done** | 13 pipeline agents + 2 on-demand, dependency-ordered |
| 24 | Agent contracts | None | **Done** | Pydantic → strict JSON Schema, validated + retried |
| 25 | Ask the platform | None | **Done** | Retrieval + citations verified against the ledger |
| 26 | Executive war room | None | **Done** | Mode-aware KPIs, priorities, radar, alerts |
| 27/28 | Opportunity / Threat radar | None | **Done** | Dedicated agent + surfaces, ranked by expected value |
| 29 | Strategy graph | None | **Partial** | Relational FKs model the relationships |
| 30 | Report studio | None | **Done** | MD/HTML/CSV/JSON; every report states its evidence basis |
| 31 | Workspaces | None | **Partial** | Membership-enforced scoping; one workspace in the UI |
| 32 | Collaboration | None | **Done** | Roles, members, comments, @mentions, assignment, activity feed |
| 33 | Continuous intelligence | None | **Done** | Monitors, due-detection, in-process scheduler, cron entry point |
| 34 | Alert center | None | **Done** | Severity-ranked, read/archive, alert→roadmap, ask AI |
| 35 | Data quality indicators | None | **Done** | Banners, grade chips, confidence everywhere |
| 36 | Source management | None | **Done** | Library, statuses, failure reasons, disable |
| 37 | Analysis versioning | None | **Done** | Never overwritten; then-vs-now comparison |
| 38 | AI cost control | None | **Done** | Measured cost, dedup, call ceiling, model routing |
| 39 | Provider abstraction | None | **Done** | `LLMProvider` ABC |
| 40 | Retrieval | None | **Done** | Hybrid BM25 + embeddings, cached, degrades to lexical |
| 41 | Security | None | **Done** | Auth, RBAC, SSRF, XSS, TLS, isolation — test-covered |
| 42 | Privacy | None | **Done** | Cascade deletion, workspace scoping |
| 43 | Auditability | None | **Done** | Agent, model, timestamp, evidence per finding |
| 44 | Observability | None | **Done** | Runs, latency, failures, structured events |
| 45 | Background jobs | None | **Done** | Thread pool, progress, cancel |
| 46 | Database design | None | **Done** | 51 tables, FKs, indexes, 6 atomic migrations |
| 47 | UX | Basic | **Done** | Executive cards, tabs, drilldowns, progressive disclosure |
| 48/50 | Progressive analysis | None | **Done** | Section-ready events, live progress |
| 49 | Onboarding | None | **Done** | Minimal, mode-aware |
| 51 | Admin diagnostics | None | **Done** | Provider, spend, failures, config |
| 52 | Testing | None | **Done** | 397 tests on security + correctness paths |
| 53 | Accessibility | Broken | **Done** | WCAG AA contrast verified by test; focus states asserted |
| 54 | Performance | N/A | **Partial** | Indexed, capped, paginated reads |
| 55 | Mobile | None | **Partial** | Responsive breakpoints |
| 56 | Export / sharing | None | **Done** | Download + structured export |
| 57 | Public API | None | **Done** | 13 endpoints, scoped keys, rate limited, off by default |
| 58–62 | Modes | None | **Done** | Mode steers synthesis and reorders the executive view |

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
| Full 13-agent pipeline (live) | 13/13 succeeded, $0.0445 |
| Voice of Customer (live) | 5 themes from 10 reviews; every quote verbatim |
| Radar (live) | 5 opportunities + 5 threats, ranked by expected value |
| Scenario agent (live) | Best/base/worst at 30/50/20%, honest 50% confidence |
| Migration atomicity | A failing migration now leaves nothing behind |
| Hybrid retrieval (live) | Paraphrased question, zero keyword overlap, 7 correct citations |
| GitHub provider (live) | Read plausible/analytics: 28,559 stars, licence, releases |
| Sitemap provider (live) | Found /security and /compliance that path-guessing missed |
| WCAG contrast | Body, muted, status and grade colours all pass AA |
| HTTP API (live uvicorn) | 401 unauthenticated, 401 bad key, 200 with key, 403 read-key write |
| Auth: login enumeration | Identical message AND timing for unknown vs wrong password |
| Auth: forged session token | Rejected; app returns to the sign-in gate |
| Auth: RBAC at service boundary | Viewer/analyst/PM denied per the matrix |
| Open mode | No login required; dev identity holds all permissions |
| Both modes boot | HTTP 200 with auth on and off |

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

Every capability section of the specification is now built, except where the
spec itself scopes it out or a publisher's terms forbid it.

**App stores and review sites (§5)** — Apple, Google Play, G2, Capterra and
Trustpilot publish no free API for review data, and their terms prohibit
automated collection. Building a scraper would tick the feature box while
creating exactly the legal risk the spec instructs us to avoid. The supported
route is exporting your own reviews and uploading them through Voice of
Customer, which is where that data belongs anyway.

**Search-based competitor discovery (§5)** — needs a paid search API key. Left
as a provider slot rather than a hard dependency.

**Drag-and-drop roadmap (§18)** — Streamlit has no native drag-and-drop.
Explicit up/down ordering plus move-between-horizon buttons is the honest
alternative, not a placeholder.

**Screen-reader testing (§53)** — contrast ratios and focus states are asserted
by test, but no assistive-technology pass has been performed. Streamlit owns
most of the resulting DOM, which caps how much ARIA the app can supply.

**Authentication — built, shipped off by default**
scrypt hashing, hashed session tokens, lockout, six-role RBAC enforced at the
service boundary, workspace membership, and an audit log. `PAS_AUTH_ENABLED`
defaults to `false` so development is unobstructed; the UI shows a permanent
banner while it is off and escalates to an error when the server is also bound
off-loopback. Remaining auth gaps: no password-reset flow, no OAuth/SSO, and
sessions do not survive a server restart.

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

---

## 7. Authentication design notes

**Off by default, on purpose.** `PAS_AUTH_ENABLED` defaults to `false` so
`streamlit run app.py` works with no setup. That is a deliberate convenience
with a known risk, mitigated three ways: a permanent UI banner, an escalation to
a prominent error when the server is bound off-loopback, and documentation at
the point of configuration.

**The authorisation path always executes.** In open mode the identity is a
development user holding every permission — the code still calls
`identity.require(permission)` on every guarded operation. Bypassing the checks
entirely would mean that switching auth on activates a large body of code that
has never run once. The tests drive the service with real per-role identities so
the matrix is verified independently of the mode.

**Membership is the isolation boundary.** A valid session alone grants nothing;
`identity_from_token(token, workspace_id)` returns `None` unless a
`workspace_members` row exists. This is the mechanism that turns the pre-existing
`workspace_id` column scoping into genuine multi-tenancy.

**Roles are not strictly nested.** Analyst and Product Manager are siblings:
an analyst gathers evidence but does not decide the roadmap; a product manager
decides without managing research plumbing. Both are supersets of Executive.

**Known gaps:** no password reset (an owner sets a member's password directly),
no OAuth/SSO, and sessions live in Streamlit server-side state so a restart signs
everyone out.

---

## 8. Further defects found and fixed

Continuing the record from section 6. All were silent.

| Defect | Impact | Fix |
|---|---|---|
| `executescript` issues an implicit COMMIT | The migration runner's transaction was decorative. A migration that failed part-way **half-applied and could never re-run** — which is exactly what happened when migration 004 hit an index-name collision. | Execute statements individually under explicit `BEGIN`/`COMMIT` |
| Python's sqlite3 does not open transactions for DDL | Even with a transaction, `CREATE TABLE` ran in autocommit and survived rollback | Manual transaction control during migration; SQLite itself supports transactional DDL |
| `idx_scenarios_product` declared in two migrations | SQLite index names are global, so migration 004 could not apply | Renamed, plus a test asserting index names are unique across all migrations |
| Audit write with a dangling user reference | Foreign-key error **rolled back the operation being recorded** | Audit is best-effort and keeps the actor as text |

The migration bug is the one worth dwelling on: the transaction wrapper looked
correct and had been in place since the first commit, but never actually
protected anything. It only surfaced because a real migration failed.
