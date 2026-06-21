"""API endpoints over a seeded temp DB (mock-classified)."""

from __future__ import annotations

import time

import pytest
from conftest import make_raw
from fastapi.testclient import TestClient

from niw_stats.api.app import create_app
from niw_stats.classify import service
from niw_stats.config import Settings
from niw_stats.db import connection
from niw_stats.db import repository as repo

DAY = 86_400
NOW = int(time.time())


@pytest.fixture
def client(tmp_path):
    dbp = tmp_path / "api.db"
    conn = connection.connect(dbp)
    repo.upsert_raw_posts(conn, [
        make_raw("p1", is_candidate=1, created_utc=NOW - 10 * DAY, title="NIW approved",
                 selftext="Approved! NIW PhD machine learning, 0 citations, 3 publications, approved in 90 days, DIY."),
        make_raw("p2", is_candidate=1, created_utc=NOW - 100 * DAY, title="NIW denied",
                 selftext="Denied. NIW masters degree, 50 citations."),
        make_raw("p3", is_candidate=1, created_utc=NOW - 800 * DAY, title="NIW approved",
                 selftext="Approved! NIW PhD biology."),
        make_raw("p4", is_candidate=1, created_utc=NOW - 5 * DAY, title="Update",
                 selftext="My I-485 was approved, EAD in hand.", link_flair_text="APPROVED"),
    ])
    settings = Settings(db_path=dbp, classifier_backend="mock")
    service.classify_pending(conn, settings=settings, now=1)
    repo.set_meta(conn, "last_refresh", "2026-06-14T08:00:00Z")
    conn.close()
    return TestClient(create_app(settings))


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["post_count"] == 4
    assert m["classified_count"] == 3      # p1,p2,p3 ok
    assert m["excluded_count"] == 1        # p4 (485)
    assert m["last_refresh"].startswith("2026-06-14")
    assert "data_version" in m and "degree" in m["metrics"]


def test_summary_no_range(client):
    s = client.get("/api/stats/summary").json()
    assert (s["approved"], s["denied"], s["total_decided"]) == (2, 1, 3)
    assert abs(s["rate"] - 2 / 3) < 1e-9


def test_summary_range_filters_by_post_date(client):
    assert client.get("/api/stats/summary", params={"range": "3m"}).json()["total_decided"] == 1   # only p1
    assert client.get("/api/stats/summary", params={"range": "24m"}).json()["total_decided"] == 2  # p1,p2 (p3 too old)


def test_distribution_degree(client):
    d = client.get("/api/stats/distribution", params={"metric": "degree"}).json()
    by = {b["label"]: b["count"] for b in d["buckets"]}
    assert by["PhD"] == 2 and by["Masters"] == 1


def test_distribution_hide_unknown_keeps_explicit_zero(client):
    shown = client.get("/api/stats/distribution", params={"metric": "citations"}).json()
    by = {b["label"]: b["count"] for b in shown["buckets"]}
    assert by["0"] == 1                        # p1 explicit zero
    assert shown["unknown_count"] == 1         # p3 not mentioned

    hidden = client.get("/api/stats/distribution",
                        params={"metric": "citations", "hide_unknown": "true"}).json()
    assert all(b["label"] != "Unknown" for b in hidden["buckets"])
    assert hidden["n"] == 2


def test_distribution_bad_metric(client):
    assert client.get("/api/stats/distribution", params={"metric": "nope"}).status_code == 422


def test_approval_rate_by_group(client):
    g = client.get("/api/stats/approval-rate-by", params={"group": "degree"}).json()
    labels = {row["label"] for row in g["groups"]}
    assert "PhD" in labels and "Masters" in labels
    assert client.get("/api/stats/approval-rate-by", params={"group": "bad"}).status_code == 422


def test_records_endpoint(client):
    r = client.get("/api/stats/records").json()
    assert r["count"] == 3
    assert r["records"][0]["publications"] in ([3, True], [None, False], [0, True], [50, True])


def test_etag_304(client):
    first = client.get("/api/meta")
    etag = first.headers["etag"]
    assert "Cache-Control" in first.headers
    second = client.get("/api/meta", headers={"If-None-Match": etag})
    assert second.status_code == 304
