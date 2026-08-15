-- Initial schema for Product Analysis Studio.
--
-- Design notes:
--  * Every intelligence row carries workspace_id. The product is single-user
--    today, but tenant isolation belongs in the schema from the start - adding
--    it later means rewriting every query (spec 31/42).
--  * Analyses are versioned and never overwritten, so "then vs now"
--    comparison is possible (spec 37).
--  * Structured fields are columns; only genuinely free-shaped metadata is
--    JSON, so intelligence stays queryable (spec 46).

CREATE TABLE workspaces (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE products (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    one_liner       TEXT NOT NULL DEFAULT '',
    intake_kind     TEXT NOT NULL,
    intake_input    TEXT NOT NULL DEFAULT '',
    source_url      TEXT,
    category        TEXT NOT NULL DEFAULT '',
    subcategory     TEXT NOT NULL DEFAULT '',
    industry        TEXT NOT NULL DEFAULT '',
    business_model  TEXT NOT NULL DEFAULT 'other',
    market_segment  TEXT NOT NULL DEFAULT 'b2b',
    maturity        TEXT NOT NULL DEFAULT 'idea',
    revenue_model   TEXT NOT NULL DEFAULT '',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX idx_products_workspace ON products(workspace_id, created_at DESC);

CREATE TABLE analyses (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'founder',
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        REAL NOT NULL DEFAULT 0.0,
    stage           TEXT NOT NULL DEFAULT '',
    error           TEXT,
    research_enabled INTEGER NOT NULL DEFAULT 1,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    UNIQUE (product_id, version)
);
CREATE INDEX idx_analyses_product ON analyses(product_id, version DESC);
CREATE INDEX idx_analyses_workspace ON analyses(workspace_id, started_at DESC);

-- Source library (spec 36).
CREATE TABLE sources (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_id     TEXT REFERENCES analyses(id) ON DELETE CASCADE,
    url             TEXT,
    title           TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT 'other',
    published_date  TEXT,
    fetched_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    reliability     REAL NOT NULL DEFAULT 0.5,
    content_hash    TEXT,
    excerpt         TEXT NOT NULL DEFAULT '',
    failure_reason  TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_sources_analysis ON sources(analysis_id);
CREATE INDEX idx_sources_url ON sources(workspace_id, url);

-- The evidence spine: claim -> evidence -> source -> confidence -> date.
CREATE TABLE evidence (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    claim           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    grade           TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0.5,
    agent           TEXT NOT NULL DEFAULT '',
    subject_type    TEXT NOT NULL DEFAULT '',
    subject_id      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_evidence_analysis ON evidence(analysis_id, grade);
CREATE INDEX idx_evidence_subject ON evidence(subject_type, subject_id);

CREATE TABLE evidence_sources (
    evidence_id     TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    source_id       TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (evidence_id, source_id)
);

-- Product intelligence profile (spec 2).
CREATE TABLE product_profiles (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    summary             TEXT NOT NULL DEFAULT '',
    primary_problem     TEXT NOT NULL DEFAULT '',
    pricing_model       TEXT NOT NULL DEFAULT '',
    distribution_model  TEXT NOT NULL DEFAULT '',
    switching_costs     TEXT NOT NULL DEFAULT '',
    defensibility       TEXT NOT NULL DEFAULT '',
    lists_json          TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL
);

CREATE TABLE product_features (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    grade           TEXT NOT NULL DEFAULT 'ai_hypothesis'
);
CREATE INDEX idx_features_analysis ON product_features(analysis_id);

-- Transparent scoring (spec 3).
CREATE TABLE product_scores (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL,
    score           REAL NOT NULL,
    weight          REAL NOT NULL,
    inverted        INTEGER NOT NULL DEFAULT 0,
    explanation     TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 0.5,
    assumptions_json TEXT NOT NULL DEFAULT '[]',
    evidence_json   TEXT NOT NULL DEFAULT '[]',
    calculated_at   TEXT NOT NULL,
    UNIQUE (analysis_id, dimension)
);

CREATE TABLE competitors (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    company         TEXT NOT NULL DEFAULT '',
    website         TEXT,
    competitor_type TEXT NOT NULL DEFAULT 'direct',
    positioning     TEXT NOT NULL DEFAULT '',
    target_customer TEXT NOT NULL DEFAULT '',
    pricing_summary TEXT NOT NULL DEFAULT '',
    threat_level    TEXT NOT NULL DEFAULT 'medium',
    rationale       TEXT NOT NULL DEFAULT '',
    grade           TEXT NOT NULL DEFAULT 'ai_hypothesis',
    confidence      REAL NOT NULL DEFAULT 0.5,
    strengths_json  TEXT NOT NULL DEFAULT '[]',
    weaknesses_json TEXT NOT NULL DEFAULT '[]',
    is_user_added   INTEGER NOT NULL DEFAULT 0,
    pinned          INTEGER NOT NULL DEFAULT 0,
    position        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_competitors_analysis ON competitors(analysis_id, position);

CREATE TABLE competitor_features (
    id              TEXT PRIMARY KEY,
    competitor_id   TEXT NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    name            TEXT NOT NULL
);
CREATE INDEX idx_cfeatures_competitor ON competitor_features(competitor_id);

CREATE TABLE market_analyses (
    id                      TEXT PRIMARY KEY,
    analysis_id             TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    market_definition       TEXT NOT NULL DEFAULT '',
    maturity                TEXT NOT NULL DEFAULT '',
    competitive_concentration TEXT NOT NULL DEFAULT '',
    entry_barriers_json     TEXT NOT NULL DEFAULT '[]',
    adjacent_markets_json   TEXT NOT NULL DEFAULT '[]',
    created_at              TEXT NOT NULL
);

CREATE TABLE market_models (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,
    value_usd       REAL NOT NULL DEFAULT 0,
    formula         TEXT NOT NULL DEFAULT '',
    variables_json  TEXT NOT NULL DEFAULT '[]',
    assumptions_json TEXT NOT NULL DEFAULT '[]',
    basis           TEXT NOT NULL DEFAULT 'top_down',
    confidence      REAL NOT NULL DEFAULT 0.4,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_market_models_analysis ON market_models(analysis_id);

CREATE TABLE personas (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    is_buyer        INTEGER NOT NULL DEFAULT 0,
    is_user         INTEGER NOT NULL DEFAULT 1,
    grade           TEXT NOT NULL DEFAULT 'ai_hypothesis',
    confidence      REAL NOT NULL DEFAULT 0.5,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_personas_analysis ON personas(analysis_id);

CREATE TABLE customer_profiles (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    icp             TEXT NOT NULL DEFAULT '',
    switching_concerns_json TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);

-- Recommendations carry their decision state inline: a recommendation and the
-- user's verdict on it are one row, which keeps the AI Product Board (spec 19)
-- a single queryable surface.
CREATE TABLE recommendations (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_id         TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    gap_category        TEXT NOT NULL DEFAULT '',
    problem             TEXT NOT NULL DEFAULT '',
    recommendation      TEXT NOT NULL DEFAULT '',
    verdict             TEXT NOT NULL DEFAULT 'should_build',
    reason              TEXT NOT NULL DEFAULT '',
    customer_impact     TEXT NOT NULL DEFAULT '',
    competitive_impact  TEXT NOT NULL DEFAULT '',
    effort              TEXT NOT NULL DEFAULT 'm',
    risk                TEXT NOT NULL DEFAULT '',
    expected_outcome    TEXT NOT NULL DEFAULT '',
    dependencies_json   TEXT NOT NULL DEFAULT '[]',
    evidence_json       TEXT NOT NULL DEFAULT '[]',
    priority            INTEGER NOT NULL DEFAULT 99,
    confidence          REAL NOT NULL DEFAULT 0.5,
    decision_state      TEXT NOT NULL DEFAULT 'pending',
    decision_note       TEXT NOT NULL DEFAULT '',
    decided_at          TEXT,
    fingerprint         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_recs_analysis ON recommendations(analysis_id, priority);
CREATE INDEX idx_recs_decision ON recommendations(product_id, decision_state);
CREATE INDEX idx_recs_fingerprint ON recommendations(product_id, fingerprint);

CREATE TABLE roadmap_items (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    recommendation_id   TEXT REFERENCES recommendations(id) ON DELETE SET NULL,
    title               TEXT NOT NULL,
    detail              TEXT NOT NULL DEFAULT '',
    horizon             TEXT NOT NULL DEFAULT 'next',
    status              TEXT NOT NULL DEFAULT 'planned',
    owner               TEXT NOT NULL DEFAULT '',
    due_date            TEXT,
    effort              TEXT NOT NULL DEFAULT 'm',
    position            INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_roadmap_product ON roadmap_items(product_id, horizon, position);

-- Strategy memory (spec 22): why the AI must not re-recommend rejected work.
CREATE TABLE strategy_memory (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    summary         TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    payload_json    TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_memory_product ON strategy_memory(product_id, kind, created_at DESC);

-- Observability (spec 43/44).
CREATE TABLE agent_runs (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    agent           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    model           TEXT NOT NULL DEFAULT '',
    attempts        INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX idx_agent_runs_analysis ON agent_runs(analysis_id, started_at);

CREATE TABLE ai_usage (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_id         TEXT REFERENCES analyses(id) ON DELETE CASCADE,
    agent_run_id        TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL NOT NULL DEFAULT 0,
    latency_ms          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_usage_analysis ON ai_usage(analysis_id);
CREATE INDEX idx_usage_created ON ai_usage(workspace_id, created_at DESC);
