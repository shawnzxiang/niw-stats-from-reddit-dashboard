"""SQLite connection management and schema initialisation."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

PathLike = str | Path


def _schema_sql() -> str:
    return resources.files("niw_stats.db").joinpath("schema.sql").read_text(encoding="utf-8")


# Additive column migrations for databases created before a column existed.
# (CREATE TABLE IF NOT EXISTS won't add columns to an existing table.)
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "classified_records": [
        ("premium_processing", "INTEGER"),
        ("was_rfed", "INTEGER"),
        ("rfe_date", "TEXT"),
        ("rfe_response_date", "TEXT"),
        ("recommendation_letters", "INTEGER"),
        ("recommendation_letters_known", "INTEGER NOT NULL DEFAULT 0"),
        ("profession_raw", "TEXT"),
        ("profession_normalized", "TEXT"),
        ("patents", "INTEGER"),
        ("patents_known", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "raw_posts": [
        ("op_comments", "TEXT"),
    ],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not info:
            continue  # table doesn't exist yet (a fresh DB is handled by schema.sql)
        existing = {row[1] for row in info}
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def _migrate_run_key(conn: sqlite3.Connection) -> None:
    """Rebuild classified_records to add ``run_key`` to the primary key.

    A PK change can't be done with ALTER TABLE, so we rename the old table, recreate
    the new schema, and copy rows — backfilling ``run_key`` from backend/model so existing
    classifications land under a sensible run identity (e.g. ``claude-cli/sonnet``).
    """
    info = conn.execute("PRAGMA table_info(classified_records)").fetchall()
    if not info:
        return  # fresh DB: schema.sql already created the new table
    cols = {row[1] for row in info}
    if "run_key" in cols:
        return  # already migrated

    conn.executescript("ALTER TABLE classified_records RENAME TO classified_records_old;")
    conn.executescript(_schema_sql())  # recreate classified_records with the new PK (index name busy)
    old_cols = {r[1] for r in conn.execute("PRAGMA table_info(classified_records_old)")}
    new_cols = [r[1] for r in conn.execute("PRAGMA table_info(classified_records)")]
    shared = [c for c in new_cols if c in old_cols]  # copy every column both schemas share
    collist = ", ".join(shared)
    # run_key backfill: backend/model, falling back to backend when model is null.
    run_key_expr = "classifier_backend || '/' || COALESCE(NULLIF(classifier_model, ''), classifier_backend)"
    conn.execute(
        f"INSERT INTO classified_records ({collist}, run_key, run_label, run_effort) "
        f"SELECT {collist}, {run_key_expr}, '', '' FROM classified_records_old"
    )
    conn.executescript("DROP TABLE classified_records_old;")
    conn.executescript(_schema_sql())  # recreate the index now that the old one is gone
    conn.commit()


def connect(db_path: PathLike, *, ensure_schema: bool = True) -> sqlite3.Connection:
    """Open a connection with sane PRAGMAs. Creates parent dirs and schema by default."""
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if ensure_schema:
        conn.executescript(_schema_sql())
        conn.commit()
        _migrate(conn)
        _migrate_run_key(conn)
    return conn


def init_db(db_path: PathLike) -> None:
    """Create the database file and apply the schema (idempotent)."""
    conn = connect(db_path, ensure_schema=True)
    conn.close()
