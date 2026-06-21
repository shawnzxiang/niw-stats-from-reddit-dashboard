"""Runtime configuration, sourced from environment (prefix ``NIW_``) or ``.env``.

Examples::

    NIW_CLASSIFIER_BACKEND=mock
    NIW_DB_PATH=/tmp/test.db
    NIW_CLAUDE_MODEL=opus
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NIW_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Data source
    subreddit: str = "EB2_NIW"
    arctic_base_url: str = "https://arctic-shift.photon-reddit.com"
    request_rate_per_sec: float = 1.5
    request_timeout_sec: float = 30.0
    request_max_retries: int = 6

    # Storage
    db_path: Path = Path("data/niw.db")

    # Classifier
    classifier_backend: str = "claude-cli"  # claude-cli | codex-cli | mock
    claude_bin: str = "claude"
    codex_bin: str = "codex"
    claude_model: str = "sonnet"  # Claude "effort" == model choice (sonnet | opus | haiku)
    codex_model: str = ""  # empty -> use codex's configured default model
    codex_reasoning_effort: str = "low"  # minimal | low | medium | high (extraction is simple)
    classify_workers: int = 4  # parallel LLM calls; sweet spot for the claude CLI (override per-run)
    classify_retries: int = 3
    classify_timeout_sec: int = 120
    classify_timeout_backoff_sec: float = 5.0
    classify_timeout_backoff_max_sec: float = 60.0
    classify_max_budget_usd: float = 0.5
    limit_poll_interval: int = 300  # seconds to wait before retrying after a usage limit
    fetch_op_comments: bool = True  # pull the OP's own comments and feed them to the LLM
    op_comments_max_chars: int = 4000  # cap concatenated OP-comment text in the prompt

    # Run identity: a classification run is (backend, model, effort, label). Re-running the
    # same dataset under a different model/label produces a SEPARATE run (no clobbering), so
    # you can compare models. `run_label` is a free-form tag to distinguish runs.
    run_label: str = ""
    # Which run stats/snapshot/serve show by default: "composite" (per-post majority vote
    # across all runs, most-recent breaking ties) or a specific run_key (e.g. "claude-cli/haiku").
    view_run: str = "composite"

    # Output
    snapshot_path: Path = Path("frontend/public/snapshot.json")
    # When set (NIW_PUBLIC_SNAPSHOT=1), the snapshot drops PII (post body, OP comments, username)
    # for public hosting. Re-file flags are computed server-side first so the badge still works.
    public_snapshot: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
