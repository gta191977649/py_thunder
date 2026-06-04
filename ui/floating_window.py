from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from dataclasses import field

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from app.config import AppConfig
from app.i18n import Translator
from app.paths import get_thunder5_icons_dir
from core.formatters import format_progress, format_speed
from core.task_model import DownloadTask, TaskStatus
from ui.thunder_menu import ThunderMenu


def _parse_qcolor(value: str) -> QColor:
    color_text = str(value).strip()
    lower_text = color_text.lower()
    if lower_text.startswith(("rgb(", "rgba(")) and color_text.endswith(")"):
        channel_text = color_text[color_text.index("(") + 1 : -1]
        channels = [part.strip() for part in channel_text.split(",")]
        if len(channels) in (3, 4):
            try:
                red = int(channels[0])
                green = int(channels[1])
                blue = int(channels[2])
                alpha = 255
                if len(channels) == 4:
                    alpha_value = float(channels[3])
                    alpha = int(alpha_value * 255) if alpha_value <= 1 else int(alpha_value)
                return QColor(red, green, blue, max(0, min(alpha, 255)))
            except ValueError:
                pass
    return QColor(color_text)


@dataclass(slots=True)
class FloatingWindowModel:
    is_visible: bool = False
    position: QPoint | None = None
    has_live_tasks: bool = False
    total_speed: int = 0
    progress_percent: float = 0.0
    speed_history: deque[int] = field(default_factory=lambda: deque(maxlen=18))

    @property
    def is_active(self) -> bool:
        return self.has_live_tasks


@dataclass(slots=True)
class FloatingTaskTooltipItem:
    name: str
    progress_text: str
    speed_text: str


class FloatingTaskTooltip(QWidget):
    hover_changed = pyqtSignal(bool)

    def __init__(self, theme: dict, font: QFont, parent: QWidget | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.theme = theme
        self._items: list[FloatingTaskTooltipItem] = []
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setFont(font)
        self.hide()

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _color(self, key: str, fallback: str) -> QColor:
        color = _parse_qcolor(self.theme.get("colors", {}).get(key, fallback))
        return color if color.isValid() else _parse_qcolor(fallback)

    def has_items(self) -> bool:
        return bool(self._items)

    def set_items(self, items: list[FloatingTaskTooltipItem]) -> None:
        self._items = list(items)
        self._sync_size()
        self.update()

    def _sync_size(self) -> None:
        padding_x = self._metric("floating_tooltip_padding_x", 8)
        padding_y = self._metric("floating_tooltip_padding_y", 5)
        row_gap = self._metric("floating_tooltip_row_gap", 2)
        row_height = self._metric("floating_tooltip_row_height", 30)
        min_width = self._metric("floating_tooltip_min_width", 220)

        name_font = QFont(self.font())
        name_font.setBold(True)
        detail_font = QFont(self.font())
        detail_font.setPointSize(max(7, detail_font.pointSize() - 1))
        detail_font.setBold(False)
        name_metrics = QFontMetrics(name_font)
        detail_metrics = QFontMetrics(detail_font)

        text_width = 0
        for item in self._items:
            text_width = max(
                text_width,
                name_metrics.horizontalAdvance(item.name),
                detail_metrics.horizontalAdvance(
                    f"{item.progress_text}    {item.speed_text}"
                ),
            )

        width = max(min_width, padding_x * 2 + text_width + 12)
        height = padding_y * 2
        if self._items:
            height += len(self._items) * row_height
            height += max(0, len(self._items) - 1) * row_gap
        else:
            height += row_height
        self.resize(width, height)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, self._color("floating_tooltip_background", "#FCFFBE"))
        painter.setPen(QPen(self._color("floating_tooltip_border", "#000000"), 1))
        painter.drawRect(rect)

        padding_x = self._metric("floating_tooltip_padding_x", 8)
        padding_y = self._metric("floating_tooltip_padding_y", 5)
        row_gap = self._metric("floating_tooltip_row_gap", 2)
        row_height = self._metric("floating_tooltip_row_height", 30)

        name_font = QFont(self.font())
        name_font.setBold(True)
        detail_font = QFont(self.font())
        detail_font.setPointSize(max(7, detail_font.pointSize() - 1))

        content_width = max(10, rect.width() - padding_x * 2)
        top = padding_y
        for index, item in enumerate(self._items):
            row_rect = QRectF(padding_x, top, content_width, row_height)
            painter.setFont(name_font)
            painter.setPen(self._color("floating_tooltip_text", "#000000"))
            name_text = painter.fontMetrics().elidedText(
                item.name,
                Qt.TextElideMode.ElideRight,
                int(content_width),
            )
            painter.drawText(
                row_rect.adjusted(0.0, 0.0, 0.0, -row_height / 2.0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                name_text,
            )

            painter.setFont(detail_font)
            painter.setPen(self._color("floating_tooltip_meta_text", "#000000"))
            painter.drawText(
                row_rect.adjusted(0.0, row_height / 2.0 - 3.0, 0.0, 0.0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                f"{item.progress_text}    {item.speed_text}",
            )

            if index < len(self._items) - 1:
                separator_y = int(row_rect.bottom() + row_gap / 2.0)
                painter.setPen(QPen(self._color("floating_tooltip_separator", "#808080"), 1))
                painter.drawLine(padding_x, separator_y, rect.right() - padding_x, separator_y)
            top += row_height + row_gap

    def enterEvent(self, event) -> None:
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_changed.emit(False)
        super().leaveEvent(event)


class FloatingWindowView(QWidget):
    close_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    show_main_window_requested = pyqtSignal()
    toggle_main_window_requested = pyqtSignal()
    moved = pyqtSignal(QPoint)

    def __init__(self, theme: dict, font: QFont, translator: Translator) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.theme = theme
        self.translator = translator
        self._speed_text = ""
        self._progress_text = ""
        self._progress_percent = 0.0
        self._speed_history: list[int] = []
        self._tooltip_items: list[FloatingTaskTooltipItem] = []
        self._active = False
        self._main_window_visible = True
        self._drag_offset: QPoint | None = None
        self._idle_pixmap = QPixmap(
            str(get_thunder5_icons_dir() / "float_window" / "166.bmp")
        )
        self._tooltip_hovered = False
        self._window_hovered = False
        self._tooltip_show_timer = QTimer(self)
        self._tooltip_show_timer.setSingleShot(True)
        self._tooltip_show_timer.setInterval(140)
        self._tooltip_show_timer.timeout.connect(self._show_task_tooltip)
        self._tooltip_hide_timer = QTimer(self)
        self._tooltip_hide_timer.setSingleShot(True)
        self._tooltip_hide_timer.setInterval(220)
        self._tooltip_hide_timer.timeout.connect(self._hide_task_tooltip)
        self._task_tooltip = FloatingTaskTooltip(theme, font, self)
        self._task_tooltip.hover_changed.connect(self._on_tooltip_hover_changed)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFont(font)
        self._sync_window_size()
        self._apply_shadow()

    def _sync_window_size(self) -> None:
        self.setFixedSize(
            self._pixel_metric("floating_window_width", 68),
            self._pixel_metric("floating_window_height", 68),
        )

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _dpi_scale_factor(self) -> float:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return 1.0
        return max(float(screen.devicePixelRatio()), 1.0)

    def _pixel_metric(self, key: str, fallback: int, minimum: int = 1) -> int:
        value = self._metric(key, fallback)
        scaled = int(round(value / self._dpi_scale_factor()))
        return max(minimum, scaled)

    def _color(self, key: str, fallback: str) -> QColor:
        color = _parse_qcolor(self.theme.get("colors", {}).get(key, fallback))
        return color if color.isValid() else _parse_qcolor(fallback)

    def _apply_shadow(self) -> None:
        shadow_color = self._color("floating_window_shadow", "rgba(0, 0, 0, 90)")
        if not shadow_color.isValid() or shadow_color.alpha() <= 0:
            self.setGraphicsEffect(None)
            return
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(12)
        effect.setOffset(0, 2)
        effect.setColor(shadow_color)
        self.setGraphicsEffect(effect)

    def set_snapshot(
        self,
        speed_text: str,
        progress_text: str,
        progress_percent: float,
        speed_history: list[int],
        active: bool,
    ) -> None:
        self._speed_text = speed_text if active else ""
        self._progress_text = progress_text if active else ""
        self._progress_percent = max(0.0, min(progress_percent, 100.0)) if active else 0.0
        self._speed_history = list(speed_history) if active else []
        self._active = active
        self.update()

    def set_task_details(self, tasks: list[DownloadTask]) -> None:
        self._tooltip_items = [
            FloatingTaskTooltipItem(
                name=task.name or task.gid,
                progress_text=format_progress(task.progress),
                speed_text=format_speed(max(int(task.download_speed or 0), 0)),
            )
            for task in tasks
        ]
        self._task_tooltip.set_items(self._tooltip_items)
        if not self._tooltip_items:
            self._task_tooltip.hide()
            return
        if self._should_keep_tooltip_visible():
            self._show_task_tooltip()

    def set_main_window_visible(self, visible: bool) -> None:
        self._main_window_visible = bool(visible)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        outer_rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if not self._active and not self._idle_pixmap.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(self.rect(), self._idle_pixmap)
            self._draw_outer_border(painter, outer_rect)
            return

        outer_margin = self._pixel_metric("floating_window_outer_margin", 0, minimum=0)
        inner_margin = self._pixel_metric("floating_window_inner_margin", 0, minimum=0)
        radius = max(0, self._pixel_metric("floating_window_radius", 0, minimum=0))
        rect = QRectF(outer_rect)
        if outer_margin > 0:
            rect = rect.adjusted(
                float(outer_margin),
                float(outer_margin),
                float(-outer_margin),
                float(-outer_margin),
            )
        border = self._color("floating_window_border", "#082955")
        top_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top_gradient.setColorAt(0.0, self._color("floating_window_active_background", "#1f5f92"))
        top_gradient.setColorAt(1.0, self._color("floating_window_speed_background", "#0d3e67"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(top_gradient)
        self._draw_frame_rect(painter, rect, radius)

        content_rect = rect.adjusted(
            float(inner_margin),
            float(inner_margin),
            float(-inner_margin),
            float(-inner_margin),
        )
        if self._active:
            self._draw_dashboard(painter, content_rect, radius)
            self._draw_outer_border(painter, outer_rect)
            return
        self._draw_placeholder_icon(painter, content_rect)
        self._draw_outer_border(painter, outer_rect)

    def _draw_frame_rect(self, painter: QPainter, rect: QRectF, radius: int) -> None:
        if radius <= 0:
            painter.drawRect(rect)
            return
        painter.drawRoundedRect(rect, radius, radius)

    def _draw_outer_border(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    def _draw_dashboard(
        self,
        painter: QPainter,
        rect: QRectF,
        radius: int,
    ) -> None:
        separator_gap = self._pixel_metric("floating_window_separator_gap", 1)
        top_ratio = 0.2
        top_height = max(
            10.0,
            min(rect.height() * top_ratio, rect.height() - 12.0),
        )
        top_rect = QRectF(
            rect.left(),
            rect.top(),
            rect.width(),
            top_height,
        )
        plot_rect = QRectF(
            rect.left(),
            top_rect.bottom() + separator_gap,
            rect.width(),
            max(12.0, rect.bottom() - top_rect.bottom() - separator_gap),
        )

        self._draw_speed_block(painter, top_rect, radius)
        self._draw_progress_text(painter, top_rect)
        self._draw_plot_block(painter, plot_rect, radius)

    def _draw_speed_block(self, painter: QPainter, rect: QRectF, radius: int) -> None:
        top_color = self._color("floating_window_active_background", "#1f5f92")
        bottom_color = self._color("floating_window_speed_background", "#0d3e67")
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bottom_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        self._fill_frame_rect(painter, rect, radius)

    def _draw_plot_block(self, painter: QPainter, rect: QRectF, radius: int) -> None:
        plot_background_top = self._color("floating_window_plot_background", "#0a355a")
        plot_background_bottom = self._color("floating_window_plot_background_end", "#0e6f94")
        plot_line = self._color("floating_window_plot_line", "#8fe7ff")
        plot_fill = self._color("floating_window_plot_fill", "rgba(143, 231, 255, 90)")
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, plot_background_top)
        gradient.setColorAt(1.0, plot_background_bottom)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(rect)

        if not self._speed_history:
            return

        max_speed = max(max(self._speed_history), 1)
        point_count = max(len(self._speed_history), 1)
        step = rect.width() / max(point_count - 1, 1)
        points: list[QPointF] = []
        for index, speed in enumerate(self._speed_history):
            x = rect.left() + step * index
            normalized = max(0.0, min(speed / max_speed, 1.0))
            y = rect.bottom() - max(2.0, normalized * max(1.0, rect.height() - 3.0))
            points.append(QPointF(x, y))

        if len(points) == 1:
            points.append(QPointF(rect.right(), points[0].y()))

        fill_polygon = QPolygonF()
        fill_polygon.append(QPointF(rect.left(), rect.bottom()))
        fill_polygon.append(points[0])
        for point in points[1:]:
            fill_polygon.append(point)
        fill_polygon.append(QPointF(rect.right(), rect.bottom()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color("floating_window_plot_fill", "rgba(143, 231, 255, 110)"))
        painter.drawPolygon(fill_polygon)

        painter.setPen(QPen(plot_line, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))

    def _fill_frame_rect(self, painter: QPainter, rect: QRectF, radius: int) -> None:
        if radius <= 0:
            painter.drawRect(rect)
            return
        painter.drawRoundedRect(rect, radius, radius)

    def _draw_placeholder_icon(self, painter: QPainter, rect: QRectF) -> None:
        if not self._idle_pixmap.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap(rect.toRect(), self._idle_pixmap)
            return
        icon_color = self._color("floating_window_icon", "#ffffff")
        pen_width = max(2, int(rect.width() / 9))
        painter.setPen(
            QPen(
                icon_color,
                pen_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)

        mark = QPainterPath()
        mark.moveTo(rect.right() - rect.width() * 0.08, rect.top() + rect.height() * 0.18)
        mark.cubicTo(
            rect.left() + rect.width() * 0.32,
            rect.top() + rect.height() * 0.28,
            rect.left() + rect.width() * 0.18,
            rect.top() + rect.height() * 0.58,
            rect.left() + rect.width() * 0.10,
            rect.bottom() - rect.height() * 0.12,
        )
        painter.drawPath(mark)
        painter.drawLine(
            int(rect.left() + rect.width() * 0.24),
            int(rect.top() + rect.height() * 0.58),
            int(rect.right() - rect.width() * 0.08),
            int(rect.bottom() - rect.height() * 0.12),
        )

    def _draw_progress_text(self, painter: QPainter, rect: QRectF) -> None:
        horizontal_padding = self._pixel_metric("floating_window_text_padding_x", 1)
        vertical_padding = self._pixel_metric("floating_window_text_padding_y", 1)
        font = QFont(self.font())
        font.setPointSize(max(6, self._metric("base_font_size", 10) - 5))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._color("floating_window_progress_text", "#dff6ff"))
        painter.drawText(
            rect.adjusted(
                float(horizontal_padding),
                float(vertical_padding),
                float(-horizontal_padding),
                float(-vertical_padding),
            ),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._progress_text,
        )

    def enterEvent(self, event) -> None:
        self._window_hovered = True
        self._tooltip_hide_timer.stop()
        if self._tooltip_items:
            self._tooltip_show_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._window_hovered = False
        self._tooltip_show_timer.stop()
        self._schedule_tooltip_hide()
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = ThunderMenu(self.theme, self.font(), "", self)
        main_window_text = self.translator.t(
            "floating.hide_main_window"
            if self._main_window_visible
            else "floating.show_main_window"
        )
        show_action = QAction(main_window_text, menu)
        close_action = QAction(self.translator.t("floating.close"), menu)
        exit_action = QAction(self.translator.t("floating.exit_program"), menu)
        show_action.triggered.connect(self.toggle_main_window_requested.emit)
        close_action.triggered.connect(self.close_requested.emit)
        exit_action.triggered.connect(self.exit_requested.emit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(close_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self._ensure_menu_width(menu, [show_action, close_action, exit_action])
        menu.exec(event.globalPos())

    def _ensure_menu_width(self, menu: ThunderMenu, actions: list[QAction]) -> None:
        font_metrics = menu.fontMetrics()
        strip_width = int(self.theme.get("metrics", {}).get("context_menu_icon_strip_width", 26))
        text_gap = int(self.theme.get("metrics", {}).get("context_menu_text_gap", 12))
        right_padding = int(self.theme.get("metrics", {}).get("context_menu_padding_right", 14))
        left_padding = int(self.theme.get("metrics", {}).get("context_menu_padding_left", 18))
        extra_padding = 24

        text_width = 0
        for action in actions:
            text = action.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
            text_width = max(text_width, font_metrics.horizontalAdvance(text))

        minimum_width = strip_width + text_gap + left_padding + right_padding + text_width + extra_padding
        menu.setMinimumWidth(max(minimum_width, 160))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self.show_main_window_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            if self._task_tooltip.isVisible():
                self._position_task_tooltip()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit(self.pos())
            if self._task_tooltip.isVisible():
                self._position_task_tooltip()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:
        self._task_tooltip.hide()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        if self._task_tooltip.isVisible():
            self._position_task_tooltip()
        super().moveEvent(event)

    def _on_tooltip_hover_changed(self, hovered: bool) -> None:
        self._tooltip_hovered = hovered
        if hovered:
            self._tooltip_hide_timer.stop()
            return
        self._schedule_tooltip_hide()

    def _should_keep_tooltip_visible(self) -> bool:
        return (
            self.isVisible()
            and bool(self._tooltip_items)
            and (self._window_hovered or self._tooltip_hovered)
        )

    def _show_task_tooltip(self) -> None:
        if not self._tooltip_items or not self.isVisible():
            return
        self._tooltip_hide_timer.stop()
        self._position_task_tooltip()
        self._task_tooltip.show()
        self._task_tooltip.raise_()
        self._task_tooltip.update()

    def _schedule_tooltip_hide(self) -> None:
        if self._window_hovered or self._tooltip_hovered:
            return
        self._tooltip_hide_timer.start()

    def _hide_task_tooltip(self) -> None:
        if self._window_hovered or self._tooltip_hovered:
            return
        self._task_tooltip.hide()

    def _position_task_tooltip(self) -> None:
        gap = self._pixel_metric("floating_tooltip_gap", 2)
        tooltip_width = self._task_tooltip.width()
        tooltip_height = self._task_tooltip.height()
        preferred = QPoint(
            self.x() - tooltip_width - gap,
            self.y(),
        )
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen is None:
            self._task_tooltip.move(preferred)
            return

        available = screen.availableGeometry()
        x = preferred.x()
        if x < available.left():
            x = self.x() + self.width() + gap
        if x + tooltip_width > available.right():
            x = max(available.left(), available.right() - tooltip_width)

        y = min(
            max(self.y(), available.top()),
            max(available.top(), available.bottom() - tooltip_height),
        )
        self._task_tooltip.move(x, y)


class FloatingWindowPresenter(QObject):
    def __init__(
        self,
        config: AppConfig,
        theme: dict,
        translator: Translator,
        toggle_action: QAction,
        main_window: QWidget,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.theme = theme
        self.translator = translator
        self.toggle_action = toggle_action
        self.main_window = main_window
        self.model = FloatingWindowModel(
            is_visible=bool(config.floating_window_enabled),
            position=self._position_from_config(),
        )
        self.view = FloatingWindowView(theme, main_window.font(), translator)

        self.toggle_action.toggled.connect(self.set_enabled)
        self.view.close_requested.connect(lambda: self.set_enabled(False))
        self.view.exit_requested.connect(self._exit_application)
        self.view.show_main_window_requested.connect(self._show_main_window)
        self.view.toggle_main_window_requested.connect(self._toggle_main_window)
        self.view.moved.connect(self._save_position)

        self._sync_action()
        self._sync_main_window_visibility()
        self._sync_view_visibility(persist=False)

    def update_tasks(self, tasks: list[DownloadTask]) -> None:
        active_tasks = [
            task
            for task in tasks
            if task.status_enum == TaskStatus.ACTIVE
        ]
        self.model.has_live_tasks = bool(active_tasks)
        self.model.total_speed = sum(
            max(int(task.download_speed or 0), 0) for task in active_tasks
        )
        self.model.progress_percent = self._calculate_progress_percent(active_tasks)
        if self.model.has_live_tasks:
            self.model.speed_history.append(self.model.total_speed)
        else:
            self.model.speed_history.clear()

        self.view.set_snapshot(
            speed_text=format_speed(self.model.total_speed),
            progress_text=f"{self.model.progress_percent:.1f}%",
            progress_percent=self.model.progress_percent,
            speed_history=list(self.model.speed_history),
            active=self.model.is_active,
        )
        self.view.set_task_details(active_tasks)

    def set_enabled(self, enabled: bool, persist: bool = True) -> None:
        self.model.is_visible = bool(enabled)
        if persist:
            self.config.floating_window_enabled = self.model.is_visible
            self.config.save()
        self._sync_action()
        self._sync_view_visibility(persist=persist)

    def shutdown(self) -> None:
        self.view.hide()

    def _sync_action(self) -> None:
        with QSignalBlocker(self.toggle_action):
            self.toggle_action.setChecked(self.model.is_visible)

    def _sync_view_visibility(self, persist: bool) -> None:
        if not self.model.is_visible:
            self.view.hide()
            return

        if self.model.position is None:
            self.model.position = self._default_position()
            if persist:
                self._save_position(self.model.position)
        self.view.move(self._clamp_position(self.model.position))
        self.view.show()
        self.view.raise_()

    def _position_from_config(self) -> QPoint | None:
        if self.config.floating_window_x is None or self.config.floating_window_y is None:
            return None
        return QPoint(
            int(self.config.floating_window_x),
            int(self.config.floating_window_y),
        )

    def _default_position(self) -> QPoint:
        screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(80, 80)
        available = screen.availableGeometry()
        return QPoint(
            available.right() - self.view.width() - 24,
            available.center().y() - self.view.height() // 2,
        )

    def _clamp_position(self, position: QPoint) -> QPoint:
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        if screen is None:
            return position
        available = screen.availableGeometry()
        x = min(max(position.x(), available.left()), available.right() - self.view.width())
        y = min(max(position.y(), available.top()), available.bottom() - self.view.height())
        return QPoint(x, y)

    def _save_position(self, position: QPoint) -> None:
        self.model.position = self._clamp_position(position)
        self.config.floating_window_x = self.model.position.x()
        self.config.floating_window_y = self.model.position.y()
        self.config.save()

    def _show_main_window(self) -> None:
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.activateWindow()
        self._sync_main_window_visibility()

    def _toggle_main_window(self) -> None:
        toggle_handler = getattr(self.main_window, "toggle_main_window_visibility", None)
        if callable(toggle_handler):
            toggle_handler()
            return

        if self._is_main_window_visible():
            self.main_window.hide()
        else:
            self._show_main_window()
        self._sync_main_window_visibility()

    def _exit_application(self) -> None:
        exit_handler = getattr(self.main_window, "exit_from_tray", None)
        if callable(exit_handler):
            exit_handler()
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _is_main_window_visible(self) -> bool:
        return self.main_window.isVisible() and not self.main_window.isMinimized()

    def _sync_main_window_visibility(self) -> None:
        self.view.set_main_window_visible(self._is_main_window_visible())

    def _calculate_progress_percent(self, live_tasks: list[DownloadTask]) -> float:
        total_length = 0
        completed_length = 0
        for task in live_tasks:
            task_total = max(int(task.total_length or 0), 0)
            if task_total <= 0:
                continue
            total_length += task_total
            completed_length += min(max(int(task.completed_length or 0), 0), task_total)

        if total_length <= 0:
            return 0.0

        refresh_seconds = max(float(self.config.refresh_interval_ms or 0), 0.0) / 1000.0
        predicted_completed = min(
            total_length,
            completed_length + int(self.model.total_speed * refresh_seconds),
        )
        return min((predicted_completed / total_length) * 100.0, 100.0)
