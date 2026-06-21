"""Prompt + JSON schema for the extractor. Bump a version to trigger re-classification."""

from __future__ import annotations

from typing import Any

from niw_stats.models import extracted_fields_json_schema

# Bump either to re-classify everything into new rows (old rows are retained).
PROMPT_VERSION = "p3"  # p3: filing-time counts, comment-parent context, lawyer aliases, 0 pubs => 0 citations
SCHEMA_VERSION = "s3"  # s3: added letters, patents, and profession fields

SYSTEM_PROMPT = """You extract structured data from a single Reddit post about a US EB-2 NIW \
(National Interest Waiver) immigration case. Output ONLY a JSON object that validates against \
the provided schema. No prose, no code fences.

Rules:
- is_niw_i140_decision = true ONLY if the post reports a FINAL I-140 NIW APPROVAL or DENIAL.
  An RFE that the poster says was later approved counts as approved. Set false for: questions,
  general discussion, profile-evaluation requests, RFE with no final outcome, and
  I-485 / adjustment-of-status / consular (NVC) updates.
- outcome: "approved" or "denied" (only when is_niw_i140_decision is true).
- For every numeric field use {"value": N, "known": true} when the poster states a number,
  INCLUDING zero (e.g. "no publications" -> {"value": 0, "known": true}). Use
  {"value": null, "known": false} when the post does not mention it. Never guess or infer.
- publications: the total publication count AT THE TIME OF I-140 FILING. Count journal
  articles/papers, conference papers/proceedings papers, and preprints. Do NOT count conference
  abstracts, poster presentations, oral presentations, talks, seminars, workshops, reviews, peer
  reviews, manuscripts reviewed, extension articles, patents, or media mentions as publications.
  If a combined total appears to include ineligible items and the eligible publication count cannot
  be separated, use {"value": null, "known": false}. If the poster gives a breakdown, sum only
  eligible categories (e.g. 6 journal papers + 2 conference papers + 4 preprints + 12 conference
  abstracts => 12, excluding the abstracts). If both "at filing" and "now/current" counts are
  stated, use the filing count.
- citations: citation count AT THE TIME OF I-140 FILING. If both "at filing" and "now/current"
  citation counts are stated, use the filing count. If the poster has zero publications (or says
  they have no publications/papers), set citations to {"value": 0, "known": true} as well — no
  publications means no citations — UNLESS they explicitly state a citation count. Do not confuse
  citations with receipt numbers, officer IDs, form numbers, dates, post IDs, or statute/regulation
  numbers.
- patents: combined number of issued patents, patent applications, pending patents, and
  provisional patents AT THE TIME OF I-140 FILING. Sum them if split by type. If the poster
  explicitly says no/zero patents, use {"value": 0, "known": true}. Do not count patents as
  publications.
- recommendation_letters: combined count of recommendation letters, testimonial letters,
  expert letters, reference letters, and support letters. Sum them if split by type. If the
  poster explicitly says none/no letters, use {"value": 0, "known": true}.
- degree: one of PhD, Masters, Bachelors, MD, Postdoc, Other; null if unstated.
- field_raw: the poster's research/endeavor area in their own words; null if unstated.
- profession_raw: the poster's occupation/professional role at the time of filing, in their
  own words when stated (e.g. PhD student, postdoc, software engineer, physician, researcher,
  assistant professor, entrepreneur); null if unstated. Do not infer profession from degree
  alone.
- law_firm_raw: the law firm name if mentioned, or "DIY"/"self-petition" if they filed
  without a lawyer; null if unstated. If a firm is named but is not one of the common aliases,
  output the stated firm name; do NOT output "Other". Common aliases: Chen / Chen Immigration /
  WeGreened are the same firm; Ellis Porter / EP / EllisPorter are the same firm; RAJU_LAW /
  Raju Law are the same firm.
- timeline: if both a receipt/filing date and a decision date are given, return them as
  receipt_date and decision_date ("YYYY-MM-DD"). If only a duration is stated (e.g.
  "approved in 88 days"), set processing_days and processing_source="stated_duration".
- timeline.premium_processing: true if the case used USCIS Premium Processing (PP / expedited,
  ~15-45 day SLA); false if the poster says it was regular/standard processing; null if unstated.
- timeline.was_rfed: true if the case received a Request for Evidence (RFE) at any point (even if
  later approved); false if the poster says it was approved without an RFE / "no RFE"; null if unstated.
- timeline.rfe_date / timeline.rfe_response_date: the dates ("YYYY-MM-DD") the RFE was issued and the
  RFE response was received/submitted, if stated; null otherwise.
- Do not infer values from flair alone; rely on the post text.
- The input may include the original poster's (OP's) own follow-up comments. Treat them as
  authoritative additional detail about the SAME case (e.g. field, premium vs regular, RFE,
  citation/publication counts the OP only revealed in replies). Some OP replies include the
  parent comment they answered; use that parent context to interpret bare answers. For example,
  if the parent asks "how many citations did you have at filing?" and OP replies "91", that
  means citations={"value": 91, "known": true}; do not treat the number in isolation.
"""


def build_user_prompt(
    title: str, body: str | None, flair: str | None, op_comments: str | None = None
) -> str:
    if not body or body in ("[removed]", "[deleted]"):
        body = "[body unavailable]"
    parts = [f"Flair: {flair or 'none'}", f"Title: {title}", "", f"Body:\n{body}"]
    if op_comments and op_comments.strip():
        parts += ["", "OP's own comments on this post, sometimes with parent-comment context "
                  "(authoritative detail about the same case):",
                  op_comments.strip()]
    parts += ["", "Extract the structured data as a single JSON object."]
    return "\n".join(parts)


def json_schema() -> dict[str, Any]:
    return extracted_fields_json_schema()
