#!/usr/bin/env bash
#
# Daily PUBLISH: compute fresh data -> build the static dashboard -> deploy to GitHub Pages.
#
# This is `compute.sh` + a frontend build + a one-line deploy, meant to be run once a day by
# launchd (see scripts/com.niw.publish.plist.example). It is safe to re-run and resumable:
# the pipeline is incremental (only new/changed Reddit posts are pulled and classified).
#
# Usage:
#   ./scripts/publish.sh                 # real extraction via your local `claude` subscription (no API key)
#   ./scripts/publish.sh mock            # fast heuristic run, NO LLM (great for a dry-run / demo)
#   NIW_HEALTHCHECK_URL=https://hc-ping.com/<uuid> ./scripts/publish.sh   # ping a dead-man's-switch on success
#
# Deploy target: the `gh-pages` branch of this repo's `origin` remote, force-pushed as a single
# commit each run (so a fresh ~10MB snapshot.json never accumulates branch history). Turn it on
# once in the repo: Settings -> Pages -> Deploy from a branch -> gh-pages / (root).
#
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root (scripts/ is one level down)

# Publish the PII-scrubbed snapshot: drops post body, OP comments, and username (all detected
# PII lives in the body text). Re-file flags are computed server-side before the username is
# stripped. A local `./compute.sh` without this env still writes the full snapshot for dev.
export NIW_PUBLIC_SNAPSHOT=1

BACKEND="${1:-claude-cli}"
HEALTHCHECK_URL="${NIW_HEALTHCHECK_URL:-}"

# "<processed> <failed>" for the active prompt/schema version (same numbers `niw status` shows).
# Used to diff the classify batch around compute.sh so a broken run can't deploy silently.
classify_counts() {
  PYTHONPATH=src .venv/bin/python -c '
from niw_stats.classify.service import COMPOSITE, active_identity
from niw_stats.config import get_settings
from niw_stats.db import connection
from niw_stats.db import repository as repo

s = get_settings()
conn = connection.connect(s.db_path)
try:
    pv, sv, view_run = active_identity(s, conn)
    c = repo.counts(conn, pv, sv, None if view_run == COMPOSITE else view_run)
finally:
    conn.close()
print(c["active_processed_count"], c["failed_count"])
'
}

echo "===== publish start: $(date -u '+%Y-%m-%dT%H:%M:%SZ')  backend=${BACKEND} ====="

# 1. Compute: incremental ingest + classify (only NEW posts) + write frontend/public/snapshot.json.
#    Uses your already-logged-in local `claude` CLI — $0 marginal on your subscription.
read -r PRE_PROCESSED PRE_FAILED < <(classify_counts || echo "0 0")
./compute.sh "$BACKEND"
read -r POST_PROCESSED POST_FAILED < <(classify_counts)

# 1b. Deploy gate: if this batch mostly failed to classify (expired `claude` login, API outage),
#     abort BEFORE build/deploy so launchd exits non-zero and the healthcheck ping never fires --
#     otherwise a dead classifier silently force-pushes a stale snapshot and reports "healthy".
#     Threshold: abort when >=20% of the batch failed (covers the observed all-failed OAuth case
#     while tolerating the occasional one-off timeout on a long post).
BATCH=$((POST_PROCESSED - PRE_PROCESSED)); [ "$BATCH" -lt 0 ] && BATCH=0
NEW_FAILED=$((POST_FAILED - PRE_FAILED)); [ "$NEW_FAILED" -lt 0 ] && NEW_FAILED=0
echo "classify batch: ${BATCH} posts, ${NEW_FAILED} new failures (${POST_FAILED} failed total)"
if [ "$NEW_FAILED" -gt 0 ] && [ $((NEW_FAILED * 5)) -ge "$BATCH" ]; then
  echo "ABORT: ${NEW_FAILED}/${BATCH} of this batch failed to classify; refusing to deploy." >&2
  echo "       Check \`claude\` CLI auth (run: claude /login), delete the failed rows, re-run." >&2
  exit 1
fi

# 2. Build the static site. `make build-frontend` runs `niw snapshot` then `vite build` and copies
#    snapshot.json into frontend/dist. With base="./" in vite.config.ts the asset paths are relative,
#    so the build works under the GitHub Pages /<repo>/ subpath.
make build-frontend

# 2b. Safety gate: refuse to deploy if the built snapshot still carries PII (a regression guard
#     in case NIW_PUBLIC_SNAPSHOT is ever unset or to_slim_public changes). Aborts before push.
.venv/bin/python scripts/pii_audit.py frontend/dist/snapshot.json --assert-clean

# 3. Deploy: publish frontend/dist as a single-commit gh-pages branch on origin.
#    Vite wipes dist/ on every build, so the throwaway git repo created here is always clean.
REMOTE="$(git remote get-url origin)"
(
  cd frontend/dist
  touch .nojekyll                # belt-and-suspenders: stop GitHub Pages' Jekyll from eating /assets
  rm -rf .git                    # Vite preserves dist/.git across builds, so drop last deploy's repo
  git init -q
  git checkout -q -b gh-pages
  git add -A
  git -c user.email=publish@local -c user.name=niw-publish commit -qm "deploy $(date -u +%F)"
  git push -fq "$REMOTE" gh-pages
)

# 4. Success heartbeat. Only reached if every step above succeeded (set -e). If the run fails,
#    no ping fires and healthchecks.io emails you that a day was missed.
if [ -n "$HEALTHCHECK_URL" ]; then
  curl -fsS --max-time 10 "$HEALTHCHECK_URL" >/dev/null || true
fi

echo "===== publish OK: $(date -u '+%Y-%m-%dT%H:%M:%SZ') ====="
