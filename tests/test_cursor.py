"""The date-cursor walk: dedup, boundary exclusion, and robust termination."""

from __future__ import annotations

from niw_stats.ingest.cursor import walk_window


def p(pid, ts):
    return {"id": pid, "created_utc": ts, "title": f"t{pid}"}


def scripted(pages):
    """A fetch_page that yields pre-recorded pages in order (ignores cursor args)."""
    queue = [list(pg) for pg in pages]

    def fetch(after, before):
        return queue.pop(0) if queue else []

    return fetch


def test_walks_pages_and_dedups_overlap():
    pages = [
        [p("1", 10), p("2", 20)],
        [p("2", 20), p("3", 30)],            # id 2 overlaps -> deduped
        [p("4", 40), p("9", 2000)],          # ts 2000 >= before -> excluded
        [],
    ]
    out = list(walk_window(scripted(pages), after=0, before=1000))
    assert [x["id"] for x in out] == ["1", "2", "3", "4"]


def test_empty_first_page_yields_nothing():
    assert list(walk_window(scripted([[]]), after=0, before=100)) == []


def test_short_page_then_empty_terminates():
    out = list(walk_window(scripted([[p("1", 5)]]), after=0, before=100))
    assert [x["id"] for x in out] == ["1"]


def test_terminates_when_no_progress_even_if_fetch_never_empties():
    calls = {"n": 0}

    def stuck(after, before):
        calls["n"] += 1
        assert calls["n"] < 50, "walk failed to terminate"
        return [p("1", 10)]  # always the same already-seen post

    out = list(walk_window(stuck, after=0, before=100))
    assert [x["id"] for x in out] == ["1"]
