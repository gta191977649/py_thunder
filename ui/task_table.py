from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import (
    QAbstractTableModel,
    QFileInfo,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    QSignalBlocker,
    Qt,
)
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QPolygon
from PyQt6.QtWidgets import (
    QFileIconProvider,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from app.i18n import Translator
from app.paths import get_thunder5_icons_dir
from core.formatters import format_bytes, format_eta, format_progress, format_speed
from core.task_model import DownloadTask, TaskStatus


@dataclass(slots=True)
class TaskConnectionRow:
    label: str
    speed: int


@dataclass(slots=True)
class TaskTableRow:
    task: DownloadTask
    connection: TaskConnectionRow | None = None

    @property
    def is_child(self) -> bool:
        return self.connection is not None


class TaskTableModel(QAbstractTableModel):
    ROW_KIND_ROLE = Qt.ItemDataRole.UserRole + 10
    CAN_EXPAND_ROLE = Qt.ItemDataRole.UserRole + 11
    IS_EXPANDED_ROLE = Qt.ItemDataRole.UserRole + 12
    INDENT_LEVEL_ROLE = Qt.ItemDataRole.UserRole + 13
    EXPANDER_BOX_ROLE = Qt.ItemDataRole.UserRole + 14

    HEADER_KEYS = [
        "table.status",
        "table.name",
        "table.progress",
        "table.speed",
        "table.size",
        "table.eta",
        "table.file_type",
    ]

    def __init__(
        self,
        translator: Translator,
        tasks: list[DownloadTask] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.translator = translator
        self._tasks = tasks or []
        self._thread_rows_by_gid: dict[str, list[TaskConnectionRow]] = {}
        self._expanded_gids: set[str] = set()
        self._rows: list[TaskTableRow] = []
        self._sort_column: int | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._file_icon_provider = QFileIconProvider()
        self._file_icons_by_type: dict[str, QIcon] = {}
        icons_dir = get_thunder5_icons_dir() / "task_status"
        self._status_icons = {
            status.value: QIcon(str(icons_dir / f"{status.value}.png"))
            for status in TaskStatus
            if (icons_dir / f"{status.value}.png").exists()
        }
        self._rebuild_rows()

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADER_KEYS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row_entry = self._rows[index.row()]
        task = row_entry.task
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if row_entry.is_child:
                values = [
                    "",
                    row_entry.connection.label if row_entry.connection else "",
                    "",
                    format_speed(row_entry.connection.speed) if row_entry.connection else "",
                    "",
                    "",
                    "",
                ]
                return values[column]
            remaining = max(task.total_length - task.completed_length, 0)
            speed_text = (
                "--"
                if task.status_enum == TaskStatus.COMPLETE or task.is_completed
                else format_speed(task.download_speed)
            )
            values = [
                "",
                task.name,
                format_progress(task.progress),
                speed_text,
                format_bytes(task.total_length),
                format_eta(remaining, task.download_speed),
                self._file_type_label(task),
            ]
            return values[column]

        if (
            role == Qt.ItemDataRole.DecorationRole
            and column == 0
            and not row_entry.is_child
        ):
            return self._status_icons.get(task.status) or self._status_icons.get(
                TaskStatus.UNKNOWN.value
            )

        if (
            role == Qt.ItemDataRole.DecorationRole
            and column == 1
            and not row_entry.is_child
        ):
            return self._file_icon(task)

        if role == Qt.ItemDataRole.UserRole and column == 2 and not row_entry.is_child:
            return task.progress

        if role == Qt.ItemDataRole.BackgroundRole:
            if row_entry.is_child:
                return self._row_background(task)
            return self._row_background(task)

        if role == self.ROW_KIND_ROLE:
            return "child" if row_entry.is_child else "task"

        if role == self.CAN_EXPAND_ROLE:
            return self.can_expand_row(index.row())

        if role == self.IS_EXPANDED_ROLE:
            return task.gid in self._expanded_gids

        if role == self.INDENT_LEVEL_ROLE:
            return 1 if row_entry.is_child else 0

        if role == self.EXPANDER_BOX_ROLE and column == 1 and not row_entry.is_child:
            return self.can_expand_row(index.row())

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if row_entry.is_child:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if task.status == TaskStatus.ACTIVE.value:
                pass
            if column == 0:
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ToolTipRole:
            if row_entry.is_child:
                return row_entry.connection.label if row_entry.connection else ""
            if column == 0:
                return self.translator.status_label(task.status)
            return self._file_type_label(task) if column == 6 else task.name

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.translator.t(self.HEADER_KEYS[section])
        return str(section + 1)

    def set_tasks(
        self,
        tasks: list[DownloadTask],
        thread_rows_by_gid: dict[str, list[TaskConnectionRow]] | None = None,
    ) -> None:
        self.beginResetModel()
        self._tasks = list(tasks)
        self._thread_rows_by_gid = {
            gid: list(rows) for gid, rows in (thread_rows_by_gid or {}).items()
        }
        valid_task_gids = {task.gid for task in self._tasks}
        self._expanded_gids.intersection_update(valid_task_gids)
        self._apply_task_sort()
        self._rebuild_rows()
        self.endResetModel()

    def sort(
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        if not 0 <= column < self.columnCount():
            return
        self._sort_column = column
        self._sort_order = order
        self.beginResetModel()
        self._apply_task_sort()
        self._rebuild_rows()
        self.endResetModel()

    def _apply_task_sort(self) -> None:
        if self._sort_column is None:
            return

        self._tasks.sort(key=lambda task: (task.created_at or "", task.gid), reverse=True)
        self._tasks.sort(
            key=lambda task: self._sort_value(task, self._sort_column or 0),
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )

    def _sort_value(self, task: DownloadTask, column: int):
        if column == 0:
            return self._status_sort_rank(task)
        if column == 1:
            return (task.name or "").casefold()
        if column == 2:
            return task.progress
        if column == 3:
            return int(task.download_speed or 0)
        if column == 4:
            return int(task.total_length or 0)
        if column == 5:
            remaining = max(task.total_length - task.completed_length, 0)
            if task.status_enum == TaskStatus.COMPLETE or task.is_completed:
                return 0.0
            if task.download_speed <= 0:
                return float("inf")
            return remaining / task.download_speed
        if column == 6:
            return self._file_type_label(task).casefold()
        return ""

    @staticmethod
    def _status_sort_rank(task: DownloadTask) -> int:
        return {
            TaskStatus.ACTIVE: 0,
            TaskStatus.WAITING: 1,
            TaskStatus.PAUSED: 2,
            TaskStatus.ERROR: 3,
            TaskStatus.FAILED: 3,
            TaskStatus.COMPLETE: 4,
            TaskStatus.REMOVED: 5,
            TaskStatus.UNKNOWN: 6,
        }.get(task.status_enum, 6)

    def _row_background(self, task: DownloadTask) -> QColor | None:
        if task.status == TaskStatus.ACTIVE.value:
            return QColor("#d9f4bf")
        if task.status == TaskStatus.WAITING.value:
            return QColor("#eef7cf")
        if task.status == TaskStatus.PAUSED.value:
            return QColor("#f4f1d5")
        if task.status in {TaskStatus.ERROR.value, TaskStatus.FAILED.value}:
            return QColor("#f7d9d9")
        if task.status == TaskStatus.REMOVED.value:
            return QColor("#ececec")
        return None

    def _rebuild_rows(self) -> None:
        rows: list[TaskTableRow] = []
        for task in self._tasks:
            rows.append(TaskTableRow(task=task))
            thread_rows = self._thread_rows_by_gid.get(task.gid) or []
            if task.gid in self._expanded_gids and len(thread_rows) > 1:
                rows.extend(
                    TaskTableRow(task=task, connection=thread_row)
                    for thread_row in thread_rows
                )
        self._rows = rows

    def _file_type_label(self, task: DownloadTask) -> str:
        if task.url.startswith("magnet:"):
            return self.translator.t("file_type.bt_task")

        suffix = Path(task.name or "").suffix.lower()
        if not suffix and task.url:
            parsed = urlparse(task.url)
            suffix = Path(parsed.path).suffix.lower()

        if suffix == ".torrent":
            return self.translator.t("file_type.bt_task")
        if suffix:
            return self.translator.t(
                "file_type.generic",
                ext=suffix.removeprefix(".").upper(),
            )
        return self.translator.t("file_type.unknown")

    def _file_icon(self, task: DownloadTask) -> QIcon | None:
        suffix = Path(task.name or "").suffix.lower()
        if not suffix and task.url:
            parsed = urlparse(task.url)
            suffix = Path(parsed.path).suffix.lower()

        cache_key = suffix or "__generic_file__"
        cached = self._file_icons_by_type.get(cache_key)
        if cached is not None:
            return cached

        if suffix:
            file_info = QFileInfo(f"dummy{suffix}")
            icon = self._file_icon_provider.icon(file_info)
        else:
            icon = self._file_icon_provider.icon(QFileIconProvider.IconType.File)

        self._file_icons_by_type[cache_key] = icon
        return icon

    def get_task_at_row(self, row: int) -> DownloadTask | None:
        if 0 <= row < len(self._rows) and not self._rows[row].is_child:
            return self._rows[row].task
        return None

    def get_owner_task_at_row(self, row: int) -> DownloadTask | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].task
        return None

    def is_child_row(self, row: int) -> bool:
        return 0 <= row < len(self._rows) and self._rows[row].is_child

    def can_expand_row(self, row: int) -> bool:
        if not (0 <= row < len(self._rows)):
            return False
        row_entry = self._rows[row]
        if row_entry.is_child:
            return False
        return len(self._thread_rows_by_gid.get(row_entry.task.gid) or []) > 1

    def toggle_expanded_at_row(self, row: int) -> bool:
        if not self.can_expand_row(row):
            return False
        task = self._rows[row].task
        self.beginResetModel()
        if task.gid in self._expanded_gids:
            self._expanded_gids.remove(task.gid)
        else:
            self._expanded_gids.add(task.gid)
        self._rebuild_rows()
        self.endResetModel()
        return True

    def find_row_by_gid(self, gid: str) -> int:
        for index, row_entry in enumerate(self._rows):
            if not row_entry.is_child and row_entry.task.gid == gid:
                return index
        return -1

    def visible_parent_tasks(self) -> list[DownloadTask]:
        return [row_entry.task for row_entry in self._rows if not row_entry.is_child]


class ProgressBarDelegate(QStyledItemDelegate):
    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme

    def metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def paint(self, painter, option, index) -> None:
        if index.column() != 2 or index.data(TaskTableModel.ROW_KIND_ROLE) == "child":
            super().paint(painter, option, index)
            return

        progress = float(index.data(Qt.ItemDataRole.UserRole) or 0.0)
        pad_x = self.metric("progress_padding_x", 4)
        pad_y = self.metric("progress_padding_y", 4)
        rect = option.rect.adjusted(pad_x, pad_y, -pad_x, -pad_y).adjusted(0, 0, -1, -1)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        if is_selected:
            painter.fillRect(
                option.rect,
                self.color("table_selected_background", "#2f702a"),
            )
        else:
            painter.fillRect(option.rect, self.color("table_background", "#ffffff"))

        border_width = self.metric("progress_border_width", 1)
        inner_rect = rect.adjusted(
            border_width,
            border_width,
            -border_width,
            -border_width,
        )
        painter.fillRect(inner_rect, self.color("progress_track_background", "#ffffff"))
        painter.setPen(
            QPen(
                self.color("progress_border", "#7f8652"),
                border_width,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        fill_inner_width = int(
            inner_rect.width() * max(min(progress, 100.0), 0.0) / 100.0
        )
        if fill_inner_width > 0:
            fill_rect = inner_rect.adjusted(
                0,
                0,
                -(inner_rect.width() - fill_inner_width),
                0,
            )
            painter.fillRect(fill_rect, self.color("progress_fill", "#c8f000"))

        painter.setPen(self.color("progress_text", "#303030"))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            f"{progress:.1f}%",
        )
        painter.restore()


class TaskItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
        if alignment is not None:
            option.displayAlignment = Qt.AlignmentFlag(int(alignment))
        else:
            option.displayAlignment = (
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

        if index.column() == 0:
            option.decorationAlignment = Qt.AlignmentFlag.AlignCenter

    def paint(self, painter, option, index) -> None:
        if index.column() != 1:
            super().paint(painter, option, index)
            return

        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        text_color = (
            option.palette.highlightedText().color()
            if option.state & QStyle.StateFlag.State_Selected
            else QColor("#000000")
        )
        painter.setPen(text_color)
        text_rect = option.rect.adjusted(4, 0, -4, 0)

        indent_level = int(index.data(TaskTableModel.INDENT_LEVEL_ROLE) or 0)
        can_expand = bool(index.data(TaskTableModel.CAN_EXPAND_ROLE))
        is_expanded = bool(index.data(TaskTableModel.IS_EXPANDED_ROLE))
        x = text_rect.left()

        if indent_level:
            x += 18 * indent_level

        if can_expand:
            box_size = 11
            box_rect = QRect(
                x,
                option.rect.center().y() - box_size // 2,
                box_size,
                box_size,
            )
            painter.setBrush(QColor("#f7f7f7"))
            painter.setPen(QPen(QColor("#6f6f6f"), 1))
            painter.drawRect(box_rect)
            painter.drawLine(
                box_rect.left() + 2,
                box_rect.center().y(),
                box_rect.right() - 2,
                box_rect.center().y(),
            )
            if not is_expanded:
                painter.drawLine(
                    box_rect.center().x(),
                    box_rect.top() + 2,
                    box_rect.center().x(),
                    box_rect.bottom() - 2,
                )
            x = box_rect.right() + 6

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon_size = option.widget.iconSize() if option.widget is not None else QSize(16, 16)
            icon_rect = QRect(
                x,
                option.rect.center().y() - icon_size.height() // 2,
                icon_size.width(),
                icon_size.height(),
            )
            icon.paint(
                painter,
                icon_rect,
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal,
                QIcon.State.Off,
            )
            x = icon_rect.right() + 6

        text_rect.setLeft(x)
        painter.setPen(text_color)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
        )
        painter.restore()


class TaskHeaderView(QHeaderView):
    def __init__(self, orientation: Qt.Orientation, theme: dict, parent=None) -> None:
        super().__init__(orientation, parent)
        self.theme = theme
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def set_task_sort_indicator(self, section: int, order: Qt.SortOrder) -> None:
        self._sort_column = section
        self._sort_order = order
        self.viewport().update()

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        if not rect.isValid():
            return

        painter.save()
        gradient = QLinearGradient(
            float(rect.left()),
            float(rect.top()),
            float(rect.left()),
            float(rect.bottom()),
        )
        gradient.setColorAt(0, self._color("table_header_gradient_top", "#f4f8fd"))
        gradient.setColorAt(0.55, self._color("table_header_gradient_mid", "#d4e0ee"))
        gradient.setColorAt(1, self._color("table_header_gradient_bottom", "#bccdde"))
        painter.fillRect(rect, gradient)

        painter.setPen(QPen(self._color("table_header_border", "#92a4bb"), 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        text = str(
            self.model().headerData(
                logicalIndex,
                self.orientation(),
                Qt.ItemDataRole.DisplayRole,
            )
            or ""
        )
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        text_color = self._color("table_header_text", "#21344e")
        painter.setPen(text_color)

        arrow_size = 7 if logicalIndex == self._sort_column else 0
        gap = 4 if arrow_size else 0
        metrics = painter.fontMetrics()
        text = metrics.elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            max(1, rect.width() - arrow_size - gap - 8),
        )
        text_width = metrics.horizontalAdvance(text)
        content_width = text_width + gap + arrow_size
        left = rect.left() + max(4, (rect.width() - content_width) // 2)
        text_rect = QRect(left, rect.top(), text_width, rect.height())
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )

        if arrow_size:
            center_x = text_rect.right() + gap + arrow_size // 2
            center_y = rect.center().y()
            if self._sort_order == Qt.SortOrder.AscendingOrder:
                arrow = QPolygon(
                    [
                        QPoint(center_x, center_y - 3),
                        QPoint(center_x - 4, center_y + 2),
                        QPoint(center_x + 4, center_y + 2),
                    ]
                )
            else:
                arrow = QPolygon(
                    [
                        QPoint(center_x - 4, center_y - 2),
                        QPoint(center_x + 4, center_y - 2),
                        QPoint(center_x, center_y + 3),
                    ]
                )
            painter.setBrush(text_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(arrow)

        painter.restore()


class TaskTableView(QTableView):
    def __init__(self, model: TaskTableModel, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("taskTable")
        self.setModel(model)
        self.setHorizontalHeader(TaskHeaderView(Qt.Orientation.Horizontal, theme, self))
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(False)
        self.setAlternatingRowColors(False)
        self.setShowGrid(True)
        self.setWordWrap(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoScroll(True)
        self.setDragEnabled(False)
        self.setIconSize(
            QSize(
                int(self.theme.get("metrics", {}).get("table_status_icon_size", 16)),
                int(self.theme.get("metrics", {}).get("table_status_icon_size", 16)),
            )
        )
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(
            int(self.theme.get("metrics", {}).get("table_row_height", 24))
        )
        self.setItemDelegate(TaskItemDelegate(self))
        self.setItemDelegateForColumn(2, ProgressBarDelegate(self.theme, self))

        header = self.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(55)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_section_clicked)
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        for section in range(model.columnCount()):
            header.setSectionResizeMode(section, QHeaderView.ResizeMode.Interactive)

        metrics = self.theme.get("metrics", {})
        self.setColumnWidth(0, int(metrics.get("column_status_width", 90)))
        self.setColumnWidth(1, int(metrics.get("column_name_width", 300)))
        self.setColumnWidth(2, int(metrics.get("column_progress_width", 150)))
        self.setColumnWidth(3, int(metrics.get("column_speed_width", 108)))
        self.setColumnWidth(4, int(metrics.get("column_size_width", 108)))
        self.setColumnWidth(5, int(metrics.get("column_eta_width", 120)))
        self.setColumnWidth(6, int(metrics.get("column_file_type_width", 120)))

    def select_all_task_rows(self) -> None:
        model = self.model()
        selection_model = self.selectionModel()
        if not isinstance(model, TaskTableModel) or selection_model is None:
            return

        selection_model.clearSelection()
        first_selected_index = QModelIndex()
        for row in range(model.rowCount()):
            if model.is_child_row(row):
                continue
            index = model.index(row, 0)
            if not first_selected_index.isValid():
                first_selected_index = index
            selection_model.select(
                index,
                selection_model.SelectionFlag.Select
                | selection_model.SelectionFlag.Rows,
            )
        if first_selected_index.isValid():
            selection_model.setCurrentIndex(
                first_selected_index,
                selection_model.SelectionFlag.NoUpdate,
            )

    def _on_header_section_clicked(self, section: int) -> None:
        model = self.model()
        if not isinstance(model, TaskTableModel):
            return

        if section == self._sort_column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = section
            self._sort_order = Qt.SortOrder.AscendingOrder

        selected_gids = self._selected_task_gids()
        model.sort(section, self._sort_order)
        header = self.horizontalHeader()
        if isinstance(header, TaskHeaderView):
            header.set_task_sort_indicator(section, self._sort_order)
        self._restore_selected_task_gids(selected_gids)

    def _selected_task_gids(self) -> list[str]:
        model = self.model()
        selection_model = self.selectionModel()
        if not isinstance(model, TaskTableModel) or selection_model is None:
            return []

        gids: list[str] = []
        seen: set[str] = set()
        for index in selection_model.selectedRows():
            task = model.get_owner_task_at_row(index.row())
            if task and task.gid not in seen:
                seen.add(task.gid)
                gids.append(task.gid)
        return gids

    def _restore_selected_task_gids(self, gids: list[str]) -> None:
        model = self.model()
        selection_model = self.selectionModel()
        if not isinstance(model, TaskTableModel) or selection_model is None:
            return

        with QSignalBlocker(selection_model):
            selection_model.clearSelection()
            first_selected_index = QModelIndex()
            for gid in gids:
                row = model.find_row_by_gid(gid)
                if row < 0:
                    continue
                index = model.index(row, 0)
                if not first_selected_index.isValid():
                    first_selected_index = index
                selection_model.select(
                    index,
                    selection_model.SelectionFlag.Select
                    | selection_model.SelectionFlag.Rows,
                )
            if first_selected_index.isValid():
                selection_model.setCurrentIndex(
                    first_selected_index,
                    selection_model.SelectionFlag.NoUpdate,
                )

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all_task_rows()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and index.column() == 1:
                model = self.model()
                if isinstance(model, TaskTableModel) and model.can_expand_row(index.row()):
                    rect = self.visualRect(index)
                    box_rect = QRect(
                        rect.left() + 4,
                        rect.center().y() - 11 // 2,
                        11,
                        11,
                    )
                    if box_rect.contains(event.position().toPoint()):
                        if model.toggle_expanded_at_row(index.row()):
                            event.accept()
                            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(self.theme["colors"].get("table_grid", "#cbd6e2")), 1))

        row_height = max(
            1,
            int(self.theme.get("metrics", {}).get("table_row_height", 24)),
        )
        row_count = self.model().rowCount() if self.model() else 0
        start_y = 0
        if row_count > 0:
            last_row = row_count - 1
            start_y = self.rowViewportPosition(last_row) + self.rowHeight(last_row)

        viewport_rect = self.viewport().rect()
        if start_y < viewport_rect.height():
            y = start_y
            while y < viewport_rect.height():
                painter.drawLine(viewport_rect.left(), y, viewport_rect.right(), y)
                y += row_height

            x_positions = [0]
            for logical_index in range(self.model().columnCount() if self.model() else 0):
                if self.isColumnHidden(logical_index):
                    continue
                x = self.columnViewportPosition(logical_index)
                if x >= viewport_rect.right():
                    continue
                x_positions.append(x)
                x_positions.append(x + self.columnWidth(logical_index))

            for x in sorted(set(x_positions)):
                painter.drawLine(x, start_y, x, viewport_rect.bottom())
