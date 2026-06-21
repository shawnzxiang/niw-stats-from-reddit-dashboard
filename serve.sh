#!/usr/bin/env bash
#
# Build (first run only) and serve the dashboard in ONE command.
# Opens at http://localhost:8000 with the latest computed data.
#
# Usage:
#   ./serve.sh            # serve on port 8000
#   PORT=8080 ./serve.sh  # serve on a different port
#
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH=src
PORT="${PORT:-8000}"

if [ ! -x .venv/bin/niw ]; then
  echo "Please run ./compute.sh first — it sets up the environment and computes the data." >&2
  exit 1
fi

# 1. Build the frontend the first time (needs Node + npm).
if [ ! -f frontend/dist/index.html ]; then
  echo "▶ First run: building the dashboard (this takes a moment)…"
  ( cd frontend && npm install && npm run build )
fi

# 2. If a previous dashboard is still bound to the port, stop it so we can rebind.
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "▶ Port ${PORT} is busy — stopping the previous server…"
  kill $(lsof -ti:"$PORT") 2>/dev/null || true
  for _ in 1 2 3 4 5 6; do lsof -ti:"$PORT" >/dev/null 2>&1 || break; sleep 0.5; done
fi

# 3. Serve live data straight from the database: drop any bundled static snapshot so the page
#    always reflects the most recent ./compute.sh run.
rm -f frontend/dist/snapshot.json

echo
echo "▶ Dashboard ready:  http://localhost:${PORT}     (press Ctrl-C to stop)"
echo
exec .venv/bin/niw serve --port "$PORT"
