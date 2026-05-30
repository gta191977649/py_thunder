from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import QProxyStyle, QStyle, QTreeWidget, QTreeWidgetItem

from app.i18n import Translator
from app.paths import get_thunder5_icons_dir
from core.task_model import DownloadTask


class SidebarBranchStyle(QProxyStyle):
    def __init__(self, theme: dict, base_style=None) -> None:
        super().__init__(base_style)
        self.theme = theme

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        if element == QStyle.PrimitiveElement.PE_IndicatorBranch:
            self._draw_branch(option, painter)
            return
        super().drawPrimitive(element, option, painter, widget)

    def _draw_branch(self, option, painter: QPainter) -> None:
        rect = option.rect
        if not rect.isValid():
            return

        state = option.state
        has_children = bool(state & QStyle.StateFlag.State_Children)
        has_sibling = bool(state & QStyle.StateFlag.State_Sibling)
        has_item = bool(state & QStyle.StateFlag.State_Item)
        is_open = bool(state & QStyle.StateFlag.State_Open)

        center_x = rect.center().x()
        center_y = rect.center().y()

        painter.save()
        guide_pen = QPen(self._color("sidebar_branch_line", "#777777"), 1)
        guide_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(guide_pen)

        if has_sibling:
            painter.drawLine(center_x, rect.top(), center_x, rect.bottom())
        elif has_item:
            painter.drawLine(center_x, rect.top(), center_x, center_y)

        if has_item:
            painter.drawLine(center_x, center_y, rect.right(), center_y)

        if has_children and is_open:
            painter.drawLine(center_x, center_y, center_x, rect.bottom())

        if has_children:
            control_size = self._metric("sidebar_branch_control_size", 13)
            control_rect = rect.adjusted(0, 0, 0, 0)
            control_rect.setWidth(control_size)
            control_rect.setHeight(control_size)
            control_rect.moveCenter(rect.center())

            painter.fillRect(
                control_rect,
                self._color("sidebar_branch_control_background", "#f7f7f7"),
            )
            painter.setPen(
                QPen(self._color("sidebar_branch_control_border", "#6f6f6f"), 1)
            )
            painter.drawRect(control_rect.adjusted(0, 0, -1, -1))

            symbol_margin = self._metric("sidebar_branch_control_symbol_margin", 3)
            symbol_rect = control_rect.adjusted(
                symbol_margin,
                symbol_margin,
                -symbol_margin,
                -symbol_margin,
            )
            painter.setPen(
                QPen(self._color("sidebar_branch_control_symbol", "#202020"), 1)
            )
            painter.drawLine(
                symbol_rect.left(),
                symbol_rect.center().y(),
                symbol_rect.right(),
                symbol_rect.center().y(),
            )
            if not is_open:
                painter.drawLine(
                    symbol_rect.center().x(),
                    symbol_rect.top(),
                    symbol_rect.center().x(),
                    symbol_rect.bottom(),
                )

        painter.restore()


class TaskSidebar(QTreeWidget):
    filter_changed = pyqtSignal(str)

    FILTER_KEYS = [
        "all",
        "downloading",
        "completed",
        "paused",
        "failed",
        "trash",
    ]

    def __init__(self, translator: Translator, ui_font: QFont, parent=None) -> None:
        super().__init__(parent)
        self.translator = translator
        self.ui_font = ui_font
        self.theme = getattr(parent, "theme", {}) if parent is not None else {}
        self.setObjectName("taskSidebar")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(self._metric("sidebar_tree_indent", 14))
        self.setIconSize(
            QSize(
                self._metric("sidebar_icon_size", 18),
                self._metric("sidebar_icon_size", 18),
            )
        )
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFont(self.ui_font)
        self._branch_style = SidebarBranchStyle(self.theme, self.style())
        self.setStyle(self._branch_style)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._base_labels: dict[str, str] = {}
        self._build_tree()
        self.currentItemChanged.connect(self._emit_filter_change)
        self.itemCollapsed.connect(self._select_root_if_current_item_is_hidden)
        self.setCurrentItem(self._items["all"])
        self.expandAll()

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def current_filter_key(self) -> str:
        item = self.currentItem()
        if item is None:
            return "all"
        return item.data(0, Qt.ItemDataRole.UserRole) or "all"

    def _select_root_if_current_item_is_hidden(self, item: QTreeWidgetItem) -> None:
        root = self._items.get("all")
        current = self.currentItem()
        if item is root and current is not None and current is not root:
            self.setCurrentItem(root)

    def _build_tree(self) -> None:
        root_label = self.translator.t("sidebar.all")
        root = QTreeWidgetItem([root_label])
        root.setData(0, Qt.ItemDataRole.UserRole, "all")
        root.setFont(0, self.ui_font)
        root.setIcon(0, self._make_sidebar_icon("all"))
        self.addTopLevelItem(root)
        self._items["all"] = root
        self._base_labels["all"] = root_label

        for filter_key in self.FILTER_KEYS[1:]:
            item_label = self.translator.t(f"sidebar.{filter_key}")
            item = QTreeWidgetItem([item_label])
            item.setData(0, Qt.ItemDataRole.UserRole, filter_key)
            item.setFont(0, self.ui_font)
            item.setIcon(0, self._make_sidebar_icon(filter_key))
            root.addChild(item)
            self._items[filter_key] = item
            self._base_labels[filter_key] = item_label

    def set_task_counts(self, tasks: list[DownloadTask]) -> None:
        for filter_key, item in self._items.items():
            base_label = self._base_labels.get(filter_key, item.text(0))
            count = sum(1 for task in tasks if task.matches_filter(filter_key))
            item.setText(0, f"{base_label}({count})")

    def _make_sidebar_icon(self, filter_key: str) -> QIcon:
        icon_path = get_thunder5_icons_dir() / "sidebar" / f"{filter_key}.png"
        return QIcon(str(icon_path))

    def _emit_filter_change(self, current, _previous) -> None:
        if current is None:
            return
        self.filter_changed.emit(current.data(0, Qt.ItemDataRole.UserRole) or "all")
