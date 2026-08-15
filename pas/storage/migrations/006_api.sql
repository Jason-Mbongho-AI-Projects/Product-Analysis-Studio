-- Public API keys (spec 57) and their usage.

CREATE TABLE api_keys (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
    name            TEXT NOT NULL DEFAULT '',
    -- Only a hash is stored. The key itself is shown once at creation and is
    -- unrecoverable afterwards.
    key_hash        TEXT NOT NULL UNIQUE,
    -- First characters of the key, so a user can tell their keys apart in a
    -- list without the full secret being retrievable.
    key_prefix      TEXT NOT NULL DEFAULT '',
    scopes          TEXT NOT NULL DEFAULT 'read',
    rate_per_minute INTEGER NOT NULL DEFAULT 60,
    revoked         INTEGER NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    request_count   INTEGER NOT NULL DEFAULT 0,
    expires_at      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash, revoked);
CREATE INDEX idx_api_keys_workspace ON api_keys(workspace_id);

CREATE TABLE api_requests (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    api_key_id      TEXT REFERENCES api_keys(id) ON DELETE CASCADE,
    method          TEXT NOT NULL DEFAULT 'GET',
    path            TEXT NOT NULL DEFAULT '',
    status          INTEGER NOT NULL DEFAULT 200,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_api_requests_key ON api_requests(api_key_id, created_at DESC);
