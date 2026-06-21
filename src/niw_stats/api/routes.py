"""API routes. All stats endpoints filter by post date and honour hide_unknown."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from niw_stats.api.deps import Ctx, cached_json, get_ctx, resolve_window
from niw_stats.db import connection
from niw_stats.stats import aggregate as agg
from niw_stats.stats import snapshot as snap

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/meta")
def meta(request: Request, run: str | None = None, ctx: Ctx = Depends(get_ctx)):
    payload = {**ctx.meta_payload(run), "metrics": agg.METRICS}
    return cached_json(request, ctx.data_version, payload)


def _window(ctx: Ctx, run, range_key, start, end):
    s, e = resolve_window(ctx, range_key, start, end)
    return agg.filter_by_range(ctx.records_for(run), s, e), (s, e)


@router.get("/stats/summary")
def summary(
    request: Request,
    run: str | None = None,
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ctx: Ctx = Depends(get_ctx),
):
    records, (s, e) = _window(ctx, run, range, start, end)
    payload = {"window": {"start": s, "end": e}, **agg.summary(records)}
    return cached_json(request, ctx.data_version, payload)


@router.get("/stats/distribution")
def distribution(
    request: Request,
    metric: str,
    run: str | None = None,
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    hide_unknown: bool = False,
    ctx: Ctx = Depends(get_ctx),
):
    if metric not in agg.METRICS:
        raise HTTPException(status_code=422, detail=f"unknown metric {metric!r}; valid: {agg.METRICS}")
    records, _ = _window(ctx, run, range, start, end)
    return cached_json(request, ctx.data_version, agg.distribution(records, metric, hide_unknown))


@router.get("/stats/approval-rate-by")
def approval_rate_by(
    request: Request,
    group: str,
    run: str | None = None,
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    hide_unknown: bool = False,
    ctx: Ctx = Depends(get_ctx),
):
    valid = ("degree", "field", "law_firm", "citation_bucket", "premium", "rfe")
    if group not in valid:
        raise HTTPException(status_code=422, detail=f"unknown group {group!r}; valid: {list(valid)}")
    records, _ = _window(ctx, run, range, start, end)
    return cached_json(request, ctx.data_version, agg.approval_rate_by_group(records, group, hide_unknown))


@router.get("/stats/records")
def records_endpoint(
    request: Request,
    run: str | None = None,
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 1000,
    ctx: Ctx = Depends(get_ctx),
):
    records, _ = _window(ctx, run, range, start, end)
    payload = {
        "data_version": ctx.data_version,
        "count": len(records),
        "records": [agg.to_slim(r) for r in records[:limit]],
    }
    return cached_json(request, ctx.data_version, payload)


@router.get("/snapshot")
def snapshot_endpoint(request: Request, ctx: Ctx = Depends(get_ctx)):
    """The same payload the static snapshot.json carries — for the client-side path.

    Carries all versioned runs' ok records (each tagged with ``prompt_version``,
    ``schema_version``, and ``run``) so the client can switch prompt/schema and model
    offline.
    """
    conn = connection.connect(ctx.settings.db_path)
    try:
        payload = snap.build_snapshot(conn, ctx.settings, generated_at=ctx.now)
    finally:
        conn.close()
    return cached_json(request, payload["data_version"], payload)
