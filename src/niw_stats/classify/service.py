"""Classification orchestration: cache check -> backend -> map to columns -> upsert."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import date
from typing import Any

from niw_stats.classify.base import ClassificationOutcome, Classifier, content_hash
from niw_stats.classify.cli_backend import ClaudeCliBackend, CodexCliBackend
from niw_stats.classify.mock_backend import MockBackend
from niw_stats.classify.prompt import PROMPT_VERSION, SCHEMA_VERSION
from niw_stats.classify.taxonomy import normalize_field, normalize_law_firm, normalize_profession
from niw_stats.config import Settings
from niw_stats.db import repository as repo
from niw_stats.models import Timeline
from niw_stats.stats import aggregate as agg

COMPOSITE = agg.COMPOSITE


def get_classifier(settings: Settings) -> Classifier:
    backend = settings.classifier_backend
    if backend == "mock":
        return MockBackend()
    if backend == "claude-cli":
        return ClaudeCliBackend(settings)
    if backend == "codex-cli":
        return CodexCliBackend(settings)
    raise ValueError(f"unknown classifier backend: {backend!r}")


def run_identity(settings: Settings) -> tuple[str, str, str, str]:
    """The (backend, model, effort, label) that identifies a classification run."""
    backend = settings.classifier_backend
    if backend == "claude-cli":
        model, effort = settings.claude_model, ""
    elif backend == "codex-cli":
        model, effort = (settings.codex_model or "codex"), settings.codex_reasoning_effort
    else:
        model, effort = "mock", ""
    return backend, model, effort, (settings.run_label or "")


def run_key_of(backend: str, model: str, effort: str = "", label: str = "") -> str:
    """Canonical run identity string: ``backend/model[@effort][#label]``."""
    key = f"{backend}/{model}"
    if effort:
        key += f"@{effort}"
    if label:
        key += f"#{label}"
    return key


def settings_run_key(settings: Settings) -> str:
    """The run_key a classify run under these settings writes to."""
    return run_key_of(*run_identity(settings))


def resolve_view_run(settings: Settings, run: str | None = None) -> str:
    """Which run the stats/snapshot show: an explicit arg, else config, else composite."""
    return run or settings.view_run or COMPOSITE


def active_identity(
    settings: Settings, conn: sqlite3.Connection | None = None
) -> tuple[str, str, str]:
    """The (prompt_version, schema_version, view_run) the stats read from.

    ``view_run`` is ``"composite"`` by default (vote across all runs) or a specific run_key.
    """
    return (PROMPT_VERSION, SCHEMA_VERSION, resolve_view_run(settings))


def load_view_records(
    conn: sqlite3.Connection, settings: Settings, run: str | None = None
) -> tuple[str, list, list]:
    """Resolve (view_run, selected records, all multi-run records) for the dashboard."""
    run = resolve_view_run(settings, run)
    rows = repo.get_all_ok_records(conn, PROMPT_VERSION, SCHEMA_VERSION)
    all_records = [agg.record_from_row(r) for r in rows]
    return run, agg.select_view(all_records, run), all_records


def _processing_days(tl: Timeline) -> tuple[int | None, str | None]:
    if tl.processing_days is not None:
        return tl.processing_days, tl.processing_source or "stated_duration"
    if tl.receipt_date and tl.decision_date:
        try:
            days = (date.fromisoformat(tl.decision_date) - date.fromisoformat(tl.receipt_date)).days
            if days >= 0:
                return days, "dates"
        except ValueError:
            pass
    return None, tl.processing_source


def _needs_op_comment_refresh(op_comments: str | None) -> bool:
    """True for non-empty OP-comment blobs cached before parent context was included."""
    if not op_comments:
        return False
    return "OP comment:" not in op_comments and "Parent comment (" not in op_comments


def _build_record(
    row: sqlite3.Row,
    chash: str,
    outcome: ClassificationOutcome,
    *,
    run_key: str,
    backend: str,
    effort: str,
    label: str,
    now: int,
) -> dict[str, Any]:
    selftext = row["selftext"]
    body_available = 1 if selftext and selftext not in ("[removed]", "[deleted]") else 0
    rec: dict[str, Any] = {
        "post_id": row["id"],
        "content_hash": chash,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "run_key": run_key,
        "classifier_backend": backend,
        "classifier_model": outcome.model,
        "run_effort": effort or None,
        "run_label": label or None,
        "body_available": body_available,
        "failure_reason": outcome.failure_reason,
        "classified_at": now,
        "raw_llm_output": outcome.raw_output,
        "outcome": None, "degree": None, "field_raw": None, "field_normalized": None,
        "profession_raw": None, "profession_normalized": None,
        "law_firm_raw": None, "law_firm_normalized": None,
        "publications": None, "publications_known": 0,
        "patents": None, "patents_known": 0,
        "citations": None, "citations_known": 0,
        "recommendation_letters": None, "recommendation_letters_known": 0,
        "years_experience": None, "years_experience_known": 0,
        "receipt_date": None, "decision_date": None,
        "processing_days": None, "processing_days_known": 0, "processing_source": None,
        "premium_processing": None, "was_rfed": None, "rfe_date": None, "rfe_response_date": None,
    }

    if outcome.status == "failed" or outcome.fields is None:
        rec["status"] = "failed"
        return rec

    f = outcome.fields
    rec["status"] = "ok" if f.is_niw_i140_decision else "excluded"
    rec["outcome"] = f.outcome.value if f.outcome else None
    rec["degree"] = f.degree.value if f.degree else None
    rec["field_raw"] = f.field_raw
    rec["field_normalized"] = normalize_field(f.field_raw)
    rec["profession_raw"] = f.profession_raw
    rec["profession_normalized"] = normalize_profession(f.profession_raw)
    rec["law_firm_raw"] = f.law_firm_raw
    rec["law_firm_normalized"] = normalize_law_firm(f.law_firm_raw)
    rec["publications"] = f.publications.value
    rec["publications_known"] = int(f.publications.known)
    rec["patents"] = f.patents.value
    rec["patents_known"] = int(f.patents.known)
    rec["citations"] = f.citations.value
    rec["citations_known"] = int(f.citations.known)
    rec["recommendation_letters"] = f.recommendation_letters.value
    rec["recommendation_letters_known"] = int(f.recommendation_letters.known)
    rec["years_experience"] = f.years_experience.value
    rec["years_experience_known"] = int(f.years_experience.known)
    rec["receipt_date"] = f.timeline.receipt_date
    rec["decision_date"] = f.timeline.decision_date
    pdays, psource = _processing_days(f.timeline)
    rec["processing_days"] = pdays
    rec["processing_days_known"] = int(pdays is not None)
    rec["processing_source"] = psource
    tl = f.timeline
    rec["premium_processing"] = None if tl.premium_processing is None else int(tl.premium_processing)
    rec["was_rfed"] = None if tl.was_rfed is None else int(tl.was_rfed)
    rec["rfe_date"] = tl.rfe_date
    rec["rfe_response_date"] = tl.rfe_response_date
    return rec


def classify_pending(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    classifier: Classifier | None = None,
    limit: int | None = None,
    now: int | None = None,
    on_start: Callable[[int, int], None] | None = None,
    progress: Callable[[dict], None] | None = None,
    on_wait: Callable[[float, int | None], None] | None = None,
    enricher: Callable[[sqlite3.Row], str] | None = None,
) -> dict[str, object]:
    """Classify candidate posts that have no record for the active version tuple.

    Resumable: already-classified posts are skipped (the checkpoint) and records are
    written incrementally. Callbacks: ``on_start(total, already_done)`` once; ``progress``
    with a state dict after each post; ``on_wait(seconds_left, reset_epoch)`` while waiting
    out a usage limit.
    """
    classifier = classifier or get_classifier(settings)
    backend = classifier.backend_name
    _, _model, effort, label = run_identity(settings)
    run_key = settings_run_key(settings)
    now = int(time.time()) if now is None else now
    # Record the most-recent run so a viewer can default to it if desired; the dashboard's
    # default view is the composite across all runs.
    repo.set_meta(conn, "active_run", run_key)
    repo.set_meta(conn, "active_backend", backend)
    if on_wait is not None and hasattr(classifier, "on_wait"):
        classifier.on_wait = on_wait

    done = repo.get_classified_keys(conn, PROMPT_VERSION, SCHEMA_VERSION, run_key)
    done_posts = {pid for pid, _ in done}
    # todo item = (row, chash | None, op | None, needs_fetch). For a post never classified under
    # this run, the OP-comment fetch is deferred into the worker thread so it OVERLAPS the LLM
    # calls of other posts (the fetch is rate-limited by Arctic Shift; overlapping hides it).
    todo: list[tuple[sqlite3.Row, str | None, str | None, bool]] = []
    already = 0
    for row in repo.iter_candidate_posts(conn):
        if row["id"] in done_posts:
            # Previously classified: resolve OP comments now (cached, else fetch) so the
            # content hash can decide whether anything changed and we should re-run.
            op = row["op_comments"]
            if (op is None or _needs_op_comment_refresh(op)) and enricher is not None:
                refreshed = enricher(row)
                if refreshed or op is None:
                    op = refreshed
                    repo.set_op_comments(conn, row["id"], op)
            chash = content_hash(row["title"], row["selftext"], row["link_flair_text"], op)
            if (row["id"], chash) in done:
                already += 1  # already done for this content == the resume checkpoint
                continue
            todo.append((row, chash, op, False))
        else:
            # Never classified under this run: it's todo regardless of content, so defer the
            # fetch + hashing into the worker (overlapped with other posts' classification).
            todo.append((row, None, None, True))
        if limit and len(todo) >= limit:
            break

    total = len(todo)
    if on_start:
        on_start(total, already)

    counts = {"ok": 0, "excluded": 0, "failed": 0}
    cost = 0.0
    if not todo:
        return {"processed": 0, "already_done": already, "cost_usd": 0.0, **counts}

    def work(item: tuple[sqlite3.Row, str | None, str | None, bool]):
        row, chash, op, needs_fetch = item
        if needs_fetch:
            op = row["op_comments"]
            if (op is None or _needs_op_comment_refresh(op)) and enricher is not None:
                refreshed = enricher(row)  # network fetch, overlapped with other workers' classification
                if refreshed or op is None:
                    op = refreshed
            chash = content_hash(row["title"], row["selftext"], row["link_flair_text"], op)
        outcome = classifier.classify(
            title=row["title"], body=row["selftext"], flair=row["link_flair_text"], op_comments=op
        )
        return row, chash, op, needs_fetch, outcome

    def store(row, chash, op, needs_fetch, outcome: ClassificationOutcome) -> str:
        nonlocal cost
        if (
            needs_fetch
            and op is not None
            and (row["op_comments"] is None or _needs_op_comment_refresh(row["op_comments"]))
        ):
            repo.set_op_comments(conn, row["id"], op)  # cache the fetch (main-thread DB write)
        rec = _build_record(
            row, chash, outcome, run_key=run_key, backend=backend, effort=effort, label=label, now=now
        )
        repo.upsert_classification(conn, rec)  # incremental write -> resumable
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
        cost += outcome.cost_usd or 0.0
        return rec["status"]

    completed = 0

    def emit(status: str) -> None:
        if progress:
            progress({
                "done": completed, "total": total, "ok": counts["ok"],
                "excluded": counts["excluded"], "failed": counts["failed"],
                "cost": cost, "last_status": status,
            })

    workers = settings.classify_workers if backend != "mock" else 1
    # The LLM call runs in worker threads; the DB write stays on the main thread.
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(work, item) for item in todo]):
                status = store(*fut.result())
                completed += 1
                emit(status)
    else:
        for item in todo:
            status = store(*work(item))
            completed += 1
            emit(status)

    return {"processed": total, "already_done": already, "cost_usd": round(cost, 4), **counts}
