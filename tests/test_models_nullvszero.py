"""The crux of the project: not-mentioned (unknown) must stay distinct from explicit zero."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from niw_stats.models import (
    Degree,
    ExtractedFields,
    FloatField,
    IntField,
    Outcome,
    Timeline,
    extracted_fields_json_schema,
)


class TestIntField:
    def test_explicit_zero_is_known(self):
        f = IntField(value=0)
        assert f.value == 0
        assert f.known is True

    def test_absent_is_unknown(self):
        f = IntField()
        assert f.value is None
        assert f.known is False

    def test_positive_value_is_known(self):
        assert IntField(value=42).known is True

    def test_known_is_derived_not_trusted(self):
        # The LLM might claim known=True with a null value (or vice versa);
        # the invariant value-is-None <=> not-known is enforced regardless.
        assert IntField(value=None, known=True).known is False
        assert IntField(value=0, known=False).known is True

    def test_extra_keys_forbidden(self):
        with pytest.raises(ValidationError):
            IntField(value=1, bogus=2)


class TestFloatField:
    def test_explicit_zero_is_known(self):
        f = FloatField(value=0.0)
        assert f.value == 0.0
        assert f.known is True

    def test_absent_is_unknown(self):
        assert FloatField().known is False

    def test_fractional_years(self):
        assert FloatField(value=3.5).value == 3.5


class TestExtractedFields:
    def test_defaults_are_all_unknown(self):
        ef = ExtractedFields(is_niw_i140_decision=False)
        assert ef.outcome is None
        assert ef.degree is None
        assert ef.field_raw is None
        assert ef.profession_raw is None
        assert ef.law_firm_raw is None
        assert ef.publications.known is False
        assert ef.patents.known is False
        assert ef.citations.known is False
        assert ef.recommendation_letters.known is False
        assert ef.years_experience.known is False
        assert ef.timeline.processing_days is None

    def test_full_record_roundtrips_through_json(self):
        ef = ExtractedFields(
            is_niw_i140_decision=True,
            outcome=Outcome.approved,
            degree=Degree.phd,
            field_raw="machine learning",
            profession_raw="research scientist",
            law_firm_raw="DIY",
            publications={"value": 3},
            patents={"value": 2},
            citations={"value": 0},  # explicit zero
            recommendation_letters={"value": 0},  # explicit no recommendation/testimonial letters
            years_experience={"value": 5.0},
            timeline={
                "receipt_date": "2024-01-10",
                "decision_date": "2024-04-09",
                "processing_days": 90,
                "processing_source": "dates",
            },
        )
        again = ExtractedFields.model_validate_json(ef.model_dump_json())
        assert again.citations.value == 0
        assert again.citations.known is True
        assert again.publications.known is True
        assert again.patents.value == 2
        assert again.patents.known is True
        assert again.recommendation_letters.value == 0
        assert again.recommendation_letters.known is True
        assert again.is_usable_decision() is True

    def test_gate_without_outcome_is_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedFields(is_niw_i140_decision=True, outcome=None)

    def test_excluded_post_is_not_usable(self):
        ef = ExtractedFields(is_niw_i140_decision=False, outcome=Outcome.approved)
        assert ef.is_usable_decision() is False

    def test_unknown_enum_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedFields(is_niw_i140_decision=True, degree="HighSchool")

    def test_top_level_extra_keys_forbidden(self):
        with pytest.raises(ValidationError):
            ExtractedFields(is_niw_i140_decision=True, hallucinated_field="x")


class TestTimeline:
    def test_rejects_bad_date(self):
        with pytest.raises(ValidationError):
            Timeline(receipt_date="01/10/2024")

    def test_rejects_negative_processing_days(self):
        with pytest.raises(ValidationError):
            Timeline(processing_days=-1)

    def test_rejects_unknown_processing_source(self):
        with pytest.raises(ValidationError):
            Timeline(processing_source="guessed")


def test_json_schema_exposes_nested_known_pairs():
    schema = extracted_fields_json_schema()
    assert schema["type"] == "object"
    assert "is_niw_i140_decision" in schema["properties"]
    assert "recommendation_letters" in schema["properties"]
    assert "profession_raw" in schema["properties"]
    assert "patents" in schema["properties"]
    # IntField/FloatField/Timeline are emitted as referenced definitions.
    defs = schema.get("$defs", {})
    assert "IntField" in defs
    assert set(defs["IntField"]["properties"]) == {"value", "known"}
