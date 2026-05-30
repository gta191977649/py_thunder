from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QCheckBox


class ThemedCheckBox(QCheckBox):
    def __init__(self, text: str, theme: dict, parent=None) -> None:
        super().__init__(text, parent)
        self.theme = theme

    def _color(self, key: str) -> QColor:
        return QColor(self.theme["colors"][key])

    def _metric(self, key: str) -> int:
        return int(self.theme["metrics"][key])

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        text_height = self.fontMetrics().height()
        indicator_size = self._metric("delete_dialog_checkbox_indicator_size")
        spacing = self._metric("delete_dialog_checkbox_spacing")
        height = max(indicator_size, text_height) + 4
        width = indicator_size + spacing + text_width + 4
        return QSize(width, height)

    def paintEvent(self, event) -> None:
        del event
        indicator_size = self._metric("delete_dialog_checkbox_indicator_size")
        spacing = self._metric("delete_dialog_checkbox_spacing")
        checkmark_width = self._metric("delete_dialog_checkbox_checkmark_width")
        indicator_rect = QRect(
            0,
            (self.height() - indicator_size) // 2,
            indicator_size,
            indicator_size,
        )
        text_rect = QRect(
            indicator_size + spacing,
            0,
            max(self.width() - indicator_size - spacing, 0),
            self.height(),
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        border_color = self._color("delete_dialog_checkbox_indicator_border")
        fill_color = self._color("delete_dialog_checkbox_indicator_background")
        if self.isChecked():
            border_color = self._color("delete_dialog_checkbox_indicator_checked_border")
            fill_color = self._color(
                "delete_dialog_checkbox_indicator_checked_background"
            )
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(fill_color)
        painter.drawRect(indicator_rect.adjusted(0, 0, -1, -1))

        if self.isChecked():
            painter.setPen(
                QPen(
                    self._color("delete_dialog_checkbox_checkmark"),
                    checkmark_width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(
                indicator_rect.left() + indicator_size * 0.22,
                indicator_rect.top() + indicator_size * 0.55,
            )
            path.lineTo(
                indicator_rect.left() + indicator_size * 0.43,
                indicator_rect.top() + indicator_size * 0.75,
            )
            path.lineTo(
                indicator_rect.left() + indicator_size * 0.78,
                indicator_rect.top() + indicator_size * 0.28,
            )
            painter.drawPath(path)

        painter.setPen(self._color("delete_dialog_checkbox_text"))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.text(),
        )
