# NIW Stats — r/EB2_NIW approval/denial data

Pull EB-2 NIW (I-140 National Interest Waiver) **approval/denial** data points shared on
[r/EB2_NIW](https://www.reddit.com/r/EB2_NIW/), have an LLM extract structured fields from each
post, and explore the distributions on a **local website**.

> ⚠️ The data is **self-reported** by Reddit users and unverifiable. This is a descriptive
> exploration tool, not ground truth.

## What it extracts (per qualifying post)

Outcome (approved/denied) · degree · proposed endeavor field · publications · citations ·
years of experience · processing time (receipt → decision) · premium processing (vs regular) ·
whether the case received an RFE (+ RFE date / response date) · law firm (incl. DIY/self-petition).

Only posts reporting a **final I-140 NIW approval or denial** are counted — discussion,
questions, RFE-without-outcome, and I-485 posts are filtered out.

The classifier reads each post's title/body/flair **and the OP's own follow-up comments** — people
often reveal their field, premium-vs-regular, RFE, or citation count only in replies, not the post.

## Architecture

```
Arctic Shift (bulk .zst dump │ API cursor) ─► ingest (upsert by Reddit id) ─► raw_posts
claude CLI / mock ─► classify (cached by content-hash + version) ─► classified_records
SQLite ─► stats/aggregate ─► FastAPI /api/* ─► React dashboard (local)
                          └─► snapshot.json ─► static site ($0 external hosting)
```

## Quick start — two commands

Prerequisites: `python3.10` (or set `PYTHON=...`) and Node/`npm`. Both scripts self-bootstrap the
environment on first run.

```bash
./compute.sh      # pull r/EB2_NIW -> classify (your `claude` CLI) -> write the dashboard data
./serve.sh        # build (first run) + serve the dashboard at http://localhost:8000
```

- **First `./compute.sh`** does a full ~2-year backfill then classifies; later runs are incremental
  (only new/changed posts are pulled, only un-classified posts hit the LLM). Safe to re-run; resumable.
- Quick no-LLM demo: `./compute.sh mock`. Partial/resumable run: `./compute.sh claude-cli 200`.
- Different port: `PORT=8080 ./serve.sh`.

### Manual / advanced

```bash
/opt/homebrew/bin/python3.10 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export PYTHONPATH=src                       # see note below
.venv/bin/niw init-db
.venv/bin/niw backfill --dump ~/Downloads/EB2_NIW.zst   # bulk dump (arctic-shift.photon-reddit.com/download-tool)
.venv/bin/niw backfill --via-api --days 730             # ...or straight from the API
.venv/bin/niw classify --backend claude-cli             # or --backend mock for a dry run
.venv/bin/niw classify --backend claude-cli --workers 6 # parallel LLM calls (faster; default 4)
.venv/bin/niw snapshot
( cd frontend && npm install && npm run build )
.venv/bin/niw serve                                     # -> http://localhost:8000
```

> Note: invoke the CLI as `PYTHONPATH=src .venv/bin/niw …` if `niw` can't find the package
> (an editable-install quirk in some shells). The two scripts above already handle this.

## Long classification runs

`niw classify` / `niw refresh` show a live, in-place progress display (config, bar, elapsed/ETA,
ok/excluded/failed tally, cumulative `$` usage), and are robust for long runs:

- **Resumable checkpoint** — already-classified posts are skipped and each result is written
  immediately, so re-running the same command continues exactly where it left off (Ctrl-C safe).
- **Waits out usage limits** — if the `claude`/`codex` CLI reports a usage limit, it pauses, shows a
  "resuming ≈HH:MM" countdown, and continues automatically once the limit clears (no lost work).
- **Timeout backoff** — subprocess timeouts retry with exponential delays controlled by
  `NIW_CLASSIFY_TIMEOUT_BACKOFF_SEC` (default 5s) and `NIW_CLASSIFY_TIMEOUT_BACKOFF_MAX_SEC`
  (default 60s). Usage-limit waits use their own reset/poll flow.
- **Parallelism** — `--workers N` (or `NIW_CLASSIFY_WORKERS=N`); usage-limit poll interval via
  `NIW_LIMIT_POLL_INTERVAL` (default 300s). The OP-comment fetch overlaps the LLM calls inside the
  worker threads, so it doesn't add a serial up-front wait.

```bash
NIW_CLASSIFY_WORKERS=6 ./compute.sh claude-cli      # full run, 6 parallel calls, resumable
```

**Cost & time (measured, Sonnet via the `claude` CLI).** ~4,190 candidates ≈ **5–7 h at 4 workers**
(~4.5 h at 6), resumable, plus any usage-limit waits. Per-call cost is dominated by the Claude Code
CLI shipping ~44K tokens of its own harness prompt per invocation (not our prompt or the post), so a
full run is **~$150–250** of subscription-equivalent usage — much of it prompt-cache creation that
falls once the cache is warm. Smoke-test first and read the live ETA/`$` before committing:

```bash
time PYTHONPATH=src .venv/bin/niw classify --backend claude-cli --workers 4 --limit 20
```

## Comparing models / runs

A classification **run** is identified by `(backend, model, effort, label)` — its `run_key` is e.g.
`claude-cli/sonnet`, `claude-cli/haiku`, or `claude-cli/sonnet#promptB`. Running the same dataset
under a different model or `--label` writes a **separate** run (no clobbering), so you can compare
them. The dashboard's **Model picker** shows each run plus a **Composite** view (default) that takes,
per post, the **majority-vote outcome across runs**, breaking ties by the most recent run.

```bash
PYTHONPATH=src .venv/bin/niw classify --backend claude-cli --workers 6                        # claude-cli/sonnet
NIW_CLAUDE_MODEL=haiku PYTHONPATH=src .venv/bin/niw classify --backend claude-cli --workers 6  # claude-cli/haiku
PYTHONPATH=src .venv/bin/niw runs                                                              # list runs + counts
PYTHONPATH=src .venv/bin/niw classify --backend claude-cli --label promptB                     # tag an A/B variant
PYTHONPATH=src .venv/bin/niw clear-classifications --run claude-cli/haiku                       # drop one run
```

## Staying fresh

`niw refresh` does an incremental API pull + classify + snapshot, all idempotent
(deduped by Reddit post id; only new/changed posts hit the LLM). Schedule it daily via the
`scripts/com.niw.refresh.plist.example` launchd template or cron.

## Development

```bash
.venv/bin/pytest            # Python unit + API tests (no network, no LLM — uses the mock backend)
cd frontend && npm test     # frontend + client-aggregation parity tests
```

## How it scales

`niw refresh` is the daily driver: incremental API pull (deduped by Reddit post id) + classify
(only new/changed posts hit the LLM, cached by content hash + prompt/schema version) + snapshot.
Schedule it with `scripts/com.niw.refresh.plist.example`. Bump `PROMPT_VERSION`/`SCHEMA_VERSION` in
`src/niw_stats/classify/prompt.py` to safely re-classify into new rows (old rows retained for rollback).

For cheap external hosting, deploy the static `frontend/dist` (which bundles `snapshot.json`) to any
CDN — the dashboard aggregates entirely client-side, so there's no server to run.

## Publish as a public website ($0, daily)

`scripts/publish.sh` chains the daily driver into a live site: `./compute.sh` (incremental
ingest + classify on your local `claude` subscription — no API key) → `make build-frontend` →
force-push `frontend/dist` to a **`gh-pages`** branch, served free by **GitHub Pages**. The build
uses `base: "./"` (relative asset paths) so it works under the `https://<you>.github.io/<repo>/`
subpath, and `frontend/public/.nojekyll` stops Jekyll from dropping the `assets/` dir.

One-time setup:

```bash
git init && gh repo create niw-stats --public --source=. --remote=origin --push   # data/ and *.db stay gitignored
./scripts/publish.sh                       # first run does the full backfill, builds, pushes gh-pages
# then: repo Settings → Pages → Deploy from a branch → gh-pages / (root)
```

Schedule the daily refresh with the `scripts/com.niw.publish.plist.example` launchd template
(runs the missed job on next wake, so a sleeping laptop just catches up). Set `NIW_HEALTHCHECK_URL`
to a free [healthchecks.io](https://healthchecks.io) check to be emailed if a daily run is ever
missed. If traffic ever outgrows GitHub Pages' ~100 GB/mo, swap the deploy line for a Cloudflare
Pages `wrangler pages deploy frontend/dist` (unlimited bandwidth).
