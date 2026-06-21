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

BACKEND="${1:-claude-cli}"
HEALTHCHECK_URL="${NIW_HEALTHCHECK_URL:-}"

echo "===== publish start: $(date -u '+%Y-%m-%dT%H:%M:%SZ')  backend=${BACKEND} ====="

# 1. Compute: incremental ingest + classify (only NEW posts) + write frontend/public/snapshot.json.
#    Uses your already-logged-in local `claude` CLI — $0 marginal on your subscription.
./compute.sh "$BACKEND"

# 2. Build the static site. `make build-frontend` runs `niw snapshot` then `vite build` and copies
#    snapshot.json into frontend/dist. With base="./" in vite.config.ts the asset paths are relative,
#    so the build works under the GitHub Pages /<repo>/ subpath.
make build-frontend

# 3. Deploy: publish frontend/dist as a single-commit gh-pages branch on origin.
#    Vite wipes dist/ on every build, so the throwaway git repo created here is always clean.
REMOTE="$(git remote get-url origin)"
(
  cd frontend/dist
  touch .nojekyll                # belt-and-suspenders: stop GitHub Pages' Jekyll from eating /assets
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
