"""Request context, time-window resolution, and ETag/Cache-Control responses."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from niw_stats.classify import service
from niw_stats.config import Settings
from niw_stats.db import connection
from niw_stats.db import repository as repo
from niw_stats.stats import aggregate as agg
from niw_stats.stats.aggregate import Record, record_from_row, window_from_range

DAY = 86_400
CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=86400"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@dataclass
class Ctx:
    settings: Settings
    all_records: list[Record]   # status='ok' records across EVERY run (tagged with .run)
    runs: list[dict[str, Any]]  # the runs present, for the model picker
    default_run: str
    counts: dict[str, Any]
    last_refresh: str | None
    data_version: str
    now: int
    prompt_version: str
    schema_version: str

    def records_for(self, run: str | None) -> list[Record]:
        """Records for the requested run (defaults to the configured view: composite)."""
        return agg.select_view(self.all_records, service.resolve_view_run(self.settings, run))

    def meta_payload(self, run: str | None = None) -> dict[str, Any]:
        """Common metadata block reused by /api/meta and /api/snapshot."""
        resolved = service.resolve_view_run(self.settings, run)
        return {
            **self.counts,
            "last_refresh": self.last_refresh,
            "data_version": self.data_version,
            "subreddit": self.settings.subreddit,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "view_run": resolved,
            "runs": self.runs,
        }


def get_ctx(settings: Settings = Depends(get_settings)) -> Ctx:
    conn = connection.connect(settings.db_path)
    try:
        pv, sv, default_run = service.active_identity(settings, conn)
        all_records = [record_from_row(r) for r in repo.get_all_ok_records(conn, pv, sv)]
        runs = repo.list_runs(conn, pv, sv)
        # Composite counts back the freshness banner; per-run counts are in `runs`.
        counts = repo.counts(conn, pv, sv, None if default_run == agg.COMPOSITE else default_run)
        last_refresh = repo.get_meta(conn, "last_refresh")
        # Content-sensitive ETag: changes when any record VALUE changes (e.g. after
        # `niw renormalize`), so the browser doesn't keep a stale 304-cached response.
        data_version = agg.content_fingerprint(all_records, prefix=f"{pv}|{sv}|{default_run}")
        return Ctx(
            settings, all_records, runs, default_run, counts, last_refresh,
            data_version, int(time.time()), pv, sv,
        )
    finally:
        conn.close()


def _parse_date(value: str, *, end: bool) -> int:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad date {value!r}, expected YYYY-MM-DD") from exc
    epoch = int(dt.timestamp())
    return epoch + DAY - 1 if end else epoch  # make `end` inclusive of the whole day


def resolve_window(
    ctx: Ctx, range_key: str | None, start: str | None, end: str | None
) -> tuple[int | None, int | None]:
    if range_key:
        if range_key not in ("3m", "6m", "12m", "24m"):
            raise HTTPException(status_code=422, detail=f"bad range {range_key!r}")
        return window_from_range(range_key, ctx.now)
    s = _parse_date(start, end=False) if start else None
    e = _parse_date(end, end=True) if end else None
    return (s, e)


def cached_json(request: Request, data_version: str, payload: Any) -> Response:
    qhash = hashlib.sha1(str(request.url.query).encode()).hexdigest()[:10]
    etag = f'W/"{data_version}-{qhash}"'
    headers = {"Cache-Control": CACHE_CONTROL, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
