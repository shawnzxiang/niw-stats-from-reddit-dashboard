"""Classify service: caching, version bumps, failure isolation, null-vs-zero mapping."""

from __future__ import annotations

from conftest import make_cls, make_raw

from niw_stats.classify import service
from niw_stats.classify.base import ClassificationOutcome, Classifier
from niw_stats.config import Settings
from niw_stats.db import repository as repo

SETTINGS = Settings(classifier_backend="mock")

RICH = (
    "NIW I-140 approved via Premium Processing! PhD in machine learning, 3 publications, "
    "2 patents, 0 citations, 6 years of experience, occupation: research scientist, "
    "approved in 90 days, got an RFE that I answered, filed DIY."
)


def seed(db, posts):
    repo.upsert_raw_posts(db, posts)


def active(db):
    # The single mock run's records (the composite over one run is identical).
    run = service.settings_run_key(SETTINGS)
    rows = repo.get_records_for_run(db, service.PROMPT_VERSION, service.SCHEMA_VERSION, run)
    return {r["post_id"]: r for r in rows}


def test_caching_skips_already_classified(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext=RICH)])
    r1 = service.classify_pending(db, settings=SETTINGS, now=1)
    assert r1["processed"] == 1 and r1["ok"] == 1
    r2 = service.classify_pending(db, settings=SETTINGS, now=2)
    assert r2["processed"] == 0  # cache hit, no re-classification


def test_classify_reports_progress(db):
    seed(db, [
        make_raw(f"p{i}", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")
        for i in range(3)
    ])
    events: list[dict] = []
    starts: list[tuple[int, int]] = []
    service.classify_pending(
        db, settings=SETTINGS, now=1,
        on_start=lambda total, already: starts.append((total, already)),
        progress=lambda ev: events.append(ev),
    )
    assert starts == [(3, 0)]
    assert [e["done"] for e in events] == [1, 2, 3]      # called once per post, monotonic
    assert all(e["total"] == 3 for e in events)
    assert events[-1]["ok"] + events[-1]["excluded"] + events[-1]["failed"] == 3


def test_resume_skips_checkpoint_and_reports_already_done(db):
    seed(db, [
        make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW."),
        make_raw("b", is_candidate=1, title="NIW approved", selftext="Approved! NIW."),
    ])
    r1 = service.classify_pending(db, settings=SETTINGS, now=1)
    assert (r1["processed"], r1["already_done"]) == (2, 0)

    starts: list[tuple[int, int]] = []
    r2 = service.classify_pending(db, settings=SETTINGS, now=2, on_start=lambda t, a: starts.append((t, a)))
    assert (r2["processed"], r2["already_done"]) == (0, 2)  # resumed from the checkpoint
    assert starts == [(0, 2)]


def test_null_vs_zero_and_field_mapping(db):
    seed(db, [
        make_raw("rich", is_candidate=1, title="NIW approved", selftext=RICH),
        make_raw("sparse", is_candidate=1, title="NIW approved, masters degree", selftext="Approved! NIW petition."),
    ])
    service.classify_pending(db, settings=SETTINGS, now=1)
    recs = active(db)

    rich = recs["rich"]
    assert rich["outcome"] == "approved"
    assert rich["degree"] == "PhD"
    assert rich["field_normalized"] == "CS/AI"
    assert rich["profession_raw"] == "research scientist"
    assert rich["law_firm_normalized"] == "DIY/Self-petition"
    assert (rich["citations"], rich["citations_known"]) == (0, 1)        # explicit zero
    assert (rich["publications"], rich["publications_known"]) == (3, 1)
    assert (rich["patents"], rich["patents_known"]) == (2, 1)
    assert (rich["years_experience"], rich["years_experience_known"]) == (6.0, 1)
    assert (rich["processing_days"], rich["processing_days_known"]) == (90, 1)
    assert (rich["premium_processing"], rich["was_rfed"]) == (1, 1)  # PP + RFE detected

    sparse = recs["sparse"]
    assert sparse["degree"] == "Masters"
    assert (sparse["citations"], sparse["citations_known"]) == (None, 0)  # not mentioned != 0
    assert (sparse["publications_known"], sparse["years_experience_known"]) == (0, 0)


def test_content_change_triggers_reclassification(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)
    assert active(db)["a"]["citations_known"] == 0

    db.execute("UPDATE raw_posts SET selftext = ? WHERE id='a'", ("Approved NIW with 12 citations.",))
    db.commit()
    r = service.classify_pending(db, settings=SETTINGS, now=2)
    assert r["processed"] == 1  # new content hash -> re-run
    assert active(db)["a"]["citations"] == 12


def test_op_comment_change_triggers_reclassification(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)
    assert active(db)["a"]["citations_known"] == 0

    repo.set_op_comments(db, "a", "OP later clarified: 12 citations.")
    r = service.classify_pending(db, settings=SETTINGS, now=2)
    assert r["processed"] == 1
    assert active(db)["a"]["citations"] == 12


def test_op_comments_are_fetched_before_cache_skip(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)

    enrich = lambda row: "OP follow-up: 0 citations."  # noqa: E731
    r = service.classify_pending(db, settings=SETTINGS, now=2, enricher=enrich)

    assert r["processed"] == 1
    assert active(db)["a"]["citations"] == 0
    assert db.execute("SELECT op_comments FROM raw_posts WHERE id='a'").fetchone()[0] == "OP follow-up: 0 citations."


def test_old_style_op_comments_are_refreshed_for_parent_context(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    repo.set_op_comments(db, "a", "Old cached OP reply without parent context.")
    enrich = lambda row: "Parent comment (u1): How many citations at filing?\nOP reply: 91"  # noqa: E731

    service.classify_pending(db, settings=SETTINGS, now=1, enricher=enrich)

    stored = db.execute("SELECT op_comments FROM raw_posts WHERE id='a'").fetchone()[0]
    assert stored == "Parent comment (u1): How many citations at filing?\nOP reply: 91"


def test_version_bump_reclassifies_into_new_rows(db, monkeypatch):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)
    assert db.execute("SELECT COUNT(*) FROM classified_records").fetchone()[0] == 1

    monkeypatch.setattr(service, "PROMPT_VERSION", "p-test-bump")
    r = service.classify_pending(db, settings=SETTINGS, now=2)
    assert r["processed"] == 1
    # Old p1 row retained; new p2 row added.
    assert db.execute("SELECT COUNT(*) FROM classified_records").fetchone()[0] == 2


def test_run_identity_and_active_run_recorded(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    service.classify_pending(db, settings=SETTINGS, now=1)
    assert repo.get_meta(db, "active_run") == "mock/mock"
    # The default view is the composite across all runs (here: just one run).
    assert service.active_identity(SETTINGS, db)[2] == "composite"


def test_run_key_distinguishes_models_so_multiple_runs_coexist(db):
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! NIW.")])
    sonnet = Settings(classifier_backend="claude-cli", claude_model="sonnet")
    haiku = Settings(classifier_backend="claude-cli", claude_model="haiku")
    assert service.settings_run_key(sonnet) == "claude-cli/sonnet"
    assert service.settings_run_key(haiku) == "claude-cli/haiku"
    labelled = Settings(classifier_backend="claude-cli", claude_model="sonnet", run_label="promptB")
    assert service.settings_run_key(labelled) == "claude-cli/sonnet#promptB"
    codex = Settings(classifier_backend="codex-cli", codex_model="gpt-5", codex_reasoning_effort="high")
    assert service.settings_run_key(codex) == "codex-cli/gpt-5@high"


def test_composite_view_majority_votes_per_post(db):
    seed(db, [make_raw("a", is_candidate=1)])
    # Three runs disagree on post "a": approved, approved, denied -> composite = approved.
    repo.upsert_classification(db, make_cls("a", run_key="r1", outcome="approved", classified_at=10))
    repo.upsert_classification(db, make_cls("a", run_key="r2", outcome="approved", classified_at=20))
    repo.upsert_classification(db, make_cls("a", run_key="r3", outcome="denied", classified_at=30))
    rows = repo.get_all_ok_records(db, "p1", "s1")
    from niw_stats.stats import aggregate as agg

    records = [agg.record_from_row(r) for r in rows]
    composite = agg.select_view(records, "composite")
    assert len(composite) == 1 and composite[0].outcome == "approved"
    # A tie is broken by the most recent run.
    repo.upsert_classification(db, make_cls("a", run_key="r4", outcome="denied", classified_at=40))
    records = [agg.record_from_row(r) for r in repo.get_all_ok_records(db, "p1", "s1")]
    assert agg.select_view(records, "composite")[0].outcome == "denied"  # 2-2 tie, newest is denied
    # Selecting a single run ignores the others.
    assert agg.select_view(records, "r1")[0].outcome == "approved"


def test_op_comments_are_fetched_stored_and_fed_to_classifier(db):
    # The post body says "approved" but reveals nothing about degree/premium;
    # the OP's own comment carries those details.
    seed(db, [make_raw("a", is_candidate=1, title="NIW approved", selftext="Approved! My NIW petition.")])
    enrich = lambda row: "PhD in CS. 0 citations. Filed via Premium Processing."  # noqa: E731

    service.classify_pending(db, settings=SETTINGS, now=1, enricher=enrich)

    stored = db.execute("SELECT op_comments FROM raw_posts WHERE id='a'").fetchone()[0]
    assert stored == "PhD in CS. 0 citations. Filed via Premium Processing."  # cached on the raw row

    rec = active(db)["a"]
    assert rec["degree"] == "PhD"               # extracted from the comment, not the body
    assert rec["premium_processing"] == 1
    assert (rec["citations"], rec["citations_known"]) == (0, 1)


def test_build_user_prompt_includes_op_comments_section_only_when_present():
    from niw_stats.classify.prompt import build_user_prompt

    with_comments = build_user_prompt("Title", "body", "APPROVED", "I'm a banker in finance")
    assert "banker in finance" in with_comments and "OP" in with_comments

    without = build_user_prompt("Title", "body", "APPROVED", None)
    assert "banker" not in without


def test_system_prompt_pins_publication_patent_profession_and_law_firm_rules():
    from niw_stats.classify.prompt import PROMPT_VERSION, SCHEMA_VERSION, SYSTEM_PROMPT

    assert (PROMPT_VERSION, SCHEMA_VERSION) == ("p3", "s3")
    assert "Do NOT count conference\n  abstracts" in SYSTEM_PROMPT
    assert "poster presentations" in SYSTEM_PROMPT
    assert "- patents:" in SYSTEM_PROMPT
    assert "- profession_raw:" in SYSTEM_PROMPT
    assert 'do NOT output "Other"' in SYSTEM_PROMPT


def test_excluded_when_not_a_decision(db):
    # candidate by flair, but the body is an I-485 update -> not an I-140 decision
    seed(db, [make_raw("a", is_candidate=1, title="Update", selftext="My I-485 was approved, EAD in hand.", link_flair_text="APPROVED")])
    r = service.classify_pending(db, settings=SETTINGS, now=1)
    assert r["excluded"] == 1
    assert "a" not in active(db)  # excluded rows don't feed stats


class _PickyBackend(Classifier):
    """Fails any post whose title contains FAIL; otherwise defers to the mock."""

    backend_name = "mock"

    def classify(self, *, title, body, flair, op_comments=None):
        if "FAIL" in title:
            return ClassificationOutcome(status="failed", failure_reason="boom")
        from niw_stats.classify.mock_backend import MockBackend

        return MockBackend().classify(title=title, body=body, flair=flair, op_comments=op_comments)


def test_failure_is_isolated_and_recorded(db):
    seed(db, [
        make_raw("ok", is_candidate=1, title="NIW approved", selftext="Approved! NIW."),
        make_raw("bad", is_candidate=1, title="FAIL post", selftext="Approved! NIW."),
    ])
    r = service.classify_pending(db, settings=SETTINGS, classifier=_PickyBackend(), now=1)
    assert r["ok"] == 1 and r["failed"] == 1  # batch completed despite the failure
    row = db.execute("SELECT status, failure_reason FROM classified_records WHERE post_id='bad'").fetchone()
    assert row["status"] == "failed"
    assert row["failure_reason"] == "boom"
