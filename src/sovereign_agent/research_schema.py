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

SCHEMA_29 = """
CREATE TABLE research_campaigns (
    id TEXT PRIMARY KEY,
    investigation TEXT NOT NULL REFERENCES investigations(id),
    deadline REAL NOT NULL,
    source TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'OPEN',
    calls INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    actions INTEGER NOT NULL DEFAULT 0,
    evaluations INTEGER NOT NULL DEFAULT 0,
    call_limit INTEGER NOT NULL,
    token_limit INTEGER NOT NULL,
    action_limit INTEGER NOT NULL,
    evaluation_limit INTEGER NOT NULL
);
INSERT INTO research_campaigns
SELECT 'legacy-'||id,id,deadline,'preserved original allowance','OPEN',
       calls,tokens,actions,evaluations,12,12000,24,12 FROM investigations;
ALTER TABLE research_work ADD COLUMN campaign TEXT REFERENCES research_campaigns(id);
UPDATE research_work SET campaign='legacy-'||investigation;
CREATE TABLE research_inference (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES research_work(work_id),
    campaign TEXT NOT NULL REFERENCES research_campaigns(id),
    reserved INTEGER NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'RESERVED',
    detail TEXT NOT NULL DEFAULT ''
);
INSERT INTO research_inference(id,work_id,campaign,reserved,status,detail)
SELECT e.id,w.work_id,w.campaign,json_extract(e.payload,'$.output_allowance'),
       'UNKNOWN','legacy reservation; no silent refund'
FROM events e JOIN research_work w ON w.work_id=json_extract(e.payload,'$.work')
WHERE e.kind='research.inference_reserved';
"""
