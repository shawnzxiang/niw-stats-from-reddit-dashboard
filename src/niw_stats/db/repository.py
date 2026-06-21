"""Data-access helpers. Functions take an open :class:`sqlite3.Connection`.

The only dedup key is the Reddit post ``id`` (``raw_posts`` PRIMARY KEY); every
ingest upserts on it, so re-runs and dump/API overlap collapse to one row.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

# --- column definitions -----------------------------------------------------

RAW_COLS = [
    "id", "subreddit", "title", "selftext", "link_flair_text", "author",
    "score", "num_comments", "permalink", "url", "created_utc", "fetched_at",
    "raw_json", "source", "is_candidate", "prefilter_reason",
]
# Never overwrite these on a re-ingest of an existing post.
RAW_IMMUTABLE = {"id", "created_utc"}

CLS_COLS = [
    "post_id", "content_hash", "prompt_version", "schema_version",
    "run_key", "classifier_backend", "classifier_model", "run_effort", "run_label",
    "status", "failure_reason",
    "body_available", "outcome", "degree", "field_raw", "field_normalized",
    "profession_raw", "profession_normalized", "law_firm_raw", "law_firm_normalized",
    "publications", "publications_known", "patents", "patents_known",
    "citations", "citations_known",
    "recommendation_letters", "recommendation_letters_known",
    "years_experience", "years_experience_known",
    "receipt_date", "decision_date", "processing_days", "processing_days_known",
    "processing_source", "premium_processing", "was_rfed", "rfe_date", "rfe_response_date",
    "classified_at", "raw_llm_output",
]
CLS_PK = {
    "post_id", "content_hash", "prompt_version", "schema_version", "run_key",
}


def _upsert_sql(table: str, cols: list[str], conflict: set[str], no_update: set[str] = frozenset()) -> str:
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(
        f"{c}=excluded.{c}" for c in cols if c not in conflict and c not in no_update
    )
    return (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({','.join(sorted(conflict))}) DO UPDATE SET {updates}"
    )


_UPSERT_RAW = _upsert_sql("raw_posts", RAW_COLS, {"id"}, RAW_IMMUTABLE)
_UPSERT_CLS = _upsert_sql("classified_records", CLS_COLS, CLS_PK)


def _params(row: dict[str, Any], cols: list[str]) -> list[Any]:
    return [row.get(c) for c in cols]


def _chunks(seq: list[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# --- raw posts --------------------------------------------------------------

def upsert_raw_posts(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """Insert or update posts keyed by id. Returns ``(inserted, updated)`` unique counts."""
    rows = list(rows)
    if not rows:
        return (0, 0)
    unique_ids = list(dict.fromkeys(r["id"] for r in rows))
    existing: set[str] = set()
    for chunk in _chunks(unique_ids, 400):
        q = f"SELECT id FROM raw_posts WHERE id IN ({','.join('?' for _ in chunk)})"
        existing.update(r[0] for r in conn.execute(q, chunk))
    inserted = sum(1 for i in unique_ids if i not in existing)
    conn.executemany(_UPSERT_RAW, [_params(r, RAW_COLS) for r in rows])
    conn.commit()
    return (inserted, len(unique_ids) - inserted)


def get_ingest_state(conn: sqlite3.Connection, subreddit: str) -> int | None:
    row = conn.execute(
        "SELECT last_created_utc FROM ingest_state WHERE subreddit = ?", (subreddit,)
    ).fetchone()
    return int(row[0]) if row else None


def set_ingest_state(
    conn: sqlite3.Connection, subreddit: str, last_created_utc: int, last_run_at: int
) -> None:
    conn.execute(
        "INSERT INTO ingest_state (subreddit, last_created_utc, last_run_at) VALUES (?,?,?) "
        "ON CONFLICT(subreddit) DO UPDATE SET last_created_utc=excluded.last_created_utc, "
        "last_run_at=excluded.last_run_at",
        (subreddit, last_created_utc, last_run_at),
    )
    conn.commit()


def iter_candidate_posts(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    # Newest first, so a limited/streaming classify run handles the most recent posts first.
    q = (
        "SELECT id, title, selftext, link_flair_text, created_utc, author, op_comments "
        "FROM raw_posts WHERE is_candidate = 1 ORDER BY created_utc DESC"
    )
    if limit is not None:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


def set_op_comments(conn: sqlite3.Connection, post_id: str, text: str) -> None:
    conn.execute("UPDATE raw_posts SET op_comments = ? WHERE id = ?", (text, post_id))
    conn.commit()


def clear_classifications(
    conn: sqlite3.Connection,
    *,
    backend: str | None = None,
    run_key: str | None = None,
    model: str | None = None,
) -> int:
    """Delete classifications matching any combination of backend/run_key/model.

    With no filter, deletes ALL classifications. Used to force a fresh LLM re-run.
    """
    clauses, params = [], []
    for column, value in (
        ("classifier_backend", backend),
        ("run_key", run_key),
        ("classifier_model", model),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    n = conn.execute(f"DELETE FROM classified_records{where}", params).rowcount
    conn.commit()
    return n


def renormalize_classifications(conn: sqlite3.Connection) -> int:
    """One-off: recompute the normalized law-firm + profession buckets for every row with the
    current taxonomy, merging variants in place. Returns the rows touched."""
    from niw_stats.classify.taxonomy import normalize_law_firm, normalize_profession

    rows = conn.execute(
        "SELECT rowid AS rid, law_firm_raw, profession_raw FROM classified_records"
    ).fetchall()
    updated = 0
    for r in rows:
        firm = normalize_law_firm(r["law_firm_raw"])
        prof = normalize_profession(r["profession_raw"])
        conn.execute(
            "UPDATE classified_records SET law_firm_normalized=?, profession_normalized=? WHERE rowid=?",
            (firm, prof, r["rid"]),
        )
        updated += 1
    conn.commit()
    return updated


# --- classifications --------------------------------------------------------

def get_classified_keys(
    conn: sqlite3.Connection, prompt_version: str, schema_version: str, run_key: str
) -> set[tuple[str, str]]:
    """Set of ``(post_id, content_hash)`` already classified for this run identity."""
    rows = conn.execute(
        "SELECT post_id, content_hash FROM classified_records "
        "WHERE prompt_version=? AND schema_version=? AND run_key=?",
        (prompt_version, schema_version, run_key),
    ).fetchall()
    return {(r[0], r[1]) for r in rows}


def upsert_classification(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(_UPSERT_CLS, _params(row, CLS_COLS))
    conn.commit()


_OK_RECORDS_SELECT = (
    "SELECT r.created_utc AS created_utc, r.title AS title, r.permalink AS permalink, "
    "r.link_flair_text AS flair, r.selftext AS selftext, r.op_comments AS op_comments, "
    "r.author AS author, c.* "
    "FROM classified_records c "
    "JOIN raw_posts r ON r.id = c.post_id "
    "WHERE c.prompt_version=? AND c.schema_version=? AND c.status='ok'"
)

_ALL_OK_RECORDS_SELECT = (
    "SELECT r.created_utc AS created_utc, r.title AS title, r.permalink AS permalink, "
    "r.link_flair_text AS flair, r.selftext AS selftext, r.op_comments AS op_comments, "
    "r.author AS author, c.* "
    "FROM classified_records c "
    "JOIN raw_posts r ON r.id = c.post_id "
    "WHERE c.status='ok'"
)


def get_records_for_run(
    conn: sqlite3.Connection, prompt_version: str, schema_version: str, run_key: str
) -> list[sqlite3.Row]:
    """Status='ok' records for a single run, joined to the post's created_utc."""
    return conn.execute(
        _OK_RECORDS_SELECT + " AND c.run_key=?", (prompt_version, schema_version, run_key)
    ).fetchall()


def get_all_ok_records(
    conn: sqlite3.Connection, prompt_version: str, schema_version: str
) -> list[sqlite3.Row]:
    """Status='ok' records across EVERY run (each tagged with run_key) for composite views."""
    return conn.execute(_OK_RECORDS_SELECT, (prompt_version, schema_version)).fetchall()


def get_all_ok_records_all_versions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Status='ok' records across every prompt/schema version and every run."""
    return conn.execute(_ALL_OK_RECORDS_SELECT).fetchall()


# Back-compat alias: the single-run view used to be the only one.
def get_active_records(
    conn: sqlite3.Connection, prompt_version: str, schema_version: str, run_key: str
) -> list[sqlite3.Row]:
    return get_records_for_run(conn, prompt_version, schema_version, run_key)


def list_runs(
    conn: sqlite3.Connection, prompt_version: str, schema_version: str
) -> list[dict[str, Any]]:
    """Distinct classification runs present for this version, for the model picker."""
    rows = conn.execute(
        "SELECT run_key, "
        "MAX(classifier_backend) AS backend, MAX(classifier_model) AS model, "
        "MAX(run_effort) AS effort, MAX(run_label) AS label, "
        "SUM(status='ok') AS ok, SUM(status='excluded') AS excluded, "
        "SUM(status='failed') AS failed, COUNT(DISTINCT post_id) AS posts, "
        "MAX(classified_at) AS last_classified_at "
        "FROM classified_records WHERE prompt_version=? AND schema_version=? "
        "GROUP BY run_key ORDER BY last_classified_at DESC",
        (prompt_version, schema_version),
    ).fetchall()
    return [dict(r) for r in rows]


def list_runs_all_versions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Distinct classification runs across every prompt/schema version."""
    rows = conn.execute(
        "SELECT prompt_version, schema_version, run_key, "
        "MAX(classifier_backend) AS backend, MAX(classifier_model) AS model, "
        "MAX(run_effort) AS effort, MAX(run_label) AS label, "
        "SUM(status='ok') AS ok, SUM(status='excluded') AS excluded, "
        "SUM(status='failed') AS failed, COUNT(DISTINCT post_id) AS posts, "
        "MAX(classified_at) AS last_classified_at "
        "FROM classified_records "
        "GROUP BY prompt_version, schema_version, run_key "
        "ORDER BY last_classified_at DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def list_versions(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Prompt/schema versions with at least one classification row."""
    rows = conn.execute(
        "SELECT prompt_version, schema_version, MAX(classified_at) AS last_classified_at "
        "FROM classified_records GROUP BY prompt_version, schema_version "
        "ORDER BY last_classified_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# --- meta / counts ----------------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def counts(
    conn: sqlite3.Connection,
    prompt_version: str,
    schema_version: str,
    run_key: str | None = None,
) -> dict[str, Any]:
    """Summary counts for the /api/meta endpoint and `niw stats`.

    ``run_key=None`` gives the COMPOSITE view: a post counts once across all runs (status
    folded as ok > failed > excluded). A specific ``run_key`` gives that single run's counts.
    """
    post_count = conn.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0]
    candidate_count = conn.execute(
        "SELECT COUNT(*) FROM raw_posts WHERE is_candidate=1"
    ).fetchone()[0]
    if run_key is not None:
        by_status = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM classified_records "
                "WHERE prompt_version=? AND schema_version=? AND run_key=? GROUP BY status",
                (prompt_version, schema_version, run_key),
            ).fetchall()
        )
        ok = int(by_status.get("ok", 0))
        excluded = int(by_status.get("excluded", 0))
        failed = int(by_status.get("failed", 0))
        max_classified_at = conn.execute(
            "SELECT MAX(classified_at) FROM classified_records "
            "WHERE prompt_version=? AND schema_version=? AND run_key=?",
            (prompt_version, schema_version, run_key),
        ).fetchone()[0]
    else:
        # Composite: collapse each post to one status across all of its runs.
        per_post = conn.execute(
            "SELECT post_id, MAX(status='ok') AS has_ok, MAX(status='failed') AS has_failed "
            "FROM classified_records WHERE prompt_version=? AND schema_version=? GROUP BY post_id",
            (prompt_version, schema_version),
        ).fetchall()
        ok = sum(1 for p in per_post if p["has_ok"])
        failed = sum(1 for p in per_post if not p["has_ok"] and p["has_failed"])
        excluded = len(per_post) - ok - failed
        max_classified_at = conn.execute(
            "SELECT MAX(classified_at) FROM classified_records "
            "WHERE prompt_version=? AND schema_version=?",
            (prompt_version, schema_version),
        ).fetchone()[0]
    by_status = {"ok": ok, "excluded": excluded, "failed": failed}
    processed = ok + excluded + failed
    drange = conn.execute(
        "SELECT MIN(created_utc), MAX(created_utc) FROM raw_posts"
    ).fetchone()
    return {
        "post_count": post_count,
        "candidate_count": candidate_count,
        "classified_count": by_status.get("ok", 0),
        "failed_count": by_status.get("failed", 0),
        "excluded_count": by_status.get("excluded", 0),
        "active_processed_count": processed,
        "active_pending_count": max(candidate_count - processed, 0),
        "active_completion_rate": (processed / candidate_count) if candidate_count else None,
        "is_partial": processed < candidate_count,
        "max_classified_at": max_classified_at,
        "active_status_counts": {
            "ok": by_status.get("ok", 0),
            "excluded": by_status.get("excluded", 0),
            "failed": by_status.get("failed", 0),
        },
        "min_post_utc": drange[0],
        "max_post_utc": drange[1],
    }
