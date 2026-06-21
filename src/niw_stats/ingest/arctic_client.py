"""Thin HTTP client for the Arctic Shift posts API, with rate limiting + retries."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable

import httpx

from niw_stats.config import Settings

# Verified-valid `fields` set for /api/posts/search (permalink is NOT accepted here).
FIELDS = "id,title,selftext,link_flair_text,created_utc,author,score,num_comments,url,subreddit"
# Arctic Shift returns 422/408 transiently under load (the same request succeeds on
# retry), so treat them as retryable alongside the usual rate-limit/5xx statuses.
_RETRY_STATUS = {408, 422, 425, 429, 500, 502, 503, 504}


class ArcticClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s = settings
        self._client = client or httpx.Client(
            timeout=settings.request_timeout_sec, headers={"User-Agent": "niw-stats/0.1"}
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request = 0.0
        self._min_interval = 1.0 / max(settings.request_rate_per_sec, 0.01)
        self._lock = threading.Lock()  # rate limiter is shared across classify worker threads

    def __enter__(self) -> ArcticClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        with self._lock:
            wait = self._min_interval - (self._monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = self._monotonic()

    def _respect_headers(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        try:
            if remaining is not None and float(remaining) < 5 and reset is not None:
                self._sleep(min(float(reset), 60.0))
        except ValueError:
            pass

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(60.0, (2**attempt) + random.uniform(0, 1)))

    def _get(self, path: str, params: dict) -> list[dict]:
        url = f"{self.s.arctic_base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.s.request_max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as exc:  # network hiccup -> retry
                last_exc = exc
                self._backoff(attempt)
                continue
            if resp.status_code == 200:
                self._respect_headers(resp)
                data = resp.json()
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data if isinstance(data, list) else []
            if resp.status_code in _RETRY_STATUS:
                self._backoff(attempt)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Arctic Shift request failed after retries: {last_exc}")

    def fetch_page(self, *, after: int, before: int, limit: int = 100, sort: str = "asc") -> list[dict]:
        return self._get("/api/posts/search", {
            "subreddit": self.s.subreddit, "after": int(after), "before": int(before),
            "limit": limit, "sort": sort, "fields": FIELDS,
        })

    def fetch_comments(self, *, link_id: str, author: str | None = None, limit: int = 100) -> list[dict]:
        """Comments on a post (link_id = base36 post id), optionally filtered to one author."""
        params: dict = {
            "subreddit": self.s.subreddit, "link_id": link_id, "limit": limit, "sort": "asc",
            "fields": "id,author,body,created_utc,parent_id",
        }
        if author:
            params["author"] = author
        return self._get("/api/comments/search", params)
