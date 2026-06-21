"""Shared test fixtures. Tests never hit the network or a real LLM."""

from __future__ import annotations

import os

# Belt-and-suspenders: force the deterministic mock classifier for the whole suite.
os.environ.setdefault("NIW_CLASSIFIER_BACKEND", "mock")

import pytest

from niw_stats.db import connection


@pytest.fixture
def db(tmp_path):
    """A fresh, schema-initialised SQLite connection backed by a temp file."""
    conn = connection.connect(tmp_path / "test.db")
    try:
        yield conn
    finally:
        conn.close()


def make_raw(post_id: str, **over):
    """Build a raw_posts row dict with sensible defaults for tests."""
    row = {
        "id": post_id,
        "subreddit": "EB2_NIW",
        "title": f"post {post_id}",
        "selftext": "body",
        "link_flair_text": None,
        "author": "alice",
        "score": 1,
        "num_comments": 0,
        "permalink": f"/r/EB2_NIW/comments/{post_id}/",
        "url": f"https://reddit.com/{post_id}",
        "created_utc": 1_700_000_000,
        "fetched_at": 1_700_000_100,
        "raw_json": "{}",
        "source": "api",
        "is_candidate": 0,
        "prefilter_reason": None,
    }
    row.update(over)
    return row


def make_cls(post_id: str, content_hash: str = "h1", **over):
    """Build a classified_records row dict with NOT-NULL defaults filled in."""
    backend = over.get("classifier_backend", "mock")
    row = {
        "post_id": post_id,
        "content_hash": content_hash,
        "prompt_version": "p1",
        "schema_version": "s1",
        "run_key": backend,  # default run identity == backend; override via over for multi-model tests
        "classifier_backend": "mock",
        "classifier_model": None,
        "run_effort": None,
        "run_label": None,
        "status": "ok",
        "failure_reason": None,
        "body_available": 1,
        "outcome": "approved",
        "degree": None,
        "field_raw": None,
        "field_normalized": None,
        "profession_raw": None,
        "law_firm_raw": None,
        "law_firm_normalized": None,
        "publications": None,
        "publications_known": 0,
        "patents": None,
        "patents_known": 0,
        "citations": None,
        "citations_known": 0,
        "recommendation_letters": None,
        "recommendation_letters_known": 0,
        "years_experience": None,
        "years_experience_known": 0,
        "receipt_date": None,
        "decision_date": None,
        "processing_days": None,
        "processing_days_known": 0,
        "processing_source": None,
        "classified_at": 1_700_000_200,
        "raw_llm_output": None,
    }
    row.update(over)
    return row
