"""`niw` command-line interface: ingest, classify, snapshot, serve."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import typer

from niw_stats.config import Settings, get_settings

app = typer.Typer(add_completion=False, help="Pull, classify, and visualize r/EB2_NIW data points.")


def _settings(
    backend: str | None = None, workers: int | None = None, label: str | None = None
) -> Settings:
    s = get_settings()
    updates: dict = {}
    if backend:
        updates["classifier_backend"] = backend
    if workers:
        updates["classify_workers"] = workers
    if label is not None:
        updates["run_label"] = label
    return s.model_copy(update=updates) if updates else s


def _classify_config(s: Settings, limit: int | None) -> dict:
    from niw_stats.classify.prompt import PROMPT_VERSION, SCHEMA_VERSION
    from niw_stats.classify.service import settings_run_key

    if s.classifier_backend == "claude-cli":
        model = s.claude_model
    elif s.classifier_backend == "codex-cli":
        model = f"{s.codex_model or 'codex'} ({s.codex_reasoning_effort})"
    else:
        model = "—"
    uses_llm = s.classifier_backend != "mock"
    return {
        "run": settings_run_key(s),
        "model": model,
        "workers": s.classify_workers,
        "limit": limit if limit else "all remaining",
        "OP comments": "on" if (uses_llm and s.fetch_op_comments) else "off",
        "version": f"{PROMPT_VERSION}/{SCHEMA_VERSION}",
        "database": str(s.db_path),
    }


def _run_classify(conn, s: Settings, limit: int | None) -> dict:
    """Run classification with a live in-place progress display (rich on a TTY)."""
    from niw_stats.classify import service
    from niw_stats.classify.reporter import ProgressReporter

    reporter = ProgressReporter(_classify_config(s, limit))

    # Feed the OP's own comments to the LLM (skip for the offline mock backend).
    client = None
    enricher = None
    if s.fetch_op_comments and s.classifier_backend != "mock":
        from niw_stats.ingest.arctic_client import ArcticClient
        from niw_stats.ingest.comments import make_op_comment_enricher

        client = ArcticClient(s)
        enricher = make_op_comment_enricher(client, s)

    def go() -> dict:
        return service.classify_pending(
            conn, settings=s, limit=limit, enricher=enricher,
            on_start=reporter.on_start, progress=reporter.on_progress, on_wait=reporter.on_wait,
        )

    try:
        if reporter.interactive:
            from rich.console import Console
            from rich.live import Live

            with Live(reporter, console=Console(stderr=True), refresh_per_second=8):
                return go()
        return go()
    finally:
        if client is not None:
            client.close()


def _echo(title: str, data: dict) -> None:
    typer.echo(title)
    for k, v in data.items():
        typer.echo(f"  {k:<16} {v}")


def _fmt_utc(epoch: int | None) -> str:
    if epoch is None:
        return "—"
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _warn_if_partial(counts: dict) -> None:
    if counts.get("is_partial"):
        processed = counts.get("active_processed_count", 0)
        candidates = counts.get("candidate_count", 0)
        pending = counts.get("active_pending_count", 0)
        typer.echo(
            f"WARNING: Active dataset is partial: {processed}/{candidates} candidates processed "
            f"({pending} pending). Stats are preliminary.",
            err=True,
        )


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the database file and apply the schema."""
    from niw_stats.db import connection

    s = _settings()
    connection.init_db(s.db_path)
    typer.echo(f"Initialised {s.db_path}")


@app.command()
def backfill(
    dump: Path | None = typer.Option(None, help="Path to an Arctic Shift / Academic-Torrents dump file."),
    via_api: bool = typer.Option(False, "--via-api", help="Backfill from the API instead of a dump."),
    days: int = typer.Option(730, help="How many days back to pull (API mode)."),
    backend: str | None = typer.Option(None, help="(unused here; see `classify`)."),
) -> None:
    """First-time ~2-year backfill, from a bulk dump (default) or the API."""
    from niw_stats.db import connection
    from niw_stats.ingest import service

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        if dump and not via_api:
            res = service.backfill_from_dump(conn, dump, settings=s)
        elif via_api:
            res = service.backfill_via_api(conn, settings=s, days=days)
        else:
            raise typer.BadParameter("Provide --dump PATH or --via-api")
    finally:
        conn.close()
    _echo("Backfill complete:", res)


@app.command("load-dump")
def load_dump(path: Path) -> None:
    """Ingest a downloaded dump file into raw_posts."""
    from niw_stats.db import connection
    from niw_stats.ingest import service

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        res = service.backfill_from_dump(conn, path, settings=s)
    finally:
        conn.close()
    _echo("Loaded dump:", res)


@app.command()
def ingest() -> None:
    """Incremental API pull since the last ingested post."""
    from niw_stats.db import connection
    from niw_stats.ingest import service

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        res = service.incremental(conn, settings=s)
    finally:
        conn.close()
    _echo("Ingest complete:", res)


@app.command()
def classify(
    backend: str | None = typer.Option(None, help="claude-cli | codex-cli | mock"),
    limit: int | None = typer.Option(None, help="Max posts to classify this run."),
    workers: int | None = typer.Option(None, help="Parallel LLM calls (default 4; e.g. 6 to go faster)."),
    label: str | None = typer.Option(None, help="Free-form run tag to compare prompt/model variants."),
) -> None:
    """Classify candidate posts that aren't yet done for this RUN (resumable).

    A run is identified by (backend, model, effort, label), so re-running the same dataset
    under a different model or --label produces a separate, comparable dataset.
    """
    from niw_stats.classify.service import settings_run_key
    from niw_stats.db import connection

    s = _settings(backend, workers, label)
    conn = connection.connect(s.db_path)
    try:
        res = _run_classify(conn, s, limit)
    finally:
        conn.close()
    _echo(f"Classified (run {settings_run_key(s)}, {s.classify_workers} workers):", res)


@app.command()
def renormalize() -> None:
    """One-off: re-apply the current law-firm + profession taxonomy to all stored rows."""
    from niw_stats.db import connection
    from niw_stats.db import repository as repo

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        n = repo.renormalize_classifications(conn)
    finally:
        conn.close()
    typer.echo(f"Re-normalized {n} rows (firm + profession). Run `niw snapshot` to refresh.")


@app.command()
def runs() -> None:
    """List the classification runs present (the model picker's options)."""
    from niw_stats.classify.prompt import PROMPT_VERSION, SCHEMA_VERSION
    from niw_stats.db import connection
    from niw_stats.db import repository as repo

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        rows = repo.list_runs(conn, PROMPT_VERSION, SCHEMA_VERSION)
    finally:
        conn.close()
    if not rows:
        typer.echo("No classification runs yet.")
        return
    typer.echo(f"Runs for {PROMPT_VERSION}/{SCHEMA_VERSION} (default view: composite):")
    for r in rows:
        typer.echo(
            f"  {r['run_key']:<28} ok={r['ok']} excluded={r['excluded']} failed={r['failed']} "
            f"posts={r['posts']} latest={_fmt_utc(r['last_classified_at'])}"
        )


@app.command("clear-classifications")
def clear_classifications(
    backend: str | None = typer.Option(None, help="Delete only this backend's rows."),
    run: str | None = typer.Option(None, help="Delete only this run_key's rows (e.g. claude-cli/haiku)."),
    model: str | None = typer.Option(None, help="Delete only this model's rows."),
    all: bool = typer.Option(False, "--all", help="Delete ALL classifications (required if no filter)."),
) -> None:
    """Delete classifications (by backend/run/model) to force a fresh LLM re-run."""
    from niw_stats.db import connection
    from niw_stats.db import repository as repo

    if not any([backend, run, model, all]):
        raise typer.BadParameter("Specify --backend/--run/--model, or --all to clear everything.")
    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        n = repo.clear_classifications(conn, backend=backend, run_key=run, model=model)
    finally:
        conn.close()
    flt = run or model or backend or "ALL"
    typer.echo(f"Cleared {n} '{flt}' classification rows. Re-run `classify`/`refresh` to repopulate.")


@app.command()
def snapshot(
    out: Path | None = typer.Option(None, help="Output path (default: settings.snapshot_path)."),
) -> None:
    """Write the static snapshot.json the dashboard reads."""
    from niw_stats.db import connection
    from niw_stats.stats import snapshot as snap

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        res = snap.write_snapshot(conn, s, generated_at=int(time.time()), path=out)
    finally:
        conn.close()
    _echo("Snapshot written:", res)


@app.command()
def status() -> None:
    """Show active dataset provenance and classification progress."""
    from niw_stats.classify.service import COMPOSITE, active_identity
    from niw_stats.db import connection
    from niw_stats.db import repository as repo

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        pv, sv, view_run = active_identity(s, conn)
        counts = repo.counts(conn, pv, sv, None if view_run == COMPOSITE else view_run)
        runs = repo.list_runs(conn, pv, sv)
        last_refresh = repo.get_meta(conn, "last_refresh")
    finally:
        conn.close()

    _echo("NIW status:", {
        "database": s.db_path,
        "snapshot": s.snapshot_path,
        "view": f"{view_run} {pv}/{sv}",
        "runs": ", ".join(r["run_key"] for r in runs) or "—",
        "raw_posts": counts["post_count"],
        "candidates": counts["candidate_count"],
        "processed": counts["active_processed_count"],
        "pending": counts["active_pending_count"],
        "completion": (
            "—" if counts["active_completion_rate"] is None
            else f"{counts['active_completion_rate']:.1%}"
        ),
        "partial": counts["is_partial"],
        "ok": counts["classified_count"],
        "excluded": counts["excluded_count"],
        "failed": counts["failed_count"],
        "latest_classify": _fmt_utc(counts["max_classified_at"]),
        "last_refresh": last_refresh or "—",
    })


@app.command()
def refresh(
    backend: str | None = typer.Option(None, help="Classifier backend for this run."),
    limit: int | None = typer.Option(None, help="Max posts to classify this run (resumable)."),
    workers: int | None = typer.Option(None, help="Parallel LLM calls (default 4; e.g. 6 to go faster)."),
    label: str | None = typer.Option(None, help="Free-form run tag to compare prompt/model variants."),
) -> None:
    """Incremental ingest + classify + snapshot (idempotent; the daily driver).

    On an empty database the ingest step performs a full ~2-year backfill.
    """
    from niw_stats.db import connection
    from niw_stats.db import repository as repo
    from niw_stats.ingest import service as ingest_service
    from niw_stats.stats import snapshot as snap

    s = _settings(backend, workers, label)
    conn = connection.connect(s.db_path)
    try:
        typer.echo("Pulling new posts from Arctic Shift…")
        ing = ingest_service.incremental(conn, settings=s)
        cls = _run_classify(conn, s, limit)
        repo.set_meta(conn, "last_refresh", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        snp = snap.write_snapshot(conn, s, generated_at=int(time.time()))
    finally:
        conn.close()
    _echo("Ingest:", ing)
    _echo("Classify:", cls)
    _echo("Snapshot:", snp)


@app.command()
def stats(
    range: str = typer.Option("12m", help="3m | 6m | 12m | 24m"),
    run: str | None = typer.Option(None, help="View a specific run_key instead of the composite."),
) -> None:
    """Print a quick terminal summary for a time range (composite view by default)."""
    from niw_stats.classify import service
    from niw_stats.classify.service import COMPOSITE
    from niw_stats.db import connection
    from niw_stats.db import repository as repo
    from niw_stats.stats import aggregate as agg

    s = _settings()
    conn = connection.connect(s.db_path)
    try:
        view_run, records, _all = service.load_view_records(conn, s, run)
        counts = repo.counts(
            conn, service.PROMPT_VERSION, service.SCHEMA_VERSION,
            None if view_run == COMPOSITE else view_run,
        )
    finally:
        conn.close()
    _warn_if_partial(counts)
    start, end = agg.window_from_range(range, int(time.time()))
    windowed = agg.filter_by_range(records, start, end)
    _echo(f"Corpus (view: {view_run}):", counts)
    _echo(f"Summary ({range}):", agg.summary(windowed))
    deg = agg.distribution(windowed, "degree")
    _echo("Degrees:", {b["label"]: b["count"] for b in deg["buckets"]})


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
) -> None:
    """Serve the API + built dashboard locally."""
    import uvicorn

    from niw_stats.api.app import create_app

    uvicorn.run(create_app(_settings()), host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
