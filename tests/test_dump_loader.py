"""Dump loader streams submissions from .jsonl / .zst / .json, skipping non-posts."""

from __future__ import annotations

import json

import zstandard

from niw_stats.ingest.dump_loader import iter_dump_file

SUBS = [
    {"id": "a", "title": "Approved!", "created_utc": 1, "selftext": "x"},
    {"id": "b", "title": "Denied", "created_utc": 2, "selftext": "y"},
]
COMMENT = {"id": "c1", "body": "a comment, no title", "created_utc": 3}


def _write_ndjson(path, objs):
    path.write_text("\n".join(json.dumps(o) for o in objs) + "\n", encoding="utf-8")


def test_jsonl(tmp_path):
    f = tmp_path / "dump.jsonl"
    _write_ndjson(f, [*SUBS, COMMENT])
    out = list(iter_dump_file(f))
    assert [o["id"] for o in out] == ["a", "b"]  # comment skipped (no title)


def test_zst(tmp_path):
    payload = ("\n".join(json.dumps(o) for o in [*SUBS, COMMENT])).encode("utf-8")
    f = tmp_path / "dump.zst"
    f.write_bytes(zstandard.ZstdCompressor().compress(payload))
    out = list(iter_dump_file(f))
    assert [o["id"] for o in out] == ["a", "b"]


def test_json_array(tmp_path):
    f = tmp_path / "dump.json"
    f.write_text(json.dumps([*SUBS, COMMENT]), encoding="utf-8")
    out = list(iter_dump_file(f))
    assert [o["id"] for o in out] == ["a", "b"]


def test_skips_malformed_lines(tmp_path):
    f = tmp_path / "dump.jsonl"
    f.write_text(json.dumps(SUBS[0]) + "\nnot json\n" + json.dumps(SUBS[1]) + "\n", encoding="utf-8")
    assert [o["id"] for o in iter_dump_file(f)] == ["a", "b"]
