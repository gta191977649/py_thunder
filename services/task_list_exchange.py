from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from core.task_model import DownloadTask, TaskStatus, utc_now_iso


class TaskListExchangeError(ValueError):
    pass


@dataclass(slots=True)
class TaskListEntry:
    url: str
    save_path: str = ""
    name: str = ""
    status: str = TaskStatus.WAITING.value
    total_length: int = 0
    completed_length: int = 0
    created_at: str | None = None

    @property
    def is_incomplete(self) -> bool:
        return self.status not in {
            TaskStatus.COMPLETE.value,
            TaskStatus.REMOVED.value,
        }

    @classmethod
    def from_download_task(cls, task: DownloadTask) -> "TaskListEntry":
        return cls(
            url=task.url,
            save_path=task.save_path,
            name=task.name,
            status=task.status,
            total_length=int(task.total_length or 0),
            completed_length=int(task.completed_length or 0),
            created_at=task.created_at,
        )


class TaskListExchangeService:
    EXPORT_VERSION = 1

    def export_tasks(self, tasks: list[DownloadTask], path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix.lower() == ".txt":
            lines = [
                task.url.strip()
                for task in tasks
                if task.url.strip()
            ]
            content = "\n".join(lines) + ("\n" if lines else "")
            destination.write_text(content, encoding="utf-8")
            return destination

        payload = {
            "format": "pythunder-task-list",
            "version": self.EXPORT_VERSION,
            "exported_at": utc_now_iso(),
            "tasks": [
                asdict(TaskListEntry.from_download_task(task))
                for task in tasks
            ],
        }
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return destination

    def load_entries(self, path: str | Path) -> list[TaskListEntry]:
        source = Path(path)
        if not source.exists():
            raise TaskListExchangeError(f"Task list file was not found: {source}")

        suffix = source.suffix.lower()
        if suffix == ".txt":
            return self._load_text_entries(source)
        if suffix != ".json":
            raise TaskListExchangeError(
                f"Unsupported task list format: {source.suffix or '<no extension>'}"
            )
        return self._load_json_entries(source)

    def _load_text_entries(self, path: Path) -> list[TaskListEntry]:
        entries: list[TaskListEntry] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            entries.append(TaskListEntry(url=line))
        return entries

    def _load_json_entries(self, path: Path) -> list[TaskListEntry]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TaskListExchangeError(f"Failed to parse task list: {path}") from exc

        raw_entries: list[dict]
        if isinstance(payload, dict):
            tasks_value = payload.get("tasks", [])
            if not isinstance(tasks_value, list):
                raise TaskListExchangeError("Task list JSON does not contain a valid tasks array.")
            raw_entries = [entry for entry in tasks_value if isinstance(entry, dict)]
        elif isinstance(payload, list):
            raw_entries = [entry for entry in payload if isinstance(entry, dict)]
        else:
            raise TaskListExchangeError("Unsupported task list JSON structure.")

        entries: list[TaskListEntry] = []
        for entry in raw_entries:
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            entries.append(
                TaskListEntry(
                    url=url,
                    save_path=str(entry.get("save_path") or "").strip(),
                    name=str(entry.get("name") or "").strip(),
                    status=str(entry.get("status") or TaskStatus.WAITING.value).strip(),
                    total_length=int(entry.get("total_length") or 0),
                    completed_length=int(entry.get("completed_length") or 0),
                    created_at=entry.get("created_at"),
                )
            )
        return entries
