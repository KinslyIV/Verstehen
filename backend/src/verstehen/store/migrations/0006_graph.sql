CREATE TABLE graph_nodes (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_node_links (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_chains (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_coverage (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_checkpoints (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_sources (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_source_folders (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_source_placements (id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK (json_valid(payload)));
CREATE TABLE graph_positions (id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL);
CREATE TABLE graph_revision (revision INTEGER NOT NULL);
INSERT INTO graph_revision VALUES (0);

ALTER TABLE usage RENAME TO usage_before_graph;
CREATE TABLE usage (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    account TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
INSERT INTO usage SELECT * FROM usage_before_graph;
DROP TABLE usage_before_graph;
CREATE TRIGGER delete_session_usage AFTER DELETE ON sessions
BEGIN
    DELETE FROM usage WHERE session_id = OLD.id;
END;
