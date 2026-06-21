"""Build/write the static snapshot.json the frontend aggregates client-side.

``data_version`` deliberately excludes ``generated_at`` so it only changes when
the underlying data changes — that makes it a stable ETag for cheap caching.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from niw_stats.classify import service
from niw_stats.config import Settings
from niw_stats.db import repository as repo
from niw_stats.stats.aggregate import (
    content_fingerprint,
    mark_refiled,
    record_from_row,
    to_slim,
    to_slim_public,
)


def compute_data_version(
    pv: str,
    sv: str,
    view_run: str,
    count: int,
    max_post_utc: int | None,
    *,
    status_counts: dict[str, int] | None = None,
    max_classified_at: int | None = None,
) -> str:
    status = status_counts or {}
    raw = (
        f"{pv}|{sv}|{view_run}|{count}|{max_post_utc}|{max_classified_at}|"
        f"{status.get('ok', 0)}|{status.get('excluded', 0)}|{status.get('failed', 0)}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_multi_version_data_version(
    active: tuple[str, str, str],
    versions: list[dict[str, Any]],
    all_runs: list[dict[str, Any]],
    record_count: int,
    content_fp: str = "",
) -> str:
    """Stable hash for a snapshot that carries multiple prompt/schema versions.

    ``content_fp`` is a fingerprint of the record VALUES so re-normalization (which leaves
    counts/dates unchanged) still changes the version and busts ETag/304 caches.
    """
    raw = json.dumps(
        {
            "active": active,
            "versions": versions,
            "runs": all_runs,
            "record_count": record_count,
            "content": content_fp,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _runs_for_version(all_runs: list[dict[str, Any]], pv: str, sv: str) -> list[dict[str, Any]]:
    return [r for r in all_runs if r["prompt_version"] == pv and r["schema_version"] == sv]


def _version_payload(
    conn: sqlite3.Connection, all_runs: list[dict[str, Any]], pv: str, sv: str
) -> dict[str, Any]:
    c = repo.counts(conn, pv, sv, None)
    runs = _runs_for_version(all_runs, pv, sv)
    return {
        "prompt_version": pv,
        "schema_version": sv,
        "version_key": f"{pv}/{sv}",
        "runs": runs,
        **c,
    }


def build_snapshot(conn: sqlite3.Connection, settings: Settings, *, generated_at: int) -> dict[str, Any]:
    pv, sv, view_run = service.active_identity(settings, conn)
    # Carry every version's ok records so the client can audit older prompt/schema runs offline.
    records = [record_from_row(r) for r in repo.get_all_ok_records_all_versions(conn)]
    if settings.public_snapshot:
        # Compute re-file flags from the username BEFORE it's stripped, then PII-scrub each record.
        mark_refiled(records)
        all_records = [to_slim_public(r) for r in records]
    else:
        all_records = [to_slim(r) for r in records]
    all_runs = repo.list_runs_all_versions(conn)
    versions_seen = repo.list_versions(conn)
    versions = [
        _version_payload(conn, all_runs, v["prompt_version"], v["schema_version"])
        for v in versions_seen
    ]
    runs = repo.list_runs(conn, pv, sv)
    c = repo.counts(conn, pv, sv, None if view_run == service.COMPOSITE else view_run)
    data_version = compute_multi_version_data_version(
        (pv, sv, view_run),
        versions,
        all_runs,
        len(all_records),
        content_fp=content_fingerprint(records),
    )
    return {
        "data_version": data_version,
        "generated_at": generated_at,
        "meta": {
            **c,
            "subreddit": settings.subreddit,
            "prompt_version": pv,
            "schema_version": sv,
            "view_run": view_run,
            "runs": runs,
            "all_runs": all_runs,
            "versions": versions,
        },
        "records": all_records,
    }


def write_snapshot(
    conn: sqlite3.Connection, settings: Settings, *, generated_at: int, path: Path | None = None
) -> dict[str, Any]:
    out = Path(path) if path is not None else Path(settings.snapshot_path)
    data = build_snapshot(conn, settings, generated_at=generated_at)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return {"path": str(out), "records": len(data["records"]), "data_version": data["data_version"]}
