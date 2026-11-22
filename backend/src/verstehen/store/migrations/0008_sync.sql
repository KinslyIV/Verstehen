CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    device_id TEXT NOT NULL,
    server_url TEXT,
    last_pushed_seq INTEGER NOT NULL DEFAULT 0,
    last_pulled_seq INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'disabled' CHECK (
        status IN ('disabled', 'idle', 'syncing', 'offline', 'update_required', 'error')
    ),
    last_error TEXT,
    last_sync_at TEXT
);

INSERT INTO sync_state (id, device_id) VALUES (1, lower(hex(randomblob(16))));

CREATE TABLE sync_log (
    change_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    op TEXT NOT NULL CHECK (op IN ('upsert', 'delete')),
    entity_id TEXT NOT NULL,
    session_id TEXT,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    origin_device_id TEXT NOT NULL,
    origin_seq INTEGER NOT NULL,
    pushed INTEGER NOT NULL DEFAULT 0 CHECK (pushed IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (origin_device_id, origin_seq)
);

CREATE INDEX sync_log_by_session ON sync_log(session_id, change_seq);

CREATE TABLE sync_tombstones (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    origin_device_id TEXT NOT NULL,
    PRIMARY KEY (entity, entity_id)
);

CREATE TABLE sync_versions (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    server_seq INTEGER NOT NULL,
    PRIMARY KEY (entity, entity_id)
);

CREATE TABLE sync_prompt_state (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);

ALTER TABLE settings ADD COLUMN updated_at TEXT;
UPDATE settings SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE updated_at IS NULL;

ALTER TABLE artifact_views ADD COLUMN updated_at TEXT;
UPDATE artifact_views SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE updated_at IS NULL;

ALTER TABLE graph_positions ADD COLUMN updated_at TEXT;
UPDATE graph_positions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE updated_at IS NULL;

ALTER TABLE graph_source_placements ADD COLUMN updated_at TEXT;
UPDATE graph_source_placements SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE updated_at IS NULL;

ALTER TABLE jobs ADD COLUMN owner_device_id TEXT;
UPDATE jobs
SET owner_device_id = (SELECT device_id FROM sync_state WHERE id = 1)
WHERE owner_device_id IS NULL;

ALTER TABLE graph_nodes ADD COLUMN sync_id TEXT;
UPDATE graph_nodes SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_nodes_sync_id ON graph_nodes(sync_id);

ALTER TABLE graph_node_links ADD COLUMN sync_id TEXT;
UPDATE graph_node_links SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_node_links_sync_id ON graph_node_links(sync_id);

ALTER TABLE graph_chains ADD COLUMN sync_id TEXT;
UPDATE graph_chains SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_chains_sync_id ON graph_chains(sync_id);

ALTER TABLE graph_coverage ADD COLUMN sync_id TEXT;
UPDATE graph_coverage SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_coverage_sync_id ON graph_coverage(sync_id);

ALTER TABLE graph_checkpoints ADD COLUMN sync_id TEXT;
UPDATE graph_checkpoints SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_checkpoints_sync_id ON graph_checkpoints(sync_id);

ALTER TABLE graph_sources ADD COLUMN sync_id TEXT;
UPDATE graph_sources SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_sources_sync_id ON graph_sources(sync_id);

ALTER TABLE graph_source_folders ADD COLUMN sync_id TEXT;
UPDATE graph_source_folders SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL;
CREATE UNIQUE INDEX graph_source_folders_sync_id ON graph_source_folders(sync_id);
