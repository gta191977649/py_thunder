from __future__ import annotations

import math
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.aria2_client import Aria2Client, Aria2ConnectionError, Aria2RPCError
from core.formatters import format_speed
from core.piece_map import Aria2ControlFileParser, PieceMapSnapshot
from core.task_mapper import aria2_dict_to_download_task
from ui.task_table import TaskConnectionRow
from core.task_model import (
    DownloadTask,
    ResumeSupport,
    TaskStatus,
    parse_iso_datetime,
    utc_now_iso,
)
from services.os_integration import OSIntegrationService
from services.task_list_exchange import TaskListExchangeService
from storage.task_repository import TaskRepository


@dataclass(slots=True)
class TaskUiOverride:
    status: str
    completed_length: int | None = None
    total_length: int | None = None


@dataclass(slots=True)
class TaskRuntimeSnapshot:
    connection_rows: list[TaskConnectionRow]
    thread_count: int
    thread_lines: list[str]
    piece_map_snapshot: PieceMapSnapshot


@dataclass(slots=True)
class SyncResult:
    tasks: list[DownloadTask]
    task_error_message: str | None = None
    aria2_online: bool | None = None
    aria2_message: str = ""


@dataclass(slots=True)
class RuntimeDetailResult:
    connection_rows_by_gid: dict[str, list[TaskConnectionRow]]
    watched_task_gid: str | None = None
    watched_runtime_snapshot: TaskRuntimeSnapshot | None = None
    task_error_message: str | None = None


class DownloadManager(QObject):
    tasks_updated = pyqtSignal(list)
    runtime_details_updated = pyqtSignal()
    task_runtime_snapshot_updated = pyqtSignal(str, object)
    task_error = pyqtSignal(str)
    aria2_unavailable = pyqtSignal(str)
    _sync_result_ready = pyqtSignal(object)
    _runtime_detail_result_ready = pyqtSignal(object)

    def __init__(
        self,
        client: Aria2Client,
        repository: TaskRepository,
        refresh_interval_ms: int = 1000,
        os_service: OSIntegrationService | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.repository = repository
        self.os_service = os_service or OSIntegrationService()
        self._sync_client = Aria2Client(
            host=client.host,
            port=client.port,
            rpc_secret=client.rpc_secret,
            timeout=client.timeout,
        )
        self._detail_client = Aria2Client(
            host=client.host,
            port=client.port,
            rpc_secret=client.rpc_secret,
            timeout=client.timeout,
        )
        self.timer = QTimer(self)
        self.timer.setInterval(refresh_interval_ms)
        self.timer.timeout.connect(self.sync_tasks)
        self._sync_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="pythunder-sync",
        )
        self._detail_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="pythunder-runtime",
        )
        self._sync_future: Future | None = None
        self._detail_future: Future | None = None
        self._shutdown = False
        self._state_lock = threading.RLock()
        self._aria2_online: bool | None = None
        self._last_aria2_message = ""
        self._last_runtime_detail_sync_started = 0.0
        self._ui_state_overrides: dict[str, TaskUiOverride] = {}
        self._suppressed_deleted_gids: set[str] = set()
        self._piece_map_parser = Aria2ControlFileParser()
        self._piece_map_cache: dict[str, tuple[tuple[str, int, int], PieceMapSnapshot]] = {}
        self._connection_slot_count_by_gid: dict[str, int] = {}
        self._connected_servers_by_gid: dict[str, tuple[float, list[dict]]] = {}
        self._connected_peers_by_gid: dict[str, tuple[float, list[dict]]] = {}
        self._cached_connection_rows_by_gid: dict[str, list[TaskConnectionRow]] = {}
        self._runtime_snapshot_by_gid: dict[str, TaskRuntimeSnapshot] = {}
        self._observed_connection_row_gids: set[str] = set()
        self._watched_task_gid: str | None = None
        self._watched_task_default_slot_count = 16
        self._watched_task_max_display_cells = 8192
        self.task_list_exchange = TaskListExchangeService()
        self._sync_result_ready.connect(self._apply_sync_result)
        self._runtime_detail_result_ready.connect(self._apply_runtime_detail_result)

    def start(self) -> None:
        if not self.timer.isActive():
            self.timer.start()
        self.sync_tasks()

    def stop(self) -> None:
        self.timer.stop()
        self._shutdown = True
        self._sync_executor.shutdown(wait=False, cancel_futures=True)
        self._detail_executor.shutdown(wait=False, cancel_futures=True)

    def add_http_task(self, url: str, download_dir: str):
        return self.add_uri_task(url, download_dir)

    def add_uri_task(self, url: str, download_dir: str):
        normalized_url = url.strip()
        if not self._is_supported_source_url(normalized_url):
            raise ValueError("Please enter a valid download URL.")

        target_dir = Path(download_dir or "").expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        options, output_name = self._build_unique_uri_options(
            normalized_url,
            target_dir,
        )

        try:
            gid = self.client.add_uri([normalized_url], options)
            try:
                raw_task = self.client.tell_status(gid)
                task = aria2_dict_to_download_task(raw_task)
            except Aria2RPCError:
                task = DownloadTask(
                    gid=gid,
                    name=output_name or Path(urlparse(normalized_url).path).name or gid,
                    url=normalized_url,
                    save_path=str(target_dir),
                    status=TaskStatus.WAITING.value,
                    created_at=utc_now_iso(),
                )

            self.repository.upsert_from_download_task(task)
            self._set_aria2_state(True)
            self.sync_tasks()
            return gid
        except Aria2RPCError as exc:
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to add download task: {exc}")
            return None

    def add_uri_tasks(
        self,
        urls: list[str],
        download_dir: str,
    ) -> tuple[list[str], list[str]]:
        gids: list[str] = []
        errors: list[str] = []
        for url in urls:
            try:
                gid = self.add_uri_task(url, download_dir)
            except ValueError as exc:
                errors.append(f"{url}: {exc}")
                continue
            if gid:
                gids.append(gid)
            else:
                errors.append(url)
        return gids, errors

    def add_torrent_task(self, torrent_path: str, download_dir: str) -> str | None:
        source = Path(torrent_path).expanduser()
        if not source.exists():
            raise ValueError(f"Torrent file was not found: {source}")

        target_dir = Path(download_dir or "").expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            gid = self.client.add_torrent(str(source), {"dir": str(target_dir)})
            try:
                raw_task = self.client.tell_status(gid)
                task = aria2_dict_to_download_task(raw_task)
            except Aria2RPCError:
                task = DownloadTask(
                    gid=gid,
                    name=source.name,
                    url=source.as_uri(),
                    save_path=str(target_dir),
                    status=TaskStatus.WAITING.value,
                    created_at=utc_now_iso(),
                )

            self.repository.upsert_from_download_task(task)
            self._set_aria2_state(True)
            self.sync_tasks()
            return gid
        except Aria2RPCError as exc:
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to add torrent task: {exc}")
            return None

    def pause_task(self, gid: str) -> None:
        self.pause_tasks([gid])

    def resume_task(self, gid: str) -> None:
        self.resume_tasks([gid])

    def pause_tasks(self, gids: list[str]) -> None:
        self._run_task_actions("pause", gids, self.client.force_pause, "can_pause")

    def resume_tasks(self, gids: list[str]) -> None:
        self._run_resume_actions(gids)

    def remove_task(self, gid: str) -> None:
        existing_task = self.repository.get_by_gid(gid)
        try:
            self.client.remove(gid)
            self._ui_state_overrides.pop(gid, None)
            self._connection_slot_count_by_gid.pop(gid, None)
            self._connected_servers_by_gid.pop(gid, None)
            self._connected_peers_by_gid.pop(gid, None)
            self._cached_connection_rows_by_gid.pop(gid, None)
            self._runtime_snapshot_by_gid.pop(gid, None)
            self.repository.mark_removed(gid)
            self._set_aria2_state(True)
            self.sync_tasks()
        except Aria2RPCError as exc:
            if existing_task and existing_task.status_enum in {
                TaskStatus.COMPLETE,
                TaskStatus.ERROR,
                TaskStatus.FAILED,
                TaskStatus.REMOVED,
            }:
                self.repository.mark_removed(gid)
                self._emit_persisted_tasks()
                return
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to remove task: {exc}")

    def remove_tasks(self, gids: list[str]) -> None:
        for gid in gids:
            self.remove_task(gid)

    def permanently_delete_task(
        self,
        task: DownloadTask,
        *,
        delete_files: bool = False,
    ) -> None:
        self.permanently_delete_tasks([task], delete_files=delete_files)

    def permanently_delete_tasks(
        self,
        tasks: list[DownloadTask],
        *,
        delete_files: bool = False,
    ) -> None:
        any_deleted = False
        for task in tasks:
            if self._permanently_delete_single_task(task, delete_files=delete_files):
                any_deleted = True
        if any_deleted:
            self._emit_persisted_tasks()
            QTimer.singleShot(200, self.sync_tasks)

    def sync_tasks(self) -> None:
        if self._shutdown:
            return
        with self._state_lock:
            if self._sync_future is not None and not self._sync_future.done():
                return
            self._sync_future = self._sync_executor.submit(self._sync_tasks_worker)

    def _sync_tasks_worker(self) -> None:
        try:
            result = self._build_sync_result()
        except Aria2RPCError as exc:
            result = SyncResult(
                tasks=self.sort_tasks(self.repository.list_all()),
                aria2_online=False if isinstance(exc, Aria2ConnectionError) else None,
                aria2_message=str(exc) if isinstance(exc, Aria2ConnectionError) else "",
            )
        except Exception as exc:  # pragma: no cover - defensive UI safety
            result = SyncResult(
                tasks=self.sort_tasks(self.repository.list_all()),
                task_error_message=f"Unexpected sync error: {exc}",
            )
        self._sync_result_ready.emit(result)

    def _build_sync_result(self) -> SyncResult:
        repository_tasks = {task.gid: task for task in self.repository.list_all()}
        live_tasks: dict[str, DownloadTask] = {}
        seen_rpc_gids: set[str] = set()
        rpc_task_sets = [
            self._sync_client.tell_active() or [],
            self._sync_client.tell_waiting() or [],
            self._sync_client.tell_stopped() or [],
        ]

        with self._state_lock:
            suppressed_deleted_gids = set(self._suppressed_deleted_gids)

        for rpc_tasks in rpc_task_sets:
            for task_data in rpc_tasks:
                gid = task_data.get("gid", "")
                if gid:
                    seen_rpc_gids.add(gid)
                if gid in suppressed_deleted_gids:
                    self._purge_download_result(gid, client=self._sync_client)
                    continue
                existing_task = repository_tasks.get(gid)
                if existing_task and existing_task.status_enum == TaskStatus.REMOVED:
                    live_tasks[existing_task.gid] = existing_task
                    continue
                task = aria2_dict_to_download_task(task_data)
                if existing_task and existing_task.resume_support:
                    task.resume_support = existing_task.resume_support
                self._merge_task_timing(existing_task, task)
                self.repository.upsert_from_download_task(task)
                live_tasks[task.gid] = task

        repository_tasks.update(live_tasks)
        self._normalize_detached_tasks(repository_tasks, seen_rpc_gids)
        tasks = self.sort_tasks(repository_tasks.values())
        return SyncResult(
            tasks=tasks,
            aria2_online=True,
        )

    def sync_runtime_details(self, *, force: bool = False) -> None:
        if self._shutdown:
            return

        with self._state_lock:
            should_sync = bool(
                self._watched_task_gid or self._observed_connection_row_gids
            )
            if not should_sync:
                return
            if self._detail_future is not None and not self._detail_future.done():
                return
            now = monotonic()
            if not force and now - self._last_runtime_detail_sync_started < 0.4:
                return
            self._last_runtime_detail_sync_started = now
            self._detail_future = self._detail_executor.submit(
                self._runtime_detail_worker
            )

    def _runtime_detail_worker(self) -> None:
        try:
            result = self._build_runtime_detail_result()
        except Exception as exc:  # pragma: no cover - defensive UI safety
            result = RuntimeDetailResult(
                connection_rows_by_gid={},
                task_error_message=f"Unexpected runtime sync error: {exc}",
            )
        self._runtime_detail_result_ready.emit(result)

    def _build_runtime_detail_result(self) -> RuntimeDetailResult:
        repository_tasks = {
            task.gid: task for task in self.sort_tasks(self.repository.list_all())
        }
        with self._state_lock:
            observed_gids = set(self._observed_connection_row_gids)
            watched_task_gid = self._watched_task_gid
            default_slot_count = self._watched_task_default_slot_count
            max_display_cells = self._watched_task_max_display_cells

        connection_rows_by_gid: dict[str, list[TaskConnectionRow]] = {}
        for gid in observed_gids:
            task = repository_tasks.get(gid)
            if task is None or task.status_enum != TaskStatus.ACTIVE:
                continue
            rows = self.get_task_connection_rows(
                task,
                default_slot_count=default_slot_count,
                client=self._detail_client,
            )
            if rows:
                connection_rows_by_gid[gid] = rows

        if not watched_task_gid:
            return RuntimeDetailResult(connection_rows_by_gid=connection_rows_by_gid)

        watched_task = repository_tasks.get(watched_task_gid)
        if watched_task is None:
            return RuntimeDetailResult(
                connection_rows_by_gid=connection_rows_by_gid,
                watched_task_gid=watched_task_gid,
            )

        connection_rows = self.get_task_connection_rows(
            watched_task,
            default_slot_count=default_slot_count,
            client=self._detail_client,
        )
        if connection_rows:
            connection_rows_by_gid[watched_task_gid] = connection_rows
        thread_count, thread_lines = self.get_thread_runtime_view(
            watched_task,
            default_slot_count=default_slot_count,
            client=self._detail_client,
        )
        piece_map_snapshot = self.get_task_piece_map_snapshot(
            watched_task,
            max_display_cells=max_display_cells,
            client=self._detail_client,
        )
        return RuntimeDetailResult(
            connection_rows_by_gid=connection_rows_by_gid,
            watched_task_gid=watched_task_gid,
            watched_runtime_snapshot=TaskRuntimeSnapshot(
                connection_rows=connection_rows,
                thread_count=thread_count,
                thread_lines=thread_lines,
                piece_map_snapshot=piece_map_snapshot,
            ),
        )

    def _normalize_detached_tasks(
        self,
        repository_tasks: dict[str, DownloadTask],
        seen_rpc_gids: set[str],
    ) -> None:
        for gid, task in list(repository_tasks.items()):
            if gid in seen_rpc_gids:
                continue
            if task.status_enum in {
                TaskStatus.COMPLETE,
                TaskStatus.ERROR,
                TaskStatus.FAILED,
                TaskStatus.REMOVED,
            }:
                continue
            if task.status_enum == TaskStatus.ACTIVE:
                self._finalize_active_elapsed(task)
            task.status = TaskStatus.PAUSED.value
            task.download_speed = 0
            task.updated_at = utc_now_iso()
            task.active_started_at = None
            self.repository.upsert_from_download_task(task)
            repository_tasks[gid] = task

    def _build_connection_rows_snapshot(
        self,
        tasks: list[DownloadTask],
    ) -> dict[str, list[TaskConnectionRow]]:
        connection_rows_by_gid: dict[str, list[TaskConnectionRow]] = {}
        for task in tasks:
            if task.status_enum != TaskStatus.ACTIVE:
                continue
            rows = self.get_task_connection_rows(
                task,
                client=self._sync_client,
            )
            if rows:
                connection_rows_by_gid[task.gid] = rows
        return connection_rows_by_gid

    def _build_watched_runtime_snapshot(
        self,
        tasks: list[DownloadTask],
    ) -> tuple[str | None, TaskRuntimeSnapshot | None]:
        with self._state_lock:
            watched_task_gid = self._watched_task_gid
            default_slot_count = self._watched_task_default_slot_count
            max_display_cells = self._watched_task_max_display_cells

        if not watched_task_gid:
            return None, None

        watched_task = next((task for task in tasks if task.gid == watched_task_gid), None)
        if watched_task is None:
            return watched_task_gid, None

        connection_rows = self.get_task_connection_rows(
            watched_task,
            default_slot_count=default_slot_count,
            client=self._sync_client,
        )
        thread_count, thread_lines = self.get_thread_runtime_view(
            watched_task,
            default_slot_count=default_slot_count,
            client=self._sync_client,
        )
        piece_map_snapshot = self.get_task_piece_map_snapshot(
            watched_task,
            max_display_cells=max_display_cells,
            client=self._sync_client,
        )
        return watched_task_gid, TaskRuntimeSnapshot(
            connection_rows=connection_rows,
            thread_count=thread_count,
            thread_lines=thread_lines,
            piece_map_snapshot=piece_map_snapshot,
        )

    def _apply_sync_result(self, result: SyncResult) -> None:
        with self._state_lock:
            active_gids = {task.gid for task in result.tasks if task.status_enum == TaskStatus.ACTIVE}
            observed_gids = set(self._observed_connection_row_gids)
            watched_task_gid = self._watched_task_gid
            stale_connection_gids = [
                gid
                for gid in self._cached_connection_rows_by_gid
                if gid not in active_gids or gid not in observed_gids
            ]
            for gid in stale_connection_gids:
                self._cached_connection_rows_by_gid.pop(gid, None)
            stale_runtime_gids = [
                gid
                for gid in self._runtime_snapshot_by_gid
                if gid not in active_gids and gid != watched_task_gid
            ]
            for gid in stale_runtime_gids:
                self._runtime_snapshot_by_gid.pop(gid, None)
            self._suppressed_deleted_gids.intersection_update({task.gid for task in result.tasks})

        if result.aria2_online is not None:
            self._set_aria2_state(result.aria2_online, result.aria2_message)
        if result.task_error_message:
            self.task_error.emit(result.task_error_message)

        tasks = [self._clone_task(task) for task in result.tasks]
        for task in tasks:
            self._apply_ui_override(task, reported_status=task.status)

        self.tasks_updated.emit(tasks)
        self.sync_runtime_details(force=True)

    def _apply_runtime_detail_result(self, result: RuntimeDetailResult) -> None:
        with self._state_lock:
            self._cached_connection_rows_by_gid = {
                gid: list(rows) for gid, rows in result.connection_rows_by_gid.items()
            }
            if result.watched_task_gid:
                if result.watched_runtime_snapshot is None:
                    self._runtime_snapshot_by_gid.pop(result.watched_task_gid, None)
                else:
                    self._runtime_snapshot_by_gid[result.watched_task_gid] = (
                        result.watched_runtime_snapshot
                    )

        if result.task_error_message:
            self.task_error.emit(result.task_error_message)

        self.runtime_details_updated.emit()
        if result.watched_task_gid and result.watched_runtime_snapshot is not None:
            self.task_runtime_snapshot_updated.emit(
                result.watched_task_gid,
                result.watched_runtime_snapshot,
            )

    def watch_task_runtime(
        self,
        task: DownloadTask | None,
        *,
        default_slot_count: int = 16,
        max_display_cells: int = 8192,
    ) -> None:
        with self._state_lock:
            next_gid = task.gid if task is not None else None
            next_slot_count = max(int(default_slot_count or 1), 1)
            next_display_cells = max(int(max_display_cells or 1), 1)
            changed = (
                self._watched_task_gid != next_gid
                or self._watched_task_default_slot_count != next_slot_count
                or self._watched_task_max_display_cells != next_display_cells
            )
            self._watched_task_gid = task.gid if task is not None else None
            self._watched_task_default_slot_count = next_slot_count
            self._watched_task_max_display_cells = next_display_cells
        if task is None:
            return
        if changed:
            self.sync_runtime_details(force=True)

    def set_observed_connection_row_tasks(
        self,
        tasks: list[DownloadTask],
        *,
        default_slot_count: int = 16,
    ) -> None:
        next_gids = {task.gid for task in tasks if task is not None}
        next_slot_count = max(int(default_slot_count or 1), 1)
        with self._state_lock:
            removed_gids = self._observed_connection_row_gids.difference(next_gids)
            changed = (
                self._observed_connection_row_gids != next_gids
                or self._watched_task_default_slot_count != next_slot_count
            )
            self._observed_connection_row_gids = next_gids
            self._watched_task_default_slot_count = next_slot_count
            for gid in removed_gids:
                self._cached_connection_rows_by_gid.pop(gid, None)
        if changed and next_gids:
            self.sync_runtime_details(force=True)

    def get_cached_task_connection_rows(self, task: DownloadTask) -> list[TaskConnectionRow]:
        with self._state_lock:
            rows = self._cached_connection_rows_by_gid.get(task.gid) or []
            return list(rows)

    def get_cached_task_runtime_snapshot(self, gid: str) -> TaskRuntimeSnapshot | None:
        with self._state_lock:
            snapshot = self._runtime_snapshot_by_gid.get(gid)
            if snapshot is None:
                return None
            return TaskRuntimeSnapshot(
                connection_rows=list(snapshot.connection_rows),
                thread_count=int(snapshot.thread_count),
                thread_lines=list(snapshot.thread_lines),
                piece_map_snapshot=snapshot.piece_map_snapshot,
            )

    @staticmethod
    def _clone_task(task: DownloadTask) -> DownloadTask:
        return DownloadTask(
            gid=task.gid,
            name=task.name,
            url=task.url,
            save_path=task.save_path,
            status=task.status,
            total_length=int(task.total_length or 0),
            completed_length=int(task.completed_length or 0),
            download_speed=int(task.download_speed or 0),
            created_at=task.created_at,
            updated_at=task.updated_at,
            completed_at=task.completed_at,
            error_message=task.error_message,
            resume_support=task.resume_support,
            elapsed_seconds=int(task.elapsed_seconds or 0),
            active_started_at=task.active_started_at,
        )

    def _run_task_action(self, action_name: str, gid: str, action) -> None:
        try:
            action(gid)
            self._set_aria2_state(True)
            self.sync_tasks()
        except Aria2RPCError as exc:
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to {action_name} task: {exc}")

    def _run_task_actions(
        self,
        action_name: str,
        gids: list[str],
        action,
        capability_attr: str,
    ) -> None:
        actionable_gids: list[str] = []
        for gid in gids:
            task = self.repository.get_by_gid(gid)
            if task and getattr(task, capability_attr, False):
                actionable_gids.append(gid)

        if not actionable_gids:
            return

        any_success = False
        for gid in actionable_gids:
            try:
                action(gid)
                any_success = True
                self._set_aria2_state(True)
                self._optimistically_update_task(gid, action_name)
            except Aria2RPCError as exc:
                self._update_aria2_state_from_error(exc)
                self.task_error.emit(f"Unable to {action_name} task: {exc}")

        if any_success:
            self._emit_persisted_tasks()
            QTimer.singleShot(250, self.sync_tasks)

    def _run_resume_actions(self, gids: list[str]) -> None:
        actionable_tasks: list[DownloadTask] = []
        for gid in gids:
            task = self.repository.get_by_gid(gid)
            if task and task.can_resume:
                actionable_tasks.append(task)

        if not actionable_tasks:
            return

        any_success = False
        for task in actionable_tasks:
            try:
                if task.status_enum in {TaskStatus.ERROR, TaskStatus.FAILED}:
                    new_gid = self._restore_incomplete_task(task)
                    if new_gid:
                        any_success = True
                elif task.status_enum == TaskStatus.REMOVED:
                    self._restore_removed_task(task)
                    any_success = True
                else:
                    try:
                        self.client.unpause(task.gid)
                        self._optimistically_update_task(task.gid, "resume")
                    except Aria2RPCError as exc:
                        if not self._is_missing_aria2_task_error(exc):
                            raise
                        new_gid = self._restore_incomplete_task(task)
                        if new_gid:
                            any_success = True
                            self._set_aria2_state(True)
                            continue
                    any_success = True
                self._set_aria2_state(True)
            except Aria2RPCError as exc:
                self._update_aria2_state_from_error(exc)
                self.task_error.emit(f"Unable to resume task: {exc}")
            except ValueError as exc:
                self.task_error.emit(f"Unable to resume task: {exc}")

        if any_success:
            self._emit_persisted_tasks()
            QTimer.singleShot(250, self.sync_tasks)

    def _restore_removed_task(self, task: DownloadTask) -> None:
        if task.completed_at or task.is_completed:
            task.status = TaskStatus.COMPLETE.value
            task.download_speed = 0
            task.updated_at = utc_now_iso()
            task.active_started_at = None
            self.repository.upsert_from_download_task(task)
            return

        restored_gid = self._restore_incomplete_task(task)
        if restored_gid is None:
            raise ValueError("No task URL is available for restore.")

    def _optimistically_update_task(self, gid: str, action_name: str) -> None:
        task = self.repository.get_by_gid(gid)
        if not task:
            return

        if action_name == "pause":
            self._ui_state_overrides[gid] = TaskUiOverride(
                status=TaskStatus.PAUSED.value,
                completed_length=task.completed_length,
                total_length=task.total_length or None,
            )
            self._finalize_active_elapsed(task)
            task.status = TaskStatus.PAUSED.value
            task.download_speed = 0
        elif action_name == "resume":
            self._ui_state_overrides[gid] = TaskUiOverride(
                status=TaskStatus.WAITING.value
            )
            task.status = TaskStatus.WAITING.value
            task.download_speed = 0
        else:
            return

        task.updated_at = utc_now_iso()
        self.repository.upsert_from_download_task(task)

    def _restore_incomplete_task(self, task: DownloadTask) -> str | None:
        if not task.url:
            raise ValueError("No task URL is available for restore.")

        target_dir = Path(task.save_path).expanduser() if task.save_path else Path(".")
        target_dir.mkdir(parents=True, exist_ok=True)
        options, output_name = self._build_resume_uri_options(task, target_dir)
        new_gid = self.client.add_uri([task.url], options or None)

        self._ui_state_overrides.pop(task.gid, None)
        self._connection_slot_count_by_gid.pop(task.gid, None)
        self._connected_servers_by_gid.pop(task.gid, None)
        self._connected_peers_by_gid.pop(task.gid, None)
        self._cached_connection_rows_by_gid.pop(task.gid, None)
        self._runtime_snapshot_by_gid.pop(task.gid, None)
        self._piece_map_cache.pop(task.gid, None)
        try:
            self.client.remove(task.gid)
        except Aria2RPCError:
            pass
        self.repository.delete_by_gid(task.gid)

        try:
            restored_task = aria2_dict_to_download_task(self.client.tell_status(new_gid))
        except Aria2RPCError:
            restored_task = DownloadTask(
                gid=new_gid,
                name=output_name or task.name,
                url=task.url,
                save_path=str(target_dir),
                status=TaskStatus.WAITING.value,
                total_length=task.total_length,
                completed_length=task.completed_length,
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
                resume_support=task.resume_support,
                elapsed_seconds=max(int(task.elapsed_seconds or 0), 0),
                active_started_at=None,
            )

        if not restored_task.resume_support:
            restored_task.resume_support = task.resume_support
        self.repository.upsert_from_download_task(restored_task)
        return new_gid

    def _apply_ui_override(
        self,
        task: DownloadTask,
        *,
        reported_status: str | None = None,
    ) -> None:
        desired_override = self._ui_state_overrides.get(task.gid)
        if not desired_override:
            return

        desired_status = desired_override.status
        if desired_status == TaskStatus.PAUSED.value:
            if reported_status == TaskStatus.PAUSED.value:
                self._ui_state_overrides.pop(task.gid, None)
                task.status = TaskStatus.PAUSED.value
                task.download_speed = 0
                return
            task.status = TaskStatus.PAUSED.value
            task.download_speed = 0
            if desired_override.completed_length is not None:
                task.completed_length = desired_override.completed_length
            if task.total_length <= 0 and desired_override.total_length is not None:
                task.total_length = desired_override.total_length
            return

        if desired_status == TaskStatus.WAITING.value:
            if reported_status in {TaskStatus.WAITING.value, TaskStatus.ACTIVE.value}:
                self._ui_state_overrides.pop(task.gid, None)
                return
            task.status = TaskStatus.WAITING.value
            task.download_speed = 0

    def _permanently_delete_single_task(
        self,
        task: DownloadTask,
        *,
        delete_files: bool = False,
    ) -> bool:
        try:
            self._suppressed_deleted_gids.add(task.gid)
            self._ui_state_overrides.pop(task.gid, None)
            self._piece_map_cache.pop(task.gid, None)
            self._cached_connection_rows_by_gid.pop(task.gid, None)
            self._runtime_snapshot_by_gid.pop(task.gid, None)
            if task.status_enum in {
                TaskStatus.ACTIVE,
                TaskStatus.WAITING,
                TaskStatus.PAUSED,
            }:
                self.client.remove(task.gid)
                self._set_aria2_state(True)
                self._purge_download_result(task.gid)
            else:
                try:
                    self.client.remove(task.gid)
                    self._set_aria2_state(True)
                except Aria2RPCError as exc:
                    if not self._is_missing_aria2_task_error(exc):
                        raise
                self._purge_download_result(task.gid)

            if delete_files:
                self.os_service.delete_task_files(task)

            self.repository.delete_by_gid(task.gid)
            return True
        except Aria2RPCError as exc:
            self._suppressed_deleted_gids.discard(task.gid)
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to permanently delete task: {exc}")
            return False
        except (RuntimeError, ValueError) as exc:
            self._suppressed_deleted_gids.discard(task.gid)
            self.task_error.emit(f"Unable to permanently delete task: {exc}")
            return False

    @staticmethod
    def _is_missing_aria2_task_error(exc: Aria2RPCError) -> bool:
        message = str(exc).lower()
        missing_markers = (
            "not found",
            "cannot be found",
            "gid is not found",
            "download result not found",
            "active download not found",
            "invalid gid",
        )
        return any(marker in message for marker in missing_markers)

    def _update_aria2_state_from_error(self, exc: Aria2RPCError) -> None:
        if isinstance(exc, Aria2ConnectionError):
            self._set_aria2_state(False, str(exc))

    def _purge_download_result(
        self,
        gid: str,
        *,
        client: Aria2Client | None = None,
    ) -> None:
        rpc_client = client or self.client
        try:
            rpc_client.remove_download_result(gid)
        except Aria2RPCError:
            pass

    def _emit_persisted_tasks(self) -> None:
        tasks = [self._clone_task(task) for task in self.sort_tasks(self.repository.list_all())]
        for task in tasks:
            self._apply_ui_override(task, reported_status=task.status)
        self.tasks_updated.emit(tasks)

    def _set_aria2_state(self, online: bool, message: str = "") -> None:
        previous_state = self._aria2_online
        self._aria2_online = online
        if online:
            self._last_aria2_message = ""
            return
        if previous_state is not False or message != self._last_aria2_message:
            self._last_aria2_message = message
            self.aria2_unavailable.emit(message)

    def sort_tasks(self, tasks) -> list[DownloadTask]:
        return sorted(
            tasks,
            key=self._task_sort_key,
        )

    def _task_sort_key(self, task: DownloadTask) -> tuple[int, float, str]:
        status_rank = {
            TaskStatus.ACTIVE: 0,
            TaskStatus.WAITING: 1,
            TaskStatus.PAUSED: 2,
            TaskStatus.ERROR: 3,
            TaskStatus.FAILED: 3,
            TaskStatus.COMPLETE: 4,
            TaskStatus.REMOVED: 5,
            TaskStatus.UNKNOWN: 6,
        }.get(task.status_enum, 6)
        if task.status_enum == TaskStatus.COMPLETE:
            sort_dt = parse_iso_datetime(task.completed_at) or parse_iso_datetime(task.updated_at)
        else:
            sort_dt = parse_iso_datetime(task.created_at)
        sort_ts = sort_dt.timestamp() if sort_dt else 0.0
        return status_rank, -sort_ts, task.gid

    def filter_tasks(
        self,
        tasks: list[DownloadTask],
        filter_key: str,
    ) -> list[DownloadTask]:
        return [task for task in tasks if task.matches_filter(filter_key)]

    def can_resume_tasks(self, tasks: list[DownloadTask]) -> bool:
        return any(task.can_resume for task in tasks)

    def can_pause_tasks(self, tasks: list[DownloadTask]) -> bool:
        return any(task.can_pause for task in tasks)

    def can_remove_tasks(self, tasks: list[DownloadTask]) -> bool:
        return any(task.can_remove for task in tasks)

    def can_move_tasks(self, tasks: list[DownloadTask]) -> bool:
        return any(self._can_move_task(task) for task in tasks)

    def open_task_folder(self, task: DownloadTask) -> None:
        self.os_service.reveal_task_in_folder(task)

    def open_task_file(self, task: DownloadTask) -> None:
        self.os_service.open_task_file(task)

    def task_file_exists(self, task: DownloadTask) -> bool:
        return self.os_service.task_file_exists(task)

    def redownload_tasks(
        self,
        tasks: list[DownloadTask],
    ) -> tuple[list[str], list[str]]:
        gids: list[str] = []
        errors: list[str] = []
        for task in tasks:
            try:
                gid = self.redownload_task(task)
            except ValueError as exc:
                errors.append(f"{task.name}: {exc}")
                continue
            if gid:
                gids.append(gid)
            else:
                errors.append(task.name)
        return gids, errors

    def move_tasks_to_directory(
        self,
        tasks: list[DownloadTask],
        destination_dir: str,
    ) -> tuple[int, list[str]]:
        moved_count = 0
        errors: list[str] = []
        for task in tasks:
            if not self._can_move_task(task):
                errors.append(task.name)
                continue
            try:
                self.os_service.move_task_files(task, destination_dir)
                task.save_path = str(Path(destination_dir).expanduser())
                task.updated_at = utc_now_iso()
                self.repository.upsert_from_download_task(task)
                moved_count += 1
            except (RuntimeError, ValueError, FileNotFoundError, FileExistsError):
                errors.append(task.name)
        if moved_count:
            self._emit_persisted_tasks()
        return moved_count, errors

    def clear_trash(self) -> int:
        trash_tasks = [
            task
            for task in self.repository.list_all()
            if task.status_enum == TaskStatus.REMOVED
        ]
        if not trash_tasks:
            return 0
        self.permanently_delete_tasks(trash_tasks, delete_files=False)
        return len(trash_tasks)

    def list_exportable_tasks(self) -> list[DownloadTask]:
        return [task for task in self.repository.list_all() if task.url.strip()]

    def export_task_list(
        self,
        path: str,
        tasks: list[DownloadTask] | None = None,
    ) -> int:
        if tasks is None:
            tasks = self.list_exportable_tasks()
        self.task_list_exchange.export_tasks(tasks, path)
        return len(tasks)

    def import_task_list(
        self,
        path: str,
        default_download_dir: str,
        *,
        only_incomplete: bool = False,
    ) -> tuple[list[str], list[str]]:
        entries = self.task_list_exchange.load_entries(path)
        if only_incomplete:
            entries = [entry for entry in entries if entry.is_incomplete]

        gids: list[str] = []
        errors: list[str] = []
        for entry in entries:
            target_dir = entry.save_path or default_download_dir
            try:
                gid = self.add_uri_task(entry.url, target_dir)
            except ValueError as exc:
                errors.append(f"{entry.url}: {exc}")
                continue
            if gid:
                gids.append(gid)
            else:
                errors.append(entry.url)
        return gids, errors

    def get_task_piece_map_snapshot(
        self,
        task: DownloadTask,
        *,
        max_display_cells: int = 8192,
        client: Aria2Client | None = None,
    ) -> PieceMapSnapshot:
        rpc_snapshot = self._get_task_piece_map_snapshot_from_rpc(
            task,
            max_display_cells=max_display_cells,
            client=client,
        )
        if rpc_snapshot is not None:
            return rpc_snapshot

        control_path = self.os_service.get_task_control_file_path(task)
        if control_path is None or not control_path.exists():
            return PieceMapSnapshot(
                total_pieces=0,
                display_cells=[],
                available=False,
                message="piece_map.no_data",
            )

        try:
            stat = control_path.stat()
        except OSError:
            return PieceMapSnapshot(
                total_pieces=0,
                display_cells=[],
                available=False,
                message="piece_map.no_data",
            )

        signature = (str(control_path), int(stat.st_mtime_ns), int(stat.st_size))
        cached_entry = self._piece_map_cache.get(task.gid)
        if cached_entry and cached_entry[0] == signature:
            return self._apply_piece_map_progress_fallback(
                task,
                cached_entry[1],
                active_connection_count=self._get_active_connection_count(
                    task,
                    client=client,
                ),
            )

        snapshot = self._piece_map_parser.parse(
            control_path,
            max_display_cells=max_display_cells,
        )
        self._piece_map_cache[task.gid] = (signature, snapshot)
        return self._apply_piece_map_progress_fallback(
            task,
            snapshot,
            active_connection_count=self._get_active_connection_count(
                task,
                client=client,
            ),
        )

    def _get_task_piece_map_snapshot_from_rpc(
        self,
        task: DownloadTask,
        *,
        max_display_cells: int,
        client: Aria2Client | None = None,
    ) -> PieceMapSnapshot | None:
        rpc_client = client or self.client
        try:
            status_data = rpc_client.tell_status(
                task.gid,
                [
                    "gid",
                    "status",
                    "bitfield",
                    "numPieces",
                    "pieceLength",
                    "totalLength",
                    "connections",
                    "downloadSpeed",
                ],
            ) or {}
        except Aria2RPCError:
            return None

        bitfield_hex = str(status_data.get("bitfield") or "")
        num_pieces = int(status_data.get("numPieces", 0) or 0)
        if num_pieces <= 0:
            piece_length = int(status_data.get("pieceLength", 0) or 0)
            total_length = int(status_data.get("totalLength", 0) or 0)
            if piece_length > 0 and total_length > 0:
                num_pieces = math.ceil(total_length / piece_length)

        if num_pieces <= 0:
            return None

        active_count = int(status_data.get("connections", 0) or 0)
        status_value = str(status_data.get("status") or task.status)
        is_live = status_value in {TaskStatus.ACTIVE.value, TaskStatus.WAITING.value}
        snapshot = self._piece_map_parser.build_snapshot_from_rpc(
            bitfield_hex=bitfield_hex,
            num_pieces=num_pieces,
            active_count=active_count,
            is_live=is_live,
            max_display_cells=max_display_cells,
        )
        return snapshot

    def _get_active_connection_count(
        self,
        task: DownloadTask,
        *,
        client: Aria2Client | None = None,
    ) -> int:
        try:
            if self._is_bt_task(task):
                return len(self._fetch_connected_peers(task, client=client))
            return len(self._fetch_connected_servers(task, client=client))
        except Exception:
            return 0

    @staticmethod
    def _apply_piece_map_progress_fallback(
        task: DownloadTask,
        snapshot: PieceMapSnapshot,
        *,
        active_connection_count: int = 0,
    ) -> PieceMapSnapshot:
        if (
            not snapshot.available
            or snapshot.total_pieces <= 0
            or not snapshot.display_cells
            or task.total_length <= 0
            or task.completed_length <= 0
        ):
            return snapshot

        display_cells = list(snapshot.display_cells)
        estimated_display_complete = min(
            max(
                int(
                    (task.completed_length / task.total_length)
                    * len(display_cells)
                ),
                0,
            ),
            len(display_cells),
        )
        existing_complete_like = sum(
            1
            for status in display_cells
            if status
            in {
                "complete",
                "partial",
            }
        )
        missing_complete = max(estimated_display_complete - existing_complete_like, 0)
        if missing_complete > 0:
            for index, status in enumerate(display_cells):
                if status in {"empty", "unavailable"}:
                    display_cells[index] = "complete"
                    missing_complete -= 1
                    if missing_complete <= 0:
                        break

        is_live = task.status_enum in {TaskStatus.ACTIVE, TaskStatus.WAITING}
        for index, status in enumerate(display_cells):
            if status == "active" and not is_live:
                display_cells[index] = (
                    "complete" if index < estimated_display_complete else "empty"
                )

        if is_live and task.download_speed > 0 and display_cells:
            desired_active_count = max(int(active_connection_count or 0), 1)
            existing_active_count = sum(
                1 for status in display_cells if status == "active"
            )
            missing_active = max(desired_active_count - existing_active_count, 0)
            frontier_index = min(estimated_display_complete, len(display_cells) - 1)

            search_indexes: list[int] = []
            for offset in range(len(display_cells)):
                for candidate in (frontier_index + offset, frontier_index - offset):
                    if 0 <= candidate < len(display_cells) and candidate not in search_indexes:
                        search_indexes.append(candidate)

            for index in search_indexes:
                if missing_active <= 0:
                    break
                if display_cells[index] in {"empty", "unavailable"}:
                    display_cells[index] = "active"
                    missing_active -= 1

        if display_cells == snapshot.display_cells:
            return snapshot

        return PieceMapSnapshot(
            total_pieces=snapshot.total_pieces,
            display_cells=display_cells,
            available=snapshot.available,
            message=snapshot.message,
        )

    @staticmethod
    def _merge_task_timing(
        existing_task: DownloadTask | None,
        task: DownloadTask,
    ) -> None:
        if existing_task is None:
            if task.status_enum == TaskStatus.COMPLETE and not task.completed_at:
                task.completed_at = utc_now_iso()
            if task.status_enum == TaskStatus.ACTIVE:
                task.active_started_at = task.created_at or utc_now_iso()
            return

        task.elapsed_seconds = int(existing_task.elapsed_seconds or 0)
        task.active_started_at = existing_task.active_started_at
        task.completed_at = existing_task.completed_at

        previous_status = existing_task.status_enum
        current_status = task.status_enum

        if previous_status != TaskStatus.COMPLETE and current_status == TaskStatus.COMPLETE:
            task.completed_at = task.completed_at or utc_now_iso()

        if previous_status != TaskStatus.ACTIVE and current_status == TaskStatus.ACTIVE:
            task.active_started_at = utc_now_iso()
            return

        if previous_status == TaskStatus.ACTIVE and current_status != TaskStatus.ACTIVE:
            DownloadManager._finalize_active_elapsed(task)
            return

        if current_status == TaskStatus.ACTIVE and not task.active_started_at:
            task.active_started_at = utc_now_iso()

    @staticmethod
    def _finalize_active_elapsed(task: DownloadTask) -> None:
        started_at = parse_iso_datetime(task.active_started_at)
        if started_at is not None:
            finished_at = parse_iso_datetime(utc_now_iso())
            if finished_at is not None:
                task.elapsed_seconds = max(
                    int(task.elapsed_seconds or 0)
                    + max(int((finished_at - started_at).total_seconds()), 0),
                    0,
                )
        task.active_started_at = None

    def update_task_resume_support(self, gid: str, resume_support: str) -> None:
        if resume_support not in {
            ResumeSupport.YES.value,
            ResumeSupport.NO.value,
            ResumeSupport.UNKNOWN.value,
        }:
            return
        task = self.repository.get_by_gid(gid)
        if not task:
            return
        if task.resume_support == resume_support:
            return
        self.repository.update_resume_support(gid, resume_support)

    def redownload_task(self, task: DownloadTask) -> str | None:
        if not task.url:
            raise ValueError("No task URL is available for re-download.")

        target_dir = Path(task.save_path).expanduser() if task.save_path else Path(".")
        target_dir.mkdir(parents=True, exist_ok=True)
        options, output_name = self._build_unique_uri_options(
            task.url,
            target_dir,
            preferred_name=task.name,
            exclude_gid=task.gid,
        )

        try:
            new_gid = self.client.add_uri([task.url], options or None)
            try:
                raw_task = self.client.tell_status(new_gid)
                new_task = aria2_dict_to_download_task(raw_task)
            except Aria2RPCError:
                new_task = DownloadTask(
                    gid=new_gid,
                    name=output_name or task.name,
                    url=task.url,
                    save_path=str(target_dir),
                    status=TaskStatus.WAITING.value,
                    created_at=utc_now_iso(),
                    resume_support=task.resume_support,
                    elapsed_seconds=0,
                    active_started_at=None,
                )

            try:
                self.client.remove(task.gid)
            except Aria2RPCError:
                pass
            self.repository.delete_by_gid(task.gid)
            self.repository.upsert_from_download_task(new_task)
            self._set_aria2_state(True)
            self.sync_tasks()
            return new_gid
        except Aria2RPCError as exc:
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to re-download task: {exc}")
            return None

    def _build_unique_uri_options(
        self,
        url: str,
        target_dir: Path,
        *,
        preferred_name: str | None = None,
        exclude_gid: str | None = None,
    ) -> tuple[dict[str, str], str | None]:
        options = {"dir": str(target_dir)}
        candidate_name = (
            preferred_name or self._infer_output_name_from_url(url) or ""
        ).strip()
        if not candidate_name:
            return options, None

        output_name = self._make_unique_output_name(
            target_dir,
            candidate_name,
            exclude_gid=exclude_gid,
        )
        options["out"] = output_name
        return options, output_name

    def _build_resume_uri_options(
        self,
        task: DownloadTask,
        target_dir: Path,
    ) -> tuple[dict[str, str], str | None]:
        options = {"dir": str(target_dir)}
        candidate_name = (
            (task.name or "").strip()
            or self._infer_output_name_from_url(task.url)
            or ""
        ).strip()
        if candidate_name:
            options["out"] = candidate_name
            return options, candidate_name
        return options, None

    def _make_unique_output_name(
        self,
        target_dir: Path,
        candidate_name: str,
        *,
        exclude_gid: str | None = None,
    ) -> str:
        if not self._output_name_conflicts(
            target_dir,
            candidate_name,
            exclude_gid=exclude_gid,
        ):
            return candidate_name

        stem, suffix = self._split_filename(candidate_name)
        index = 2
        while True:
            resolved_name = f"{stem} ({index}){suffix}"
            if not self._output_name_conflicts(
                target_dir,
                resolved_name,
                exclude_gid=exclude_gid,
            ):
                return resolved_name
            index += 1

    def _output_name_conflicts(
        self,
        target_dir: Path,
        name: str,
        *,
        exclude_gid: str | None = None,
    ) -> bool:
        file_name_key = self._filename_key(name)
        target_dir_key = self._path_key(target_dir)

        for task in self.repository.list_all():
            if exclude_gid and task.gid == exclude_gid:
                continue
            if not task.name:
                continue
            if self._path_key(task.save_path) != target_dir_key:
                continue
            if self._filename_key(task.name) == file_name_key:
                return True

        target = target_dir / name
        if target.exists() or Path(f"{target}.aria2").exists():
            return True
        return False

    @staticmethod
    def _infer_output_name_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        name = Path(parsed.path).name.strip()
        return name or None

    @staticmethod
    def _split_filename(name: str) -> tuple[str, str]:
        suffixes = Path(name).suffixes
        suffix = "".join(suffixes)
        if suffix:
            stem = name[: -len(suffix)]
        else:
            stem = name
        return stem or name, suffix

    @staticmethod
    def _filename_key(name: str) -> str:
        return name.casefold()

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return str(Path(path).expanduser()).casefold()

    def get_thread_runtime_view(
        self,
        task: DownloadTask,
        *,
        default_slot_count: int = 16,
        client: Aria2Client | None = None,
    ) -> tuple[int, list[str]]:
        slot_count = self._get_connection_slot_count(
            task.gid,
            default_slot_count=default_slot_count,
            client=client,
        )

        if self._is_bt_task(task):
            lines = self._build_peer_runtime_lines(task, slot_count, client=client)
            return len(lines), lines
        lines = self._build_server_runtime_lines(task, slot_count, client=client)
        return len(lines), lines

    def get_task_connection_rows(
        self,
        task: DownloadTask,
        *,
        default_slot_count: int = 16,
        client: Aria2Client | None = None,
    ) -> list[TaskConnectionRow]:
        slot_count = self._get_connection_slot_count(
            task.gid,
            default_slot_count=default_slot_count,
            client=client,
        )

        if self._is_bt_task(task):
            return self._build_peer_connection_rows(task, slot_count, client=client)
        return self._build_server_connection_rows(task, slot_count, client=client)

    def _get_connection_slot_count(
        self,
        gid: str,
        *,
        default_slot_count: int = 16,
        client: Aria2Client | None = None,
    ) -> int:
        fallback = max(int(default_slot_count or 1), 1)
        cached = self._connection_slot_count_by_gid.get(gid)
        if cached is not None:
            return cached

        slot_count = fallback
        rpc_client = client or self.client
        try:
            options = rpc_client.get_option(gid) or {}
            slot_count = max(
                int(options.get("max-connection-per-server", slot_count) or slot_count),
                1,
            )
        except (Aria2RPCError, ValueError, TypeError):
            slot_count = fallback

        self._connection_slot_count_by_gid[gid] = slot_count
        return slot_count

    def open_task_url(self, task: DownloadTask) -> None:
        self.os_service.open_url(task.url)

    def copy_task_urls(self, tasks: list[DownloadTask]) -> int:
        urls = [task.url for task in tasks if task.url]
        if not urls:
            raise ValueError("No task URLs are available.")
        self.os_service.copy_text("\n".join(urls))
        return len(urls)

    @staticmethod
    def _is_http_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _is_magnet_url(url: str) -> bool:
        return url.lower().startswith("magnet:?")

    @classmethod
    def _is_supported_source_url(cls, url: str) -> bool:
        return cls._is_http_url(url) or cls._is_magnet_url(url)

    @staticmethod
    def _is_bt_task(task: DownloadTask) -> bool:
        url = (task.url or "").lower()
        name = (task.name or "").lower()
        return url.startswith("magnet:") or name.endswith(".torrent")

    @staticmethod
    def _can_move_task(task: DownloadTask) -> bool:
        return (
            task.status_enum
            in {
                TaskStatus.COMPLETE,
                TaskStatus.ERROR,
                TaskStatus.FAILED,
                TaskStatus.REMOVED,
            }
            and bool(task.save_path)
        )

    def _build_server_runtime_lines(
        self,
        task: DownloadTask,
        slot_count: int,
        *,
        client: Aria2Client | None = None,
    ) -> list[str]:
        connected_servers = self._fetch_connected_servers(task, client=client)
        lines: list[str] = []
        for server in connected_servers[:slot_count]:
            lines.append(
                "\n".join(
                    [
                        "状态：已连接",
                        f"原始地址：{server.get('uri') or '-'}",
                        f"当前地址：{server.get('currentUri') or server.get('uri') or '-'}",
                        f"速度：{format_speed(int(server.get('downloadSpeed', 0) or 0))}",
                    ]
                )
            )
        return lines

    def _build_server_connection_rows(
        self,
        task: DownloadTask,
        slot_count: int,
        *,
        client: Aria2Client | None = None,
    ) -> list[TaskConnectionRow]:
        rows: list[TaskConnectionRow] = []
        for index, server in enumerate(
            self._fetch_connected_servers(task, client=client)[:slot_count],
            start=1,
        ):
            rows.append(
                TaskConnectionRow(
                    label=f"连接{index}",
                    speed=int(server.get("downloadSpeed", 0) or 0),
                )
            )
        return rows

    def _fetch_connected_servers(
        self,
        task: DownloadTask,
        *,
        client: Aria2Client | None = None,
    ) -> list[dict]:
        if task.status_enum != TaskStatus.ACTIVE:
            self._connected_servers_by_gid.pop(task.gid, None)
            return []

        cached = self._connected_servers_by_gid.get(task.gid)
        now = monotonic()
        if cached is not None and now - cached[0] < 2.0:
            return cached[1]

        connected_servers: list[dict] = []
        rpc_client = client or self.client
        try:
            server_groups = rpc_client.get_servers(task.gid) or []
            for group in server_groups:
                connected_servers.extend(group.get("servers") or [])
        except Aria2RPCError:
            connected_servers = []
        self._connected_servers_by_gid[task.gid] = (now, connected_servers)
        return connected_servers

    def _build_peer_runtime_lines(
        self,
        task: DownloadTask,
        slot_count: int,
        *,
        client: Aria2Client | None = None,
    ) -> list[str]:
        lines: list[str] = []
        for peer in self._fetch_connected_peers(task, client=client)[:slot_count]:
            lines.append(
                "\n".join(
                    [
                        "状态：已连接",
                        f"对端：{peer.get('ip') or '-'}:{peer.get('port') or '-'}",
                        f"下载速度：{format_speed(int(peer.get('downloadSpeed', 0) or 0))}",
                        f"上传速度：{format_speed(int(peer.get('uploadSpeed', 0) or 0))}",
                        f"对端阻塞：{'是' if peer.get('peerChoking') == 'true' else '否'}",
                        f"本端阻塞：{'是' if peer.get('amChoking') == 'true' else '否'}",
                        f"做种端：{'是' if peer.get('seeder') == 'true' else '否'}",
                    ]
                )
            )
        return lines

    def _build_peer_connection_rows(
        self,
        task: DownloadTask,
        slot_count: int,
        *,
        client: Aria2Client | None = None,
    ) -> list[TaskConnectionRow]:
        rows: list[TaskConnectionRow] = []
        for index, peer in enumerate(
            self._fetch_connected_peers(task, client=client)[:slot_count],
            start=1,
        ):
            rows.append(
                TaskConnectionRow(
                    label=f"连接{index}",
                    speed=int(peer.get("downloadSpeed", 0) or 0),
                )
            )
        return rows

    def _fetch_connected_peers(
        self,
        task: DownloadTask,
        *,
        client: Aria2Client | None = None,
    ) -> list[dict]:
        if task.status_enum != TaskStatus.ACTIVE:
            self._connected_peers_by_gid.pop(task.gid, None)
            return []

        cached = self._connected_peers_by_gid.get(task.gid)
        now = monotonic()
        if cached is not None and now - cached[0] < 2.0:
            return cached[1]

        peers: list[dict] = []
        rpc_client = client or self.client
        try:
            peers = rpc_client.get_peers(task.gid) or []
        except Aria2RPCError:
            peers = []
        self._connected_peers_by_gid[task.gid] = (now, peers)
        return peers
