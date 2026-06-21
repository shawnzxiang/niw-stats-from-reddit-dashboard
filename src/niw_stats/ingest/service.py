"""Source-agnostic ingestion: normalize -> pre-filter -> upsert by Reddit id."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from typing import Any

from niw_stats.config import Settings
from niw_stats.db import repository as repo
from niw_stats.ingest import prefilter
from niw_stats.ingest.arctic_client import ArcticClient
from niw_stats.ingest.cursor import walk_window

DAY = 86_400


def normalize_post(raw: dict, *, subreddit: str, source: str, fetched_at: int) -> dict[str, Any]:
    pid = raw.get("id")
    sub = raw.get("subreddit") or subreddit
    is_candidate, reason = prefilter.decide_candidate(raw)
    return {
        "id": pid,
        "subreddit": sub,
        "title": raw.get("title") or "",
        "selftext": raw.get("selftext"),
        "link_flair_text": raw.get("link_flair_text"),
        "author": raw.get("author"),
        "score": raw.get("score"),
        "num_comments": raw.get("num_comments"),
        "permalink": f"/r/{sub}/comments/{pid}/",
        "url": raw.get("url"),
        "created_utc": int(raw["created_utc"]),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(raw, separators=(",", ":")),
        "source": source,
        "is_candidate": 1 if is_candidate else 0,
        "prefilter_reason": reason,
    }


def _valid(raw: dict) -> bool:
    return bool(raw.get("id")) and raw.get("title") is not None and raw.get("created_utc") is not None


def ingest_posts(
    conn: sqlite3.Connection,
    raw_iter: Iterable[dict],
    *,
    subreddit: str,
    source: str,
    fetched_at: int | None = None,
    advance_state: bool = False,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Consume an iterator of raw post dicts; upsert in batches keyed by id."""
    fetched_at = int(time.time()) if fetched_at is None else fetched_at
    total = inserted = updated = candidates = 0
    max_ts: int | None = None
    batch: list[dict] = []

    def flush() -> None:
        nonlocal inserted, updated
        if batch:
            ins, upd = repo.upsert_raw_posts(conn, batch)
            inserted += ins
            updated += upd
            batch.clear()

    for raw in raw_iter:
        if not _valid(raw):
            continue
        row = normalize_post(raw, subreddit=subreddit, source=source, fetched_at=fetched_at)
        batch.append(row)
        total += 1
        candidates += row["is_candidate"]
        ts = row["created_utc"]
        max_ts = ts if max_ts is None else max(max_ts, ts)
        if len(batch) >= batch_size:
            flush()
    flush()

    if advance_state and max_ts is not None:
        prev = repo.get_ingest_state(conn, subreddit) or 0
        repo.set_ingest_state(conn, subreddit, max(prev, max_ts), fetched_at)

    return {
        "total": total,
        "inserted": inserted,
        "updated": updated,
        "candidates": candidates,
        "max_created_utc": max_ts,
    }


# --- entry points -----------------------------------------------------------

def backfill_from_dump(
    conn: sqlite3.Connection, path, *, settings: Settings, fetched_at: int | None = None
) -> dict[str, Any]:
    from niw_stats.ingest.dump_loader import iter_dump_file

    return ingest_posts(
        conn, iter_dump_file(path), subreddit=settings.subreddit, source="dump",
        fetched_at=fetched_at, advance_state=True,
    )


def ingest_via_api(
    conn: sqlite3.Connection,
    client: ArcticClient,
    *,
    subreddit: str,
    after: int,
    before: int,
    fetched_at: int | None = None,
    advance_state: bool = True,
) -> dict[str, Any]:
    def fetch_page(a: int, b: int) -> list[dict]:
        return client.fetch_page(after=a, before=b, limit=100, sort="asc")

    walk = walk_window(fetch_page, after, before)
    return ingest_posts(
        conn, walk, subreddit=subreddit, source="api", fetched_at=fetched_at,
        advance_state=advance_state,
    )


def backfill_via_api(
    conn: sqlite3.Connection, *, settings: Settings, days: int = 730, now: int | None = None
) -> dict[str, Any]:
    now = int(time.time()) if now is None else now
    with ArcticClient(settings) as client:
        return ingest_via_api(
            conn, client, subreddit=settings.subreddit, after=now - days * DAY, before=now,
            fetched_at=now,
        )


def incremental(
    conn: sqlite3.Connection, *, settings: Settings, now: int | None = None, lookback_days: int = 730
) -> dict[str, Any]:
    """Pull everything since the last ingested post (with a small safety overlap)."""
    now = int(time.time()) if now is None else now
    last = repo.get_ingest_state(conn, settings.subreddit)
    after = (last - DAY) if last else (now - lookback_days * DAY)  # 1-day overlap; dedup handles it
    with ArcticClient(settings) as client:
        return ingest_via_api(
            conn, client, subreddit=settings.subreddit, after=after, before=now, fetched_at=now,
        )
