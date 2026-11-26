-- foreign_keys: off
CREATE TABLE sessions_new (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('teach', 'practice', 'chat')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    model_account TEXT,
    model_id TEXT,
    thinking_level TEXT
);

INSERT INTO sessions_new (
    id, title, kind, created_at, updated_at, model_account, model_id, thinking_level
)
SELECT id, title, kind, created_at, updated_at, model_account, model_id, thinking_level
FROM sessions;

DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;

CREATE TRIGGER delete_session_usage AFTER DELETE ON sessions
BEGIN
    DELETE FROM usage WHERE session_id = OLD.id;
END;

CREATE TABLE session_create_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
);
