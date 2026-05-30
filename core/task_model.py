from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class TaskStatus(str, Enum):
    ACTIVE = "active"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    REMOVED = "removed"
    UNKNOWN = "unknown"


class ResumeSupport(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class DownloadTask:
    gid: str
    name: str
    url: str
    save_path: str
    status: str
    total_length: int = 0
    completed_length: int = 0
    download_speed: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    resume_support: str | None = None
    elapsed_seconds: int = 0
    active_started_at: str | None = None

    @property
    def progress(self) -> float:
        if self.total_length <= 0:
            return 0.0
        return min((self.completed_length / self.total_length) * 100.0, 100.0)

    @property
    def is_completed(self) -> bool:
        return self.status == TaskStatus.COMPLETE.value or (
            self.total_length > 0 and self.completed_length >= self.total_length
        )

    @property
    def status_enum(self) -> TaskStatus:
        try:
            return TaskStatus(self.status)
        except ValueError:
            return TaskStatus.UNKNOWN

    @property
    def can_resume(self) -> bool:
        if self.status_enum == TaskStatus.PAUSED:
            return True
        if self.status_enum in {TaskStatus.ERROR, TaskStatus.FAILED}:
            return bool(self.url)
        return (
            self.status_enum == TaskStatus.REMOVED
            and bool(self.url)
            and not self.is_completed
        )

    @property
    def can_pause(self) -> bool:
        return self.status_enum in {TaskStatus.ACTIVE, TaskStatus.WAITING}

    @property
    def can_remove(self) -> bool:
        return True

    def matches_filter(self, filter_key: str) -> bool:
        if filter_key == "all":
            return self.status_enum != TaskStatus.REMOVED
        if filter_key == "downloading":
            return self.status_enum in {TaskStatus.ACTIVE, TaskStatus.WAITING}
        if filter_key == "completed":
            return self.status_enum == TaskStatus.COMPLETE
        if filter_key == "paused":
            return self.status_enum == TaskStatus.PAUSED
        if filter_key == "failed":
            return self.status_enum in {TaskStatus.ERROR, TaskStatus.FAILED}
        if filter_key == "trash":
            return self.status_enum == TaskStatus.REMOVED
        return True

    def current_elapsed_seconds(self, now: datetime | None = None) -> int:
        elapsed = max(int(self.elapsed_seconds or 0), 0)
        if self.status_enum != TaskStatus.ACTIVE or not self.active_started_at:
            return elapsed
        started_at = parse_iso_datetime(self.active_started_at)
        if started_at is None:
            return elapsed
        now_dt = now or datetime.now(timezone.utc)
        return elapsed + max(int((now_dt - started_at).total_seconds()), 0)
