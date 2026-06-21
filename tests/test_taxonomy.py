"""Deterministic field / law-firm normalisation."""

from __future__ import annotations

import pytest

from niw_stats.classify.taxonomy import (
    normalize_field,
    normalize_law_firm,
    normalize_profession,
)


@pytest.mark.parametrize(
    "raw, bucket",
    [
        ("PhD student", "PhD Student"),
        ("Ph.D. candidate", "PhD Student"),
        ("5th year PhD student", "PhD Student"),
        ("postdoc", "Postdoc/Researcher"),
        ("postdoctoral researcher", "Postdoc/Researcher"),
        ("research scientist", "Postdoc/Researcher"),
        ("software engineer", "Software Engineer"),
        ("Senior Software Engineer", "Software Engineer"),
        ("data scientist", "Data Scientist/Engineer"),
        ("Machine Learning Engineer", "Data Scientist/Engineer"),
        ("SWE", "Software Engineer"),
        ("Assistant Professor", "Professor/Faculty"),
        ("Lecturer at Yale", "Professor/Faculty"),
        ("Physician", "Physician/Clinician"),
        ("doctor of physical therapy", "Physician/Clinician"),
        ("Mechanical Engineer", "Engineer (other)"),
        ("structural engineer", "Engineer (other)"),
        # "developer" in a non-software/industrial role must NOT become Software Engineer.
        ("Project Developer at Global Water Treatment Solution Provider", "Engineer (other)"),
        ("Software Developer", "Software Engineer"),  # genuine software dev stays put
        ("BI developer", "Software Engineer"),  # existing behavior unchanged
        # Any "software" wording => Software Engineer, even when not a contiguous "software engineer".
        ("software/system engineer", "Software Engineer"),
        ("Software Quality Assurance", "Software Engineer"),
        ("software professional", "Software Engineer"),
        ("Software / AI Engineer", "Data Scientist/Engineer"),  # explicit AI engineer still wins
        ("Entrepreneur", "Entrepreneur/Founder"),
        ("startup founder", "Entrepreneur/Founder"),
        ("finance professional", "Finance/Business"),
        ("SVP at Bank NYC in Trading", "Finance/Business"),
        ("underwater basket weaver", "Other"),
    ],
)
def test_normalize_profession(raw, bucket):
    assert normalize_profession(raw) == bucket


def test_normalize_profession_empty():
    assert normalize_profession(None) is None
    assert normalize_profession("") is None


@pytest.mark.parametrize(
    "raw, bucket",
    [
        ("Wegreen", "Chen/WeGreened"),
        ("Chen group", "Chen/WeGreened"),
        ("W Chen", "Chen/WeGreened"),
        ("Raju", "Raju Law"),
        ("Colombo & Hurd", "Colombo & Hurd"),
        ("Columbo & Hurd", "Colombo & Hurd"),
        ("C&H", "Colombo & Hurd"),
        ("Sedaghat Law Firm", "Sedaghat Law"),
        ("Sedaghat", "Sedaghat Law"),
        ("Dunn (Arkell)", "Dunn Law"),
        ("Peak Immigration Associates", "Peak Immigration"),
        ("Fragomen", "Fragomen"),
        # passthrough canonicalisation: strip generic suffixes so variants merge…
        ("Ashoori Law Firm", "Ashoori"),
        ("Ashoori", "Ashoori"),
        ("Manifest Law", "Manifest"),
        ("Pogue Law Offices", "Pogue"),
        # …but preserve acronyms / names with no generic suffix
        ("BAL", "BAL"),
        ("USAIMCO", "USAIMCO"),
    ],
)
def test_normalize_law_firm_new_aliases(raw, bucket):
    assert normalize_law_firm(raw) == bucket


@pytest.mark.parametrize(
    "raw, bucket",
    [
        ("machine learning", "CS/AI"),
        ("Deep Learning for NLP", "CS/AI"),
        ("molecular biology", "Biology"),
        ("clinical oncology", "Biomedical/Medicine"),
        ("materials science", "Materials"),
        ("theoretical physics", "Physics"),
        ("econometrics", "Economics/Finance"),
        ("underwater basket weaving", "Other"),
    ],
)
def test_normalize_field(raw, bucket):
    assert normalize_field(raw) == bucket


def test_normalize_field_none():
    assert normalize_field(None) is None
    assert normalize_field("") is None


@pytest.mark.parametrize(
    "raw, bucket",
    [
        ("DIY", "DIY/Self-petition"),
        ("self-petition", "DIY/Self-petition"),
        ("I filed pro se", "DIY/Self-petition"),
        ("WeGreened", "Chen/WeGreened"),
        ("Chen", "Chen/WeGreened"),
        ("Chen Immigration", "Chen/WeGreened"),
        ("Chen Immigration (WeGreened)", "Chen/WeGreened"),
        ("Chen Immigration & Attorneys (WeGreened)", "Chen/WeGreened"),
        ("EP", "Ellis Porter"),
        ("Ellis Porter", "Ellis Porter"),
        ("EllisPorter", "Ellis Porter"),
        ("RAJU_LAW", "Raju Law"),
        ("Raju law", "Raju Law"),
        ("Smith & Jones LLP", "Smith & Jones"),
        ("independent consultant", "independent consultant"),
        ("Other", None),
    ],
)
def test_normalize_law_firm(raw, bucket):
    assert normalize_law_firm(raw) == bucket


def test_normalize_law_firm_none():
    assert normalize_law_firm(None) is None
