"""Pydantic models: the LLM extraction contract and the null-vs-zero carriers.

The crux of this project is distinguishing *"not mentioned"* (unknown) from an
*explicit zero* (e.g. a post that says "0 citations"). Every numeric metric is
therefore a ``(value, known)`` pair rather than a bare ``Optional[int]``::

    IntField(value=0, known=True)   # poster stated "no citations"
    IntField()                      # post is silent about citations

Invariant enforced by validators: ``value is None  <=>  known is False``.
``ExtractedFields`` is also the single source of truth for the JSON schema we
hand to the LLM (via :func:`extracted_fields_json_schema`), so what the model is
asked to produce is exactly what we validate.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Outcome(str, Enum):
    approved = "approved"
    denied = "denied"


class Degree(str, Enum):
    phd = "PhD"
    masters = "Masters"
    bachelors = "Bachelors"
    md = "MD"
    postdoc = "Postdoc"
    other = "Other"


class IntField(BaseModel):
    """Null-vs-zero carrier for an integer metric (publications, citations, patents, letters)."""

    model_config = ConfigDict(extra="forbid")

    value: int | None = None
    known: bool = False

    @model_validator(mode="after")
    def _enforce_invariant(self) -> IntField:
        # ``known`` is authoritative-derived from ``value`` so a present value
        # (including 0) is always "known" and absence is always "unknown".
        self.known = self.value is not None
        return self


class FloatField(BaseModel):
    """Null-vs-zero carrier for a real-valued metric (years of experience)."""

    model_config = ConfigDict(extra="forbid")

    value: float | None = None
    known: bool = False

    @model_validator(mode="after")
    def _enforce_invariant(self) -> FloatField:
        self.known = self.value is not None
        return self


class Timeline(BaseModel):
    """Processing-time information. ``processing_days`` is the headline metric."""

    model_config = ConfigDict(extra="forbid")

    receipt_date: str | None = None  # 'YYYY-MM-DD'
    decision_date: str | None = None  # 'YYYY-MM-DD'
    processing_days: int | None = None
    processing_source: str | None = None  # 'dates' | 'stated_duration'
    premium_processing: bool | None = None  # True=Premium Processing, False=regular, None=unknown
    was_rfed: bool | None = None  # True=case received an RFE, False=no RFE, None=unknown
    rfe_date: str | None = None  # 'YYYY-MM-DD' the RFE was issued
    rfe_response_date: str | None = None  # 'YYYY-MM-DD' the RFE response was received/submitted

    @model_validator(mode="after")
    def _validate_timeline(self) -> Timeline:
        for field in ("receipt_date", "decision_date", "rfe_date", "rfe_response_date"):
            value = getattr(self, field)
            if value is not None:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{field} must be YYYY-MM-DD") from exc
        if self.processing_days is not None and self.processing_days < 0:
            raise ValueError("processing_days must be non-negative")
        if self.processing_source not in (None, "dates", "stated_duration"):
            raise ValueError("processing_source must be 'dates' or 'stated_duration'")
        return self


class ExtractedFields(BaseModel):
    """The structured record the LLM must return for a single Reddit post."""

    model_config = ConfigDict(extra="forbid")

    # Gate: True ONLY when the post reports a FINAL I-140 NIW approval/denial.
    # False for questions, discussion, profile checks, RFE-without-outcome, and
    # I-485 / adjustment-of-status / consular (NVC) updates.
    is_niw_i140_decision: bool

    outcome: Outcome | None = None  # required-in-spirit when the gate is True
    degree: Degree | None = None
    field_raw: str | None = None  # endeavor field in the poster's words
    profession_raw: str | None = None  # role/occupation in the poster's words
    law_firm_raw: str | None = None  # firm name, "DIY"/"self-petition", or None

    publications: IntField = Field(default_factory=IntField)
    patents: IntField = Field(default_factory=IntField)
    citations: IntField = Field(default_factory=IntField)
    recommendation_letters: IntField = Field(default_factory=IntField)
    years_experience: FloatField = Field(default_factory=FloatField)
    timeline: Timeline = Field(default_factory=Timeline)

    def is_usable_decision(self) -> bool:
        """True when this is a final decision *and* an outcome was extracted."""
        return self.is_niw_i140_decision and self.outcome is not None

    @model_validator(mode="after")
    def _validate_decision_gate(self) -> ExtractedFields:
        if self.is_niw_i140_decision and self.outcome is None:
            raise ValueError("outcome is required when is_niw_i140_decision is true")
        return self


def extracted_fields_json_schema() -> dict[str, Any]:
    """JSON schema handed to the classifier CLI (e.g. ``claude --json-schema``)."""
    return ExtractedFields.model_json_schema()
