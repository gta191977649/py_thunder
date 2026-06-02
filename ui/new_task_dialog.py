from __future__ import annotations

import shutil
import threading
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import Translator
from core.formatters import format_bytes
from ui.themed_checkbox import ThemedCheckBox


class SpaceUsageBar(QWidget):
    def __init__(self, translator: Translator, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.translator = translator
        self.theme = theme
        self.required_bytes: int | None = None
        self.total_bytes: int | None = None
        self.available_bytes: int | None = None

        self.setObjectName("newTaskSpaceBar")
        self.setFixedHeight(self._metric("new_task_space_bar_height", 20))

        self.required_space_title = QLabel(
            self.translator.t("dialog.new_task.required_space"),
            self,
        )
        self.required_space_value = QLabel(
            self.translator.t("dialog.new_task.space_unknown"),
            self,
        )
        self.available_space_title = QLabel(
            self.translator.t("dialog.new_task.available_space"),
            self,
        )
        self.available_space_value = QLabel(
            self.translator.t("dialog.new_task.space_unknown"),
            self,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            self._metric("new_task_space_bar_padding_x", 10),
            self._metric("new_task_space_bar_padding_y", 1),
            self._metric("new_task_space_bar_padding_x", 10),
            self._metric("new_task_space_bar_padding_y", 1),
        )
        layout.setSpacing(self._metric("new_task_space_bar_spacing", 4))

        self.required_space_title.setObjectName("newTaskSpaceTitle")
        self.required_space_value.setObjectName("newTaskSpaceValue")
        self.available_space_title.setObjectName("newTaskSpaceTitle")
        self.available_space_value.setObjectName("newTaskSpaceValue")

        layout.addStretch(1)
        layout.addWidget(self.required_space_title)
        layout.addWidget(self.required_space_value)
        layout.addSpacing(self._metric("new_task_space_bar_section_spacing", 18))
        layout.addWidget(self.available_space_title)
        layout.addWidget(self.available_space_value)
        layout.addStretch(1)

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def set_space_values(
        self,
        *,
        required_bytes: int | None,
        total_bytes: int | None,
        available_bytes: int | None,
    ) -> None:
        self.required_bytes = required_bytes
        self.total_bytes = total_bytes
        self.available_bytes = available_bytes
        unknown_text = self.translator.t("dialog.new_task.space_unknown")
        self.required_space_value.setText(
            format_bytes(required_bytes) if required_bytes is not None else unknown_text
        )
        self.available_space_value.setText(
            format_bytes(available_bytes)
            if available_bytes is not None
            else unknown_text
        )
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, self._color("new_task_space_bar_total_fill", "#eef8fc"))

        total_bytes = self.total_bytes or 0
        available_bytes = max(int(self.available_bytes or 0), 0)
        required_bytes = max(int(self.required_bytes or 0), 0)

        if total_bytes > 0:
            bar_width = rect.width() + 1
            capped_available_bytes = min(available_bytes, total_bytes)
            capped_required_bytes = min(required_bytes, capped_available_bytes)
            used_bytes = max(total_bytes - capped_available_bytes, 0)
            remaining_available_bytes = max(capped_available_bytes - capped_required_bytes, 0)

            used_width = int(round(bar_width * used_bytes / total_bytes))
            required_width = int(round(bar_width * capped_required_bytes / total_bytes))
            remaining_width = int(round(bar_width * remaining_available_bytes / total_bytes))

            total_segment_width = used_width + required_width + remaining_width
            width_delta = bar_width - total_segment_width
            if width_delta != 0:
                remaining_width = max(0, remaining_width + width_delta)

            x = rect.left()

            if used_width > 0:
                used_rect = rect.adjusted(0, 0, -(rect.width() - used_width + 1), 0)
                painter.fillRect(
                    used_rect,
                    self._color("new_task_space_bar_total_fill", "#eef8fc"),
                )
                x += used_width

            if required_width > 0:
                required_rect = QRect(x, rect.top(), required_width, rect.height() + 1)
                painter.fillRect(
                    required_rect,
                    self._color("new_task_space_bar_required_fill", "#6fa9ff"),
                )
                x += required_width

            if remaining_width > 0:
                remaining_rect = QRect(
                    x,
                    rect.top(),
                    remaining_width,
                    rect.height() + 1,
                )
                painter.fillRect(
                    remaining_rect,
                    self._color("new_task_space_bar_available_fill", "#b89af5"),
                )

        painter.setPen(QPen(self._color("new_task_space_bar_border", "#84d4ec"), 1))
        painter.drawRect(rect)


class NewTaskDialog(QDialog):
    required_space_resolved = pyqtSignal(int, object)

    def __init__(
        self,
        default_download_dir: str,
        translator: Translator,
        theme: dict,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.translator = translator
        self.theme = theme
        self.setWindowTitle(self.translator.t("dialog.new_task.title"))
        self.setModal(True)
        self.resize(600, 190)
        self._probe_serial = 0

        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText(self.translator.t("dialog.new_task.placeholder"))
        self._prefill_url_from_clipboard()

        self.download_dir_edit = QLineEdit(self)
        self.download_dir_edit.setText(default_download_dir)
        self.save_as_default_checkbox = ThemedCheckBox(
            self.translator.t("dialog.new_task.save_as_default"),
            self.theme,
            self,
        )
        self._required_space_bytes: int | None = None
        self._total_space_bytes: int | None = None
        self._available_space_bytes: int | None = None
        self._size_probe_timer = QTimer(self)
        self._size_probe_timer.setSingleShot(True)
        self._size_probe_timer.setInterval(350)
        self._size_probe_timer.timeout.connect(self._probe_required_space)
        self.required_space_resolved.connect(self._apply_required_space_result)

        browse_button = QPushButton(self.translator.t("dialog.new_task.browse"), self)
        browse_button.clicked.connect(self._browse_directory)

        directory_row = QWidget(self)
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        directory_layout.addWidget(self.download_dir_edit)
        directory_layout.addWidget(browse_button)

        self.space_bar = SpaceUsageBar(self.translator, self.theme, self)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setDefault(True)
            ok_button.setAutoDefault(True)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        form_layout = QFormLayout()
        form_layout.addRow(self.translator.t("dialog.new_task.url"), self.url_edit)
        form_layout.addRow(
            self.translator.t("dialog.new_task.download_to"),
            directory_row,
        )
        form_layout.addRow("", self.save_as_default_checkbox)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self.space_bar)
        layout.addWidget(button_box)

        self.url_edit.textChanged.connect(self._schedule_required_space_probe)
        self.download_dir_edit.textChanged.connect(self._update_available_space)
        self._update_available_space()
        self._schedule_required_space_probe()

    def get_values(self) -> tuple[str, str]:
        return self.url_edit.text().strip(), self.download_dir_edit.text().strip()

    def should_save_as_default(self) -> bool:
        return self.save_as_default_checkbox.isChecked()

    def _prefill_url_from_clipboard(self) -> None:
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            return
        self.url_edit.setText(clipboard_text)
        self.url_edit.setCursorPosition(len(clipboard_text))

    def _schedule_required_space_probe(self) -> None:
        self._required_space_bytes = None
        self._refresh_space_bar()
        self._size_probe_timer.start()

    def _probe_required_space(self) -> None:
        url = self.url_edit.text().strip()
        self._probe_serial += 1
        serial = self._probe_serial
        if not url.lower().startswith(("http://", "https://")):
            self._required_space_bytes = None
            self._refresh_space_bar()
            return

        worker = threading.Thread(
            target=self._resolve_required_space,
            args=(serial, url),
            daemon=True,
        )
        worker.start()

    def _resolve_required_space(self, serial: int, url: str) -> None:
        required_bytes = self._fetch_content_length(url)
        self.required_space_resolved.emit(serial, required_bytes)

    def _apply_required_space_result(self, serial: int, required_bytes) -> None:
        if serial != self._probe_serial:
            return
        self._required_space_bytes = required_bytes
        self._refresh_space_bar()

    def _fetch_content_length(self, url: str) -> int | None:
        try:
            head_request = Request(url, method="HEAD")
            with urlopen(head_request, timeout=4) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    return int(content_length)
        except (OSError, ValueError, URLError):
            pass

        try:
            range_request = Request(url, headers={"Range": "bytes=0-0"})
            with urlopen(range_request, timeout=4) as response:
                content_range = response.headers.get("Content-Range", "")
                if "/" in content_range:
                    total = content_range.rsplit("/", 1)[-1].strip()
                    if total.isdigit():
                        return int(total)
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    return int(content_length)
        except (OSError, ValueError, URLError):
            return None
        return None

    def _update_available_space(self) -> None:
        total_bytes, available_bytes = self._disk_usage_for_path(self.download_dir_edit.text())
        self._total_space_bytes = total_bytes
        self._available_space_bytes = available_bytes
        self._refresh_space_bar()

    def _refresh_space_bar(self) -> None:
        self.space_bar.set_space_values(
            required_bytes=self._required_space_bytes,
            total_bytes=self._total_space_bytes,
            available_bytes=self._available_space_bytes,
        )

    def _disk_usage_for_path(self, path_text: str) -> tuple[int | None, int | None]:
        candidate = Path(path_text.strip() or ".")
        current = candidate
        while not current.exists():
            if current.parent == current:
                break
            current = current.parent
        try:
            usage = shutil.disk_usage(current)
            return usage.total, usage.free
        except OSError:
            return None, None

    def _browse_directory(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            self.translator.t("dialog.new_task.select_dir"),
            self.download_dir_edit.text().strip(),
        )
        if selected_dir:
            self.download_dir_edit.setText(selected_dir)

    def accept(self) -> None:
        url, download_dir = self.get_values()
        if not url:
            QMessageBox.warning(
                self,
                self.translator.t("dialog.missing_url.title"),
                self.translator.t("dialog.missing_url.body"),
            )
            return
        if not download_dir:
            QMessageBox.warning(
                self,
                self.translator.t("dialog.missing_folder.title"),
                self.translator.t("dialog.missing_folder.body"),
            )
            return
        super().accept()
