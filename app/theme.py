from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.paths import get_theme_path, get_theme_presets_dir

FALLBACK_THEME = {
    "meta": {
        "name": "classic_blue",
        "version": 1,
    },
    "colors": {
        "window_background": "#e7edf6",
        "text_primary": "#1a1a1a",
        "menu_background": "#f4f4f0",
        "menu_border": "#93a7c3",
        "menu_hover_background": "#d7e6fa",
        "menu_hover_border": "#8ea2c0",
        "context_menu_background": "#fffef9",
        "context_menu_border": "#7d7d7d",
        "context_menu_icon_strip_background": "#f0f0d2",
        "context_menu_text": "#082955",
        "context_menu_disabled_text": "#bcbcbc",
        "context_menu_hover_background": "#d2d2d2",
        "context_menu_hover_border": "#2f62c8",
        "context_menu_hover_text": "#082955",
        "context_menu_separator": "#8f8f8f",
        "banner_border": "#6f8fb6",
        "banner_gradient_start": "#2b78c4",
        "banner_gradient_mid": "#5ebeff",
        "banner_gradient_end": "#d9e7f6",
        "banner_mark_start": "#f8c665",
        "banner_mark_mid": "#e28c22",
        "banner_mark_end": "#84440b",
        "banner_text": "#ffffff",
        "banner_note_border": "rgba(255, 255, 255, 0.45)",
        "banner_note_background": "rgba(255, 255, 255, 0.15)",
        "toolbar_gradient_top": "#edf3fb",
        "toolbar_gradient_bottom": "#cfdbeb",
        "toolbar_border": "#8ea4c1",
        "toolbar_hover_background": "rgba(255, 255, 255, 0.55)",
        "toolbar_hover_border": "#9ab1ce",
        "toolbar_pressed_background": "rgba(190, 212, 238, 0.75)",
        "toolbar_pressed_border": "#6f93bb",
        "toolbar_disabled_text": "#7a7a7a",
        "toolbar_disabled_icon_fill": "#c8c8c8",
        "toolbar_disabled_icon_border": "#8a8a8a",
        "toolbar_disabled_symbol_highlight": "#f6f6f6",
        "toolbar_disabled_symbol_shadow": "#6c6c6c",
        "panel_border": "#7f99bb",
        "panel_background": "#f7f7f3",
        "panel_title_gradient_top": "#d8e6f8",
        "panel_title_gradient_bottom": "#b6cde7",
        "panel_title_border": "#89a3c3",
        "panel_title_text": "#243a5d",
        "splitter_handle": "#b8c7db",
        "sidebar_background": "#fbfbf7",
        "sidebar_selected_background": "#d6e5f8",
        "sidebar_selected_text": "#17355a",
        "sidebar_branch_line": "#777777",
        "sidebar_branch_control_border": "#6f6f6f",
        "sidebar_branch_control_background": "#f7f7f7",
        "sidebar_branch_control_symbol": "#202020",
        "table_background": "#ffffff",
        "table_grid": "#cbd6e2",
        "table_text": "#000000",
        "table_selected_background": "#2f702a",
        "table_selected_text": "#000000",
        "table_header_gradient_top": "#f4f8fd",
        "table_header_gradient_mid": "#d4e0ee",
        "table_header_gradient_bottom": "#bccdde",
        "table_header_border": "#92a4bb",
        "table_header_text": "#21344e",
        "task_row_active": "#d9f4bf",
        "task_row_waiting": "#eef7cf",
        "task_row_paused": "#f4f1d5",
        "task_row_failed": "#f7d9d9",
        "task_row_removed": "#ececec",
        "progress_border": "#000000",
        "progress_track_background": "#ffffff",
        "progress_fill": "#c8f000",
        "progress_text": "#000000",
        "runtime_background": "#fffef8",
        "runtime_text": "#1f2b38",
        "runtime_selection_background": "#d7e8f8",
        "runtime_tab_background": "#f7f3de",
        "runtime_tab_inactive_background": "#e4e4e4",
        "runtime_tab_active_background": "#fffef8",
        "runtime_tab_border": "#8fa4bf",
        "runtime_tab_text": "#1f2e42",
        "runtime_tab_active_text": "#000000",
        "piece_map_complete": "#2c4fd0",
        "piece_map_active": "#2f7cff",
        "piece_map_partial": "#86a8ff",
        "piece_map_empty": "#ddd8cd",
        "piece_map_unavailable": "#ece8df",
        "piece_map_border": "#6b7c98",
        "input_border": "#88a2bf",
        "input_background": "#ffffff",
        "input_hover_background": "#f2f7fd",
        "delete_dialog_checkbox_text": "#1f2b38",
        "delete_dialog_checkbox_indicator_background": "#fffef8",
        "delete_dialog_checkbox_indicator_border": "#5f7492",
        "delete_dialog_checkbox_indicator_checked_background": "#d6e5f8",
        "delete_dialog_checkbox_indicator_checked_border": "#3b5f91",
        "delete_dialog_checkbox_checkmark": "#243a5d",
        "new_task_space_bar_total_fill": "#eef8fc",
        "new_task_space_bar_background": "#eef8fc",
        "new_task_space_bar_border": "#84d4ec",
        "new_task_space_bar_text": "#1a1a1a",
        "new_task_space_bar_available_fill": "#b89af5",
        "new_task_space_bar_required_fill": "#6fa9ff",
        "status_background": "#d8e5f4",
        "status_gradient_top": "#f8fbff",
        "status_gradient_bottom": "#b8cde7",
        "status_border": "#8ea4c1",
        "floating_window_idle_background": "rgba(4, 115, 184, 120)",
        "floating_window_active_background": "#0473b8",
        "floating_window_border": "#004f85",
        "floating_window_icon": "#ffffff",
        "floating_window_speed_text": "#ffffff",
        "floating_window_progress_text": "#dff6ff",
        "floating_window_speed_background": "#03598f",
        "floating_window_divider": "rgba(255, 255, 255, 90)",
        "floating_window_plot_background": "#02476f",
        "floating_window_plot_background_end": "#0e6f94",
        "floating_window_plot_progress_fill": "#0b88d6",
        "floating_window_plot_progress_edge": "rgba(255, 255, 255, 80)",
        "floating_window_plot_line": "#8fe7ff",
        "floating_window_plot_fill": "rgba(143, 231, 255, 90)",
        "floating_window_shadow": "rgba(0, 0, 0, 0)",
        "floating_tooltip_background": "#FCFFBE",
        "floating_tooltip_border": "#000000",
        "floating_tooltip_text": "#000000",
        "floating_tooltip_meta_text": "#000000",
        "floating_tooltip_separator": "#808080",
    },
    "metrics": {
        "base_font_size": 10,
        "window_width": 1230,
        "window_height": 760,
        "root_margin": 4,
        "root_spacing": 4,
        "toolbar_margin_left": 0,
        "toolbar_margin_top": 0,
        "toolbar_margin_right": 0,
        "toolbar_margin_bottom": 0,
        "toolbar_button_spacing": 0,
        "toolbar_separator_spacing": 2,
        "toolbar_separator_height": 52,
        "toolbar_button_width": 54,
        "toolbar_icon_size": 28,
        "toolbar_button_padding_top": 0,
        "toolbar_button_padding_right": 0,
        "toolbar_button_padding_bottom": 0,
        "toolbar_button_padding_left": 0,
        "sidebar_width": 250,
        "sidebar_icon_size": 18,
        "sidebar_tree_indent": 20,
        "sidebar_tree_line_x": 22,
        "sidebar_tree_tick_width": 14,
        "sidebar_tree_line_gap": 10,
        "sidebar_tree_tick_gap": 4,
        "sidebar_tree_start_offset_y": 8,
        "sidebar_branch_control_size": 13,
        "sidebar_branch_control_symbol_margin": 3,
        "runtime_panel_height": 190,
        "runtime_tab_height": 24,
        "runtime_tab_min_width": 54,
        "runtime_tab_padding_x": 12,
        "runtime_tab_padding_y": 2,
        "runtime_tab_slant": 9,
        "runtime_tab_overlap": 1,
        "piece_map_cell_size": 8,
        "piece_map_cell_gap": 2,
        "piece_map_padding": 8,
        "piece_map_min_height": 120,
        "table_row_height": 24,
        "table_status_icon_size": 16,
        "table_header_padding_top": 0,
        "table_header_padding_right": 0,
        "table_header_padding_bottom": 0,
        "table_header_padding_left": 0,
        "column_name_width": 300,
        "column_size_width": 108,
        "column_progress_width": 150,
        "column_speed_width": 108,
        "column_eta_width": 120,
        "column_status_width": 36,
        "column_file_type_width": 120,
        "progress_padding_x": 4,
        "progress_padding_y": 4,
        "progress_border_width": 1,
        "context_menu_item_height": 22,
        "context_menu_icon_size": 18,
        "context_menu_icon_strip_width": 26,
        "context_menu_icon_offset_x": 0,
        "context_menu_icon_offset_y": 0,
        "context_menu_padding_left": 18,
        "context_menu_padding_right": 14,
        "context_menu_text_gap": 12,
        "delete_dialog_checkbox_spacing": 6,
        "delete_dialog_checkbox_indicator_size": 15,
        "delete_dialog_checkbox_checkmark_width": 2,
        "new_task_space_bar_height": 20,
        "new_task_space_bar_padding_x": 10,
        "new_task_space_bar_padding_y": 1,
        "new_task_space_bar_spacing": 4,
        "new_task_space_bar_section_spacing": 18,
        "floating_window_width": 68,
        "floating_window_height": 68,
        "floating_window_icon_size": 30,
        "floating_window_radius": 0,
        "floating_window_speed_block_height": 26,
        "floating_window_plot_height": 30,
        "floating_tooltip_padding_x": 8,
        "floating_tooltip_padding_y": 5,
        "floating_tooltip_row_gap": 2,
        "floating_tooltip_row_height": 30,
        "floating_tooltip_min_width": 220,
        "floating_tooltip_gap": 2,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _strip_matching_defaults(user_value, reference_value):
    if isinstance(user_value, dict) and isinstance(reference_value, dict):
        stripped: dict = {}
        for key, value in user_value.items():
            if key not in reference_value:
                stripped[key] = value
                continue
            candidate = _strip_matching_defaults(value, reference_value[key])
            if candidate not in ({}, None):
                stripped[key] = candidate
        return stripped
    if user_value == reference_value:
        return None
    return user_value


def compact_legacy_theme_snapshot(user_theme: dict) -> dict:
    stripped = _strip_matching_defaults(user_theme, FALLBACK_THEME)
    if not isinstance(stripped, dict):
        return {}

    meta = user_theme.get("meta")
    if meta:
        stripped["meta"] = meta
    return stripped


def load_default_theme() -> dict:
    preset_path = get_theme_presets_dir() / "classic_blue.json"
    if not preset_path.exists():
        return deepcopy(FALLBACK_THEME)
    return deep_merge(
        FALLBACK_THEME,
        json.loads(preset_path.read_text(encoding="utf-8")),
    )


def ensure_theme_file() -> Path:
    theme_path = get_theme_path()
    if not theme_path.exists():
        theme_path.write_text(
            json.dumps(load_default_theme(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return theme_path


def load_theme() -> dict:
    theme_path = ensure_theme_file()
    default_theme = load_default_theme()
    try:
        user_theme = json.loads(theme_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default_theme

    compact_theme = compact_legacy_theme_snapshot(user_theme)
    if compact_theme != user_theme:
        try:
            theme_path.write_text(
                json.dumps(compact_theme, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        user_theme = compact_theme

    return deep_merge(default_theme, user_theme)


def build_stylesheet(theme: dict, font_family: str | None = None) -> str:
    colors = theme["colors"]
    if font_family:
        escaped_font_family = font_family.replace("\\", "\\\\").replace('"', '\\"')
        font_family_rule = f'font-family: "{escaped_font_family}";'
    else:
        font_family_rule = ""
    base_font_size = int(theme["metrics"].get("base_font_size", 9))
    strip_width = int(theme["metrics"].get("context_menu_icon_strip_width", 26))
    strip_stop = max(0.06, min(0.2, strip_width / 220))
    return f"""
QMainWindow,
QWidget {{
    background-color: {colors['window_background']};
    color: {colors['text_primary']};
    {font_family_rule}
    font-weight: normal;
    font-size: {base_font_size}pt;
}}

QMenuBar {{
    background: {colors['menu_background']};
    border-bottom: 1px solid {colors['menu_border']};
    spacing: 2px;
    {font_family_rule}
    font-weight: normal;
    font-size: {base_font_size}pt;
}}

QMenuBar::item {{
    background: transparent;
    padding: 3px 8px;
}}

QMenuBar::item:selected {{
    background: {colors['menu_hover_background']};
    border: 1px solid {colors['menu_hover_border']};
}}

QMenu {{
    {font_family_rule}
    font-weight: normal;
    font-size: {base_font_size}pt;
}}

QMenu#thunderMenu {{
    background: transparent;
    border: 1px solid transparent;
    padding: 2px 0;
    font-size: 11pt;
    font-weight: normal;
}}

QMenu#thunderMenu::item {{
    min-height: {theme['metrics'].get('context_menu_item_height', 22)}px;
    padding: 2px {theme['metrics'].get('context_menu_padding_right', 14)}px 2px {theme['metrics'].get('context_menu_padding_left', 18)}px;
    color: {colors['context_menu_text']};
    background: transparent;
    text-align: left;
}}

QMenu#thunderMenu::item:selected {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {colors['context_menu_icon_strip_background']},
        stop:{strip_stop:.4f} {colors['context_menu_icon_strip_background']},
        stop:{strip_stop + 0.0001:.4f} {colors['context_menu_hover_background']},
        stop:1 {colors['context_menu_hover_background']}
    );
    border: 1px solid {colors['context_menu_hover_border']};
    color: {colors['context_menu_hover_text']};
}}

QMenu#thunderMenu::item:disabled {{
    color: {colors['context_menu_disabled_text']};
}}

QMenu#thunderMenu::separator {{
    height: 1px;
    background: {colors['context_menu_separator']};
    margin: 5px 8px 5px 26px;
}}

#bannerPanel {{
    border: 1px solid {colors['banner_border']};
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {colors['banner_gradient_start']},
        stop:0.55 {colors['banner_gradient_mid']},
        stop:1 {colors['banner_gradient_end']}
    );
}}

#bannerMark {{
    background: qradialgradient(
        cx:0.3, cy:0.3, radius:0.9,
        fx:0.3, fy:0.3,
        stop:0 {colors['banner_mark_start']},
        stop:0.55 {colors['banner_mark_mid']},
        stop:1 {colors['banner_mark_end']}
    );
    color: {colors['banner_text']};
    border: 2px solid rgba(255, 255, 255, 0.75);
    border-radius: 28px;
    font-size: 24pt;
    font-weight: bold;
}}

#bannerBrand {{
    color: {colors['banner_text']};
    font-size: 18pt;
    font-weight: bold;
    background: transparent;
}}

#bannerSubtitle,
#bannerSlogan,
#bannerNote {{
    background: transparent;
    color: {colors['banner_text']};
}}

#bannerSlogan {{
    font-size: 16pt;
    font-weight: bold;
}}

#bannerNote {{
    padding: 6px 10px;
    border: 1px solid {colors['banner_note_border']};
    background: {colors['banner_note_background']};
}}

#toolbarPanel {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {colors['toolbar_gradient_top']},
        stop:1 {colors['toolbar_gradient_bottom']}
    );
    border: 1px solid {colors['toolbar_border']};
}}

QToolButton#toolbarButton {{
    background: transparent;
    border: 1px solid transparent;
    padding: {theme['metrics'].get('toolbar_button_padding_top', 0)}px {theme['metrics'].get('toolbar_button_padding_right', 0)}px {theme['metrics'].get('toolbar_button_padding_bottom', 0)}px {theme['metrics'].get('toolbar_button_padding_left', 0)}px;
    color: {colors['text_primary']};
    {font_family_rule}
    font-weight: normal;
}}

QToolButton#toolbarButton:hover {{
    background: {colors['toolbar_hover_background']};
    border: 1px solid {colors['toolbar_hover_border']};
}}

QToolButton#toolbarButton:pressed {{
    background: {colors['toolbar_pressed_background']};
    border: 1px solid {colors['toolbar_pressed_border']};
}}

QToolButton#toolbarButton:disabled {{
    color: {colors['toolbar_disabled_text']};
}}

QFrame#panelFrame {{
    border: 1px solid {colors['panel_border']};
    background: {colors['panel_background']};
}}

QLabel#panelTitle {{
    padding: 3px 8px;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {colors['panel_title_gradient_top']},
        stop:1 {colors['panel_title_gradient_bottom']}
    );
    border-bottom: 1px solid {colors['panel_title_border']};
    font-weight: bold;
    color: {colors['panel_title_text']};
    {font_family_rule}
}}

QSplitter#mainSplitter::handle,
QSplitter#leftPaneSplitter::handle,
QSplitter#rightPaneSplitter::handle {{
    background-color: {colors['splitter_handle']};
}}

QTreeWidget#taskSidebar {{
    background: {colors['sidebar_background']};
    border: none;
    outline: none;
    padding: 3px 1px 3px 1px;
    {font_family_rule}
    font-weight: normal;
}}

QTreeWidget#taskSidebar::item {{
    height: 23px;
    padding: 1px 2px;
}}

QTreeWidget#taskSidebar::item:selected {{
    background: {colors['sidebar_selected_background']};
    color: {colors['sidebar_selected_text']};
}}


QTableView#taskTable {{
    background: {colors['table_background']};
    color: {colors.get('table_text', '#000000')};
    border: none;
    gridline-color: {colors['table_grid']};
    selection-background-color: {colors['table_selected_background']};
    selection-color: {colors['table_selected_text']};
    alternate-background-color: {colors['table_background']};
    outline: none;
    {font_family_rule}
    font-weight: normal;
}}

QTableView#taskTable::item {{
    padding: 0 4px;
    border: none;
    outline: none;
}}

QTableView#taskTable::item:selected {{
    background: {colors['table_selected_background']};
    color: {colors['table_selected_text']};
    border: none;
    outline: none;
}}

QTableView#taskTable::item:focus {{
    border: none;
    outline: none;
}}

QHeaderView::section {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {colors['table_header_gradient_top']},
        stop:0.55 {colors['table_header_gradient_mid']},
        stop:1 {colors['table_header_gradient_bottom']}
    );
    border: 1px solid {colors['table_header_border']};
    padding: {theme['metrics'].get('table_header_padding_top', 0)}px {theme['metrics'].get('table_header_padding_right', 0)}px {theme['metrics'].get('table_header_padding_bottom', 0)}px {theme['metrics'].get('table_header_padding_left', 0)}px;
    color: {colors['table_header_text']};
    {font_family_rule}
    font-weight: bold;
}}

QPlainTextEdit#logView,
QPlainTextEdit#threadLogView,
QLabel#taskInfoBody,
QScrollArea#pieceMapScroll,
QWidget#pieceMapWidget {{
    background: {colors['runtime_background']};
    border: none;
    padding: 8px;
    color: {colors['runtime_text']};
    {font_family_rule}
    font-weight: normal;
}}

QScrollArea#pieceMapScroll {{
    padding: 0;
}}

QPlainTextEdit#logView {{
    selection-background-color: {colors['runtime_selection_background']};
}}

QTabWidget#runtimeTabs::pane {{
    border-top: 1px solid {colors['toolbar_border']};
    border-left: 1px solid {colors['toolbar_border']};
    border-right: 1px solid {colors['toolbar_border']};
    border-bottom: none;
    background: {colors['runtime_background']};
    top: 0;
}}

QTabWidget#runtimeTabs QTabBar {{
    background: transparent;
}}

QTabWidget#runtimeTabs QTabBar::tab {{
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    min-width: {theme['metrics'].get('runtime_tab_min_width', 54)}px;
    {font_family_rule}
    font-weight: normal;
}}

QTabWidget#runtimeTabs QTabBar::tab:selected {{
    background: transparent;
    color: {colors['runtime_tab_text']};
}}

QTabWidget#runtimeTabs QTabBar::tab:!selected {{
    background: transparent;
}}

QLineEdit,
QPushButton,
QDialogButtonBox QPushButton {{
    border: 1px solid {colors['input_border']};
    background: {colors['input_background']};
    padding: 4px 8px;
}}

QPushButton:hover,
QDialogButtonBox QPushButton:hover {{
    background: {colors['input_hover_background']};
}}

QWidget#newTaskSpaceBar,
QFrame#newTaskSpaceBar {{
    min-height: {theme['metrics'].get('new_task_space_bar_height', 24)}px;
    background: transparent;
    border: none;
}}

QLabel#newTaskSpaceTitle,
QLabel#newTaskSpaceValue {{
    background: transparent;
    color: {colors['new_task_space_bar_text']};
}}

QLabel#newTaskSpaceTitle {{
    font-weight: bold;
}}

QStatusBar {{
    background: qlineargradient(
        x1: 0,
        y1: 0,
        x2: 0,
        y2: 1,
        stop: 0 {colors.get('status_gradient_top', colors['status_background'])},
        stop: 1 {colors.get('status_gradient_bottom', colors['status_background'])}
    );
    border-top: 1px solid {colors['status_border']};
    {font_family_rule}
    font-weight: normal;
    font-size: {base_font_size}pt;
}}

QStatusBar::item {{
    border: none;
    background: transparent;
}}

QLabel#globalSpeedLabel {{
    background: transparent;
    border: none;
    padding: 0;
    color: {colors['text_primary']};
}}

QStatusBar QSizeGrip {{
    background: transparent;
    border: none;
    width: 14px;
    height: 14px;
}}
""".strip()
