from __future__ import annotations

import math

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.piece_map import (
    PIECE_STATUS_ACTIVE,
    PIECE_STATUS_COMPLETE,
    PIECE_STATUS_EMPTY,
    PIECE_STATUS_PARTIAL,
    PIECE_STATUS_UNAVAILABLE,
    PieceMapSnapshot,
)


class PieceMapWidget(QWidget):
    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._snapshot = PieceMapSnapshot(
            total_pieces=0,
            display_cells=[],
            available=False,
            message="piece_map.no_task",
        )
        self._message = ""
        self.setObjectName("pieceMapWidget")
        self._recalculate_height()

    def set_snapshot(self, snapshot: PieceMapSnapshot, message_text: str) -> None:
        self._snapshot = snapshot
        self._message = message_text
        self._recalculate_height()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(320, self.minimumHeight())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._recalculate_height()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), self._color("runtime_background", "#fffef8"))

        if not self._snapshot.available or not self._snapshot.display_cells:
            painter.setPen(self._color("runtime_text", "#1f2b38"))
            painter.drawText(
                self.rect().adjusted(10, 10, -10, -10),
                int(
                    Qt.AlignmentFlag.AlignCenter
                    | Qt.TextFlag.TextWordWrap
                ),
                self._message,
            )
            return

        cell_size = self._metric("piece_map_cell_size", 8)
        cell_gap = self._metric("piece_map_cell_gap", 2)
        padding = self._metric("piece_map_padding", 8)
        cell_step = cell_size + cell_gap
        columns = self._column_count()
        if columns <= 0:
            return

        border_color = self._color("piece_map_border", "#7d8ba2")
        top = padding
        left = padding
        for index, status in enumerate(self._snapshot.display_cells):
            row = index // columns
            column = index % columns
            cell_rect = QRect(
                left + column * cell_step,
                top + row * cell_step,
                cell_size,
                cell_size,
            )
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(self._status_color(status))
            painter.drawRoundedRect(cell_rect, 2, 2)

    def _recalculate_height(self) -> None:
        padding = self._metric("piece_map_padding", 8)
        min_height = self._metric("piece_map_min_height", 120)
        if not self._snapshot.available or not self._snapshot.display_cells:
            self.setMinimumHeight(min_height)
            return

        columns = self._column_count()
        rows = max(math.ceil(len(self._snapshot.display_cells) / columns), 1)
        cell_step = self._metric("piece_map_cell_size", 8) + self._metric(
            "piece_map_cell_gap", 2
        )
        content_height = padding * 2 + rows * cell_step
        self.setMinimumHeight(max(min_height, content_height))

    def _column_count(self) -> int:
        padding = self._metric("piece_map_padding", 8)
        cell_step = self._metric("piece_map_cell_size", 8) + self._metric(
            "piece_map_cell_gap", 2
        )
        available_width = max(self.width() - padding * 2, cell_step)
        return max(available_width // cell_step, 1)

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def _status_color(self, status: str) -> QColor:
        if status == PIECE_STATUS_ACTIVE:
            return self._color("piece_map_active", "#2e6bf0")
        if status == PIECE_STATUS_COMPLETE:
            return self._color("piece_map_complete", "#3456da")
        if status == PIECE_STATUS_PARTIAL:
            return self._color("piece_map_partial", "#7ca2ff")
        if status == PIECE_STATUS_EMPTY:
            return self._color("piece_map_empty", "#d8d8d0")
        return self._color("piece_map_unavailable", "#ece8df")
