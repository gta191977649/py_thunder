from __future__ import annotations

import sqlite3
from pathlib import Path

from app.paths import get_database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gid TEXT UNIQUE,
    name TEXT,
    url TEXT,
    save_path TEXT,
    status TEXT,
    total_length INTEGER DEFAULT 0,
    completed_length INTEGER DEFAULT 0,
    download_speed INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT,
    updated_at TEXT,
    completed_at TEXT,
    resume_support TEXT,
    elapsed_seconds INTEGER DEFAULT 0,
    active_started_at TEXT
);
"""


def _ensure_task_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    if "completed_at" not in columns:
        connection.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
    if "resume_support" not in columns:
        connection.execute("ALTER TABLE tasks ADD COLUMN resume_support TEXT")
    if "elapsed_seconds" not in columns:
        connection.execute(
            "ALTER TABLE tasks ADD COLUMN elapsed_seconds INTEGER DEFAULT 0"
        )
    if "active_started_at" not in columns:
        connection.execute("ALTER TABLE tasks ADD COLUMN active_started_at TEXT")
    connection.execute(
        """
        UPDATE tasks
        SET completed_at = COALESCE(completed_at, updated_at, created_at)
        WHERE status = 'complete' AND completed_at IS NULL
        """
    )


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path else get_database_path()
    with get_connection(path) as connection:
        connection.executescript(SCHEMA)
        _ensure_task_columns(connection)
        connection.commit()
    return path
