from __future__ import annotations

import math
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
from storage.task_repository import TaskRepository


@dataclass(slots=True)
class TaskUiOverride:
    status: str
    completed_length: int | None = None
    total_length: int | None = None


class DownloadManager(QObject):
    tasks_updated = pyqtSignal(list)
    task_error = pyqtSignal(str)
    aria2_unavailable = pyqtSignal(str)

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
        self.timer = QTimer(self)
        self.timer.setInterval(refresh_interval_ms)
        self.timer.timeout.connect(self.sync_tasks)
        self._sync_in_progress = False
        self._aria2_online: bool | None = None
        self._last_aria2_message = ""
        self._ui_state_overrides: dict[str, TaskUiOverride] = {}
        self._piece_map_parser = Aria2ControlFileParser()
        self._piece_map_cache: dict[str, tuple[tuple[str, int, int], PieceMapSnapshot]] = {}

    def start(self) -> None:
        if not self.timer.isActive():
            self.timer.start()
        self.sync_tasks()

    def stop(self) -> None:
        self.timer.stop()

    def add_http_task(self, url: str, download_dir: str):
        normalized_url = url.strip()
        if not self._is_http_url(normalized_url):
            raise ValueError("Please enter a valid HTTP or HTTPS URL.")

        target_dir = Path(download_dir or "").expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            gid = self.client.add_uri([normalized_url], {"dir": str(target_dir)})
            try:
                raw_task = self.client.tell_status(gid)
                task = aria2_dict_to_download_task(raw_task)
            except Aria2RPCError:
                task = DownloadTask(
                    gid=gid,
                    name=Path(urlparse(normalized_url).path).name or gid,
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

    def sync_tasks(self) -> None:
        if self._sync_in_progress:
            return

        self._sync_in_progress = True
        try:
            repository_tasks = {task.gid: task for task in self.repository.list_all()}
            live_tasks = {}
            rpc_task_sets = [
                self.client.tell_active() or [],
                self.client.tell_waiting() or [],
                self.client.tell_stopped() or [],
            ]

            for rpc_tasks in rpc_task_sets:
                for task_data in rpc_tasks:
                    reported_status = task_data.get("status", TaskStatus.UNKNOWN.value)
                    existing_task = repository_tasks.get(task_data.get("gid", ""))
                    if existing_task and existing_task.status_enum == TaskStatus.REMOVED:
                        live_tasks[existing_task.gid] = existing_task
                        continue
                    task = aria2_dict_to_download_task(task_data)
                    if existing_task and existing_task.resume_support:
                        task.resume_support = existing_task.resume_support
                    self._merge_task_timing(existing_task, task)
                    self._apply_ui_override(task, reported_status=reported_status)
                    self.repository.upsert_from_download_task(task)
                    live_tasks[task.gid] = task

            for task in repository_tasks.values():
                self._apply_ui_override(task)
            repository_tasks.update(live_tasks)
            for task in repository_tasks.values():
                self._apply_ui_override(task)

            self._set_aria2_state(True)
            self.tasks_updated.emit(self._sort_tasks(repository_tasks.values()))
        except Aria2RPCError as exc:
            self._update_aria2_state_from_error(exc)
            self._emit_persisted_tasks()
        except Exception as exc:  # pragma: no cover - defensive UI safety
            self.task_error.emit(f"Unexpected sync error: {exc}")
            self._emit_persisted_tasks()
        finally:
            self._sync_in_progress = False

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
                if task.status_enum == TaskStatus.REMOVED:
                    self._restore_removed_task(task)
                else:
                    self.client.unpause(task.gid)
                    self._optimistically_update_task(task.gid, "resume")
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
        if not task.url:
            raise ValueError("No task URL is available for restore.")

        options = {}
        if task.save_path:
            options["dir"] = task.save_path
        new_gid = self.client.add_uri([task.url], options or None)

        self._ui_state_overrides.pop(task.gid, None)
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
                name=task.name,
                url=task.url,
                save_path=task.save_path,
                status=TaskStatus.WAITING.value,
                total_length=task.total_length,
                completed_length=task.completed_length,
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
                resume_support=task.resume_support,
                elapsed_seconds=0,
                active_started_at=None,
            )

        self.repository.upsert_from_download_task(restored_task)

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
            if task.status_enum in {
                TaskStatus.ACTIVE,
                TaskStatus.WAITING,
                TaskStatus.PAUSED,
            }:
                self.client.remove(task.gid)
                self._set_aria2_state(True)
            else:
                try:
                    self.client.remove(task.gid)
                    self._set_aria2_state(True)
                except Aria2RPCError as exc:
                    if not self._is_missing_aria2_task_error(exc):
                        raise

            if delete_files:
                self.os_service.delete_task_files(task)

            self.repository.delete_by_gid(task.gid)
            return True
        except Aria2RPCError as exc:
            self._update_aria2_state_from_error(exc)
            self.task_error.emit(f"Unable to permanently delete task: {exc}")
            return False
        except (RuntimeError, ValueError) as exc:
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

    def _emit_persisted_tasks(self) -> None:
        self.tasks_updated.emit(self._sort_tasks(self.repository.list_all()))

    def _set_aria2_state(self, online: bool, message: str = "") -> None:
        previous_state = self._aria2_online
        self._aria2_online = online
        if online:
            self._last_aria2_message = ""
            return
        if previous_state is not False or message != self._last_aria2_message:
            self._last_aria2_message = message
            self.aria2_unavailable.emit(message)

    def _sort_tasks(self, tasks) -> list[DownloadTask]:
        return sorted(
            tasks,
            key=lambda task: (task.created_at or "", task.gid),
            reverse=True,
        )

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

    def open_task_folder(self, task: DownloadTask) -> None:
        self.os_service.reveal_task_in_folder(task)

    def open_task_file(self, task: DownloadTask) -> None:
        self.os_service.open_task_file(task)

    def task_file_exists(self, task: DownloadTask) -> bool:
        return self.os_service.task_file_exists(task)

    def get_task_piece_map_snapshot(
        self,
        task: DownloadTask,
        *,
        max_display_cells: int = 8192,
    ) -> PieceMapSnapshot:
        rpc_snapshot = self._get_task_piece_map_snapshot_from_rpc(
            task,
            max_display_cells=max_display_cells,
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
                active_connection_count=self._get_active_connection_count(task),
            )

        snapshot = self._piece_map_parser.parse(
            control_path,
            max_display_cells=max_display_cells,
        )
        self._piece_map_cache[task.gid] = (signature, snapshot)
        return self._apply_piece_map_progress_fallback(
            task,
            snapshot,
                active_connection_count=self._get_active_connection_count(task),
            )

    def _get_task_piece_map_snapshot_from_rpc(
        self,
        task: DownloadTask,
        *,
        max_display_cells: int,
    ) -> PieceMapSnapshot | None:
        try:
            status_data = self.client.tell_status(
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

    def _get_active_connection_count(self, task: DownloadTask) -> int:
        try:
            if self._is_bt_task(task):
                return len(self._fetch_connected_peers(task))
            return len(self._fetch_connected_servers(task))
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
            if task.status_enum == TaskStatus.ACTIVE:
                task.active_started_at = task.created_at or utc_now_iso()
            return

        task.elapsed_seconds = int(existing_task.elapsed_seconds or 0)
        task.active_started_at = existing_task.active_started_at

        previous_status = existing_task.status_enum
        current_status = task.status_enum

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

        options = {}
        if task.save_path:
            target_dir = Path(task.save_path).expanduser()
            target_dir.mkdir(parents=True, exist_ok=True)
            options["dir"] = str(target_dir)

        try:
            new_gid = self.client.add_uri([task.url], options or None)
            try:
                raw_task = self.client.tell_status(new_gid)
                new_task = aria2_dict_to_download_task(raw_task)
            except Aria2RPCError:
                new_task = DownloadTask(
                    gid=new_gid,
                    name=task.name,
                    url=task.url,
                    save_path=task.save_path,
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

    def get_thread_runtime_view(
        self,
        task: DownloadTask,
        *,
        default_slot_count: int = 16,
    ) -> tuple[int, list[str]]:
        slot_count = max(int(default_slot_count or 1), 1)
        try:
            options = self.client.get_option(task.gid) or {}
            slot_count = max(
                int(options.get("max-connection-per-server", slot_count) or slot_count),
                1,
            )
        except (Aria2RPCError, ValueError, TypeError):
            pass

        if self._is_bt_task(task):
            lines = self._build_peer_runtime_lines(task, slot_count)
            return len(lines), lines
        lines = self._build_server_runtime_lines(task, slot_count)
        return len(lines), lines

    def get_task_connection_rows(
        self,
        task: DownloadTask,
        *,
        default_slot_count: int = 16,
    ) -> list[TaskConnectionRow]:
        slot_count = max(int(default_slot_count or 1), 1)
        try:
            options = self.client.get_option(task.gid) or {}
            slot_count = max(
                int(options.get("max-connection-per-server", slot_count) or slot_count),
                1,
            )
        except (Aria2RPCError, ValueError, TypeError):
            pass

        if self._is_bt_task(task):
            return self._build_peer_connection_rows(task, slot_count)
        return self._build_server_connection_rows(task, slot_count)

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
    def _is_bt_task(task: DownloadTask) -> bool:
        url = (task.url or "").lower()
        name = (task.name or "").lower()
        return url.startswith("magnet:") or name.endswith(".torrent")

    def _build_server_runtime_lines(
        self,
        task: DownloadTask,
        slot_count: int,
    ) -> list[str]:
        connected_servers = self._fetch_connected_servers(task)
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
    ) -> list[TaskConnectionRow]:
        rows: list[TaskConnectionRow] = []
        for index, server in enumerate(self._fetch_connected_servers(task)[:slot_count], start=1):
            rows.append(
                TaskConnectionRow(
                    label=f"连接{index}",
                    speed=int(server.get("downloadSpeed", 0) or 0),
                )
            )
        return rows

    def _fetch_connected_servers(self, task: DownloadTask) -> list[dict]:
        connected_servers: list[dict] = []
        try:
            server_groups = self.client.get_servers(task.gid) or []
            for group in server_groups:
                connected_servers.extend(group.get("servers") or [])
        except Aria2RPCError:
            connected_servers = []
        return connected_servers

    def _build_peer_runtime_lines(
        self,
        task: DownloadTask,
        slot_count: int,
    ) -> list[str]:
        lines: list[str] = []
        for peer in self._fetch_connected_peers(task)[:slot_count]:
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
    ) -> list[TaskConnectionRow]:
        rows: list[TaskConnectionRow] = []
        for index, peer in enumerate(self._fetch_connected_peers(task)[:slot_count], start=1):
            rows.append(
                TaskConnectionRow(
                    label=f"连接{index}",
                    speed=int(peer.get("downloadSpeed", 0) or 0),
                )
            )
        return rows

    def _fetch_connected_peers(self, task: DownloadTask) -> list[dict]:
        peers: list[dict] = []
        try:
            peers = self.client.get_peers(task.gid) or []
        except Aria2RPCError:
            peers = []
        return peers
