-- Embedding cache, roadmap ordering/assignment, and activity feed.
-- Covers spec 40 and the remaining half of spec 32.

-- Embeddings are cached by content hash, so a claim is embedded once no matter
-- how many questions reference it. The hash is the natural key; a UNIQUE index
-- makes re-embedding a no-op rather than a duplicate row.
CREATE TABLE embeddings (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    model           TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    dim             INTEGER NOT NULL,
    vector          BLOB NOT NULL,
    preview         TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_embeddings_key ON embeddings(model, content_hash);
CREATE INDEX idx_embeddings_workspace ON embeddings(workspace_id);

-- Roadmap assignment (spec 32). Position already exists; these add ownership.
ALTER TABLE roadmap_items ADD COLUMN assignee_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE roadmap_items ADD COLUMN assignee_label TEXT NOT NULL DEFAULT '';

-- Mentions extracted from comment bodies, so a user can find what needs them.
CREATE TABLE mentions (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    comment_id      TEXT NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE,
    handle          TEXT NOT NULL,
    seen            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_mentions_user ON mentions(user_id, seen, created_at DESC);
