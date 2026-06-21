"""Classifier interface, result type, and the content-hash used for caching."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

from niw_stats.models import ExtractedFields


@dataclass
class ClassificationOutcome:
    """What a backend returns. ``status`` here is only about *parsing* success.

    The service maps a parsed result to the stored status: ``excluded`` when the
    post is not a final I-140 decision, otherwise ``ok``.
    """

    status: str  # 'ok' (parsed) | 'failed' (could not parse/validate)
    fields: ExtractedFields | None = None
    failure_reason: str | None = None
    raw_output: str | None = None
    model: str | None = None
    cost_usd: float | None = None  # reported by the LLM CLI, when available


class UsageLimitError(Exception):
    """Raised when the LLM CLI reports a usage/rate limit; the caller waits and retries.

    ``reset_at`` is a unix epoch (seconds) when known, else None (poll-wait).
    """

    def __init__(self, message: str, reset_at: int | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class Classifier(ABC):
    backend_name: str = "base"

    @abstractmethod
    def classify(
        self, *, title: str, body: str | None, flair: str | None, op_comments: str | None = None
    ) -> ClassificationOutcome:
        ...


def content_hash(
    title: str | None, body: str | None, flair: str | None, op_comments: str | None = None
) -> str:
    """Stable hash of the post content used as part of the classification cache key."""
    norm = "\n".join([
        (title or "").strip(),
        (body or "").strip(),
        (flair or "").strip(),
        (op_comments or "").strip(),
    ])
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
