-- Schema for the NIW stats pipeline.
-- Two layers: raw_posts (immutable fetch layer) and classified_records (derived).
-- Re-classification never touches raw_posts; re-fetch never touches classified_records.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. Everything fetched from Arctic Shift (API cursor or bulk dump), verbatim-ish.
CREATE TABLE IF NOT EXISTS raw_posts (
    id               TEXT PRIMARY KEY,          -- Reddit base36 id == the DEDUP KEY (unique, immutable)
    subreddit        TEXT NOT NULL,
    title            TEXT NOT NULL,
    selftext         TEXT,                       -- may be '[removed]'/'[deleted]'/''
    link_flair_text  TEXT,
    author           TEXT,
    score            INTEGER,
    num_comments     INTEGER,
    permalink        TEXT,                       -- reconstructed locally
    url              TEXT,
    created_utc      INTEGER NOT NULL,           -- unix seconds; the POST date
    fetched_at       INTEGER NOT NULL,           -- when we ingested (unix seconds)
    raw_json         TEXT NOT NULL,              -- full source blob for reprocessing
    source           TEXT,                       -- 'api' | 'dump'
    is_candidate     INTEGER NOT NULL DEFAULT 0, -- pre-filter said "send to LLM"
    prefilter_reason TEXT,
    op_comments      TEXT                        -- the OP's own comments on the post (fetched lazily)
);
CREATE INDEX IF NOT EXISTS idx_raw_created ON raw_posts(created_utc);
CREATE INDEX IF NOT EXISTS idx_raw_candidate ON raw_posts(is_candidate, created_utc);

-- 2. Extracted structured fields. One row per (post, classifier identity + content hash).
CREATE TABLE IF NOT EXISTS classified_records (
    post_id                TEXT NOT NULL REFERENCES raw_posts(id) ON DELETE CASCADE,

    -- cache / versioning key. run_key = backend/model[@effort][#label] is the RUN identity,
    -- so the same dataset classified under different models/labels yields separate rows.
    content_hash           TEXT NOT NULL,
    prompt_version         TEXT NOT NULL,
    schema_version         TEXT NOT NULL,
    run_key                TEXT NOT NULL DEFAULT '',
    classifier_backend     TEXT NOT NULL,
    classifier_model       TEXT,
    run_effort             TEXT,                  -- e.g. codex reasoning effort (part of run_key)
    run_label              TEXT,                  -- free-form run tag (part of run_key)

    -- status
    status                 TEXT NOT NULL,         -- 'ok' | 'failed' | 'excluded'
    failure_reason         TEXT,
    body_available         INTEGER NOT NULL DEFAULT 1,

    -- outcome
    outcome                TEXT,                  -- 'approved' | 'denied' | NULL

    -- categorical
    degree                 TEXT,
    field_raw              TEXT,
    field_normalized       TEXT,
    profession_raw         TEXT,
    profession_normalized  TEXT,
    law_firm_raw           TEXT,
    law_firm_normalized    TEXT,

    -- numeric: each metric is a (value, known) pair to keep null vs 0 distinct
    publications           INTEGER,
    publications_known     INTEGER NOT NULL DEFAULT 0,
    patents                INTEGER,
    patents_known          INTEGER NOT NULL DEFAULT 0,
    citations              INTEGER,
    citations_known        INTEGER NOT NULL DEFAULT 0,
    recommendation_letters INTEGER,
    recommendation_letters_known INTEGER NOT NULL DEFAULT 0,
    years_experience       REAL,
    years_experience_known INTEGER NOT NULL DEFAULT 0,

    -- timeline (processing time, premium processing, RFE)
    receipt_date           TEXT,
    decision_date          TEXT,
    processing_days        INTEGER,
    processing_days_known  INTEGER NOT NULL DEFAULT 0,
    processing_source      TEXT,
    premium_processing     INTEGER,  -- 1=Premium, 0=regular, NULL=unknown
    was_rfed               INTEGER,  -- 1=RFE'd, 0=no RFE, NULL=unknown
    rfe_date               TEXT,
    rfe_response_date      TEXT,

    -- provenance
    classified_at          INTEGER NOT NULL,
    raw_llm_output         TEXT,

    PRIMARY KEY (post_id, content_hash, prompt_version, schema_version, run_key)
);
CREATE INDEX IF NOT EXISTS idx_cls_active
    ON classified_records(prompt_version, schema_version, run_key, status);
CREATE INDEX IF NOT EXISTS idx_cls_post ON classified_records(post_id);

-- 3. Ingestion bookkeeping for incremental refresh.
CREATE TABLE IF NOT EXISTS ingest_state (
    subreddit        TEXT PRIMARY KEY,
    last_created_utc INTEGER NOT NULL,
    last_run_at      INTEGER NOT NULL
);

-- 4. Free-form key/value metadata (schema version, last refresh, etc.).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
