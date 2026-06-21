"""CLI-subprocess classifier backends (no API key — uses the user's CLI subscription).

Default is ``claude`` (Claude Code) headless mode; ``codex`` is supported but not
the default. The subprocess ``runner``/``sleep``/``clock`` are injectable so the
retry, usage-limit-wait, and parse/validate logic are unit-testable without a real CLI.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable

from pydantic import ValidationError

from niw_stats.classify.base import ClassificationOutcome, Classifier, UsageLimitError
from niw_stats.classify.json_extract import extract_json_object
from niw_stats.classify.prompt import SYSTEM_PROMPT, build_user_prompt, json_schema
from niw_stats.config import Settings
from niw_stats.models import ExtractedFields

Runner = Callable[..., "subprocess.CompletedProcess"]

# Plan usage-limit messages (e.g. "Claude usage limit reached. Your limit will reset at 9pm").
# Transient 429/overload is NOT here — that's handled by the normal retry budget.
_LIMIT_RE = re.compile(
    r"usage limit reached|limit will reset|\blimit reached\b|resets? (?:at|in)|hour limit", re.I
)
_EPOCH_RE = re.compile(r"\b(1[6-9]\d{8})\b")  # a plausible 10-digit unix epoch (2023–2033)


def detect_usage_limit(text: str) -> tuple[bool, int | None]:
    """(is_limit, reset_epoch|None) for combined CLI stdout+stderr."""
    if not text or not _LIMIT_RE.search(text):
        return (False, None)
    m = _EPOCH_RE.search(text)
    return (True, int(m.group(1)) if m else None)


class _SubprocessBackend(Classifier):
    def __init__(
        self,
        settings: Settings,
        *,
        runner: Runner = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        on_wait: Callable[[float, int | None], None] | None = None,
    ) -> None:
        self.s = settings
        self._runner = runner
        self._sleep = sleep
        self._clock = clock
        self.on_wait = on_wait  # called while waiting out a usage limit

    # --- to be provided by concrete backends ---
    def _argv(self) -> list[str]:
        raise NotImplementedError

    def _compose_prompt(
        self, title: str, body: str | None, flair: str | None, op_comments: str | None
    ) -> str:
        """The prompt sent on stdin. Claude passes the system prompt via a CLI flag;
        backends without one (Codex) prepend it here so the model gets the rules."""
        return build_user_prompt(title, body, flair, op_comments)

    def _parse(self, stdout: str) -> tuple[dict, float | None]:
        """Return (fields_dict, cost_usd|None) from raw stdout. Default: plain JSON."""
        return extract_json_object(stdout), None

    @property
    def _model(self) -> str | None:
        return None

    def _env(self) -> dict[str, str] | None:
        """Subprocess environment; None inherits the parent's."""
        return None

    def _invoke(self, prompt: str) -> str:
        kwargs: dict = dict(
            input=prompt, capture_output=True, text=True, timeout=self.s.classify_timeout_sec
        )
        env = self._env()
        if env is not None:
            kwargs["env"] = env
        proc = self._runner(self._argv(), **kwargs)
        combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        limited, reset_at = detect_usage_limit(combined)
        if limited:
            raise UsageLimitError(f"{self.backend_name} usage limit reached", reset_at=reset_at)
        if proc.returncode != 0:
            raise RuntimeError(f"{self.backend_name} exited {proc.returncode}: {(proc.stderr or '')[:300]}")
        return proc.stdout or ""

    def _wait_for_limit(self, exc: UsageLimitError) -> None:
        now = self._clock()
        if exc.reset_at and exc.reset_at > now:
            remaining = (exc.reset_at - now) + 5  # small buffer past the reset
        else:
            remaining = float(self.s.limit_poll_interval)
        while remaining > 0:
            if self.on_wait:
                self.on_wait(remaining, exc.reset_at)
            step = min(remaining, 15.0)
            self._sleep(step)
            remaining -= step

    def _invoke_resilient(self, prompt: str) -> str:
        """Invoke, waiting out (and retrying through) any usage limit until it clears."""
        while True:
            try:
                return self._invoke(prompt)
            except UsageLimitError as exc:
                self._wait_for_limit(exc)

    def _timeout_backoff(self, attempt: int) -> float:
        base = max(float(self.s.classify_timeout_backoff_sec), 0.0)
        cap = max(float(self.s.classify_timeout_backoff_max_sec), 0.0)
        if base <= 0 or cap <= 0:
            return 0.0
        return min(cap, base * (2**attempt))

    def classify(
        self, *, title: str, body: str | None, flair: str | None, op_comments: str | None = None
    ) -> ClassificationOutcome:
        base_prompt = self._compose_prompt(title, body, flair, op_comments)
        last_reason: str | None = None
        last_output: str | None = None
        max_attempts = max(self.s.classify_retries, 1)
        for attempt in range(max_attempts):
            prompt = base_prompt
            if attempt > 0:
                prompt += "\n\nReturn ONLY the JSON object matching the schema. No prose, no fences."
            try:
                last_output = self._invoke_resilient(prompt)
                obj, cost = self._parse(last_output)
                fields = ExtractedFields.model_validate(obj)
                return ClassificationOutcome(
                    status="ok", fields=fields, raw_output=last_output, model=self._model, cost_usd=cost
                )
            except subprocess.TimeoutExpired as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
                if attempt < max_attempts - 1:
                    delay = self._timeout_backoff(attempt)
                    if delay > 0:
                        self._sleep(delay)
            except (ValueError, ValidationError, RuntimeError) as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
        return ClassificationOutcome(
            status="failed", failure_reason=last_reason, raw_output=last_output, model=self._model
        )


class ClaudeCliBackend(_SubprocessBackend):
    backend_name = "claude-cli"

    @property
    def _model(self) -> str | None:
        return self.s.claude_model

    def _env(self) -> dict[str, str]:
        # `claude` refuses to launch nested inside another Claude Code session; strip the
        # markers so this works whether or not it's invoked from within one.
        env = dict(os.environ)
        for var in ("CLAUDECODE", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT"):
            env.pop(var, None)
        return env

    def _argv(self) -> list[str]:
        return [
            self.s.claude_bin, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(json_schema()),
            "--append-system-prompt", SYSTEM_PROMPT,
            "--tools", "",
            "--model", self.s.claude_model,
            "--max-budget-usd", str(self.s.classify_max_budget_usd),
            "--permission-mode", "dontAsk",
            "--no-session-persistence",
        ]

    def _parse(self, stdout: str) -> tuple[dict, float | None]:
        # Claude's --output-format json wraps the result; prefer structured_output, and
        # read the reported cost.
        envelope = json.loads(stdout)
        cost = None
        obj: dict | None = None
        if isinstance(envelope, dict):
            raw_cost = envelope.get("total_cost_usd", envelope.get("cost_usd"))
            cost = float(raw_cost) if raw_cost is not None else None
            if isinstance(envelope.get("structured_output"), dict):
                obj = envelope["structured_output"]
            elif isinstance(envelope.get("result"), str):
                obj = extract_json_object(envelope["result"])
        if obj is None:
            obj = extract_json_object(stdout)
        return obj, cost


class CodexCliBackend(_SubprocessBackend):
    backend_name = "codex-cli"

    @property
    def _model(self) -> str | None:
        return self.s.codex_model or f"codex({self.s.codex_reasoning_effort})"

    def _compose_prompt(
        self, title: str, body: str | None, flair: str | None, op_comments: str | None
    ) -> str:
        # `codex exec` has no separate system-prompt flag here, so prepend the rules.
        return f"{SYSTEM_PROMPT}\n\n{build_user_prompt(title, body, flair, op_comments)}"

    def _argv(self) -> list[str]:
        # `codex exec` writes only the final agent message to stdout (logs -> stderr),
        # so the inherited json_extract handles it. Prompt is read from stdin (`-`).
        argv = [self.s.codex_bin, "exec", "--skip-git-repo-check", "--sandbox", "read-only"]
        if self.s.codex_model:
            argv += ["-m", self.s.codex_model]
        if self.s.codex_reasoning_effort:
            argv += ["-c", f"model_reasoning_effort={self.s.codex_reasoning_effort}"]
        argv += ["-"]
        return argv
