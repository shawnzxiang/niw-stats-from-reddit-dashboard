"""Deterministic, zero-LLM classifier used by tests, CI, and `--backend mock`.

Heuristic regexes mirror the real extractor's contract — in particular it keeps
the *not-mentioned vs explicit-zero* distinction so the whole pipeline can be
exercised without any model.
"""

from __future__ import annotations

import re

from niw_stats.classify.base import ClassificationOutcome, Classifier
from niw_stats.models import Degree, ExtractedFields, FloatField, IntField, Outcome, Timeline

_APPROVED = re.compile(r"\b(approved|approval|granted)\b", re.I)
_DENIED = re.compile(r"\b(denied|denial|rejected)\b", re.I)
_I485 = re.compile(r"\b(i[\s-]?485|adjustment of status|consular|nvc|ds[\s-]?260)\b", re.I)
_NIW = re.compile(r"\b(niw|i[\s-]?140|eb[\s-]?2|petition|national interest)\b", re.I)

_DEGREES = [
    (Degree.phd, re.compile(r"\bph\.?\s?d\b|\bdoctorate\b", re.I)),
    (Degree.postdoc, re.compile(r"\bpost[\s-]?doc", re.I)),
    (Degree.md, re.compile(r"\bm\.?d\b", re.I)),
    (Degree.masters, re.compile(r"master'?s?\b|\bm\.?s\.?\b|\bm\.?eng\b|\bmba\b", re.I)),
    (Degree.bachelors, re.compile(r"bachelor'?s?\b|\bb\.?s\.?\b|\bb\.?tech\b", re.I)),
]

_FIELDS = [
    "machine learning", "artificial intelligence", "computer vision", "data science",
    "bioinformatics", "biology", "genomics", "neuroscience", "chemistry", "materials science",
    "materials", "physics", "economics", "finance", "mechanical engineering",
    "electrical engineering", "civil engineering", "robotics", "public health",
]
_PROFESSION_LABEL = re.compile(
    r"\b(?:occupation|profession|role|job title|current status|position)[:\s-]+([^\n.;,]+)",
    re.I,
)
_PROFESSION_TERMS = [
    "phd student", "postdoc", "postdoctoral researcher", "software engineer", "data scientist",
    "research scientist", "researcher", "physician", "assistant professor", "professor",
    "entrepreneur", "founder", "engineer",
]


def _int_after(label_pat: str, text: str) -> IntField:
    none_pat = re.compile(rf"\b(no|zero)\s+{label_pat}", re.I)
    if none_pat.search(text):
        return IntField(value=0)
    m = re.search(rf"(\d+)\s*\+?\s*(?:peer[\s-]?reviewed\s*)?{label_pat}", text, re.I)
    if m:
        return IntField(value=int(m.group(1)))
    return IntField()


def _years(text: str) -> FloatField:
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*years?(?:\s+of)?\s+(?:experience|exp|work)", text, re.I)
    if m:
        return FloatField(value=float(m.group(1)))
    return FloatField()


def _profession(text: str) -> str | None:
    m = _PROFESSION_LABEL.search(text)
    if m:
        return m.group(1).strip()
    low = text.lower()
    for term in _PROFESSION_TERMS:
        if term in low:
            return term
    return None


def _timeline(text: str) -> Timeline:
    m = re.search(r"approved in\s+(\d+)\s+days", text, re.I)
    if m:
        return Timeline(processing_days=int(m.group(1)), processing_source="stated_duration")
    m = re.search(r"(?:approved|decision)\s+in\s+(\d+)\s+months", text, re.I)
    if m:
        return Timeline(processing_days=int(m.group(1)) * 30, processing_source="stated_duration")
    rd = re.search(r"(?:RD|receipt date)[:\s]+(\d{4}-\d{2}-\d{2})", text, re.I)
    ad = re.search(r"(?:AD|approval date|decision date)[:\s]+(\d{4}-\d{2}-\d{2})", text, re.I)
    if rd and ad:
        return Timeline(receipt_date=rd.group(1), decision_date=ad.group(1), processing_source="dates")
    return Timeline()


def _premium(text: str) -> bool | None:
    if re.search(r"\bpremium processing\b|\bexpedited\b|\bpp\b", text, re.I):
        return True
    if re.search(r"\bregular processing\b|\bstandard processing\b|\bno premium\b", text, re.I):
        return False
    return None


def _rfed(text: str) -> bool | None:
    if re.search(r"without (?:an )?rfe|\bno rfe\b", text, re.I):
        return False
    if re.search(r"\brfe\b|request for evidence", text, re.I):
        return True
    return None


def _law_firm(text: str) -> str | None:
    if re.search(r"\b(diy|self[\s-]?petition|pro se|no (?:lawyer|attorney))\b", text, re.I):
        return "DIY"
    m = re.search(r"\b(wegreened|chen immigration|chen associates)\b", text, re.I)
    if m:
        return m.group(1)
    return None


def heuristic_extract(
    title: str, body: str | None, flair: str | None, op_comments: str | None = None
) -> ExtractedFields:
    text = f"{title}\n{body or ''}\n{op_comments or ''}"
    is_485 = bool(_I485.search(text))
    approved = bool(_APPROVED.search(text))
    denied = bool(_DENIED.search(text))

    outcome: Outcome | None = None
    if denied:
        outcome = Outcome.denied
    elif approved:
        outcome = Outcome.approved

    is_decision = outcome is not None and bool(_NIW.search(text)) and not is_485

    degree: Degree | None = None
    for deg, pat in _DEGREES:
        if pat.search(text):
            degree = deg
            break

    field_raw: str | None = None
    low = text.lower()
    for f in _FIELDS:
        if f in low:
            field_raw = f
            break

    tl = _timeline(text)
    tl.premium_processing = _premium(text)
    tl.was_rfed = _rfed(text)
    return ExtractedFields(
        is_niw_i140_decision=is_decision,
        outcome=outcome if is_decision else None,
        degree=degree,
        field_raw=field_raw,
        profession_raw=_profession(text),
        law_firm_raw=_law_firm(text),
        publications=_int_after(r"(?:publications?|papers?|pubs?)", text),
        patents=_int_after(r"(?:patents?|patent applications?|provisional patents?)", text),
        citations=_int_after(r"citations?", text),
        recommendation_letters=_int_after(
            r"(?:(?:recommendation|testimonial|expert|reference|support)\s+letters?|letters?)",
            text,
        ),
        years_experience=_years(text),
        timeline=tl,
    )


class MockBackend(Classifier):
    backend_name = "mock"

    def classify(
        self, *, title: str, body: str | None, flair: str | None, op_comments: str | None = None
    ) -> ClassificationOutcome:
        fields = heuristic_extract(title, body, flair, op_comments)
        return ClassificationOutcome(status="ok", fields=fields, model="mock")
