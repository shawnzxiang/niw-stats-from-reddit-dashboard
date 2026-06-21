"""Service-level ingest: dedup-by-id, candidate counting, API cursor + state, client."""

from __future__ import annotations

import httpx
import respx

from niw_stats.config import Settings
from niw_stats.db import repository as repo
from niw_stats.ingest import service
from niw_stats.ingest.arctic_client import ArcticClient


def raw(pid, ts, title="Approved!", flair=None, **over):
    d = {"id": pid, "title": title, "created_utc": ts, "selftext": "body",
         "link_flair_text": flair, "subreddit": "EB2_NIW"}
    d.update(over)
    return d


def test_ingest_is_idempotent_by_id(db):
    posts = [raw("a", 100, flair="APPROVED"), raw("b", 200, title="random discussion")]
    r1 = service.ingest_posts(db, posts, subreddit="EB2_NIW", source="dump", fetched_at=1)
    assert (r1["inserted"], r1["updated"]) == (2, 0)
    assert r1["candidates"] == 1  # only the APPROVED one

    r2 = service.ingest_posts(db, posts, subreddit="EB2_NIW", source="dump", fetched_at=2)
    assert (r2["inserted"], r2["updated"]) == (0, 2)
    assert db.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2


def test_normalize_reconstructs_permalink():
    row = service.normalize_post(raw("xyz", 5), subreddit="EB2_NIW", source="api", fetched_at=1)
    assert row["permalink"] == "/r/EB2_NIW/comments/xyz/"


def test_ingest_via_api_advances_state_and_dedups(db):
    pages = [[raw("a", 100), raw("b", 200)], [raw("b", 200), raw("c", 300)], []]
    queue = [list(pg) for pg in pages]

    class StubClient:
        def fetch_page(self, *, after, before, limit, sort):
            return queue.pop(0) if queue else []

    res = service.ingest_via_api(
        db, StubClient(), subreddit="EB2_NIW", after=0, before=10_000, fetched_at=42
    )
    assert res["total"] == 3  # b deduped by the cursor
    assert repo.get_ingest_state(db, "EB2_NIW") == 300


@respx.mock
def test_arctic_client_parses_and_retries():
    route = respx.get("https://arctic-shift.photon-reddit.com/api/posts/search")
    route.side_effect = [
        httpx.Response(429, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}),
        httpx.Response(200, json={"data": [{"id": "a", "created_utc": 1, "title": "t"}]}),
    ]
    sleeps: list[float] = []
    client = ArcticClient(
        Settings(request_rate_per_sec=1000), sleep=sleeps.append, monotonic=lambda: 0.0
    )
    out = client.fetch_page(after=0, before=10)
    assert out == [{"id": "a", "created_utc": 1, "title": "t"}]
    assert route.call_count == 2  # retried after the 429

    # request carried the expected query params
    req = route.calls[0].request
    assert req.url.params["subreddit"] == "EB2_NIW"
    assert req.url.params["sort"] == "asc"
    assert "permalink" not in req.url.params["fields"]


@respx.mock
def test_arctic_client_retries_transient_422():
    route = respx.get("https://arctic-shift.photon-reddit.com/api/posts/search")
    route.side_effect = [
        httpx.Response(422),  # Arctic Shift's transient unprocessable response
        httpx.Response(200, json={"data": [{"id": "z", "created_utc": 2, "title": "t"}]}),
    ]
    client = ArcticClient(Settings(request_rate_per_sec=1000), sleep=lambda _x: None, monotonic=lambda: 0.0)
    assert client.fetch_page(after=0, before=10) == [{"id": "z", "created_utc": 2, "title": "t"}]
    assert route.call_count == 2


@respx.mock
def test_fetch_comments_filters_to_op_via_link_id_and_author():
    route = respx.get("https://arctic-shift.photon-reddit.com/api/comments/search")
    route.return_value = httpx.Response(200, json={"data": [
        {"id": "c1", "author": "op", "body": "I'm in finance, a banker"},
        {"id": "c2", "author": "op", "body": "Regular processing"},
    ]})
    client = ArcticClient(Settings(request_rate_per_sec=1000), sleep=lambda _x: None, monotonic=lambda: 0.0)
    out = client.fetch_comments(link_id="1ejpgst", author="op")
    assert [c["body"] for c in out] == ["I'm in finance, a banker", "Regular processing"]

    req = route.calls[0].request
    assert req.url.params["link_id"] == "1ejpgst"  # bare base36 id, no t3_ prefix
    assert req.url.params["author"] == "op"
    assert req.url.params["subreddit"] == "EB2_NIW"


def test_op_comment_enricher_concatenates_and_skips_empties():
    from niw_stats.ingest.comments import make_op_comment_enricher

    class StubClient:
        def fetch_comments(self, *, link_id, limit):
            assert link_id == "p1"
            return [
                {"author": "op", "body": "I'm a banker", "parent_id": "t3_p1"},
                {"author": "op", "body": "[deleted]", "parent_id": "t3_p1"},
                {"author": "op", "body": "  ", "parent_id": "t3_p1"},
                {"author": "op", "body": "Premium", "parent_id": "t3_p1"},
                {"author": "other", "body": "noise", "parent_id": "t3_p1"},
            ]

    enrich = make_op_comment_enricher(StubClient(), Settings())
    assert enrich({"id": "p1", "author": "op"}) == "OP comment: I'm a banker\n---\nOP comment: Premium"


def test_op_comment_enricher_includes_parent_context_for_op_replies():
    from niw_stats.ingest.comments import make_op_comment_enricher

    class StubClient:
        def fetch_comments(self, *, link_id, limit):
            assert link_id == "p1"
            return [
                {"id": "c1", "author": "other", "body": "How many citations at filing?", "parent_id": "t3_p1"},
                {"id": "c2", "author": "op", "body": "91", "parent_id": "t1_c1"},
                {"id": "c3", "author": "op", "body": "Premium", "parent_id": "t3_p1"},
                {"id": "c4", "author": "op", "body": "[deleted]", "parent_id": "t3_p1"},
            ]

    enrich = make_op_comment_enricher(StubClient(), Settings())
    assert enrich({"id": "p1", "author": "op"}) == (
        "Parent comment (other): How many citations at filing?\n"
        "OP reply: 91\n---\n"
        "OP comment: Premium"
    )


def test_op_comment_enricher_handles_no_author_and_failures():
    from niw_stats.ingest.comments import make_op_comment_enricher

    class FailClient:
        def fetch_comments(self, **kw):
            raise RuntimeError("network down")

    enrich = make_op_comment_enricher(FailClient(), Settings())
    assert enrich({"id": "p1", "author": None}) == ""   # deleted-author posts: nothing to fetch
    assert enrich({"id": "p1", "author": "op"}) == ""   # a fetch failure must never block classification
