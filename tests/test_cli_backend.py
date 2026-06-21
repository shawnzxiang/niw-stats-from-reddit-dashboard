"""The CLI subprocess harness: parse structured output, retry, and fail safely."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from niw_stats.classify.cli_backend import ClaudeCliBackend, CodexCliBackend
from niw_stats.config import Settings

GOOD = {"is_niw_i140_decision": True, "outcome": "approved"}


def runner_seq(outputs):
    """Fake subprocess.run returning queued (stdout, returncode) results."""
    state = {"n": 0}

    def run(argv, input=None, capture_output=True, text=True, timeout=None, env=None):
        i = state["n"]
        state["n"] += 1
        item = outputs[min(i, len(outputs) - 1)]
        if isinstance(item, Exception):
            raise item
        stdout, rc = item if isinstance(item, tuple) else (item, 0)
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="boom")

    run.state = state
    return run


def test_parses_structured_output():
    runner = runner_seq([json.dumps({"structured_output": GOOD})])
    out = ClaudeCliBackend(Settings(), runner=runner).classify(title="t", body="b", flair=None)
    assert out.status == "ok"
    assert out.fields.outcome.value == "approved"
    assert out.model == "sonnet"
    assert runner.state["n"] == 1


def test_falls_back_to_result_field_with_fences():
    envelope = {"result": f"```json\n{json.dumps(GOOD)}\n```"}
    runner = runner_seq([json.dumps(envelope)])
    out = ClaudeCliBackend(Settings(), runner=runner).classify(title="t", body="b", flair=None)
    assert out.status == "ok"


def test_retries_then_succeeds():
    runner = runner_seq(["I cannot help.", json.dumps({"structured_output": GOOD})])
    out = ClaudeCliBackend(Settings(classify_retries=3), runner=runner).classify(
        title="t", body="b", flair=None
    )
    assert out.status == "ok"
    assert runner.state["n"] == 2  # retried once


def test_nonzero_exit_is_retried():
    runner = runner_seq([("", 1), json.dumps({"structured_output": GOOD})])
    out = ClaudeCliBackend(Settings(classify_retries=3), runner=runner).classify(
        title="t", body="b", flair=None
    )
    assert out.status == "ok"
    assert runner.state["n"] == 2


def test_timeout_retries_with_exponential_backoff():
    runner = runner_seq([
        subprocess.TimeoutExpired(cmd="claude", timeout=120),
        subprocess.TimeoutExpired(cmd="claude", timeout=120),
        json.dumps({"structured_output": GOOD}),
    ])
    sleeps: list[float] = []
    out = ClaudeCliBackend(
        Settings(
            classify_retries=3,
            classify_timeout_backoff_sec=1.0,
            classify_timeout_backoff_max_sec=10.0,
        ),
        runner=runner,
        sleep=lambda s: sleeps.append(s),
    ).classify(title="t", body="b", flair=None)

    assert out.status == "ok"
    assert runner.state["n"] == 3
    assert sleeps == [1.0, 2.0]


def test_timeout_backoff_is_capped():
    runner = runner_seq([
        subprocess.TimeoutExpired(cmd="claude", timeout=120),
        subprocess.TimeoutExpired(cmd="claude", timeout=120),
        subprocess.TimeoutExpired(cmd="claude", timeout=120),
    ])
    sleeps: list[float] = []
    out = ClaudeCliBackend(
        Settings(
            classify_retries=3,
            classify_timeout_backoff_sec=5.0,
            classify_timeout_backoff_max_sec=6.0,
        ),
        runner=runner,
        sleep=lambda s: sleeps.append(s),
    ).classify(title="t", body="b", flair=None)

    assert out.status == "failed"
    assert runner.state["n"] == 3
    assert sleeps == [5.0, 6.0]


def test_persistent_garbage_fails_after_retries():
    runner = runner_seq(["still not json"])
    out = ClaudeCliBackend(Settings(classify_retries=2), runner=runner).classify(
        title="t", body="b", flair=None
    )
    assert out.status == "failed"
    assert out.failure_reason
    assert runner.state["n"] == 2  # exhausted the retry budget, no crash


def test_claude_argv_has_no_invalid_flags_and_strips_nested_session(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    b = ClaudeCliBackend(Settings())
    argv = b._argv()
    assert "--bare" not in argv  # not a real flag on claude v2.1.50
    assert "--json-schema" in argv and "--append-system-prompt" in argv and "-p" in argv
    assert "CLAUDECODE" not in b._env()  # nested-session marker removed for the subprocess


def test_parses_cost_from_claude_envelope():
    runner = runner_seq([json.dumps({"structured_output": GOOD, "total_cost_usd": 0.0123})])
    out = ClaudeCliBackend(Settings(), runner=runner).classify(title="t", body="b", flair=None)
    assert out.status == "ok"
    assert abs((out.cost_usd or 0) - 0.0123) < 1e-9


def test_waits_out_usage_limit_then_resumes():
    runner = runner_seq([
        "Claude usage limit reached. Your limit will reset at 9pm",  # 1st call: limited
        json.dumps({"structured_output": GOOD}),                      # 2nd call: succeeds
    ])
    sleeps: list[float] = []
    waits: list[tuple] = []
    b = ClaudeCliBackend(
        Settings(limit_poll_interval=300), runner=runner,
        sleep=lambda s: sleeps.append(s), clock=lambda: 1000.0,
    )
    b.on_wait = lambda remaining, reset: waits.append((remaining, reset))
    out = b.classify(title="t", body="b", flair=None)
    assert out.status == "ok"          # recovered after waiting, not failed
    assert runner.state["n"] == 2      # limited once, then retried
    assert sum(sleeps) >= 300          # waited ~the poll interval
    assert waits                       # the display was notified it was waiting


def test_usage_limit_does_not_consume_timeout_backoff():
    runner = runner_seq([
        "Claude usage limit reached. Your limit will reset at 9pm",
        json.dumps({"structured_output": GOOD}),
    ])
    sleeps: list[float] = []
    out = ClaudeCliBackend(
        Settings(
            limit_poll_interval=300,
            classify_timeout_backoff_sec=1.0,
            classify_timeout_backoff_max_sec=10.0,
        ),
        runner=runner,
        sleep=lambda s: sleeps.append(s),
        clock=lambda: 1000.0,
    ).classify(title="t", body="b", flair=None)

    assert out.status == "ok"
    assert runner.state["n"] == 2
    assert sleeps
    assert 1.0 not in sleeps and 2.0 not in sleeps
    assert sum(sleeps) >= 300


def test_usage_limit_waits_until_reset_epoch():
    runner = runner_seq([
        "usage limit reached; resets at 1700000300",
        json.dumps({"structured_output": GOOD}),
    ])
    sleeps: list[float] = []
    b = ClaudeCliBackend(Settings(), runner=runner, sleep=lambda s: sleeps.append(s), clock=lambda: 1700000000.0)
    out = b.classify(title="t", body="b", flair=None)
    assert out.status == "ok"
    assert 300 <= sum(sleeps) <= 320   # waited until ~the reset epoch (+ small buffer)


def test_codex_backend_prepends_system_prompt_and_sets_effort():
    captured: dict = {}

    def runner(argv, input=None, capture_output=True, text=True, timeout=None, env=None):
        captured["argv"] = argv
        captured["input"] = input
        return SimpleNamespace(returncode=0, stdout=json.dumps(GOOD), stderr="")

    settings = Settings(codex_model="gpt-5-codex", codex_reasoning_effort="low")
    out = CodexCliBackend(settings, runner=runner).classify(title="NIW approved", body="b", flair=None)

    assert out.status == "ok"
    # The system prompt (rules) must be present in the stdin prompt — Codex has no flag for it.
    assert "is_niw_i140_decision" in captured["input"]
    argv = " ".join(captured["argv"])
    assert "exec" in captured["argv"]
    assert "model_reasoning_effort=low" in argv
    assert "-m" in captured["argv"] and "gpt-5-codex" in captured["argv"]
