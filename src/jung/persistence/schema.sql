PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    stage TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('intake', 'therapy')),
    plan_id TEXT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    summary TEXT NULL,
    briefing_json TEXT NULL,
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_one_open
    ON sessions((1))
    WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    selected_style TEXT NOT NULL,
    focus TEXT NOT NULL,
    themes_json TEXT NOT NULL,
    goals_json TEXT NOT NULL,
    current_progress TEXT NOT NULL,
    planned_interventions_json TEXT NOT NULL,
    revision_recommendations_json TEXT NOT NULL,
    session_briefing_json TEXT NULL,
    source_session_id TEXT NULL UNIQUE,
    supersedes_plan_id TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id),
    FOREIGN KEY (supersedes_plan_id) REFERENCES plans(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_plans_supersedes
    ON plans(supersedes_plan_id)
    WHERE supersedes_plan_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS profile (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    name TEXT NOT NULL,
    primary_language TEXT NOT NULL,
    date_of_birth TEXT NULL,
    notes TEXT NULL,
    derived_profile_json TEXT NULL,
    current_plan_id TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (current_plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE RESTRICT,
    UNIQUE (session_id, sequence)
);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('assessment', 'post_session')),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'complete', 'failed')
    ),
    source_session_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 0),
    result_json TEXT NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT NULL,
    completed_at TEXT NULL,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id),
    UNIQUE (kind, source_session_id),
    CHECK (status = 'complete' OR result_json IS NULL),
    CHECK (status != 'complete' OR result_json IS NOT NULL),
    CHECK (status = 'failed' OR error_code IS NULL),
    CHECK (status != 'failed' OR error_code IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_one_current
    ON operations((1))
    WHERE status IN ('pending', 'running', 'failed');

CREATE TABLE IF NOT EXISTS chat_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    client_message_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'complete', 'failed')),
    user_message_id TEXT NOT NULL UNIQUE,
    assistant_message_id TEXT NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (user_message_id) REFERENCES messages(id),
    FOREIGN KEY (assistant_message_id) REFERENCES messages(id),
    UNIQUE (session_id, client_message_id),
    CHECK (status = 'complete' OR assistant_message_id IS NULL),
    CHECK (status != 'complete' OR assistant_message_id IS NOT NULL),
    CHECK (status = 'failed' OR error_code IS NULL),
    CHECK (status != 'failed' OR error_code IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_turns_one_pending
    ON chat_turns((1))
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_turns_assistant_message
    ON chat_turns(assistant_message_id)
    WHERE assistant_message_id IS NOT NULL;
