from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QPainter, QPen, QTextOption
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from app.i18n import Translator
from ui.themed_checkbox import ThemedCheckBox


class BatchUrlsEdit(QPlainTextEdit):
    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("batchUrlsEdit")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setTabChangesFocus(True)
        self.setStyleSheet(
            """
            QPlainTextEdit#batchUrlsEdit {
                background: #fffef8;
                border: 1px solid #8f8f8f;
                padding: 3px 4px;
                selection-background-color: #d7e8f8;
            }
            """
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#d8d8bc"), 1))

        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        viewport_width = self.viewport().width()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                y = round(bottom) - 1
                painter.drawLine(0, y, viewport_width, y)
            block = block.next()
            if not block.isValid():
                break
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()


class BatchTaskDialog(QDialog):
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
        self.setWindowTitle(self.translator.t("dialog.batch_task.title"))
        self.setModal(True)
        self.resize(680, 360)

        self.urls_edit = BatchUrlsEdit(self.theme, self)
        self.urls_edit.setPlaceholderText(
            self.translator.t("dialog.batch_task.placeholder")
        )
        self._prefill_urls_from_clipboard()

        self.download_dir_edit = QLineEdit(self)
        self.download_dir_edit.setText(default_download_dir)

        self.save_as_default_checkbox = ThemedCheckBox(
            self.translator.t("dialog.new_task.save_as_default"),
            self.theme,
            self,
        )

        browse_button = QPushButton(self.translator.t("dialog.new_task.browse"), self)
        browse_button.clicked.connect(self._browse_directory)

        directory_row = QWidget(self)
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        directory_layout.addWidget(self.download_dir_edit)
        directory_layout.addWidget(browse_button)

        form_layout = QFormLayout()
        form_layout.addRow(self.translator.t("dialog.batch_task.urls"), self.urls_edit)
        form_layout.addRow(
            self.translator.t("dialog.new_task.download_to"),
            directory_row,
        )
        form_layout.addRow("", self.save_as_default_checkbox)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)

    def get_values(self) -> tuple[list[str], str]:
        urls = self._normalized_urls()
        return urls, self.download_dir_edit.text().strip()

    def should_save_as_default(self) -> bool:
        return self.save_as_default_checkbox.isChecked()

    def _normalized_urls(self) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for raw_line in self.urls_edit.toPlainText().splitlines():
            url = raw_line.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def _prefill_urls_from_clipboard(self) -> None:
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            return
        if "http://" not in clipboard_text and "https://" not in clipboard_text and "magnet:" not in clipboard_text:
            return
        self.urls_edit.setPlainText(clipboard_text)

    def _browse_directory(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            self.translator.t("dialog.new_task.select_dir"),
            self.download_dir_edit.text().strip(),
        )
        if selected_dir:
            self.download_dir_edit.setText(selected_dir)

    def accept(self) -> None:
        urls, download_dir = self.get_values()
        if not urls:
            QMessageBox.warning(
                self,
                self.translator.t("dialog.batch_task.missing_urls.title"),
                self.translator.t("dialog.batch_task.missing_urls.body"),
            )
            return
        if not download_dir:
            QMessageBox.warning(
                self,
                self.translator.t("dialog.missing_folder.title"),
                self.translator.t("dialog.missing_folder.body"),
            )
            return
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        super().accept()
