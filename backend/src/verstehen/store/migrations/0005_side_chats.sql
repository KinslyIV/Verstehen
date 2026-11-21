CREATE TABLE side_threads (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    anchor TEXT NOT NULL CHECK (json_valid(anchor)),
    created_at TEXT NOT NULL
);
CREATE INDEX side_threads_by_session ON side_threads(session_id, created_at);

CREATE TABLE side_exchanges (
    id TEXT NOT NULL,
    thread_id TEXT NOT NULL REFERENCES side_threads(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    quotes TEXT NOT NULL CHECK (json_valid(quotes)),
    model TEXT,
    request_id TEXT,
    stopped INTEGER NOT NULL CHECK (stopped IN (0, 1)),
    error TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, id),
    UNIQUE (thread_id, seq)
);
