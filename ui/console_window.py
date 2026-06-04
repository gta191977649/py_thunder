from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class ConsoleWindow(QWidget):
    visibility_changed = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        font: QFont,
        *,
        icon: QIcon | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(title)
        if icon is not None and not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(900, 460)

        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(font)
        self.output.setObjectName("consoleOutput")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.output)

    def append_line(self, message: str) -> None:
        text = str(message or "").rstrip("\n")
        if not text:
            return
        self.output.appendPlainText(text)

    def showEvent(self, event) -> None:
        self.visibility_changed.emit(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.visibility_changed.emit(False)
        super().hideEvent(event)


class ConsoleStreamProxy:
    def __init__(self, emit_message, original_stream, *, prefix: str | None = None) -> None:
        self._emit_message = emit_message
        self._original_stream = original_stream
        self._prefix = prefix
        self._buffer = ""
        self.encoding = getattr(original_stream, "encoding", "utf-8")
        self.errors = getattr(original_stream, "errors", "strict")

    def write(self, text) -> int:
        if self._original_stream is not None:
            self._original_stream.write(text)

        if not text:
            return 0

        self._buffer += str(text).replace("\r\n", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit_line(line)
        return len(text)

    def flush(self) -> None:
        if self._original_stream is not None:
            self._original_stream.flush()
        if self._buffer:
            self._emit_line(self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return bool(self._original_stream and self._original_stream.isatty())

    def fileno(self) -> int:
        if self._original_stream is None:
            raise OSError("Console stream has no file descriptor.")
        return self._original_stream.fileno()

    def _emit_line(self, line: str) -> None:
        text = line.rstrip("\r")
        if not text:
            return
        if self._prefix:
            text = f"[{self._prefix}] {text}"
        self._emit_message(text)

    def __getattr__(self, name: str):
        if self._original_stream is None:
            raise AttributeError(name)
        return getattr(self._original_stream, name)


class ConsoleLogHandler(logging.Handler):
    def __init__(self, emit_message) -> None:
        super().__init__()
        self._emit_message = emit_message

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        if message:
            self._emit_message(message)
