"""Robustly pull a single JSON object out of an LLM's free-text stdout."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    """Return the JSON object found in ``text``.

    Tolerates code fences, leading/trailing prose, and preamble like
    "Here is the JSON:". Raises ``ValueError`` if no object can be parsed.
    """
    if not text or not text.strip():
        raise ValueError("empty output")
    s = text.strip()

    # 1. Already-clean JSON.
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. Fenced ```json ... ``` block.
    m = _FENCE.search(s)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 3. First '{' to last '}'.
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        try:
            obj = json.loads(s[i : j + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError as exc:
            raise ValueError(f"found braces but could not parse JSON: {exc}") from exc

    raise ValueError("no JSON object found in output")
