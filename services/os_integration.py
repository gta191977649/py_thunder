from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from PyQt6.QtGui import QGuiApplication

from core.task_model import DownloadTask


class OSIntegrationService:
    def task_file_exists(self, task: DownloadTask) -> bool:
        target = self._resolve_task_target(task, require_exists=True)
        return bool(target and target.exists())

    def open_task_file(self, task: DownloadTask) -> None:
        target = self._resolve_task_target(task, require_exists=True)
        if target and target.exists():
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(target))  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target)])
                else:
                    subprocess.Popen(["xdg-open", str(target)])
                return
            except OSError as exc:
                raise RuntimeError(str(exc)) from exc

        self.reveal_task_in_folder(task)

    def open_folder(self, path: str) -> None:
        folder = Path(path).expanduser()
        if not path:
            raise ValueError("No folder path was provided.")
        if not folder.exists():
            raise FileNotFoundError(str(folder))

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            raise RuntimeError(str(exc)) from exc

    def reveal_task_in_folder(self, task: DownloadTask) -> None:
        if not task.save_path:
            raise ValueError("No folder path was provided.")

        folder = Path(task.save_path).expanduser()
        if not folder.exists():
            raise FileNotFoundError(str(folder))

        target = self._resolve_task_target(task, require_exists=True)
        if target and target.exists():
            try:
                if sys.platform.startswith("win"):
                    subprocess.Popen(["explorer", "/select,", str(target)])
                    return
                if sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", str(target)])
                    return
            except OSError as exc:
                raise RuntimeError(str(exc)) from exc

        self.open_folder(str(folder))

    def open_url(self, url: str) -> None:
        if not url:
            raise ValueError("No URL was provided.")
        opened = webbrowser.open(url)
        if not opened:
            raise RuntimeError(f"Failed to open URL: {url}")

    def copy_text(self, text: str) -> None:
        if not text:
            raise ValueError("No text was provided.")
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)

    def delete_task_files(self, task: DownloadTask) -> None:
        target = self._resolve_task_target(task, require_exists=True)
        if not target:
            return

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

            sidecar = Path(f"{target}.aria2")
            if sidecar.exists():
                sidecar.unlink()
        except OSError as exc:
            raise RuntimeError(str(exc)) from exc

    def get_task_control_file_path(self, task: DownloadTask) -> Path | None:
        target = self._resolve_task_target(task, require_exists=False)
        if not target:
            return None
        return Path(f"{target}.aria2")

    @staticmethod
    def _resolve_task_target(
        task: DownloadTask,
        *,
        require_exists: bool,
    ) -> Path | None:
        if not task.save_path:
            return None

        base_path = Path(task.save_path).expanduser()
        name = (task.name or "").strip()
        target: Path | None = None

        if name:
            target = base_path / name

        if target is None and base_path.is_file():
            target = base_path

        if target is None:
            return None
        if require_exists and not target.exists():
            return None

        return target
