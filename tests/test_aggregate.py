"""Pure aggregation: range, hide-unknown (keep explicit zeros), buckets, approval rate."""

from __future__ import annotations

from niw_stats.stats import aggregate as agg
from niw_stats.stats.aggregate import Record


def mk(**over) -> Record:
    base = dict(
        created_utc=1_700_000_000, outcome=None, degree=None, field_normalized=None,
        profession_raw=None, law_firm_normalized=None, publications=None, publications_known=False,
        patents=None, patents_known=False,
        citations=None, citations_known=False, years_experience=None, years_experience_known=False,
        processing_days=None, processing_days_known=False,
    )
    base.update(over)
    return Record(**base)


def test_filter_by_range():
    recs = [mk(created_utc=100), mk(created_utc=200), mk(created_utc=300)]
    assert [r.created_utc for r in agg.filter_by_range(recs, 150, 250)] == [200]
    assert len(agg.filter_by_range(recs, None, None)) == 3


def test_window_from_range():
    assert agg.window_from_range("3m", 1_000_000) == (1_000_000 - 90 * 86400, 1_000_000)
    assert agg.window_from_range("24m", 1_000_000) == (1_000_000 - 730 * 86400, 1_000_000)


def test_categorical_hide_unknown():
    recs = [mk(degree="PhD"), mk(degree="PhD"), mk(degree="Masters"), mk(degree=None)]
    shown = agg.distribution(recs, "degree", hide_unknown=False)
    assert shown["buckets"][0]["label"] == "PhD" and shown["buckets"][0]["count"] == 2
    assert any(b["label"] == "Unknown" and b["count"] == 1 for b in shown["buckets"])
    assert shown["unknown_count"] == 1 and shown["n"] == 3

    hidden = agg.distribution(recs, "degree", hide_unknown=True)
    assert all(b["label"] != "Unknown" for b in hidden["buckets"])
    assert hidden["n"] == 3


def test_explicit_zero_is_kept_distinct_from_unknown():
    recs = [
        mk(citations=0, citations_known=True),     # explicit zero
        mk(citations=5, citations_known=True),
        mk(citations=None, citations_known=False),  # not mentioned
        mk(citations=1500, citations_known=True),
    ]
    d = agg.distribution(recs, "citations", hide_unknown=False)
    by = {b["label"]: b["count"] for b in d["buckets"]}
    assert by["0"] == 1                 # the explicit zero
    assert by["1–10"] == 1
    assert by["501+"] == 1              # 1500 falls in the top bucket
    assert d["unknown_count"] == 1      # the not-mentioned one, counted separately
    assert d["n"] == 3

    # Hiding unknown removes the not-mentioned record but keeps the explicit zero.
    d2 = agg.distribution(recs, "citations", hide_unknown=True)
    by2 = {b["label"]: b["count"] for b in d2["buckets"]}
    assert by2["0"] == 1
    assert all(b["label"] != "Unknown" for b in d2["buckets"])


def test_distribution_carries_outcome_split():
    recs = [
        mk(degree="PhD", outcome="approved"),
        mk(degree="PhD", outcome="approved"),
        mk(degree="PhD", outcome="denied"),
        mk(degree="Masters", outcome="denied"),
    ]
    d = agg.distribution(recs, "degree")
    phd = next(b for b in d["buckets"] if b["label"] == "PhD")
    assert (phd["count"], phd["approved"], phd["denied"]) == (3, 2, 1)
    masters = next(b for b in d["buckets"] if b["label"] == "Masters")
    assert (masters["approved"], masters["denied"]) == (0, 1)


def test_distribution_outcome_split_numeric_and_unknown():
    recs = [
        mk(citations=0, citations_known=True, outcome="approved"),
        mk(citations=0, citations_known=True, outcome="denied"),
        mk(citations=None, citations_known=False, outcome="denied"),  # unknown value bucket
    ]
    d = agg.distribution(recs, "citations")
    zero = next(b for b in d["buckets"] if b["label"] == "0")
    assert (zero["count"], zero["approved"], zero["denied"]) == (2, 1, 1)
    unk = next(b for b in d["buckets"] if b["label"] == "Unknown")
    assert (unk["count"], unk["denied"]) == (1, 1)


def test_categorical_collapses_long_tail_into_other():
    recs = []
    for i in range(12):  # 12 distinct firms, counts 12, 11, … 1
        recs += [mk(law_firm_normalized=f"Firm{i}", outcome="approved") for _ in range(12 - i)]
    d = agg.distribution(recs, "law_firm", hide_unknown=True)
    labels = [b["label"] for b in d["buckets"]]
    assert len(labels) == 10 and labels[-1] == "Other"   # top 9 + Other
    other = d["buckets"][-1]
    assert (other["count"], other["approved"]) == (3 + 2 + 1, 6)  # firms ranked 10–12
    # 9 or fewer distinct → no collapse
    few = agg.distribution([mk(degree="PhD"), mk(degree="Masters")], "degree", hide_unknown=True)
    assert all(b["label"] != "Other" for b in few["buckets"])


def test_mark_refiled_flags_denied_then_later_approved():
    recs = [
        mk(id="d1", author="alice", outcome="denied", created_utc=100, permalink="/d1"),
        mk(id="a1", author="alice", outcome="approved", created_utc=200, permalink="/a1"),
        mk(id="b1", author="bob", outcome="denied", created_utc=100, permalink="/b1"),
        mk(id="x1", author="[deleted]", outcome="denied", created_utc=100),
        mk(id="x2", author="[deleted]", outcome="approved", created_utc=200),
    ]
    agg.mark_refiled(recs)
    by = {r.id: r for r in recs}
    assert by["d1"].refiled is True and by["d1"].refiled_url == "/a1"
    assert by["a1"].refile_approval is True
    assert by["b1"].refiled is None   # denied but never later approved
    assert by["x1"].refiled is None   # [deleted] author skipped

    # An approval BEFORE the denial is not a re-file.
    recs2 = [
        mk(id="a", author="c", outcome="approved", created_utc=100),
        mk(id="d", author="c", outcome="denied", created_utc=200, permalink="/d"),
    ]
    agg.mark_refiled(recs2)
    assert all(r.refiled is None for r in recs2)


def test_patent_distribution_keeps_zero_distinct_from_unknown():
    recs = [
        mk(patents=0, patents_known=True),
        mk(patents=2, patents_known=True),
        mk(patents=None, patents_known=False),
    ]
    d = agg.distribution(recs, "patents")
    by = {b["label"]: b["count"] for b in d["buckets"]}
    assert by["0"] == 1
    assert by["2–3"] == 1
    assert d["unknown_count"] == 1


def test_numeric_bucket_boundaries():
    vals = [0, 10, 11, 20, 30, 50, 100, 200, 500, 501, 1000]
    recs = [mk(citations=v, citations_known=True) for v in vals]
    by = {b["label"]: b["count"] for b in agg.distribution(recs, "citations")["buckets"]}
    assert by["0"] == 1 and by["1–10"] == 1
    assert by["11–20"] == 2 and by["21–30"] == 1 and by["31–50"] == 1
    assert by["51–100"] == 1 and by["101–200"] == 1 and by["201–500"] == 1
    assert by["501+"] == 2


def test_years_float_buckets():
    recs = [mk(years_experience=2.5, years_experience_known=True),
            mk(years_experience=3.0, years_experience_known=True)]
    by = {b["label"]: b["count"] for b in agg.distribution(recs, "years_experience")["buckets"]}
    assert by["0–2"] == 1 and by["3–5"] == 1


def test_approval_rate():
    recs = [mk(outcome="approved"), mk(outcome="approved"), mk(outcome="denied"), mk(outcome=None)]
    r = agg.approval_rate(recs)
    assert (r["approved"], r["denied"], r["total_decided"]) == (2, 1, 3)
    assert abs(r["rate"] - 2 / 3) < 1e-9


def test_approval_rate_empty():
    assert agg.approval_rate([mk(outcome=None)])["rate"] is None


def test_approval_rate_by_degree():
    recs = [
        mk(outcome="approved", degree="PhD"), mk(outcome="denied", degree="PhD"),
        mk(outcome="approved", degree="Masters"), mk(outcome="approved", degree=None),
    ]
    groups = {g["label"]: g for g in agg.approval_rate_by_group(recs, "degree")["groups"]}
    assert groups["PhD"]["n"] == 2 and abs(groups["PhD"]["rate"] - 0.5) < 1e-9
    assert groups["Masters"]["rate"] == 1.0
    assert "Unknown" in groups

    hidden = agg.approval_rate_by_group(recs, "degree", hide_unknown=True)
    assert all(g["label"] != "Unknown" for g in hidden["groups"])


def test_premium_and_rfe_metrics():
    recs = [
        mk(outcome="approved", premium_processing=True, was_rfed=False),
        mk(outcome="denied", premium_processing=False, was_rfed=True),
        mk(outcome="approved", premium_processing=None, was_rfed=None),  # unknown
    ]
    prem = {b["label"]: b["count"] for b in agg.distribution(recs, "premium")["buckets"]}
    assert prem["Premium"] == 1 and prem["Regular"] == 1 and prem["Unknown"] == 1

    rfe = {b["label"]: b["count"] for b in agg.distribution(recs, "rfe", hide_unknown=True)["buckets"]}
    assert rfe.get("RFE'd") == 1 and rfe.get("No RFE") == 1 and "Unknown" not in rfe

    by_prem = {g["label"]: g for g in agg.approval_rate_by_group(recs, "premium")["groups"]}
    assert by_prem["Premium"]["approved"] == 1 and by_prem["Regular"]["denied"] == 1


def test_approval_rate_by_citation_bucket_ordered():
    recs = [
        mk(outcome="approved", citations=5, citations_known=True),
        mk(outcome="denied", citations=5, citations_known=True),
        mk(outcome="approved", citations=None, citations_known=False),
    ]
    out = agg.approval_rate_by_group(recs, "citation_bucket")
    labels = [g["label"] for g in out["groups"]]
    assert labels == ["1–10", "Unknown"]  # bin order, Unknown last


def test_slim_roundtrip_preserves_zero_vs_unknown():
    r = mk(outcome="approved", degree="PhD", field_normalized="CS/AI", profession_raw="Research scientist",
           citations=0, citations_known=True, publications=None, publications_known=False)
    back = agg.record_from_slim(agg.to_slim(r))
    assert back.citations == 0 and back.citations_known is True
    assert back.publications is None and back.publications_known is False
    assert back.degree == "PhD" and back.field_normalized == "CS/AI"
    assert back.profession_raw == "Research scientist"


def test_infer_premium_from_long_processing():
    # Unstated premium + processing far past the ~45-day guarantee, no RFE -> inferred regular.
    assert agg.infer_premium(None, 200, True, False) is False
    assert agg.infer_premium(None, 200, True, None) is False  # unknown RFE still inferred regular
    # An RFE on record -> premium + RFE can legitimately run long, so do NOT infer.
    assert agg.infer_premium(None, 200, True, True) is None
    # Near/within the guarantee window -> stays unknown (gray zone).
    assert agg.infer_premium(None, 60, True, False) is None
    # Unknown processing days -> can't infer.
    assert agg.infer_premium(None, None, False, False) is None
    # Explicitly stated values are never overridden.
    assert agg.infer_premium(True, 300, True, False) is True
    assert agg.infer_premium(False, 10, True, False) is False
