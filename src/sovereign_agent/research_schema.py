"""Finite research profile records in the existing agent ledger."""

SCHEMA = """
CREATE TABLE research_profile (
    id INTEGER PRIMARY KEY CHECK(id=1),
    inference_owner TEXT NOT NULL DEFAULT '',
    inference_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE investigations (
    id TEXT PRIMARY KEY REFERENCES outcomes(id),
    revision INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'ACTIVE',
    deadline REAL NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    actions INTEGER NOT NULL DEFAULT 0,
    evaluations INTEGER NOT NULL DEFAULT 0,
    next_due REAL,
    wake TEXT NOT NULL DEFAULT 'operator objective'
);
CREATE TABLE research_revisions (
    investigation TEXT NOT NULL REFERENCES investigations(id),
    revision INTEGER NOT NULL,
    question TEXT NOT NULL,
    PRIMARY KEY(investigation,revision)
);
CREATE TABLE research_work (
    work_id TEXT PRIMARY KEY REFERENCES assistant_work(id),
    investigation TEXT NOT NULL REFERENCES investigations(id),
    revision INTEGER NOT NULL
);
CREATE TABLE research_operations (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL UNIQUE REFERENCES research_work(work_id),
    request TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'INTENT',
    submitted REAL,
    receipt TEXT,
    digest TEXT
);
CREATE TRIGGER research_revision_no_update BEFORE UPDATE ON research_revisions
BEGIN SELECT RAISE(ABORT,'research revisions are immutable'); END;
CREATE TRIGGER research_revision_no_delete BEFORE DELETE ON research_revisions
BEGIN SELECT RAISE(ABORT,'research revisions are immutable'); END;
"""
