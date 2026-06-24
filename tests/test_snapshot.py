"""Snapshot build: only active 'ok' records, stable data_version, slim shape."""

from __future__ import annotations

from conftest import make_cls, make_raw

from niw_stats.classify import service
from niw_stats.config import Settings
from niw_stats.db import repository as repo
from niw_stats.stats import snapshot

SETTINGS = Settings(classifier_backend="mock")


def test_build_snapshot_contains_only_active_ok(db):
    repo.upsert_raw_posts(db, [
        make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW, PhD."),
        make_raw("b", is_candidate=1, title="Update", selftext="My I-485 approved.", link_flair_text="APPROVED"),
    ])
    service.classify_pending(db, settings=SETTINGS, now=1)  # a -> ok, b -> excluded

    snap = snapshot.build_snapshot(db, SETTINGS, generated_at=999)
    assert len(snap["records"]) == 1
    rec = snap["records"][0]
    assert rec["outcome"] == "approved"
    assert rec["degree"] == "PhD"
    assert rec["citations"] == [None, False]  # [value, known] slim shape
    assert snap["meta"]["excluded_count"] == 1
    assert snap["meta"]["latest_post_utc"] == 1_700_000_000  # newest post date for data-freshness display


def test_data_version_is_stable_until_data_changes(db):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)

    v1 = snapshot.build_snapshot(db, SETTINGS, generated_at=1)["data_version"]
    v2 = snapshot.build_snapshot(db, SETTINGS, generated_at=2)["data_version"]  # different time
    assert v1 == v2  # generated_at must not affect the version

    repo.upsert_raw_posts(db, [make_raw("c", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=3)
    v3 = snapshot.build_snapshot(db, SETTINGS, generated_at=4)["data_version"]
    assert v3 != v1  # new data -> new version


def test_data_version_changes_when_classification_changes_without_post_count_change(db):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1)])
    repo.upsert_classification(db, make_cls(
        "a",
        prompt_version=service.PROMPT_VERSION,
        schema_version=service.SCHEMA_VERSION,
        classified_at=1,
        outcome="approved",
    ))
    v1 = snapshot.build_snapshot(db, SETTINGS, generated_at=1)["data_version"]

    repo.upsert_classification(db, make_cls(
        "a",
        prompt_version=service.PROMPT_VERSION,
        schema_version=service.SCHEMA_VERSION,
        classified_at=2,
        outcome="denied",
    ))
    v2 = snapshot.build_snapshot(db, SETTINGS, generated_at=2)["data_version"]

    assert v2 != v1


def test_snapshot_carries_older_prompt_schema_versions(db):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    repo.upsert_classification(db, make_cls(
        "a",
        prompt_version="p2",
        schema_version="s2",
        run_key="claude-cli/sonnet",
        classifier_backend="claude-cli",
        classifier_model="sonnet",
        classified_at=1,
        outcome="approved",
    ))
    repo.upsert_classification(db, make_cls(
        "a",
        prompt_version=service.PROMPT_VERSION,
        schema_version=service.SCHEMA_VERSION,
        run_key="claude-cli/haiku",
        classifier_backend="claude-cli",
        classifier_model="haiku",
        classified_at=2,
        outcome="approved",
    ))

    snap = snapshot.build_snapshot(db, SETTINGS, generated_at=1)

    versions = {v["version_key"] for v in snap["meta"]["versions"]}
    assert "p2/s2" in versions
    assert f"{service.PROMPT_VERSION}/{service.SCHEMA_VERSION}" in versions
    assert {r["prompt_version"] for r in snap["records"]} == {"p2", service.PROMPT_VERSION}
    assert any(r["run_key"] == "claude-cli/sonnet" and r["prompt_version"] == "p2"
               for r in snap["meta"]["all_runs"])


def test_public_snapshot_strips_pii_and_keeps_refile(db):
    pv, sv = service.PROMPT_VERSION, service.SCHEMA_VERSION
    repo.upsert_raw_posts(db, [
        make_raw("d1", is_candidate=1, author="bob", selftext="reach me at bob@example.com",
                 created_utc=100, permalink="/r/EB2_NIW/comments/d1/"),
        make_raw("a1", is_candidate=1, author="bob", selftext="approved on re-file!",
                 created_utc=200, permalink="/r/EB2_NIW/comments/a1/"),
    ])
    repo.upsert_classification(db, make_cls("d1", prompt_version=pv, schema_version=sv,
                                            classified_at=1, outcome="denied"))
    repo.upsert_classification(db, make_cls("a1", prompt_version=pv, schema_version=sv,
                                            classified_at=2, outcome="approved"))

    pub = snapshot.build_snapshot(db, Settings(classifier_backend="mock", public_snapshot=True),
                                  generated_at=1)
    for r in pub["records"]:  # PII gone from every record
        assert "author" not in r and "selftext" not in r and "op_comments" not in r
    denied = next(r for r in pub["records"] if r["id"] == "d1")
    assert denied["refiled"] is True  # computed server-side before the username was stripped
    assert denied["refiled_url"] == "/r/EB2_NIW/comments/a1/"

    full = snapshot.build_snapshot(db, SETTINGS, generated_at=1)  # default still carries body+author
    assert "author" in full["records"][0] and "selftext" in full["records"][0]


def test_write_snapshot_to_file(db, tmp_path):
    repo.upsert_raw_posts(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)
    out = tmp_path / "snapshot.json"
    res = snapshot.write_snapshot(db, SETTINGS, generated_at=5, path=out)
    assert out.exists()
    assert res["records"] == 1
