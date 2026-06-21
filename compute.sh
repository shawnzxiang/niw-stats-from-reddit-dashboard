#!/usr/bin/env bash
#
# Compute the dataset in ONE command:
#   pull r/EB2_NIW posts from Arctic Shift  ->  classify with an LLM  ->  write the dashboard snapshot.
#
# First run does a full ~2-year backfill; later runs are incremental (only new/changed posts are
# pulled, and only un-classified posts hit the LLM — it's safe to re-run and resumable if interrupted).
#
# Usage:
#   ./compute.sh                       # real extraction via your local `claude` CLI  (default; no API key)
#   ./compute.sh mock                  # fast heuristic run, NO LLM  (great for a quick demo)
#   ./compute.sh claude-cli 200        # classify at most 200 posts this run, then re-run to continue
#   NIW_CLASSIFY_WORKERS=6 ./compute.sh claude-cli   # 6 parallel LLM calls (faster; default is 4)
#
# A live progress bar is shown during classification.
#
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH=src

BACKEND="${1:-claude-cli}"
LIMIT="${2:-}"
PYTHON_BIN="${PYTHON:-python3.10}"

# 1. One-time environment bootstrap.
if [ ! -x .venv/bin/niw ]; then
  echo "▶ First run: setting up the Python environment…"
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN=python3
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ".[dev]"
fi

# 2. Ingest (full 2-yr backfill on first run, incremental after) + classify + snapshot.
echo "▶ Computing data — backend: ${BACKEND}${LIMIT:+, limit: $LIMIT}"
if [ -n "$LIMIT" ]; then
  .venv/bin/niw refresh --backend "$BACKEND" --limit "$LIMIT"
else
  .venv/bin/niw refresh --backend "$BACKEND"
fi

echo
echo "✅ Data computed. Run ./serve.sh to open the dashboard."
