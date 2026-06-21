"""Stream a downloaded Arctic Shift / Academic-Torrents dump into post dicts.

Supports ``.zst`` (zstandard NDJSON), ``.jsonl``/``.ndjson`` and ``.json`` (array or
NDJSON). Only submission objects (those with a ``title``) are yielded, so a combined
posts+comments dump is handled gracefully.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path

import zstandard

PathLike = str | Path


def _iter_zst_lines(path: Path) -> Iterator[str]:
    # Pushshift/Arctic dumps use a large compression window — allow it explicitly.
    dctx = zstandard.ZstdDecompressor(max_window_size=2**31)
    with open(path, "rb") as fh, dctx.stream_reader(fh) as reader:
        text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        for line in text:
            line = line.strip()
            if line:
                yield line


def _iter_text_lines(path: Path) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


def _is_submission(obj: object) -> bool:
    return isinstance(obj, dict) and "id" in obj and "title" in obj


def iter_dump_file(path: PathLike) -> Iterator[dict]:
    """Yield submission dicts from a dump file (format inferred from extension)."""
    path = Path(path)
    suffixes = {s.lower() for s in path.suffixes}

    if path.suffix.lower() == ".zst":
        lines = _iter_zst_lines(path)
    elif suffixes & {".jsonl", ".ndjson"}:
        lines = _iter_text_lines(path)
    elif path.suffix.lower() == ".json":
        # A .json file may be a single JSON array or NDJSON; detect by first char.
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(64).lstrip()
        if head.startswith("["):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for obj in data:
                if _is_submission(obj):
                    yield obj
            return
        lines = _iter_text_lines(path)
    elif path.suffix.lower() == ".zst_blocks":
        raise ValueError(
            ".zst_blocks is not supported; re-download as .zst or .jsonl from the "
            "Arctic Shift download tool."
        )
    else:
        raise ValueError(f"Unsupported dump extension: {path.suffix!r}")

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _is_submission(obj):
            yield obj
