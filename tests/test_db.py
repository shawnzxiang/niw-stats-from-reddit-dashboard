"""Repository round-trips: dedup-by-id, version tuples, and stats counts."""

from __future__ import annotations

from conftest import make_cls, make_raw

from niw_stats.db import repository as repo


def test_migration_adds_new_columns_idempotently(tmp_path):
    import sqlite3

    from niw_stats.db.connection import _migrate

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE classified_records (post_id TEXT, content_hash TEXT)")  # pre-RFE schema
    conn.commit()
    _migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(classified_records)")}
    assert {
        "premium_processing", "was_rfed", "rfe_date", "rfe_response_date",
        "profession_raw", "patents", "patents_known",
    } <= cols
    _migrate(conn)  # running again must not error or duplicate columns
    conn.close()


def test_init_creates_tables(db):
    names = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"raw_posts", "classified_records", "ingest_state", "meta"} <= names


def test_upsert_dedups_by_id_and_refreshes_mutable_fields(db):
    rows = [make_raw("a", score=1), make_raw("b", score=2)]
    assert repo.upsert_raw_posts(db, rows) == (2, 0)

    # Re-ingest the same ids (e.g. dump+API overlap): 0 new rows, mutable fields refresh.
    rows2 = [make_raw("a", score=99, created_utc=999), make_raw("b", score=2)]
    assert repo.upsert_raw_posts(db, rows2) == (0, 2)

    assert db.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2
    a = db.execute("SELECT score, created_utc FROM raw_posts WHERE id='a'").fetchone()
    assert a["score"] == 99            # mutable field updated
    assert a["created_utc"] == 1_700_000_000  # created_utc is immutable


def test_empty_upsert_is_noop(db):
    assert repo.upsert_raw_posts(db, []) == (0, 0)


def test_ingest_state_roundtrip(db):
    assert repo.get_ingest_state(db, "EB2_NIW") is None
    repo.set_ingest_state(db, "EB2_NIW", 1234, 5678)
    assert repo.get_ingest_state(db, "EB2_NIW") == 1234
    repo.set_ingest_state(db, "EB2_NIW", 2000, 6000)
    assert repo.get_ingest_state(db, "EB2_NIW") == 2000


def test_candidate_filter(db):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1), make_raw("b", is_candidate=0)])
    cands = repo.iter_candidate_posts(db)
    assert [r["id"] for r in cands] == ["a"]


def test_candidates_are_newest_first(db):
    repo.upsert_raw_posts(db, [
        make_raw("old", is_candidate=1, created_utc=100),
        make_raw("new", is_candidate=1, created_utc=300),
        make_raw("mid", is_candidate=1, created_utc=200),
    ])
    assert [r["id"] for r in repo.iter_candidate_posts(db)] == ["new", "mid", "old"]


def test_op_comments_stored_survive_reingest_and_clear(db):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1)])
    repo.set_op_comments(db, "a", "OP says: I'm a banker")
    assert repo.iter_candidate_posts(db)[0]["op_comments"] == "OP says: I'm a banker"

    # Re-ingesting the post must NOT clobber the fetched OP comments.
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1, score=99)])
    assert repo.iter_candidate_posts(db)[0]["op_comments"] == "OP says: I'm a banker"

    repo.upsert_classification(db, make_cls("a", classifier_backend="claude-cli"))
    repo.upsert_classification(db, make_cls("a", classifier_backend="mock"))
    assert repo.clear_classifications(db, backend="claude-cli") == 1
    assert db.execute("SELECT COUNT(*) FROM classified_records").fetchone()[0] == 1  # mock remains


def test_classification_versioning_and_active_records(db):
    repo.upsert_raw_posts(db, [make_raw(x, is_candidate=1) for x in ("a", "b", "c")])
    repo.upsert_classification(db, make_cls("a", status="ok", outcome="approved"))
    repo.upsert_classification(db, make_cls("b", status="excluded", outcome=None))
    repo.upsert_classification(db, make_cls("c", status="failed", outcome=None))

    keys = repo.get_classified_keys(db, "p1", "s1", "mock")
    assert keys == {("a", "h1"), ("b", "h1"), ("c", "h1")}

    active = repo.get_active_records(db, "p1", "s1", "mock")
    assert [r["post_id"] for r in active] == ["a"]
    assert active[0]["created_utc"] == 1_700_000_000  # joined from raw_posts

    # Re-classifying the same key updates in place (no new row).
    repo.upsert_classification(db, make_cls("a", status="ok", outcome="denied"))
    assert db.execute("SELECT COUNT(*) FROM classified_records").fetchone()[0] == 3
    assert repo.get_active_records(db, "p1", "s1", "mock")[0]["outcome"] == "denied"

    # Bumping schema_version creates a NEW row, leaving the old one intact.
    repo.upsert_classification(db, make_cls("a", schema_version="s2", status="ok"))
    assert db.execute("SELECT COUNT(*) FROM classified_records").fetchone()[0] == 4
    assert repo.get_classified_keys(db, "p1", "s1", "mock") == {("a", "h1"), ("b", "h1"), ("c", "h1")}


def test_counts(db):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1), make_raw("b", is_candidate=1), make_raw("c")])
    repo.upsert_classification(db, make_cls("a", status="ok"))
    repo.upsert_classification(db, make_cls("b", status="failed"))
    c = repo.counts(db, "p1", "s1", "mock")
    assert c["post_count"] == 3
    assert c["candidate_count"] == 2
    assert c["classified_count"] == 1
    assert c["failed_count"] == 1
    assert c["excluded_count"] == 0
    assert c["active_processed_count"] == 2
    assert c["active_pending_count"] == 0
    assert c["active_completion_rate"] == 1.0
    assert c["is_partial"] is False
    assert c["max_classified_at"] == 1_700_000_200
    assert c["active_status_counts"] == {"ok": 1, "excluded": 0, "failed": 1}
    assert c["min_post_utc"] == 1_700_000_000


def test_counts_reports_partial_active_dataset(db):
    repo.upsert_raw_posts(db, [
        make_raw("a", is_candidate=1),
        make_raw("b", is_candidate=1),
        make_raw("c", is_candidate=1),
    ])
    repo.upsert_classification(db, make_cls("a", status="ok"))

    c = repo.counts(db, "p1", "s1", "mock")

    assert c["active_processed_count"] == 1
    assert c["active_pending_count"] == 2
    assert c["active_completion_rate"] == 1 / 3
    assert c["is_partial"] is True
