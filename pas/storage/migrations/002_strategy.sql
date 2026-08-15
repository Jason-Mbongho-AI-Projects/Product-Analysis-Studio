-- Strategy studios, continuous intelligence and conversation history.
--
-- Covers spec 8 (change detection), 14-17 (positioning/pricing/growth/GTM),
-- 25 (Ask), 33 (continuous intelligence) and 34 (alerts).

-- --------------------------------------------------------------------------
-- Positioning (spec 14)
-- --------------------------------------------------------------------------

CREATE TABLE positioning_studies (
    id                      TEXT PRIMARY KEY,
    analysis_id             TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    recommended_strategy    TEXT NOT NULL DEFAULT '',
    recommendation_reason   TEXT NOT NULL DEFAULT '',
    messaging_json          TEXT NOT NULL DEFAULT '{}',
    created_at              TEXT NOT NULL
);

CREATE TABLE positioning_options (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    strategy_name       TEXT NOT NULL,
    target_customer     TEXT NOT NULL DEFAULT '',
    value_proposition   TEXT NOT NULL DEFAULT '',
    differentiation     TEXT NOT NULL DEFAULT '',
    pricing_implications TEXT NOT NULL DEFAULT '',
    gtm_implications    TEXT NOT NULL DEFAULT '',
    competitive_reaction_risk TEXT NOT NULL DEFAULT '',
    fit_score           REAL NOT NULL DEFAULT 0,
    confidence          REAL NOT NULL DEFAULT 0.5,
    is_recommended      INTEGER NOT NULL DEFAULT 0,
    detail_json         TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_positioning_options ON positioning_options(analysis_id, fit_score DESC);

-- --------------------------------------------------------------------------
-- Pricing (spec 15)
-- --------------------------------------------------------------------------

CREATE TABLE pricing_studies (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    current_assessment  TEXT NOT NULL DEFAULT '',
    recommended_model   TEXT NOT NULL DEFAULT 'subscription',
    value_metric        TEXT NOT NULL DEFAULT '',
    rationale           TEXT NOT NULL DEFAULT '',
    pricing_power       TEXT NOT NULL DEFAULT '',
    risks_json          TEXT NOT NULL DEFAULT '[]',
    assumptions_json    TEXT NOT NULL DEFAULT '[]',
    economics_json      TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL
);

CREATE TABLE pricing_tiers (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    price_monthly_usd   REAL NOT NULL DEFAULT 0,
    target_segment      TEXT NOT NULL DEFAULT '',
    limits              TEXT NOT NULL DEFAULT '',
    rationale           TEXT NOT NULL DEFAULT '',
    capabilities_json   TEXT NOT NULL DEFAULT '[]',
    position            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_pricing_tiers ON pricing_tiers(analysis_id, position);

CREATE TABLE competitor_pricing (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    competitor          TEXT NOT NULL,
    plan_name           TEXT NOT NULL DEFAULT '',
    -- -1 means "genuinely unknown"; storing a guess here would be worse than null.
    price_monthly_usd   REAL NOT NULL DEFAULT -1,
    pricing_model       TEXT NOT NULL DEFAULT 'subscription',
    notes               TEXT NOT NULL DEFAULT '',
    grade               TEXT NOT NULL DEFAULT 'ai_hypothesis',
    confidence          REAL NOT NULL DEFAULT 0.5
);
CREATE INDEX idx_competitor_pricing ON competitor_pricing(analysis_id);

-- User-run simulations are saved so a scenario can be revisited (spec 20).
CREATE TABLE pricing_scenarios (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    analysis_id         TEXT REFERENCES analyses(id) ON DELETE SET NULL,
    label               TEXT NOT NULL DEFAULT '',
    inputs_json         TEXT NOT NULL DEFAULT '{}',
    results_json        TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_scenarios_product ON pricing_scenarios(product_id, created_at DESC);

-- --------------------------------------------------------------------------
-- Growth (spec 16)
-- --------------------------------------------------------------------------

CREATE TABLE growth_strategies (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    primary_motion      TEXT NOT NULL DEFAULT '',
    motion_rationale    TEXT NOT NULL DEFAULT '',
    sequencing_json     TEXT NOT NULL DEFAULT '[]',
    avoid_json          TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL
);

CREATE TABLE growth_channels (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    channel             TEXT NOT NULL,
    fit_score           REAL NOT NULL DEFAULT 0,
    why_appropriate     TEXT NOT NULL DEFAULT '',
    expected_cac        TEXT NOT NULL DEFAULT '',
    time_to_traction    TEXT NOT NULL DEFAULT '',
    scalability         TEXT NOT NULL DEFAULT '',
    effort              TEXT NOT NULL DEFAULT 'm',
    first_experiment    TEXT NOT NULL DEFAULT '',
    evidence_json       TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.5,
    priority            INTEGER NOT NULL DEFAULT 99
);
CREATE INDEX idx_growth_channels ON growth_channels(analysis_id, priority);

-- --------------------------------------------------------------------------
-- Go-to-market (spec 17)
-- --------------------------------------------------------------------------

CREATE TABLE gtm_plans (
    id                  TEXT PRIMARY KEY,
    analysis_id         TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    target_segment      TEXT NOT NULL DEFAULT '',
    beachhead_rationale TEXT NOT NULL DEFAULT '',
    positioning_summary TEXT NOT NULL DEFAULT '',
    messaging_summary   TEXT NOT NULL DEFAULT '',
    pricing_summary     TEXT NOT NULL DEFAULT '',
    channel_strategy    TEXT NOT NULL DEFAULT '',
    sales_strategy      TEXT NOT NULL DEFAULT '',
    launch_strategy     TEXT NOT NULL DEFAULT '',
    content_strategy    TEXT NOT NULL DEFAULT '',
    partnership_strategy TEXT NOT NULL DEFAULT '',
    metrics_json        TEXT NOT NULL DEFAULT '[]',
    budget_json         TEXT NOT NULL DEFAULT '[]',
    risks_json          TEXT NOT NULL DEFAULT '[]',
    experiments_json    TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL
);

CREATE TABLE gtm_phases (
    id              TEXT PRIMARY KEY,
    analysis_id     TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    horizon         TEXT NOT NULL,
    owner_role      TEXT NOT NULL DEFAULT '',
    objectives_json TEXT NOT NULL DEFAULT '[]',
    activities_json TEXT NOT NULL DEFAULT '[]',
    milestones_json TEXT NOT NULL DEFAULT '[]',
    position        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_gtm_phases ON gtm_phases(analysis_id, position);

-- --------------------------------------------------------------------------
-- Continuous intelligence (spec 8 / 33 / 34)
-- --------------------------------------------------------------------------

-- Point-in-time capture of a monitored URL. Change detection diffs the newest
-- snapshot against the previous one for the same source.
CREATE TABLE competitor_snapshots (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    competitor_id   TEXT REFERENCES competitors(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    content_hash    TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    captured_at     TEXT NOT NULL
);
CREATE INDEX idx_snapshots_lookup ON competitor_snapshots(product_id, url, captured_at DESC);

CREATE TABLE competitor_changes (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    competitor_id       TEXT REFERENCES competitors(id) ON DELETE SET NULL,
    snapshot_id         TEXT REFERENCES competitor_snapshots(id) ON DELETE SET NULL,
    change_type         TEXT NOT NULL DEFAULT 'other',
    summary             TEXT NOT NULL,
    previous_state      TEXT NOT NULL DEFAULT '',
    current_state       TEXT NOT NULL DEFAULT '',
    evidence            TEXT NOT NULL DEFAULT '',
    estimated_impact    TEXT NOT NULL DEFAULT '',
    recommended_action  TEXT NOT NULL DEFAULT '',
    severity            TEXT NOT NULL DEFAULT 'low',
    confidence          REAL NOT NULL DEFAULT 0.5,
    source_url          TEXT,
    detected_at         TEXT NOT NULL
);
CREATE INDEX idx_changes_product ON competitor_changes(product_id, detected_at DESC);

CREATE TABLE alerts (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    category        TEXT NOT NULL DEFAULT 'competitor',
    severity        TEXT NOT NULL DEFAULT 'low',
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    change_id       TEXT REFERENCES competitor_changes(id) ON DELETE CASCADE,
    source_url      TEXT,
    status          TEXT NOT NULL DEFAULT 'unread',
    snoozed_until   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_alerts_product ON alerts(product_id, status, created_at DESC);

CREATE TABLE monitoring_jobs (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    label               TEXT NOT NULL DEFAULT '',
    urls_json           TEXT NOT NULL DEFAULT '[]',
    interval_hours      INTEGER NOT NULL DEFAULT 168,
    enabled             INTEGER NOT NULL DEFAULT 1,
    last_run_at         TEXT,
    last_status         TEXT NOT NULL DEFAULT '',
    last_error          TEXT,
    changes_found       INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_monitoring_product ON monitoring_jobs(product_id, enabled);

-- --------------------------------------------------------------------------
-- Ask Product Analysis Studio (spec 25)
-- --------------------------------------------------------------------------

CREATE TABLE conversations (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    analysis_id     TEXT REFERENCES analyses(id) ON DELETE SET NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 0.5,
    caveats_json    TEXT NOT NULL DEFAULT '[]',
    citations_json  TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_conversations ON conversations(product_id, created_at DESC);
