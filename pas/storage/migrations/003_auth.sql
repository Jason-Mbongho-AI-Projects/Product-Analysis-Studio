-- Authentication, authorisation and audit (spec 41 / 32 / 43).
--
-- Workspace membership is what turns the existing workspace_id scoping into
-- real multi-tenancy: a user sees a workspace only if a row here says so.

CREATE TABLE users (
    id                  TEXT PRIMARY KEY,
    email               TEXT NOT NULL,
    -- Lowercased email, used for lookup and uniqueness. Storing it separately
    -- keeps the display form intact while making matching unambiguous.
    email_normalised    TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL DEFAULT '',
    password_hash       TEXT NOT NULL,
    password_salt       TEXT NOT NULL,
    -- Recorded per user so the work factor can be raised later and old hashes
    -- upgraded on next successful login without invalidating them.
    kdf                 TEXT NOT NULL DEFAULT 'scrypt',
    kdf_params          TEXT NOT NULL DEFAULT '{}',
    is_active           INTEGER NOT NULL DEFAULT 1,
    is_superuser        INTEGER NOT NULL DEFAULT 0,
    failed_attempts     INTEGER NOT NULL DEFAULT 0,
    locked_until        TEXT,
    last_login_at       TEXT,
    password_changed_at TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_users_email ON users(email_normalised);

-- Only the hash of a session token is stored, so a database leak does not hand
-- over live sessions.
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0,
    user_agent      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_sessions_token ON sessions(token_hash);
CREATE INDEX idx_sessions_user ON sessions(user_id, revoked);

CREATE TABLE workspace_members (
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'viewer',
    created_at      TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX idx_members_user ON workspace_members(user_id);

-- Who did what (spec 43). Written for state-changing actions only; reads would
-- drown the useful entries.
CREATE TABLE audit_log (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
    actor_label     TEXT NOT NULL DEFAULT '',
    action          TEXT NOT NULL,
    target_type     TEXT NOT NULL DEFAULT '',
    target_id       TEXT,
    detail          TEXT NOT NULL DEFAULT '',
    succeeded       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_audit_workspace ON audit_log(workspace_id, created_at DESC);
CREATE INDEX idx_audit_user ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_log(action, created_at DESC);
