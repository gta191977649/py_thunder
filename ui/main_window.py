from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPolygon,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProxyStyle,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyleOptionMenuItem,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.i18n import Translator
from app.paths import get_thunder5_icons_dir
from core.download_manager import DownloadManager
from core.formatters import format_bytes, format_duration, format_progress, format_speed
from core.piece_map import PieceMapSnapshot
from core.task_model import DownloadTask, ResumeSupport, TaskStatus
from ui.new_task_dialog import NewTaskDialog
from ui.piece_map_widget import PieceMapWidget
from ui.sidebar import TaskSidebar
from ui.task_table import TaskTableModel, TaskTableView
from ui.themed_checkbox import ThemedCheckBox


class RuntimeTabBar(QTabBar):
    def __init__(self, theme: dict, font: QFont, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setFont(font)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideNone)

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def tabSizeHint(self, index: int) -> QSize:
        text = self.tabText(index)
        horizontal_padding = self._metric("runtime_tab_padding_x", 14)
        vertical_padding = self._metric("runtime_tab_padding_y", 3)
        slant = self._metric("runtime_tab_slant", 10)
        min_width = self._metric("runtime_tab_min_width", 54)
        height = self._metric("runtime_tab_height", 26)
        width = max(
            self.fontMetrics().horizontalAdvance(text) + horizontal_padding * 2 + slant,
            min_width,
        )
        return QSize(width, max(height, self.fontMetrics().height() + vertical_padding * 2))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        slant = self._metric("runtime_tab_slant", 10)
        active_background = self._color("runtime_tab_active_background", "#fffef0")
        inactive_background = self._color("runtime_tab_inactive_background", "#ece4c5")
        border_color = self._color("runtime_tab_border", "#8fa4bf")
        inactive_text_color = self._color("runtime_tab_text", "#1f2e42")
        active_text_color = self._color("runtime_tab_active_text", "#000000")
        current_rect = self.tabRect(self.currentIndex()) if self.currentIndex() >= 0 else QRect()

        painter.setPen(QPen(border_color, 1))
        if current_rect.isValid():
            if current_rect.left() > 0:
                painter.drawLine(0, 0, current_rect.left(), 0)
            if current_rect.right() < self.width() - 1:
                painter.drawLine(current_rect.right(), 0, self.width() - 1, 0)
        else:
            painter.drawLine(0, 0, self.width() - 1, 0)

        for index in range(self.count()):
            rect = self.tabRect(index).adjusted(0, 0, 0, -1)
            selected = index == self.currentIndex()
            fill_color = active_background if selected else inactive_background

            polygon = QPolygon(
                [
                    QPoint(rect.left(), rect.top()),
                    QPoint(rect.right(), rect.top()),
                    QPoint(rect.right() - slant, rect.bottom()),
                    QPoint(rect.left() + slant, rect.bottom()),
                ]
            )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawPolygon(polygon)

            painter.setPen(QPen(border_color, 1))
            painter.drawLine(
                rect.left(),
                rect.top(),
                rect.left() + slant,
                rect.bottom(),
            )
            painter.drawLine(
                rect.right(),
                rect.top(),
                rect.right() - slant,
                rect.bottom(),
            )
            painter.drawLine(
                rect.left() + slant,
                rect.bottom(),
                rect.right() - slant,
                rect.bottom(),
            )

            painter.setPen(active_text_color if selected else inactive_text_color)
            text_font = QFont(self.font())
            text_font.setBold(selected)
            painter.setFont(text_font)
            text_rect = rect.adjusted(0, -1, 0, 0)
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignCenter),
                self.tabText(index),
            )


class TaskContextMenuStyle(QProxyStyle):
    def __init__(self, theme: dict, base_style=None) -> None:
        super().__init__(base_style)
        self.theme = theme

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def drawControl(self, element, option, painter, widget=None) -> None:
        if (
            element == QStyle.ControlElement.CE_MenuItem
            and isinstance(option, QStyleOptionMenuItem)
        ):
            self._draw_menu_item(option, painter, widget)
            return
        super().drawControl(element, option, painter, widget)

    def _draw_menu_item(
        self,
        option: QStyleOptionMenuItem,
        painter: QPainter,
        widget=None,
    ) -> None:
        rect = option.rect
        strip_width = self._metric("context_menu_icon_strip_width", 26)
        text_gap = self._metric("context_menu_text_gap", 12)
        right_padding = self._metric("context_menu_padding_right", 14)
        icon_offset_x = self._metric("context_menu_icon_offset_x", 0)
        icon_offset_y = self._metric("context_menu_icon_offset_y", 0)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        active_action = widget.activeAction() if isinstance(widget, QMenu) else None
        if enabled and active_action and active_action.text() == option.text:
            selected = True

        painter.save()

        if option.menuItemType == QStyleOptionMenuItem.MenuItemType.Separator:
            pen = QPen(self._color("context_menu_separator", "#8f8f8f"), 1)
            painter.setPen(pen)
            y = rect.center().y()
            painter.drawLine(rect.left() + strip_width + text_gap, y, rect.right() - 8, y)
            painter.restore()
            return

        text_rect = rect.adjusted(strip_width + text_gap, 2, -right_padding, -2)
        if selected:
            hover_rect = text_rect.adjusted(-4, 0, 2, 0)
            painter.fillRect(
                hover_rect,
                self._color("context_menu_hover_background", "#d2d2d2"),
            )
            painter.setPen(QPen(self._color("context_menu_hover_border", "#2f62c8"), 1))
            painter.drawRect(hover_rect.adjusted(0, 0, -1, -1))

        icon_strip_rect = QRect(rect.left(), rect.top(), strip_width, rect.height())
        if not option.icon.isNull():
            icon_size = self._metric("context_menu_icon_size", 18)
            mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
            pixmap = option.icon.pixmap(QSize(icon_size, icon_size), mode)
            icon_rect = QRect(0, 0, icon_size, icon_size)
            icon_rect.moveLeft(
                icon_strip_rect.left() + (icon_strip_rect.width() - icon_size) // 2
            )
            icon_rect.moveTop(
                icon_strip_rect.top() + (icon_strip_rect.height() - icon_size) // 2
            )
            icon_rect.translate(icon_offset_x, icon_offset_y)
            painter.drawPixmap(icon_rect, pixmap)

        text = option.text.split("\t", 1)[0]
        text_font = QFont(option.font)
        text_font.setBold(False)
        painter.setFont(text_font)

        if not enabled:
            text_color = self._color("context_menu_disabled_text", "#bcbcbc")
        elif selected:
            text_color = self._color("context_menu_hover_text", "#082955")
        else:
            text_color = self._color("context_menu_text", "#082955")

        painter.setPen(text_color)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        painter.restore()


class TaskContextMenu(QMenu):
    def __init__(self, theme: dict, font: QFont, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("taskContextMenu")
        menu_font = QFont(font)
        menu_font.setBold(False)
        self.setFont(menu_font)
        self.setSeparatorsCollapsible(False)
        self.setMouseTracking(True)
        self._menu_style = TaskContextMenuStyle(theme, self.style())
        self.setStyle(self._menu_style)
        self.hovered.connect(lambda _action: self.update())

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color("context_menu_background", "#fffef9"))
        painter.fillRect(
            0,
            0,
            self._metric("context_menu_icon_strip_width", 26),
            self.height(),
            self._color("context_menu_icon_strip_background", "#d5d5ba"),
        )
        painter.setPen(QPen(self._color("context_menu_border", "#7d7d7d"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        super().paintEvent(event)


class MainWindow(QMainWindow):
    resume_support_resolved = pyqtSignal(str, str)

    def __init__(
        self,
        config: AppConfig,
        theme: dict,
        translator: Translator,
        download_manager: DownloadManager,
        initial_tasks: list[DownloadTask] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.theme = theme
        self.translator = translator
        self.download_manager = download_manager
        self.all_tasks = initial_tasks or []
        self.current_filter = "all"
        self._aria2_warning_shown = False
        self._selected_task_gids: list[str] = []
        self._known_status_by_gid: dict[str, str] = {
            task.gid: task.status for task in self.all_tasks
        }
        self._resume_support_cache: dict[str, str] = {
            task.gid: task.resume_support
            for task in self.all_tasks
            if task.resume_support
        }
        self._resume_support_pending: set[str] = set()
        self.ui_font = self._make_ui_font(int(self.theme_metric("base_font_size", 9)))

        self.setWindowTitle(self.translator.t("app.title"))
        self.setWindowIcon(QIcon(str(get_thunder5_icons_dir() / "app_icon.png")))
        self.resize(
            int(self.theme_metric("window_width", 1230)),
            int(self.theme_metric("window_height", 760)),
        )
        self.setFont(self.ui_font)

        self._build_menu()
        self._build_central_ui()
        self._ensure_runtime_thread_tabs(0)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().setFont(self.ui_font)
        self.statusBar().setSizeGripEnabled(True)
        self.global_speed_label = QLabel(self.statusBar())
        self.global_speed_label.setObjectName("globalSpeedLabel")
        self.global_speed_label.setFont(self.ui_font)
        self.statusBar().addPermanentWidget(self.global_speed_label)

        self.download_manager.tasks_updated.connect(self.on_tasks_updated)
        self.download_manager.task_error.connect(self.on_task_error)
        self.download_manager.aria2_unavailable.connect(self.show_aria2_warning)
        self.resume_support_resolved.connect(self._on_resume_support_resolved)
        self._install_shortcuts()

        self.sidebar.set_task_counts(self.all_tasks)
        self._refresh_task_view()
        self._update_global_speed_label(self.all_tasks)
        self.append_log(self.translator.t("log.ready"))
        self._update_action_states()

    def _make_ui_font(self, point_size: int = 9) -> QFont:
        font = QFont(QApplication.font())
        font.setPointSize(point_size)
        font.setBold(False)
        font.setItalic(False)
        return font

    def theme_metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setFont(self.ui_font)
        for key in [
            "menu.file",
            "menu.edit",
            "menu.view",
            "menu.settings",
            "menu.center",
            "menu.tools",
            "menu.help",
        ]:
            menu = menu_bar.addMenu(self.translator.t(key))
            menu.setFont(self.ui_font)

        self.new_task_action = QAction(self.translator.t("action.new_task"), self)
        self.start_action = QAction(self.translator.t("action.start"), self)
        self.pause_action = QAction(self.translator.t("action.pause"), self)
        self.remove_action = QAction(self.translator.t("action.remove"), self)
        self.open_folder_action = QAction(
            self.translator.t("action.open_folder"),
            self,
        )
        self.settings_action = QAction(self.translator.t("action.settings"), self)

        self.new_task_action.triggered.connect(self.open_new_task_dialog)
        self.start_action.triggered.connect(self.resume_selected_task)
        self.pause_action.triggered.connect(self.pause_selected_task)
        self.remove_action.triggered.connect(self.remove_selected_task)
        self.open_folder_action.triggered.connect(self.open_selected_folder)
        self.settings_action.triggered.connect(self.show_settings_placeholder)

    def _install_shortcuts(self) -> None:
        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self)
        self.delete_shortcut.activated.connect(self.remove_selected_task)
        self.permanent_delete_shortcut = QShortcut(QKeySequence("Shift+Delete"), self)
        self.permanent_delete_shortcut.activated.connect(
            self.permanently_delete_selected_task
        )

    def _build_central_ui(self) -> None:
        root = QWidget(self)
        root.setFont(self.ui_font)
        root_layout = QVBoxLayout(root)
        margin = self.theme_metric("root_margin", 4)
        root_layout.setContentsMargins(margin, margin, margin, margin)
        root_layout.setSpacing(self.theme_metric("root_spacing", 4))

        root_layout.addWidget(self._build_banner())
        root_layout.addWidget(self._build_toolbar_panel())

        self.sidebar = TaskSidebar(self.translator, self.ui_font, self)
        self.sidebar.filter_changed.connect(self.on_filter_changed)

        self.task_model = TaskTableModel(self.translator)
        self.task_table = TaskTableView(self.task_model, self.theme, self)
        table_font = self._make_ui_font(self.theme_metric("base_font_size", 10) + 1)
        self.task_table.setFont(table_font)
        self.task_table.horizontalHeader().setFont(self.ui_font)
        self.task_table.verticalHeader().setFont(self.ui_font)
        self.task_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_table.customContextMenuRequested.connect(
            self._show_task_context_menu
        )
        self.task_table.doubleClicked.connect(self._toggle_task_from_table_index)
        self.task_table.selectionModel().selectionChanged.connect(
            self._on_table_selection_changed
        )

        self.task_info_label = QLabel(self.translator.t("info.no_task"), self)
        self.task_info_label.setObjectName("taskInfoBody")
        self.task_info_label.setFont(self.ui_font)
        self.task_info_label.setWordWrap(True)
        self.task_info_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self.runtime_tabs = self._build_runtime_tabs()

        left_panel = self._wrap_panel(
            self.translator.t("panel.task_tree"),
            self.sidebar,
        )
        right_top_panel = self._wrap_panel(
            self.translator.t("panel.task_list"),
            self.task_table,
        )
        right_bottom_panel = self._wrap_panel(
            self.translator.t("panel.runtime"),
            self.runtime_tabs,
        )

        right_splitter = QSplitter(Qt.Orientation.Vertical, self)
        right_splitter.setObjectName("rightPaneSplitter")
        right_splitter.addWidget(right_top_panel)
        right_splitter.addWidget(right_bottom_panel)
        right_splitter.setSizes([500, self.theme_metric("runtime_panel_height", 190)])

        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setObjectName("mainSplitter")
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([self.theme_metric("sidebar_width", 250), 920])

        root_layout.addWidget(main_splitter, 1)
        self.setCentralWidget(root)

    def _build_runtime_tabs(self) -> QTabWidget:
        tab_widget = QTabWidget(self)
        tab_widget.setObjectName("runtimeTabs")
        tab_widget.setFont(self.ui_font)
        tab_widget.setTabBar(RuntimeTabBar(self.theme, self.ui_font, tab_widget))
        tab_widget.setTabPosition(QTabWidget.TabPosition.South)
        tab_widget.setDocumentMode(False)
        tab_widget.currentChanged.connect(self._on_runtime_tab_changed)

        info_page = QWidget(tab_widget)
        info_layout = QVBoxLayout(info_page)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(self.task_info_label)
        tab_widget.addTab(info_page, self.translator.t("panel.task_info"))

        self.piece_map_widget = PieceMapWidget(self.theme, tab_widget)
        self.piece_map_widget.setFont(self.ui_font)
        self.piece_map_scroll = QScrollArea(tab_widget)
        self.piece_map_scroll.setObjectName("pieceMapScroll")
        self.piece_map_scroll.setWidgetResizable(True)
        self.piece_map_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.piece_map_scroll.setWidget(self.piece_map_widget)
        tab_widget.addTab(self.piece_map_scroll, self.translator.t("panel.piece_map"))

        thread_views: list[QPlainTextEdit] = []
        for thread_index in range(1, 6):
            thread_view = QPlainTextEdit(tab_widget)
            thread_view.setObjectName("logView" if thread_index == 1 else "threadLogView")
            thread_view.setFont(self.ui_font)
            thread_view.setReadOnly(True)
            if thread_index == 1:
                thread_view.setPlainText("")
                thread_view.viewport().setProperty("thread_name", "1")
            else:
                thread_view.setPlainText(self.translator.t("thread.placeholder"))
            thread_views.append(thread_view)
            tab_widget.addTab(
                thread_view,
                self.translator.t("thread.tab", index=thread_index),
            )

        self.thread_views = thread_views
        self.log_view = QPlainTextEdit(self)
        self.log_view.setObjectName("logView")
        self.log_view.setFont(self.ui_font)
        self.log_view.setReadOnly(True)
        self.log_view.hide()
        return tab_widget

    def _ensure_runtime_thread_tabs(self, count: int) -> None:
        count = max(int(count or 0), 0)

        while len(self.thread_views) > count:
            thread_view = self.thread_views.pop()
            tab_index = self.runtime_tabs.indexOf(thread_view)
            if tab_index >= 0:
                self.runtime_tabs.removeTab(tab_index)
            thread_view.deleteLater()

        while len(self.thread_views) < count:
            thread_index = len(self.thread_views) + 1
            thread_view = QPlainTextEdit(self.runtime_tabs)
            thread_view.setObjectName("threadLogView")
            thread_view.setFont(self.ui_font)
            thread_view.setReadOnly(True)
            thread_view.setPlainText(self.translator.t("thread.placeholder"))
            self.thread_views.append(thread_view)
            self.runtime_tabs.addTab(
                thread_view,
                self.translator.t("thread.tab", index=thread_index),
            )

        for thread_index, thread_view in enumerate(self.thread_views, start=1):
            tab_index = self.runtime_tabs.indexOf(thread_view)
            if tab_index >= 0:
                self.runtime_tabs.setTabText(
                    tab_index,
                    self.translator.t("thread.tab", index=thread_index),
                )

    def _build_banner(self) -> QWidget:
        banner = QFrame(self)
        banner.setObjectName("bannerPanel")
        banner.setFont(self.ui_font)

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)

        mark = QLabel("P", banner)
        mark.setObjectName("bannerMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(56, 56)
        mark.setFont(self._make_ui_font(18))

        brand_col = QVBoxLayout()
        brand = QLabel(self.translator.t("banner.brand"), banner)
        brand.setObjectName("bannerBrand")
        brand.setFont(self._make_ui_font(22))
        subtitle = QLabel(self.translator.t("banner.subtitle"), banner)
        subtitle.setObjectName("bannerSubtitle")
        subtitle.setFont(self.ui_font)
        brand_col.addWidget(brand)
        brand_col.addWidget(subtitle)

        slogan = QLabel(self.translator.t("banner.slogan"), banner)
        slogan.setObjectName("bannerSlogan")
        slogan.setFont(self._make_ui_font(18))
        note = QLabel(self.translator.t("banner.note"), banner)
        note.setObjectName("bannerNote")
        note.setFont(self.ui_font)

        layout.addWidget(mark)
        layout.addLayout(brand_col)
        layout.addStretch(1)
        layout.addWidget(slogan)
        layout.addSpacing(10)
        layout.addWidget(note)
        return banner

    def _build_toolbar_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("toolbarPanel")
        panel.setFont(self.ui_font)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(
            self.theme_metric("toolbar_margin_left", 0),
            self.theme_metric("toolbar_margin_top", 0),
            self.theme_metric("toolbar_margin_right", 0),
            self.theme_metric("toolbar_margin_bottom", 0),
        )
        layout.setSpacing(self.theme_metric("toolbar_button_spacing", 0))

        button_groups = [
            [
                (self.new_task_action, "new"),
                (self.start_action, "start"),
                (self.pause_action, "pause"),
                (self.remove_action, "remove"),
            ],
            [
                (self.open_folder_action, "open"),
                (self.settings_action, "settings"),
            ],
        ]

        for group_index, button_specs in enumerate(button_groups):
            for action, icon_kind in button_specs:
                icon = self._load_toolbar_icon(icon_kind)
                action.setIcon(icon)
                button = QToolButton(panel)
                button.setDefaultAction(action)
                button.setObjectName("toolbarButton")
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                button.setFont(self.ui_font)
                icon_size = self.theme_metric("toolbar_icon_size", 28)
                button.setIconSize(QSize(icon_size, icon_size))
                button.setFixedWidth(self.theme_metric("toolbar_button_width", 66))
                layout.addWidget(button)

            if group_index < len(button_groups) - 1:
                separator = QFrame(panel)
                separator.setObjectName("toolbarSeparator")
                separator.setFixedWidth(1)
                separator.setFixedHeight(self.theme_metric("toolbar_separator_height", 56))
                layout.addSpacing(self.theme_metric("toolbar_separator_spacing", 8))
                layout.addWidget(
                    separator,
                    0,
                    Qt.AlignmentFlag.AlignVCenter,
                )
                layout.addSpacing(self.theme_metric("toolbar_separator_spacing", 8))

        layout.addStretch(1)
        return panel

    def _wrap_panel(self, title: str, content: QWidget) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("panelFrame")
        frame.setFont(self.ui_font)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        title_label = QLabel(title, frame)
        title_label.setObjectName("panelTitle")
        title_font = QFont(self.ui_font)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        layout.addWidget(content, 1)
        return frame

    def _load_toolbar_icon(self, icon_kind: str) -> QIcon:
        icons_dir = get_thunder5_icons_dir() / "toolbar"
        normal_path = icons_dir / f"{icon_kind}_normal.png"
        disabled_path = icons_dir / f"{icon_kind}_disabled.png"
        hot_path = icons_dir / f"{icon_kind}_hot.png"
        icon = QIcon()
        icon.addFile(str(normal_path), mode=QIcon.Mode.Normal, state=QIcon.State.Off)
        if disabled_path.exists():
            icon.addFile(
                str(disabled_path),
                mode=QIcon.Mode.Disabled,
                state=QIcon.State.Off,
            )
        if hot_path.exists():
            icon.addFile(str(hot_path), mode=QIcon.Mode.Active, state=QIcon.State.Off)
            icon.addFile(
                str(hot_path),
                mode=QIcon.Mode.Selected,
                state=QIcon.State.Off,
            )
        else:
            icon.addFile(
                str(normal_path),
                mode=QIcon.Mode.Active,
                state=QIcon.State.Off,
            )
            icon.addFile(
                str(normal_path),
                mode=QIcon.Mode.Selected,
                state=QIcon.State.Off,
            )
        return icon

    def _load_menu_icon(self, icon_kind: str) -> QIcon:
        icons_dir = get_thunder5_icons_dir() / "menu"
        normal_path = icons_dir / f"{icon_kind}.png"
        disabled_path = icons_dir / f"{icon_kind}_disabled.png"
        icon = QIcon()
        icon.addFile(str(normal_path), mode=QIcon.Mode.Normal, state=QIcon.State.Off)
        if disabled_path.exists():
            icon.addFile(
                str(disabled_path),
                mode=QIcon.Mode.Disabled,
                state=QIcon.State.Off,
            )
        return icon

    def on_tasks_updated(self, tasks: list[DownloadTask]) -> None:
        self.all_tasks = tasks
        for task in tasks:
            if task.resume_support:
                self._resume_support_cache[task.gid] = task.resume_support
        self.sidebar.set_task_counts(tasks)
        self._log_status_transitions(tasks)
        self._refresh_task_view()
        self._update_global_speed_label(tasks)
        self.statusBar().showMessage(
            self.translator.t("status.loaded", count=len(tasks)),
            2000,
        )
        self._update_task_info_panel()
        self._update_action_states()

    def on_task_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        self.append_log(self.translator.t("log.task_error", message=message))

    def show_aria2_warning(self, message: str) -> None:
        if not message or self._aria2_warning_shown:
            return
        self._aria2_warning_shown = True
        self.append_log(self.translator.t("log.aria2_unavailable", message=message))
        QMessageBox.warning(self, self.translator.t("dialog.aria2.title"), message)

    def on_filter_changed(self, filter_key: str) -> None:
        self.current_filter = filter_key
        self._refresh_task_view()
        self.append_log(
            self.translator.t(
                "log.filter_changed",
                name=self.translator.t(f"status.filter.{filter_key}"),
            )
        )
        self._update_action_states()

    def open_new_task_dialog(self) -> None:
        dialog = NewTaskDialog(
            self.config.default_download_dir,
            self.translator,
            self.theme,
            self,
        )
        dialog.setFont(self.ui_font)
        if dialog.exec():
            url, download_dir = dialog.get_values()
            if dialog.should_save_as_default() and download_dir:
                Path(download_dir).mkdir(parents=True, exist_ok=True)
                self.config.default_download_dir = download_dir
                self.config.save()
            try:
                gid = self.download_manager.add_http_task(url, download_dir)
            except ValueError:
                QMessageBox.warning(
                    self,
                    self.translator.t("dialog.invalid_url.title"),
                    self.translator.t("warn.invalid_url"),
                )
                return
            if gid:
                self._selected_task_gids = [gid]
                self.statusBar().showMessage(self.translator.t("status.added"), 3000)

    def pause_selected_task(self) -> None:
        tasks = self._selected_tasks()
        if not tasks:
            self.statusBar().showMessage(self.translator.t("status.select_pause"), 3000)
            return
        actionable = [task for task in tasks if task.can_pause]
        if not actionable:
            self.statusBar().showMessage(self.translator.t("status.no_pauseable"), 3000)
            return
        self.download_manager.pause_tasks([task.gid for task in actionable])

    def resume_selected_task(self) -> None:
        tasks = self._selected_tasks()
        if not tasks:
            self.statusBar().showMessage(self.translator.t("status.select_start"), 3000)
            return
        actionable = [task for task in tasks if task.can_resume]
        if not actionable:
            self.statusBar().showMessage(self.translator.t("status.no_resumable"), 3000)
            return
        self.download_manager.resume_tasks([task.gid for task in actionable])

    def remove_selected_task(self) -> None:
        self._remove_tasks(self._selected_tasks())

    def permanently_delete_selected_task(self) -> None:
        self._remove_tasks(self._selected_tasks(), permanent=True)

    def open_selected_folder(self) -> None:
        task = self._selected_task()
        if not task or not task.save_path:
            self.statusBar().showMessage(self.translator.t("status.select_open"), 3000)
            return

        self._open_task_folder(task)

    def _open_task_folder(self, task: DownloadTask) -> None:
        try:
            self.download_manager.open_task_folder(task)
        except FileNotFoundError:
            QMessageBox.information(
                self,
                self.translator.t("dialog.folder_missing.title"),
                self.translator.t("dialog.folder_missing.body", path=task.save_path),
            )
        except (RuntimeError, ValueError) as exc:
            QMessageBox.warning(
                self,
                self.translator.t("dialog.open_folder_failed.title"),
                str(exc),
            )

    def _open_completed_task_file(self, task: DownloadTask) -> None:
        if not self.download_manager.task_file_exists(task):
            should_redownload = (
                QMessageBox.question(
                    self,
                    self.translator.t("dialog.redownload_missing_file.title"),
                    self.translator.t("dialog.redownload_missing_file.body"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                == QMessageBox.StandardButton.Yes
            )
            if not should_redownload:
                return
            try:
                new_gid = self.download_manager.redownload_task(task)
            except ValueError as exc:
                QMessageBox.warning(
                    self,
                    self.translator.t("dialog.open_folder_failed.title"),
                    str(exc),
                )
                return
            if new_gid:
                self._selected_task_gids = [new_gid]
                self.statusBar().showMessage(
                    self.translator.t("status.redownload_started"),
                    3000,
                )
            else:
                QMessageBox.warning(
                    self,
                    self.translator.t("dialog.open_folder_failed.title"),
                    self.translator.t("dialog.folder_missing.body", path=task.save_path),
                )
            return

        try:
            self.download_manager.open_task_file(task)
        except (RuntimeError, ValueError) as exc:
            QMessageBox.warning(
                self,
                self.translator.t("dialog.open_folder_failed.title"),
                str(exc),
            )

    def show_settings_placeholder(self) -> None:
        QMessageBox.information(
            self,
            self.translator.t("dialog.settings.title"),
            self.translator.t("dialog.settings.body"),
        )

    def _on_table_selection_changed(self, *_args) -> None:
        self._selected_task_gids = [task.gid for task in self._selected_tasks()]
        self._update_task_info_panel()
        self._update_action_states()

    def _on_runtime_tab_changed(self, _index: int) -> None:
        task = self._selected_task()
        if task:
            self._update_piece_map_for_task(task)

    def _toggle_task_from_table_index(self, index) -> None:
        if not index.isValid():
            return

        if self.task_model.is_child_row(index.row()):
            return

        task = self.task_model.get_task_at_row(index.row())
        if task is None:
            return

        if task.status_enum == TaskStatus.COMPLETE or task.is_completed:
            self._open_completed_task_file(task)
            return

        if task.can_pause:
            self.pause_selected_task()
            return

        if task.can_resume:
            self.resume_selected_task()

    def _selected_task(self) -> DownloadTask | None:
        selection_model = self.task_table.selectionModel()
        if selection_model:
            selected_rows = selection_model.selectedRows()
            if selected_rows:
                return self.task_model.get_owner_task_at_row(selected_rows[0].row())

        index = self.task_table.currentIndex()
        if index.isValid():
            return self.task_model.get_owner_task_at_row(index.row())
        return None

    def _selected_tasks(self) -> list[DownloadTask]:
        selection_model = self.task_table.selectionModel()
        if not selection_model:
            return []

        tasks: list[DownloadTask] = []
        seen_gids: set[str] = set()
        for index in selection_model.selectedRows():
            task = self.task_model.get_owner_task_at_row(index.row())
            if task and task.gid not in seen_gids:
                seen_gids.add(task.gid)
                tasks.append(task)
        return tasks

    def _refresh_task_view(self) -> None:
        selected_gids = list(self._selected_task_gids)
        vertical_scroll = self.task_table.verticalScrollBar().value()
        horizontal_scroll = self.task_table.horizontalScrollBar().value()
        filtered_tasks = self._filtered_tasks()
        thread_rows_by_gid: dict[str, list] = {}
        for task in filtered_tasks:
            thread_rows = self.download_manager.get_task_connection_rows(
                task,
                default_slot_count=max(int(self.config.max_connection_per_server or 1), 1),
            )
            if len(thread_rows) > 1:
                thread_rows_by_gid[task.gid] = thread_rows
        self.task_model.set_tasks(filtered_tasks, thread_rows_by_gid)
        self._restore_selection(selected_gids, scroll_to_current=False)
        self.task_table.verticalScrollBar().setValue(vertical_scroll)
        self.task_table.horizontalScrollBar().setValue(horizontal_scroll)

    def _restore_selection(self, gids: list[str], *, scroll_to_current: bool = True) -> None:
        if not gids:
            self.task_table.clearSelection()
            return

        selection_model = self.task_table.selectionModel()
        if not selection_model:
            return

        rows: list[int] = []
        for gid in gids:
            row = self.task_model.find_row_by_gid(gid)
            if row >= 0:
                rows.append(row)

        if not rows:
            self.task_table.clearSelection()
            self._selected_task_gids = []
            return

        selection_model.clearSelection()
        for row in rows:
            index = self.task_model.index(row, 0)
            selection_model.select(
                index,
                selection_model.SelectionFlag.Select
                | selection_model.SelectionFlag.Rows,
            )

        current_index = self.task_model.index(rows[0], 0)
        self.task_table.setCurrentIndex(current_index)
        if scroll_to_current:
            self.task_table.scrollTo(current_index)

    def _visible_tasks(self) -> list[DownloadTask]:
        return self.task_model.visible_parent_tasks()

    def _show_task_context_menu(self, position) -> None:
        selection_model = self.task_table.selectionModel()
        index = self.task_table.indexAt(position)
        if (
            selection_model
            and index.isValid()
            and not selection_model.isRowSelected(index.row(), index.parent())
        ):
            self.task_table.selectRow(index.row())

        menu = TaskContextMenu(self.theme, self.ui_font, self)

        selected_tasks = self._selected_tasks()
        visible_tasks = self._visible_tasks()
        has_selection = bool(selected_tasks)
        has_url = any(task.url for task in selected_tasks)
        single_completed_task = (
            selected_tasks[0]
            if len(selected_tasks) == 1
            and (
                selected_tasks[0].status_enum == TaskStatus.COMPLETE
                or selected_tasks[0].is_completed
            )
            else None
        )
        can_start = self.download_manager.can_resume_tasks(selected_tasks)
        can_pause = self.download_manager.can_pause_tasks(selected_tasks)
        can_remove = self.download_manager.can_remove_tasks(selected_tasks)
        can_start_all = self.download_manager.can_resume_tasks(visible_tasks)
        can_pause_all = self.download_manager.can_pause_tasks(visible_tasks)
        can_remove_all = self.download_manager.can_remove_tasks(visible_tasks)

        if single_completed_task:
            menu.addAction(
                self._create_context_action(
                    menu,
                    "context.open_file",
                    "open_file",
                    lambda checked=False, task=single_completed_task: self._open_completed_task_file(task),
                    enabled=True,
                )
            )
            menu.addAction(
                self._create_context_action(
                    menu,
                    "context.open_file_folder",
                    "open_file_folder",
                    lambda checked=False, task=single_completed_task: self._open_task_folder(task),
                    enabled=bool(single_completed_task.save_path),
                )
            )
        else:
            menu.addAction(
                self._create_context_action(
                    menu,
                    "context.start_task",
                    "start",
                    self.resume_selected_task,
                    enabled=has_selection and can_start,
                )
            )
            menu.addAction(
                self._create_context_action(
                    menu,
                    "context.pause_task",
                    "pause",
                    self.pause_selected_task,
                    enabled=has_selection and can_pause,
                )
            )
        menu.addAction(
            self._create_context_action(
                menu,
                "context.remove_task",
                "remove",
                self.remove_selected_task,
                enabled=has_selection and can_remove,
            )
        )
        menu.addSeparator()

        menu.addAction(
            self._create_context_action(
                menu,
                "context.play",
                "play",
                lambda: None,
                enabled=False,
            )
        )
        sequential_action = QAction(self.translator.t("context.sequential"), menu)
        sequential_action.setEnabled(False)
        menu.addAction(sequential_action)
        menu.addSeparator()

        select_all_action = QAction(self.translator.t("context.select_all"), menu)
        select_all_action.triggered.connect(self.task_table.selectAll)
        menu.addAction(select_all_action)

        start_all_action = QAction(self.translator.t("context.start_all"), menu)
        start_all_action.setEnabled(can_start_all)
        start_all_action.triggered.connect(
            lambda: self._run_on_tasks(visible_tasks, self.download_manager.resume_tasks)
        )
        menu.addAction(start_all_action)

        pause_all_action = QAction(self.translator.t("context.pause_all"), menu)
        pause_all_action.setEnabled(can_pause_all)
        pause_all_action.triggered.connect(
            lambda: self._run_on_tasks(visible_tasks, self.download_manager.pause_tasks)
        )
        menu.addAction(pause_all_action)

        remove_all_action = QAction(self.translator.t("context.remove_all"), menu)
        remove_all_action.setEnabled(can_remove_all)
        remove_all_action.triggered.connect(lambda: self._remove_tasks(visible_tasks))
        menu.addAction(remove_all_action)
        menu.addSeparator()

        menu.addAction(
            self._create_context_action(
                menu,
                "context.browse_ref",
                "browse",
                self._browse_selected_url,
                enabled=has_selection and has_url,
            )
        )
        menu.addAction(
            self._create_context_action(
                menu,
                "context.copy_url",
                "copy",
                self._copy_selected_urls,
                enabled=has_selection and has_url,
            )
        )
        save_torrent_action = QAction(self.translator.t("context.save_torrent_as"), menu)
        save_torrent_action.setEnabled(False)
        menu.addAction(save_torrent_action)

        details_action = QAction(self.translator.t("context.show_details"), menu)
        details_action.setEnabled(has_selection)
        details_action.triggered.connect(self._show_selected_task_details)
        menu.addAction(details_action)
        menu.addSeparator()

        move_top_action = QAction(self.translator.t("context.move_top"), menu)
        move_top_action.setEnabled(False)
        menu.addAction(move_top_action)
        move_bottom_action = QAction(self.translator.t("context.move_bottom"), menu)
        move_bottom_action.setEnabled(False)
        menu.addAction(move_bottom_action)
        menu.addSeparator()

        menu.addAction(
            self._create_context_action(
                menu,
                "context.properties",
                "properties",
                self._show_selected_task_properties,
                enabled=has_selection,
            )
        )
        menu.exec(self.task_table.viewport().mapToGlobal(position))

    def _create_context_action(
        self,
        menu: QMenu,
        text_key: str,
        icon_kind: str,
        handler,
        *,
        enabled: bool = True,
    ) -> QAction:
        action = QAction(self.translator.t(text_key), menu)
        action.setIcon(self._load_menu_icon(icon_kind))
        action.setEnabled(enabled)
        action.triggered.connect(handler)
        return action

    def _run_on_tasks(self, tasks: list[DownloadTask], action) -> None:
        if not tasks:
            self.statusBar().showMessage(self.translator.t("status.no_selection"), 3000)
            return
        gids = [task.gid for task in tasks]
        self._selected_task_gids = list(gids)
        action(gids)

    def _remove_tasks(
        self,
        tasks: list[DownloadTask],
        *,
        permanent: bool = False,
    ) -> None:
        if not tasks:
            self.statusBar().showMessage(self.translator.t("status.no_selection"), 3000)
            return

        should_permanently_delete = permanent or all(
            task.status_enum == TaskStatus.REMOVED for task in tasks
        )
        if should_permanently_delete:
            delete_files = self._confirm_permanent_delete(tasks)
            if delete_files is None:
                return

            self._selected_task_gids = []
            self.download_manager.permanently_delete_tasks(
                tasks,
                delete_files=delete_files,
            )
            self.statusBar().showMessage(
                self.translator.t(
                    "status.deleted_permanently_with_files"
                    if delete_files
                    else "status.deleted_permanently"
                ),
                3000,
            )
            return

        self._selected_task_gids = []
        self.download_manager.remove_tasks([task.gid for task in tasks])
        self.statusBar().showMessage(self.translator.t("status.moved_to_trash"), 3000)

    def _confirm_permanent_delete(
        self,
        tasks: list[DownloadTask],
    ) -> bool | None:
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setWindowTitle(self.translator.t("dialog.delete_permanent.title"))
        message_box.setText(self.translator.t("dialog.delete_permanent.body"))
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.No)

        checkbox = ThemedCheckBox(
            self.translator.t("dialog.delete_permanent.files"),
            self.theme,
            message_box,
        )
        checkbox.setFont(self.ui_font)
        checkbox.setChecked(False)
        message_box.setCheckBox(checkbox)
        message_box._toggle_delete_files_shortcut = QShortcut(  # type: ignore[attr-defined]
            QKeySequence("D"),
            message_box,
        )
        message_box._toggle_delete_files_shortcut.activated.connect(checkbox.toggle)  # type: ignore[attr-defined]

        result = message_box.exec()
        if result != int(QMessageBox.StandardButton.Yes):
            return None
        return checkbox.isChecked()

    def _browse_selected_url(self) -> None:
        task = self._selected_task()
        if not task or not task.url:
            self.statusBar().showMessage(self.translator.t("status.no_url"), 3000)
            return
        try:
            self.download_manager.open_task_url(task)
        except (RuntimeError, ValueError) as exc:
            self.statusBar().showMessage(str(exc), 3000)

    def _copy_selected_urls(self) -> None:
        tasks = self._selected_tasks()
        if not tasks:
            self.statusBar().showMessage(self.translator.t("status.no_url"), 3000)
            return
        try:
            self.download_manager.copy_task_urls(tasks)
        except ValueError:
            self.statusBar().showMessage(self.translator.t("status.no_url"), 3000)
            return
        self.statusBar().showMessage(self.translator.t("status.url_copied"), 3000)

    def _show_selected_task_details(self) -> None:
        task = self._selected_task()
        if not task:
            self.statusBar().showMessage(self.translator.t("status.no_selection"), 3000)
            return
        self.runtime_tabs.setCurrentIndex(0)
        self._update_task_info_panel()
        QMessageBox.information(
            self,
            self.translator.t("dialog.details.title"),
            self._task_summary_text(task),
        )

    def _show_selected_task_properties(self) -> None:
        task = self._selected_task()
        if not task:
            self.statusBar().showMessage(self.translator.t("status.no_selection"), 3000)
            return
        QMessageBox.information(
            self,
            self.translator.t("dialog.properties.title"),
            self._task_summary_text(task),
        )

    def _task_summary_text(self, task: DownloadTask) -> str:
        return self.translator.t(
            "info.properties_body",
            name=task.name,
            status=self.translator.status_label(task.status),
            progress=format_progress(task.progress),
            size=format_bytes(task.total_length),
            elapsed=format_duration(task.current_elapsed_seconds()),
            path=task.save_path or "-",
            url=task.url or "-",
        )

    def _update_action_states(self) -> None:
        selected_tasks = self._selected_tasks()
        selected_task = self._selected_task()
        has_selection = bool(selected_tasks)
        can_start = self.download_manager.can_resume_tasks(selected_tasks)
        can_pause = self.download_manager.can_pause_tasks(selected_tasks)
        can_remove = self.download_manager.can_remove_tasks(selected_tasks)
        can_open_folder = (
            selected_task is not None
            and bool(selected_task.save_path)
            and len(selected_tasks) == 1
        )

        self.new_task_action.setEnabled(True)
        self.start_action.setEnabled(has_selection and can_start)
        self.pause_action.setEnabled(has_selection and can_pause)
        self.remove_action.setEnabled(has_selection and can_remove)
        self.open_folder_action.setEnabled(can_open_folder)
        self.settings_action.setEnabled(True)

    def _update_task_info_panel(self) -> None:
        task = self._selected_task()
        if not task:
            self.task_info_label.setText(self.translator.t("info.no_task"))
            self.piece_map_widget.set_snapshot(
                PieceMapSnapshot(
                    total_pieces=0,
                    display_cells=[],
                    available=False,
                    message="piece_map.no_task",
                ),
                self.translator.t("piece_map.no_task"),
            )
            self._ensure_runtime_thread_tabs(0)
            return

        resume_support = task.resume_support or self._resume_support_cache.get(task.gid)
        if resume_support is None:
            resume_support_text = self.translator.t("info.resume_support_checking")
            self._ensure_resume_support_probe(task)
        else:
            resume_support_text = self._resume_support_text(resume_support)

        lines = [
            self.translator.t("info.task_name", name=task.name),
            self.translator.t(
                "info.task_status",
                status=self.translator.status_label(task.status),
            ),
            self.translator.t(
                "info.task_progress",
                progress=format_progress(task.progress),
            ),
            self.translator.t("info.task_size", size=format_bytes(task.total_length)),
            self.translator.t(
                "info.task_elapsed",
                value=format_duration(task.current_elapsed_seconds()),
            ),
            self.translator.t("info.task_resume_support", value=resume_support_text),
            self.translator.t("info.task_save_path", path=task.save_path or "-"),
            self.translator.t("info.task_url", url=task.url or "-"),
        ]
        self.task_info_label.setText("\n".join(lines))
        self._update_piece_map_for_task(task)
        thread_count, thread_lines = self.download_manager.get_thread_runtime_view(
            task,
            default_slot_count=max(int(self.config.max_connection_per_server or 1), 1),
        )
        self._ensure_runtime_thread_tabs(thread_count)
        for index, thread_view in enumerate(self.thread_views):
            thread_view.setPlainText(thread_lines[index])

    def _ensure_resume_support_probe(self, task: DownloadTask) -> None:
        if (
            task.resume_support
            or task.gid in self._resume_support_cache
            or task.gid in self._resume_support_pending
        ):
            return
        self._resume_support_pending.add(task.gid)
        threading.Thread(
            target=self._probe_resume_support_worker,
            args=(task.gid, task.url, task.name),
            daemon=True,
        ).start()

    def _probe_resume_support_worker(self, gid: str, url: str, name: str) -> None:
        value = self._detect_resume_support(url, name)
        self.resume_support_resolved.emit(gid, value)

    def _on_resume_support_resolved(self, gid: str, value: str) -> None:
        self._resume_support_pending.discard(gid)
        self._resume_support_cache[gid] = value
        self.download_manager.update_task_resume_support(gid, value)
        for task in self.all_tasks:
            if task.gid == gid:
                task.resume_support = value
                break
        current_task = self._selected_task()
        if current_task and current_task.gid == gid:
            current_task.resume_support = value
            self._update_task_info_panel()

    def _resume_support_text(self, value: str) -> str:
        if value == ResumeSupport.YES.value:
            return self.translator.t("info.resume_support_yes")
        if value == ResumeSupport.NO.value:
            return self.translator.t("info.resume_support_no")
        return self.translator.t("info.resume_support_unknown")

    def _detect_resume_support(self, url: str, name: str) -> str:
        lowered_url = (url or "").lower()
        lowered_name = (name or "").lower()
        if lowered_url.startswith("magnet:") or lowered_name.endswith(".torrent"):
            return ResumeSupport.YES.value

        parsed = urlparse(url or "")
        if parsed.scheme not in {"http", "https"}:
            return ResumeSupport.UNKNOWN.value

        try:
            head_response = requests.head(url, allow_redirects=True, timeout=3)
            accept_ranges = (head_response.headers.get("Accept-Ranges") or "").lower()
            if "bytes" in accept_ranges:
                return ResumeSupport.YES.value
        except requests.RequestException:
            pass

        try:
            range_response = requests.get(
                url,
                headers={"Range": "bytes=0-0"},
                stream=True,
                allow_redirects=True,
                timeout=4,
            )
            if range_response.status_code == 206:
                range_response.close()
                return ResumeSupport.YES.value
            content_range = range_response.headers.get("Content-Range") or ""
            range_response.close()
            if content_range.lower().startswith("bytes "):
                return ResumeSupport.YES.value
            if range_response.status_code == 200:
                return ResumeSupport.NO.value
        except requests.RequestException:
            return ResumeSupport.UNKNOWN.value

        return ResumeSupport.UNKNOWN.value

    def _update_piece_map_for_task(self, task: DownloadTask) -> None:
        if self.runtime_tabs.currentWidget() is not self.piece_map_scroll:
            return
        piece_snapshot = self.download_manager.get_task_piece_map_snapshot(task)
        piece_message = (
            self.translator.t(piece_snapshot.message)
            if piece_snapshot.message
            else ""
        )
        self.piece_map_widget.set_snapshot(piece_snapshot, piece_message)

    def _update_global_speed_label(self, tasks: list[DownloadTask]) -> None:
        total_speed = sum(max(int(task.download_speed or 0), 0) for task in tasks)
        self.global_speed_label.setText(
            self.translator.t(
                "status.global_speed",
                speed=format_speed(total_speed),
            )
        )

    def _log_status_transitions(self, tasks: list[DownloadTask]) -> None:
        for task in tasks:
            previous_status = self._known_status_by_gid.get(task.gid)
            if previous_status is None:
                self._known_status_by_gid[task.gid] = task.status
                continue
            if previous_status != task.status:
                self.append_log(
                    self.translator.t(
                        "log.task_status_changed",
                        name=task.name,
                        status=self.translator.status_label(task.status),
                    )
                )
                self._known_status_by_gid[task.gid] = task.status

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_view.appendPlainText(f"{timestamp}  {message}")

    def _filtered_tasks(self) -> list[DownloadTask]:
        return self.download_manager.filter_tasks(self.all_tasks, self.current_filter)
