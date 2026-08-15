-- Voice of Customer, opportunity/threat radar, scenarios and collaboration.
-- Covers spec 11, 20, 27, 28 and the comment half of 32.

-- --------------------------------------------------------------------------
-- Voice of Customer (spec 11)
-- --------------------------------------------------------------------------

-- Raw feedback is stored per item so a cluster can be drilled into and the
-- original wording inspected - a theme without its evidence is just an opinion.
CREATE TABLE feedback_batches (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    analysis_id     TEXT REFERENCES analyses(id) ON DELETE SET NULL,
    label           TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT 'upload',
    filename        TEXT NOT NULL DEFAULT '',
    item_count      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    error           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_feedback_batches ON feedback_batches(product_id, created_at DESC);

CREATE TABLE feedback_items (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    batch_id        TEXT NOT NULL REFERENCES feedback_batches(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    -- Hash of the normalised content, so re-uploading the same export does not
    -- double-count a theme.
    content_hash    TEXT NOT NULL,
    author          TEXT NOT NULL DEFAULT '',
    rating          REAL,
    occurred_at     TEXT,
    source_type     TEXT NOT NULL DEFAULT 'upload',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_feedback_items_batch ON feedback_items(batch_id);
CREATE INDEX idx_feedback_items_product ON feedback_items(product_id);
CREATE UNIQUE INDEX idx_feedback_dedupe ON feedback_items(product_id, content_hash);

CREATE TABLE feedback_analyses (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    analysis_id         TEXT REFERENCES analyses(id) ON DELETE SET NULL,
    items_analysed      INTEGER NOT NULL DEFAULT 0,
    overall_sentiment   TEXT NOT NULL DEFAULT 'neutral',
    positive_pct        REAL NOT NULL DEFAULT 0,
    neutral_pct         REAL NOT NULL DEFAULT 0,
    negative_pct        REAL NOT NULL DEFAULT 0,
    summary             TEXT NOT NULL DEFAULT '',
    complaints_json     TEXT NOT NULL DEFAULT '[]',
    praise_json         TEXT NOT NULL DEFAULT '[]',
    unmet_needs_json    TEXT NOT NULL DEFAULT '[]',
    trends_json         TEXT NOT NULL DEFAULT '[]',
    caveats_json        TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_feedback_analyses ON feedback_analyses(product_id, created_at DESC);

CREATE TABLE feedback_clusters (
    id                  TEXT PRIMARY KEY,
    feedback_analysis_id TEXT NOT NULL REFERENCES feedback_analyses(id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    theme               TEXT NOT NULL DEFAULT 'other',
    sentiment           TEXT NOT NULL DEFAULT 'neutral',
    summary             TEXT NOT NULL DEFAULT '',
    share_pct           REAL NOT NULL DEFAULT 0,
    item_count          INTEGER NOT NULL DEFAULT 0,
    is_churn_driver     INTEGER NOT NULL DEFAULT 0,
    is_feature_request  INTEGER NOT NULL DEFAULT 0,
    severity            TEXT NOT NULL DEFAULT 'low',
    suggested_action    TEXT NOT NULL DEFAULT '',
    quotes_json         TEXT NOT NULL DEFAULT '[]',
    language_json       TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.5,
    position            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_clusters_analysis ON feedback_clusters(feedback_analysis_id, position);

-- --------------------------------------------------------------------------
-- Opportunity / threat radar (spec 27 / 28)
-- --------------------------------------------------------------------------

CREATE TABLE radar_signals (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_id         TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    signal_type         TEXT NOT NULL,
    title               TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    why_now             TEXT NOT NULL DEFAULT '',
    impact              REAL NOT NULL DEFAULT 0,
    probability         REAL NOT NULL DEFAULT 0,
    -- impact x probability / 100, stored so the radar can be ordered in SQL.
    priority_score      REAL NOT NULL DEFAULT 0,
    horizon             TEXT NOT NULL DEFAULT 'near_term',
    recommended_response TEXT NOT NULL DEFAULT '',
    evidence_json       TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.5,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_radar_analysis ON radar_signals(analysis_id, signal_type, priority_score DESC);

-- --------------------------------------------------------------------------
-- Scenario simulations (spec 20)
-- --------------------------------------------------------------------------

CREATE TABLE scenarios (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    analysis_id         TEXT REFERENCES analyses(id) ON DELETE SET NULL,
    question            TEXT NOT NULL,
    recommendation      TEXT NOT NULL DEFAULT '',
    reversibility       TEXT NOT NULL DEFAULT '',
    assumptions_json    TEXT NOT NULL DEFAULT '[]',
    outcomes_json       TEXT NOT NULL DEFAULT '[]',
    indicators_json     TEXT NOT NULL DEFAULT '[]',
    risks_json          TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.5,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_scenario_runs_product ON scenarios(product_id, created_at DESC);

-- --------------------------------------------------------------------------
-- Collaboration: comments (spec 32)
-- --------------------------------------------------------------------------

CREATE TABLE comments (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
    author_label    TEXT NOT NULL DEFAULT '',
    target_type     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    body            TEXT NOT NULL,
    resolved        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_comments_target ON comments(target_type, target_id, created_at);
CREATE INDEX idx_comments_product ON comments(product_id, created_at DESC);
