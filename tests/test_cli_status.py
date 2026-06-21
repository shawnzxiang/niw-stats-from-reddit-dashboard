"""CLI status/provenance reporting."""

from __future__ import annotations

from conftest import make_cls, make_raw
from typer.testing import CliRunner

from niw_stats.classify import service
from niw_stats.cli import app
from niw_stats.config import get_settings
from niw_stats.db import connection
from niw_stats.db import repository as repo


def test_status_reports_active_identity_and_pending_count(tmp_path, monkeypatch):
    db_path = tmp_path / "status.db"
    conn = connection.connect(db_path)
    try:
        repo.upsert_raw_posts(conn, [
            make_raw("a", is_candidate=1),
            make_raw("b", is_candidate=1),
        ])
        repo.upsert_classification(conn, make_cls(
            "a",
            prompt_version=service.PROMPT_VERSION,
            schema_version=service.SCHEMA_VERSION,
            classifier_backend="mock",
        ))
    finally:
        conn.close()

    monkeypatch.setenv("NIW_DB_PATH", str(db_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["status"])
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 0
    assert "view" in result.output
    assert f"composite {service.PROMPT_VERSION}/{service.SCHEMA_VERSION}" in result.output
    assert "runs" in result.output              # the runs line lists what's present
    assert "processed        1" in result.output
    assert "pending          1" in result.output
    assert "partial          True" in result.output
