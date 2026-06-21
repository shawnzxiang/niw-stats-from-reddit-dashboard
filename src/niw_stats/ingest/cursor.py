"""Date-cursor walk over the Arctic Shift API (it has no offset pagination).

``fetch_page(after, before)`` must return a list of post dicts (each with
``id`` and ``created_utc``) in the window; we advance ``after`` to the last
post's ``created_utc + 1`` until the window is exhausted. Termination is based on
*progress* (new ids yielded), so it is robust regardless of page size.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

FetchPage = Callable[[int, int], list[dict]]


def walk_window(fetch_page: FetchPage, after: int, before: int) -> Iterator[dict]:
    cursor = int(after)
    before = int(before)
    seen: set[str] = set()

    while cursor < before:
        page = fetch_page(cursor, before)
        if not page:
            break
        page = sorted(page, key=lambda p: p["created_utc"])

        progressed = False
        for post in page:
            ts = int(post["created_utc"])
            if ts >= before:
                continue
            pid = post.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            progressed = True
            yield post

        last_ts = max(int(p["created_utc"]) for p in page)
        next_cursor = last_ts + 1
        # No new ids and we can't move the cursor forward -> we're done.
        if not progressed and next_cursor <= cursor:
            break
        cursor = max(next_cursor, cursor + 1) if not progressed else next_cursor
        if not progressed:
            break
