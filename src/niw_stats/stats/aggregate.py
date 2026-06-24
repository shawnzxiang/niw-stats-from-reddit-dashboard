"""Pure aggregation functions — no DB, no FastAPI, fully unit-testable.

These power both the API endpoints and the static snapshot path. The "hide
unknown" toggle drops records whose value is *not known* while keeping explicit
zeros, which is the whole point of the (value, known) pairs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# --- record -----------------------------------------------------------------

@dataclass
class Record:
    created_utc: int
    outcome: str | None
    degree: str | None
    field_normalized: str | None
    profession_raw: str | None
    law_firm_normalized: str | None
    publications: int | None
    publications_known: bool
    patents: int | None
    patents_known: bool
    citations: int | None
    citations_known: bool
    years_experience: float | None
    years_experience_known: bool
    processing_days: int | None
    processing_days_known: bool
    # Post identity (for the drill-down list); defaulted so hand-built test records still work.
    id: str | None = None
    title: str | None = None
    permalink: str | None = None
    flair: str | None = None
    premium_processing: bool | None = None
    was_rfed: bool | None = None
    rfe_date: str | None = None
    rfe_response_date: str | None = None
    # Run provenance (for the model picker + composite voting).
    run: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    classified_at: int | None = None
    selftext: str | None = None
    op_comments: str | None = None
    # Read-time normalized profession (taxonomy applied on read, not stored).
    profession_normalized: str | None = None
    # Re-file detection (per-author, computed at read time).
    author: str | None = None
    refiled: bool | None = None
    refiled_url: str | None = None
    refile_approval: bool | None = None


def content_fingerprint(records: list[Record], prefix: str = "") -> str:
    """A hash of the record VALUES (incl. normalized buckets) so the data_version / ETag
    changes whenever the displayed data changes — e.g. after `niw renormalize`. Without this,
    re-normalization left counts/dates unchanged and stale 304 responses were served."""
    h = hashlib.sha256(prefix.encode("utf-8"))
    for r in records:
        h.update(
            f"{r.id}|{r.outcome}|{r.degree}|{r.field_normalized}|{r.profession_normalized}|"
            f"{r.law_firm_normalized}|{r.citations}|{r.publications}|{r.years_experience}|"
            f"{r.processing_days}|{r.premium_processing}|{r.was_rfed}|{r.run}\n".encode()
        )
    return h.hexdigest()[:16]


def _int_to_bool(value) -> bool | None:
    return None if value is None else bool(value)


def _row_get(row, key, default=None):
    """Column access that tolerates rows (sqlite3.Row / dict) missing the column."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


# NIW premium processing guarantees a decision within ~45 calendar days, so a case that took
# far longer was almost certainly *regular* even when the OP didn't say so. Fill that in when
# premium status is unstated and there's no RFE on record (premium + RFE can legitimately run long).
PREMIUM_INFER_DAYS = 90


def infer_premium(
    premium: bool | None, processing_days: int | None, days_known: bool, was_rfed: bool | None
) -> bool | None:
    if (
        premium is None
        and days_known
        and processing_days is not None
        and processing_days > PREMIUM_INFER_DAYS
        and was_rfed is not True
    ):
        return False  # regular, inferred from a processing time far past the premium guarantee
    return premium


def record_from_row(row) -> Record:
    premium = infer_premium(
        _int_to_bool(row["premium_processing"]),
        row["processing_days"],
        bool(row["processing_days_known"]),
        _int_to_bool(row["was_rfed"]),
    )
    return Record(
        created_utc=row["created_utc"],
        outcome=row["outcome"],
        degree=row["degree"],
        field_normalized=row["field_normalized"],
        profession_raw=_row_get(row, "profession_raw"),
        # Both buckets are persisted in the DB and re-applied via `niw renormalize` (one-off).
        profession_normalized=_row_get(row, "profession_normalized"),
        law_firm_normalized=_row_get(row, "law_firm_normalized"),
        publications=row["publications"],
        publications_known=bool(row["publications_known"]),
        patents=_row_get(row, "patents"),
        patents_known=bool(_row_get(row, "patents_known", 0)),
        citations=row["citations"],
        citations_known=bool(row["citations_known"]),
        years_experience=row["years_experience"],
        years_experience_known=bool(row["years_experience_known"]),
        processing_days=row["processing_days"],
        processing_days_known=bool(row["processing_days_known"]),
        id=row["post_id"],
        title=row["title"],
        permalink=row["permalink"],
        flair=row["flair"],
        premium_processing=premium,
        was_rfed=_int_to_bool(row["was_rfed"]),
        rfe_date=row["rfe_date"],
        rfe_response_date=row["rfe_response_date"],
        run=_row_get(row, "run_key"),
        prompt_version=_row_get(row, "prompt_version"),
        schema_version=_row_get(row, "schema_version"),
        classified_at=_row_get(row, "classified_at"),
        selftext=_row_get(row, "selftext"),
        op_comments=_row_get(row, "op_comments"),
        author=_row_get(row, "author"),
    )


def to_slim(r: Record) -> dict[str, Any]:
    """Compact JSON form for the snapshot / records endpoint. [value, known] pairs."""
    return {
        "id": r.id,
        "title": r.title,
        "permalink": r.permalink,
        "flair": r.flair,
        "created_utc": r.created_utc,
        "outcome": r.outcome,
        "degree": r.degree,
        "field": r.field_normalized,
        "profession": r.profession_normalized,
        "profession_raw": r.profession_raw,
        "law_firm": r.law_firm_normalized,
        "publications": [r.publications, r.publications_known],
        "patents": [r.patents, r.patents_known],
        "citations": [r.citations, r.citations_known],
        "years_experience": [r.years_experience, r.years_experience_known],
        "processing_days": [r.processing_days, r.processing_days_known],
        "premium_processing": r.premium_processing,
        "was_rfed": r.was_rfed,
        "rfe_date": r.rfe_date,
        "rfe_response_date": r.rfe_response_date,
        "run": r.run,
        "prompt_version": r.prompt_version,
        "schema_version": r.schema_version,
        "classified_at": r.classified_at,
        "selftext": r.selftext,
        "op_comments": r.op_comments,
        "author": r.author,
        "refiled": r.refiled,
        "refiled_url": r.refiled_url,
    }


# Fields dropped from the PUBLIC snapshot (NIW_PUBLIC_SNAPSHOT=1): the re-hosted post body,
# the OP's comments, and the Reddit username. All detected PII lives in the body/comments, and
# dropping author stops the published file from being a username->outcome index. Re-file flags
# (refiled/refiled_url) are computed server-side via mark_refiled() BEFORE slimming, so the badge
# survives the loss of `author`. Title + permalink stay (the "keep links" choice).
_PUBLIC_DROP = ("selftext", "op_comments", "author")


def to_slim_public(r: Record) -> dict[str, Any]:
    """PII-scrubbed slim form for the public snapshot — to_slim minus body/comments/username."""
    d = to_slim(r)
    for k in _PUBLIC_DROP:
        d.pop(k, None)
    return d


def record_from_slim(d: dict[str, Any]) -> Record:
    pub = d.get("publications") or [None, False]
    pat = d.get("patents") or [None, False]
    cit = d.get("citations") or [None, False]
    yoe = d.get("years_experience") or [None, False]
    days = d.get("processing_days") or [None, False]
    return Record(
        created_utc=d["created_utc"],
        outcome=d.get("outcome"),
        degree=d.get("degree"),
        field_normalized=d.get("field"),
        profession_raw=d.get("profession_raw"),
        profession_normalized=d.get("profession"),
        law_firm_normalized=d.get("law_firm"),
        publications=pub[0], publications_known=bool(pub[1]),
        patents=pat[0], patents_known=bool(pat[1]),
        citations=cit[0], citations_known=bool(cit[1]),
        years_experience=yoe[0], years_experience_known=bool(yoe[1]),
        processing_days=days[0], processing_days_known=bool(days[1]),
        id=d.get("id"), title=d.get("title"), permalink=d.get("permalink"), flair=d.get("flair"),
        premium_processing=d.get("premium_processing"), was_rfed=d.get("was_rfed"),
        rfe_date=d.get("rfe_date"), rfe_response_date=d.get("rfe_response_date"),
        run=d.get("run"), classified_at=d.get("classified_at"),
        prompt_version=d.get("prompt_version"), schema_version=d.get("schema_version"),
        selftext=d.get("selftext"), op_comments=d.get("op_comments"),
        author=d.get("author"), refiled=d.get("refiled"), refiled_url=d.get("refiled_url"),
    )


# --- run selection / composite voting ---------------------------------------

COMPOSITE = "composite"


def _vote(group: list[Record]) -> Record:
    """Pick one representative record for a post from its runs.

    Majority vote on ``outcome``; ties (and the representative within the winning outcome)
    are broken by the most recent ``classified_at``. The winner is a real record from one
    run, so all of its fields stay mutually consistent (no field-level Frankenstein).
    """
    if len(group) == 1:
        return group[0]

    def recency(r: Record) -> int:
        return r.classified_at or 0

    tally: dict[Any, int] = {}
    for r in group:
        tally[r.outcome] = tally.get(r.outcome, 0) + 1
    best_outcome, best_count, best_recency = None, -1, -1
    for outcome, count in tally.items():
        rec = max((recency(r) for r in group if r.outcome == outcome), default=0)
        if count > best_count or (count == best_count and rec > best_recency):
            best_outcome, best_count, best_recency = outcome, count, rec
    winners = [r for r in group if r.outcome == best_outcome]
    return max(winners, key=recency)


def select_view(records: list[Record], run: str = COMPOSITE) -> list[Record]:
    """Reduce multi-run records to the view the dashboard shows.

    ``run == "composite"`` (default): one voted record per post across all runs.
    Any other value: only that run's records. Output is sorted newest-post first.
    """
    if run and run != COMPOSITE:
        chosen = [r for r in records if r.run == run]
    else:
        by_post: dict[Any, list[Record]] = {}
        for r in records:
            by_post.setdefault(r.id, []).append(r)
        chosen = [_vote(group) for group in by_post.values()]
    return sorted(chosen, key=lambda r: (-(r.created_utc or 0), r.id or ""))


# --- re-file detection ------------------------------------------------------

_AUTHOR_SKIP = {None, "", "[deleted]", "[removed]", "AutoModerator"}


def mark_refiled(records: list[Record]) -> list[Record]:
    """Flag denied cases whose author was later approved (a re-file), using only the
    classified posts in ``records``. Sets ``refiled``/``refiled_url`` on the denied record
    (pointing at the later approval) and ``refile_approval`` on the approval. Mutates in place.
    """
    for r in records:
        r.refiled = r.refiled_url = r.refile_approval = None
    by_author: dict[str, list[Record]] = {}
    for r in records:
        if r.author in _AUTHOR_SKIP:
            continue
        by_author.setdefault(r.author, []).append(r)
    for recs in by_author.values():
        approved = [r for r in recs if r.outcome == "approved"]
        if not approved:
            continue
        for d in (r for r in recs if r.outcome == "denied"):
            later = [a for a in approved if (a.created_utc or 0) > (d.created_utc or 0)]
            if later:
                first = min(later, key=lambda a: a.created_utc or 0)  # earliest later approval
                d.refiled = True
                d.refiled_url = first.permalink
                first.refile_approval = True
    return records


# --- buckets ----------------------------------------------------------------
# (label, lower_inclusive, upper_exclusive | None for +inf)

PUBLICATION_BINS = [
    ("0", 0, 1), ("1–2", 1, 3), ("3–5", 3, 6), ("6–10", 6, 11), ("11–20", 11, 21), ("21+", 21, None),
]
PATENT_BINS = [
    ("0", 0, 1), ("1", 1, 2), ("2–3", 2, 4), ("4+", 4, None),
]
CITATION_BINS = [
    ("0", 0, 1), ("1–10", 1, 11), ("11–20", 11, 21), ("21–30", 21, 31),
    ("31–50", 31, 51), ("51–100", 51, 101), ("101–200", 101, 201),
    ("201–500", 201, 501), ("501+", 501, None),
]
YEARS_BINS = [
    ("0–2", 0, 3), ("3–5", 3, 6), ("6–10", 6, 11), ("11–15", 11, 16), ("16+", 16, None),
]
DURATION_BINS = [
    ("0–30", 0, 31), ("31–60", 31, 61), ("61–90", 61, 91), ("91–120", 91, 121),
    ("121–180", 121, 181), ("181–365", 181, 366), ("365+", 366, None),
]

UNKNOWN = "Unknown"


def _bucket_label(value: float, bins: list[tuple[str, int, int | None]]) -> str:
    for label, lo, hi in bins:
        if value >= lo and (hi is None or value < hi):
            return label
    return bins[-1][0]


# --- range filtering --------------------------------------------------------

RANGE_DAYS = {"3m": 90, "6m": 180, "12m": 365, "24m": 730}
DAY = 86_400


def window_from_range(range_key: str, now: int) -> tuple[int, int]:
    days = RANGE_DAYS[range_key]
    return (now - days * DAY, now)


def filter_by_range(records: list[Record], start: int | None, end: int | None) -> list[Record]:
    def ok(r: Record) -> bool:
        return (start is None or r.created_utc >= start) and (end is None or r.created_utc <= end)

    return [r for r in records if ok(r)]


# --- metric registry --------------------------------------------------------

def _premium_label(v: bool | None) -> str | None:
    return None if v is None else ("Premium" if v else "Regular")


def _rfe_label(v: bool | None) -> str | None:
    return None if v is None else ("RFE'd" if v else "No RFE")


_CATEGORICAL: dict[str, Callable[[Record], str | None]] = {
    "outcome": lambda r: r.outcome,
    "degree": lambda r: r.degree,
    "field": lambda r: r.field_normalized,
    "profession": lambda r: r.profession_normalized,
    "law_firm": lambda r: r.law_firm_normalized,
    "premium": lambda r: _premium_label(r.premium_processing),
    "rfe": lambda r: _rfe_label(r.was_rfed),
}
_NUMERIC: dict[str, tuple[Callable[[Record], tuple[float | None, bool]], list]] = {
    "publications": (lambda r: (r.publications, r.publications_known), PUBLICATION_BINS),
    "patents": (lambda r: (r.patents, r.patents_known), PATENT_BINS),
    "citations": (lambda r: (r.citations, r.citations_known), CITATION_BINS),
    "years_experience": (lambda r: (r.years_experience, r.years_experience_known), YEARS_BINS),
    "processing_days": (lambda r: (r.processing_days, r.processing_days_known), DURATION_BINS),
}

METRICS = list(_CATEGORICAL) + list(_NUMERIC)


def _tally(slot: list[int], r: Record) -> None:
    """slot = [count, approved, denied]; accumulate the record's outcome split."""
    slot[0] += 1
    if r.outcome == "approved":
        slot[1] += 1
    elif r.outcome == "denied":
        slot[2] += 1


def _bucket(label: str, slot: list[int]) -> dict[str, Any]:
    return {"label": label, "count": slot[0], "approved": slot[1], "denied": slot[2]}


OTHERS = "Other"
MAX_CATEGORIES = 9  # categorical charts show the top N by volume, then collapse the rest into "Other"


def _collapse_others(buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the top MAX_CATEGORIES named buckets; merge the long tail (and any existing
    "Other") into a single "Other" bucket so high-cardinality charts stay readable."""
    named = sorted((b for b in buckets if b["label"] != OTHERS), key=lambda b: -b["count"])
    existing = next((b for b in buckets if b["label"] == OTHERS), None)
    if len(named) + (1 if existing else 0) <= MAX_CATEGORIES:
        return named + ([existing] if existing else [])
    keep, tail = named[:MAX_CATEGORIES], named[MAX_CATEGORIES:]
    other = {"label": OTHERS, "count": 0, "approved": 0, "denied": 0}
    for b in tail + ([existing] if existing else []):
        other["count"] += b["count"]
        other["approved"] += b["approved"]
        other["denied"] += b["denied"]
    return keep + [other]


def _categorical(records: list[Record], accessor, hide_unknown: bool) -> dict[str, Any]:
    counts: dict[str, list[int]] = {}
    unknown = [0, 0, 0]
    for r in records:
        v = accessor(r)
        _tally(unknown if v is None else counts.setdefault(v, [0, 0, 0]), r)
    buckets = _collapse_others([_bucket(k, s) for k, s in counts.items()])
    if not hide_unknown and unknown[0]:
        buckets.append(_bucket(UNKNOWN, unknown))
    n_known = sum(b["count"] for b in buckets if b["label"] != UNKNOWN)
    return {
        "kind": "categorical",
        "buckets": buckets,
        "unknown_count": unknown[0],
        "n": n_known,
        "total": len(records),
    }


def _numeric(records: list[Record], accessor, bins, hide_unknown: bool, kind: str) -> dict[str, Any]:
    order = [b[0] for b in bins]
    counts = {label: [0, 0, 0] for label in order}
    unknown = [0, 0, 0]
    for r in records:
        value, known = accessor(r)
        _tally(unknown if (not known or value is None) else counts[_bucket_label(value, bins)], r)
    buckets = [_bucket(label, counts[label]) for label in order]
    if not hide_unknown and unknown[0]:
        buckets.append(_bucket(UNKNOWN, unknown))
    return {
        "kind": kind,
        "buckets": buckets,
        "unknown_count": unknown[0],
        "n": sum(counts[label][0] for label in order),
        "total": len(records),
    }


def distribution(records: list[Record], metric: str, hide_unknown: bool = False) -> dict[str, Any]:
    if metric in _CATEGORICAL:
        return {"metric": metric, **_categorical(records, _CATEGORICAL[metric], hide_unknown)}
    if metric in _NUMERIC:
        accessor, bins = _NUMERIC[metric]
        kind = "duration" if metric == "processing_days" else "numeric"
        return {"metric": metric, **_numeric(records, accessor, bins, hide_unknown, kind)}
    raise ValueError(f"unknown metric: {metric!r}")


# --- approval rate ----------------------------------------------------------

def approval_rate(records: list[Record]) -> dict[str, Any]:
    approved = sum(1 for r in records if r.outcome == "approved")
    denied = sum(1 for r in records if r.outcome == "denied")
    decided = approved + denied
    return {
        "approved": approved,
        "denied": denied,
        "total_decided": decided,
        "rate": (approved / decided) if decided else None,
    }


_GROUPS = {"degree", "field", "law_firm", "citation_bucket", "premium", "rfe"}


def _group_label(r: Record, group: str) -> str:
    if group == "degree":
        return r.degree or UNKNOWN
    if group == "field":
        return r.field_normalized or UNKNOWN
    if group == "law_firm":
        return r.law_firm_normalized or UNKNOWN
    if group == "premium":
        return _premium_label(r.premium_processing) or UNKNOWN
    if group == "rfe":
        return _rfe_label(r.was_rfed) or UNKNOWN
    if group == "citation_bucket":
        if not r.citations_known or r.citations is None:
            return UNKNOWN
        return _bucket_label(r.citations, CITATION_BINS)
    raise ValueError(f"unknown group: {group!r}")


def approval_rate_by_group(records: list[Record], group: str, hide_unknown: bool = False) -> dict[str, Any]:
    if group not in _GROUPS:
        raise ValueError(f"unknown group: {group!r}")
    agg: dict[str, dict[str, int]] = {}
    for r in records:
        if r.outcome not in ("approved", "denied"):
            continue
        label = _group_label(r, group)
        slot = agg.setdefault(label, {"approved": 0, "denied": 0})
        slot[r.outcome] += 1

    rows = []
    for label, c in agg.items():
        if hide_unknown and label == UNKNOWN:
            continue
        n = c["approved"] + c["denied"]
        rows.append({
            "label": label,
            "approved": c["approved"],
            "denied": c["denied"],
            "n": n,
            "rate": (c["approved"] / n) if n else None,
        })

    if group == "citation_bucket":
        order = {label: i for i, (label, *_ ) in enumerate(CITATION_BINS)}
        order[UNKNOWN] = len(order)
        rows.sort(key=lambda x: order.get(x["label"], 99))
    else:
        rows.sort(key=lambda x: (x["label"] == UNKNOWN, -x["n"]))
    return {"group": group, "groups": rows}


def summary(records: list[Record]) -> dict[str, Any]:
    return {"total": len(records), **approval_rate(records)}
