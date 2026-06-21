"""Pulling a JSON object out of messy LLM stdout."""

from __future__ import annotations

import pytest

from niw_stats.classify.json_extract import extract_json_object


def test_clean_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_fenced_json():
    out = extract_json_object('```json\n{"a": 1, "b": [2,3]}\n```')
    assert out == {"a": 1, "b": [2, 3]}


def test_bare_fence():
    assert extract_json_object('```\n{"a": 1}\n```') == {"a": 1}


def test_preamble_and_trailing_prose():
    out = extract_json_object('Here is the JSON:\n{"a": 1}\nHope that helps!')
    assert out == {"a": 1}


def test_nested_braces():
    out = extract_json_object('prefix {"a": {"b": 1}} suffix')
    assert out == {"a": {"b": 1}}


@pytest.mark.parametrize("bad", ["", "   ", "I cannot help with that.", "no braces here"])
def test_no_json_raises(bad):
    with pytest.raises(ValueError):
        extract_json_object(bad)
