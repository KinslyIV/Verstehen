CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('research', 'demo', 'visual', 'pdf')),
    tool_call_id TEXT NOT NULL,
    input TEXT NOT NULL CHECK (json_valid(input)),
    status TEXT NOT NULL CHECK (status IN ('running', 'done', 'error')),
    activity TEXT NOT NULL,
    result TEXT CHECK (result IS NULL OR json_valid(result)),
    error TEXT,
    delivery_kind TEXT CHECK (delivery_kind IN ('result', 'abort', 'failure')),
    delivery_status TEXT CHECK (delivery_status IN ('pending', 'delivered')),
    usage TEXT CHECK (usage IS NULL OR json_valid(usage)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (session_id, tool_call_id)
);

CREATE INDEX jobs_by_session ON jobs(session_id, created_at);

CREATE TABLE artifact_views (
    entry_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    inverted INTEGER NOT NULL CHECK (inverted IN (0, 1))
);
