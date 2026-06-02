from __future__ import annotations

from pathlib import Path

from core.task_model import DownloadTask, TaskStatus, utc_now_iso
from storage.database import get_connection, initialize_database


class TaskRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None
        initialize_database(self.db_path)

    def create_task(
        self,
        gid: str,
        name: str,
        url: str,
        save_path: str,
        status: str,
        total_length: int = 0,
        completed_length: int = 0,
        download_speed: int = 0,
        error_message: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        completed_at: str | None = None,
        resume_support: str | None = None,
        elapsed_seconds: int = 0,
        active_started_at: str | None = None,
    ) -> None:
        now = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO tasks (
                    gid, name, url, save_path, status, total_length,
                    completed_length, download_speed, error_message,
                    created_at, updated_at, completed_at, resume_support,
                    elapsed_seconds, active_started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gid,
                    name,
                    url,
                    save_path,
                    status,
                    total_length,
                    completed_length,
                    download_speed,
                    error_message,
                    created_at or now,
                    updated_at or now,
                    completed_at,
                    resume_support,
                    int(elapsed_seconds or 0),
                    active_started_at,
                ),
            )
            connection.commit()

    def upsert_from_download_task(self, task: DownloadTask) -> None:
        now = utc_now_iso()
        created_at = task.created_at or now
        updated_at = task.updated_at or now
        completed_at = task.completed_at or (now if task.is_completed else None)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    gid, name, url, save_path, status, total_length,
                    completed_length, download_speed, error_message,
                    created_at, updated_at, completed_at, resume_support,
                    elapsed_seconds, active_started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gid) DO UPDATE SET
                    name = excluded.name,
                    url = excluded.url,
                    save_path = excluded.save_path,
                    status = excluded.status,
                    total_length = excluded.total_length,
                    completed_length = excluded.completed_length,
                    download_speed = excluded.download_speed,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at,
                    completed_at = COALESCE(tasks.completed_at, excluded.completed_at),
                    resume_support = COALESCE(excluded.resume_support, tasks.resume_support),
                    elapsed_seconds = excluded.elapsed_seconds,
                    active_started_at = excluded.active_started_at
                """,
                (
                    task.gid,
                    task.name,
                    task.url,
                    task.save_path,
                    task.status,
                    int(task.total_length),
                    int(task.completed_length),
                    int(task.download_speed),
                    task.error_message,
                    created_at,
                    updated_at,
                    completed_at,
                    task.resume_support,
                    int(task.elapsed_seconds or 0),
                    task.active_started_at,
                ),
            )
            connection.commit()

    def list_all(self) -> list[DownloadTask]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT gid, name, url, save_path, status, total_length,
                       completed_length, download_speed, created_at,
                       updated_at, completed_at, error_message, resume_support,
                       elapsed_seconds, active_started_at
                FROM tasks
                ORDER BY
                    CASE
                        WHEN status = 'complete' THEN datetime(completed_at)
                        ELSE datetime(created_at)
                    END DESC,
                    id DESC
                """
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_by_gid(self, gid: str) -> DownloadTask | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT gid, name, url, save_path, status, total_length,
                       completed_length, download_speed, created_at,
                       updated_at, completed_at, error_message, resume_support,
                       elapsed_seconds, active_started_at
                FROM tasks
                WHERE gid = ?
                """,
                (gid,),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def mark_removed(self, gid: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?
                WHERE gid = ?
                """,
                (TaskStatus.REMOVED.value, utc_now_iso(), gid),
            )
            connection.commit()

    def update_resume_support(self, gid: str, resume_support: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET resume_support = ?, updated_at = ?
                WHERE gid = ?
                """,
                (resume_support, utc_now_iso(), gid),
            )
            connection.commit()

    def delete_by_gid(self, gid: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM tasks
                WHERE gid = ?
                """,
                (gid,),
            )
            connection.commit()

    def _connect(self):
        return get_connection(self.db_path)

    @staticmethod
    def _row_to_task(row) -> DownloadTask:
        return DownloadTask(
            gid=row["gid"],
            name=row["name"] or row["gid"],
            url=row["url"] or "",
            save_path=row["save_path"] or "",
            status=row["status"] or TaskStatus.UNKNOWN.value,
            total_length=int(row["total_length"] or 0),
            completed_length=int(row["completed_length"] or 0),
            download_speed=int(row["download_speed"] or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            error_message=row["error_message"],
            resume_support=row["resume_support"],
            elapsed_seconds=int(row["elapsed_seconds"] or 0),
            active_started_at=row["active_started_at"],
        )
