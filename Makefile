# Convenience targets. Uses a local venv built from Python 3.10+.
PYTHON ?= python3.10
VENV   := .venv
PYTEST := $(VENV)/bin/pytest
# PYTHONPATH=src keeps the CLI working even if an editable-install .pth isn't honoured.
NIW    := PYTHONPATH=src $(VENV)/bin/niw
FE     := npm --prefix frontend

.PHONY: bootstrap test test-py test-fe lint backfill-api classify refresh snapshot build-frontend serve e2e clean

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -e ".[dev]"
	$(FE) install

test: test-py test-fe

test-py:
	$(PYTEST) -q

test-fe:
	$(FE) run test
	$(FE) run typecheck

lint:
	$(VENV)/bin/ruff check src tests

backfill-api:
	$(NIW) init-db
	$(NIW) backfill --via-api --days 730

# Backfill from a downloaded Arctic Shift / Academic-Torrents dump: make load DUMP=path.zst
load:
	$(NIW) init-db
	$(NIW) load-dump $(DUMP)

classify:
	$(NIW) classify

refresh:
	$(NIW) refresh

snapshot:
	$(NIW) snapshot

build-frontend: snapshot
	$(FE) run build
	cp frontend/public/snapshot.json frontend/dist/snapshot.json

serve:
	$(NIW) serve

# Hermetic pipeline smoke test — no network, no LLM.
e2e:
	NIW_CLASSIFIER_BACKEND=mock NIW_DB_PATH=/tmp/niw_e2e.db NIW_SNAPSHOT_PATH=/tmp/niw_e2e.json sh -c '\
	  $(NIW) init-db && \
	  $(NIW) load-dump tests/fixtures/dump_slice.jsonl && \
	  $(NIW) classify --backend mock && \
	  $(NIW) snapshot --out /tmp/niw_e2e.json && \
	  $(NIW) stats --range 24m'

clean:
	rm -rf $(VENV) frontend/node_modules frontend/dist data/*.db data/*.db-* frontend/public/snapshot.json
