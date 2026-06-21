"""Decide which posts are worth sending to the LLM.

Precision-leaning so we don't waste LLM calls on the large volume of questions /
discussion. The real decision signal on r/EB2_NIW is the **APPROVED / DENIAL
flairs** plus an **outcome word in the title**; a tight personal-outcome phrase in
the body adds recall without admitting generic "the approval process" chatter.
The LLM's ``is_niw_i140_decision`` gate still does the final precision pass.
"""

from __future__ import annotations

import re

# Decision flairs only (topic/stage flairs like I-140, Timeline, USCIS are NOT decisions).
INCLUDE_FLAIRS = {"APPROVED", "APPROVAL", "DENIED", "DENIAL"}

_OUTCOME = re.compile(r"\b(approved|approval|denied|denial|rejected)\b", re.I)
_NIW = re.compile(r"\b(niw|i[\s-]?140|eb[\s-]?2|petition|national interest)\b", re.I)
_I485 = re.compile(r"\b(i[\s-]?485|adjustment of status|\baos\b|advance parole|green card in hand)\b", re.I)
_NVC = re.compile(r"\b(nvc|consular|ds[\s-]?260|visa interview|visa stamp)\b", re.I)

# Personal/decision phrasing in the body: "my I-140 was approved", "petition got denied",
# "approved without RFE", "approved in 88 days" — not the generic word "approval".
_BODY_DECISION = re.compile(
    r"\b(?:was|got|been|i[\s-]?140|niw|petition|case)\b[^.\n]{0,30}\b(?:approved|denied)\b"
    r"|\b(?:approved|denied)\b[^.\n]{0,25}\b(?:without (?:an )?rfe|in \d+\s*(?:day|week|month))",
    re.I,
)


def _post_text(post: dict) -> tuple[str, str]:
    title = post.get("title") or ""
    body = post.get("selftext") or ""
    if body in ("[removed]", "[deleted]"):
        body = ""
    return title, body


def decide_candidate(post: dict) -> tuple[bool, str]:
    """Return ``(is_candidate, reason)``."""
    title, body = _post_text(post)
    flair = (post.get("link_flair_text") or "").strip().upper()

    # 1. Decision flair is the strongest, highest-precision signal.
    if flair in INCLUDE_FLAIRS:
        return True, f"flair:{flair}"

    # 2. Outcome word in the title (covers removed-body posts and any flair).
    if _OUTCOME.search(title):
        if _I485.search(title) and not _NIW.search(title):
            return False, "excluded:i485"
        if _NVC.search(title) and not _NIW.search(title):
            return False, "excluded:nvc"
        return True, "kw:title"

    # 3. A concrete personal-outcome phrase in the body.
    if _BODY_DECISION.search(body):
        if _I485.search(body) and not _NIW.search(body):
            return False, "excluded:i485"
        return True, "kw:body"

    return False, "no_signal"
