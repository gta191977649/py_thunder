from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from core.task_model import DownloadTask, TaskStatus


def extract_task_url(task_data: dict) -> str:
    files = task_data.get("files") or []
    for file_info in files:
        uris = file_info.get("uris") or []
        for uri_info in uris:
            uri = uri_info.get("uri")
            if uri:
                return uri
    return ""


def extract_save_dir(task_data: dict) -> str:
    files = task_data.get("files") or []
    file_path = files[0].get("path", "") if files else ""
    if file_path:
        return str(Path(file_path).expanduser().resolve().parent)
    if task_data.get("dir"):
        return str(Path(task_data["dir"]).expanduser())
    return ""


def extract_task_name(task_data: dict) -> str:
    files = task_data.get("files") or []
    file_path = files[0].get("path", "") if files else ""
    if file_path:
        filename = Path(file_path).name
        if filename:
            return filename

    url = extract_task_url(task_data)
    if url:
        parsed = urlparse(url)
        name = Path(parsed.path).name
        if name:
            return name

    return task_data.get("gid", "Unknown Task")


def aria2_dict_to_download_task(task_data: dict) -> DownloadTask:
    status = task_data.get("status", TaskStatus.UNKNOWN.value)
    download_speed = int(task_data.get("downloadSpeed", 0) or 0)
    if status == TaskStatus.PAUSED.value:
        # aria2 may briefly report a decaying speed after pause; keep paused UI stable.
        download_speed = 0

    return DownloadTask(
        gid=task_data.get("gid", ""),
        name=extract_task_name(task_data),
        url=extract_task_url(task_data),
        save_path=extract_save_dir(task_data),
        status=status,
        total_length=int(task_data.get("totalLength", 0) or 0),
        completed_length=int(task_data.get("completedLength", 0) or 0),
        download_speed=download_speed,
        completed_at=None,
        error_message=task_data.get("errorMessage"),
        elapsed_seconds=0,
        active_started_at=None,
    )
