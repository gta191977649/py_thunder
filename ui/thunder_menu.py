from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import QMenu, QProxyStyle, QStyle, QStyleOptionMenuItem


class ThunderMenuStyle(QProxyStyle):
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
            hover_rect = rect.adjusted(1, 0, -1, -1)
            painter.fillRect(
                hover_rect,
                self._color("context_menu_hover_background", "#d2d2d2"),
            )
            painter.setPen(QPen(self._color("context_menu_hover_border", "#2f62c8"), 1))
            painter.drawRect(hover_rect)
            strip_hover_rect = QRect(
                1,
                rect.top() + 1,
                strip_width - 1,
                rect.height() - 2,
            )
            painter.fillRect(
                strip_hover_rect,
                self._color("context_menu_icon_strip_background", "#f0f0d2"),
            )

        icon_strip_rect = QRect(0, rect.top(), strip_width, rect.height())
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

        text_parts = option.text.split("\t", 1)
        text = text_parts[0]
        shortcut_text = text_parts[1] if len(text_parts) > 1 else ""
        has_submenu = (
            option.menuItemType == QStyleOptionMenuItem.MenuItemType.SubMenu
        )
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
        arrow_width = 18 if has_submenu else 0
        shortcut_width = 58 if shortcut_text else 0
        main_text_rect = text_rect.adjusted(0, 0, -(shortcut_width + arrow_width), 0)
        painter.drawText(
            main_text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        if shortcut_text:
            shortcut_rect = QRect(
                text_rect.right() - shortcut_width - arrow_width,
                text_rect.top(),
                shortcut_width,
                text_rect.height(),
            )
            painter.drawText(
                shortcut_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                shortcut_text,
            )
        if has_submenu:
            arrow_center_x = text_rect.right() - 8
            arrow_center_y = rect.center().y()
            painter.setPen(QPen(text_color, 1))
            painter.drawLine(
                arrow_center_x - 2,
                arrow_center_y - 4,
                arrow_center_x + 1,
                arrow_center_y,
            )
            painter.drawLine(
                arrow_center_x + 1,
                arrow_center_y,
                arrow_center_x - 2,
                arrow_center_y + 4,
            )
        painter.restore()


class ThunderMenu(QMenu):
    def __init__(self, theme: dict, font: QFont, title: str = "", parent=None) -> None:
        super().__init__(title, parent)
        self.theme = theme
        self.setObjectName("thunderMenu")
        menu_font = QFont(font)
        menu_font.setBold(False)
        self.setFont(menu_font)
        self.setSeparatorsCollapsible(False)
        self.setMouseTracking(True)
        self._menu_style = ThunderMenuStyle(theme, self.style())
        self.setStyle(self._menu_style)
        self.hovered.connect(lambda _action: self.update())

    def _color(self, key: str, fallback: str) -> QColor:
        return QColor(self.theme.get("colors", {}).get(key, fallback))

    def _metric(self, key: str, fallback: int) -> int:
        return int(self.theme.get("metrics", {}).get(key, fallback))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), self._color("context_menu_background", "#fffef9"))
        painter.fillRect(
            0,
            0,
            self._metric("context_menu_icon_strip_width", 26),
            self.height(),
            self._color("context_menu_icon_strip_background", "#f0f0d2"),
        )
        painter.setPen(QPen(self._color("context_menu_border", "#7d7d7d"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        active_action = self.activeAction()
        for action in self.actions():
            rect = self.actionGeometry(action)
            if not rect.isValid():
                continue
            if action.isSeparator():
                self._draw_separator(painter, rect)
            else:
                self._draw_action(painter, rect, action, action == active_action)

    def _draw_separator(self, painter: QPainter, rect: QRect) -> None:
        strip_width = self._metric("context_menu_icon_strip_width", 26)
        text_gap = self._metric("context_menu_text_gap", 12)
        painter.setPen(QPen(self._color("context_menu_separator", "#8f8f8f"), 1))
        y = rect.center().y()
        painter.drawLine(rect.left() + strip_width + text_gap, y, rect.right() - 8, y)

    def _draw_action(
        self,
        painter: QPainter,
        rect: QRect,
        action: QAction,
        selected: bool,
    ) -> None:
        strip_width = self._metric("context_menu_icon_strip_width", 26)
        text_gap = self._metric("context_menu_text_gap", 12)
        right_padding = self._metric("context_menu_padding_right", 14)
        icon_offset_x = self._metric("context_menu_icon_offset_x", 0)
        icon_offset_y = self._metric("context_menu_icon_offset_y", 0)
        enabled = action.isEnabled()
        selected = selected and enabled

        painter.save()
        if selected:
            hover_rect = rect.adjusted(1, 0, -1, -1)
            painter.fillRect(
                hover_rect,
                self._color("context_menu_hover_background", "#d2d2d2"),
            )
            painter.fillRect(
                QRect(1, rect.top() + 1, strip_width - 1, rect.height() - 2),
                self._color("context_menu_icon_strip_background", "#f0f0d2"),
            )
            painter.setPen(QPen(self._color("context_menu_hover_border", "#2f62c8"), 1))
            painter.drawRect(hover_rect)

        icon = action.icon()
        if not icon.isNull():
            icon_size = self._metric("context_menu_icon_size", 18)
            mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
            pixmap = icon.pixmap(QSize(icon_size, icon_size), mode)
            icon_rect = QRect(0, 0, icon_size, icon_size)
            icon_rect.moveLeft((strip_width - icon_size) // 2)
            icon_rect.moveTop(rect.top() + (rect.height() - icon_size) // 2)
            icon_rect.translate(icon_offset_x, icon_offset_y)
            painter.drawPixmap(icon_rect, pixmap)

        text_font = QFont(self.font())
        text_font.setBold(False)
        painter.setFont(text_font)
        if not enabled:
            text_color = self._color("context_menu_disabled_text", "#bcbcbc")
        elif selected:
            text_color = self._color("context_menu_hover_text", "#082955")
        else:
            text_color = self._color("context_menu_text", "#082955")
        painter.setPen(text_color)

        text_rect = rect.adjusted(strip_width + text_gap, 2, -right_padding, -2)
        has_submenu = action.menu() is not None
        shortcut_text = self._shortcut_text(action)
        arrow_width = 18 if has_submenu else 0
        shortcut_width = 58 if shortcut_text else 0
        main_text_rect = text_rect.adjusted(0, 0, -(shortcut_width + arrow_width), 0)
        painter.drawText(
            main_text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._display_text(action.text()),
        )

        if shortcut_text:
            shortcut_rect = QRect(
                text_rect.right() - shortcut_width - arrow_width,
                text_rect.top(),
                shortcut_width,
                text_rect.height(),
            )
            painter.drawText(
                shortcut_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                shortcut_text,
            )

        if has_submenu:
            arrow_center_x = text_rect.right() - 8
            arrow_center_y = rect.center().y()
            painter.setPen(QPen(text_color, 1))
            painter.drawLine(
                arrow_center_x - 2,
                arrow_center_y - 4,
                arrow_center_x + 1,
                arrow_center_y,
            )
            painter.drawLine(
                arrow_center_x + 1,
                arrow_center_y,
                arrow_center_x - 2,
                arrow_center_y + 4,
            )
        painter.restore()

    def _display_text(self, text: str) -> str:
        placeholder = "\0"
        return text.replace("&&", placeholder).replace("&", "").replace(placeholder, "&")

    def _shortcut_text(self, action: QAction) -> str:
        shortcut = action.shortcut()
        if shortcut.isEmpty():
            return ""
        return shortcut.toString(QKeySequence.SequenceFormat.NativeText)
