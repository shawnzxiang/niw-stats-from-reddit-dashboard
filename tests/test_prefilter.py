"""Pre-filter: decision flairs + title outcome + tight body phrase; precision-leaning."""

from __future__ import annotations

import pytest

from niw_stats.ingest.prefilter import decide_candidate


def post(title="", body="", flair=None):
    return {"title": title, "selftext": body, "link_flair_text": flair}


@pytest.mark.parametrize(
    "p, expect_candidate, reason_prefix",
    [
        # decision flair wins
        (post("My case update", flair="APPROVED"), True, "flair:"),
        (post("My case update", flair="DENIAL"), True, "flair:"),       # DENIAL, not DENIED
        # outcome word in the title (covers any flair / removed body)
        (post("EB2 NIW I-140 approval (WeGreened)", flair="I-140"), True, "kw:title"),
        (post("EB2 NIW approved in 90 days!", body="[removed]"), True, "kw:title"),
        (post("Approved!!", flair=None), True, "kw:title"),
        (post("My petition was denied", flair=None), True, "kw:title"),
        # body-only personal-outcome phrase
        (post("My NIW journey", body="Happy to share my I-140 was approved last week!"), True, "kw:body"),
        # excludes: outcome belongs to a later (485 / consular) stage, not the I-140
        (post("I-485 approved, EAD received", flair=None), False, "excluded:i485"),
        (post("Consular interview done, approved", flair=None), False, "excluded:nvc"),
        # the noise the old filter wrongly admitted — now correctly dropped
        (post("Working with EP", flair="I-140"), False, "no_signal"),
        (post("Recommendation letter length and content", flair="I-140"), False, "no_signal"),
        (post("How long does NIW take these days?", flair=None), False, "no_signal"),
        (post("Thoughts on premium processing strategy?", flair="General"), False, "no_signal"),
    ],
)
def test_decide_candidate(p, expect_candidate, reason_prefix):
    is_candidate, reason = decide_candidate(p)
    assert is_candidate is expect_candidate
    assert reason.startswith(reason_prefix)


def test_485_with_explicit_140_outcome_is_kept_for_the_llm():
    is_candidate, reason = decide_candidate(post("I-140 NIW approved, now filing I-485"))
    assert is_candidate is True
    assert reason == "kw:title"  # has NIW context, so not excluded as a 485 post


def test_generic_approval_chatter_in_body_is_not_a_candidate():
    # "the approval process" must NOT trigger the body-decision path
    assert decide_candidate(post("Question", body="How does the approval process work for NIW?"))[0] is False
