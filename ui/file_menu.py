from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence
from PyQt6.QtWidgets import QMenuBar, QWidget

from app.i18n import Translator
from ui.thunder_menu import ThunderMenu


@dataclass(slots=True)
class FileMenuCallbacks:
    new_task: Callable[[], None]
    open_torrent: Callable[[], None]
    move_to: Callable[[], None]
    start_selected: Callable[[], None]
    pause_selected: Callable[[], None]
    remove_selected: Callable[[], None]
    redownload_selected: Callable[[], None]
    batch_new: Callable[[], None]
    start_all: Callable[[], None]
    pause_all: Callable[[], None]
    remove_all: Callable[[], None]
    clear_trash: Callable[[], None]
    import_unfinished: Callable[[], None]
    import_list: Callable[[], None]
    export_list: Callable[[], None]
    quit_app: Callable[[], None]


@dataclass(slots=True)
class FileMenuActions:
    menu: ThunderMenu
    new_task: QAction
    open_torrent: QAction
    move_to: QAction
    start_selected: QAction
    pause_selected: QAction
    remove_selected: QAction
    redownload_selected: QAction
    batch_new: QAction
    start_all: QAction
    pause_all: QAction
    remove_all: QAction
    clear_trash: QAction
    import_unfinished: QAction
    import_list: QAction
    export_list: QAction
    quit_app: QAction


def build_file_menu(
    *,
    parent: QWidget,
    menu_bar: QMenuBar,
    translator: Translator,
    theme: dict,
    font: QFont,
    callbacks: FileMenuCallbacks,
    icon_loader: Callable[[str], QIcon],
) -> FileMenuActions:
    menu = ThunderMenu(theme, font, translator.t("menu.file"), menu_bar)
    menu_bar.addMenu(menu)

    new_task = _create_action(
        parent,
        translator.t("menu.file.new_task"),
        callbacks.new_task,
        icon=icon_loader("new"),
        shortcut="Ctrl+N",
    )
    open_torrent = _create_action(
        parent,
        translator.t("menu.file.open_torrent"),
        callbacks.open_torrent,
        icon=icon_loader("open_file"),
    )
    move_to = _create_action(
        parent,
        translator.t("menu.file.move_to"),
        callbacks.move_to,
        icon=icon_loader("browse"),
    )
    start_selected = _create_action(
        parent,
        translator.t("menu.file.start"),
        callbacks.start_selected,
        icon=icon_loader("start"),
        shortcut="F5",
    )
    pause_selected = _create_action(
        parent,
        translator.t("menu.file.pause"),
        callbacks.pause_selected,
        icon=icon_loader("pause"),
        shortcut="F6",
    )
    remove_selected = _create_action(
        parent,
        translator.t("menu.file.remove"),
        callbacks.remove_selected,
        icon=icon_loader("remove"),
    )
    redownload_selected = _create_action(
        parent,
        translator.t("menu.file.redownload"),
        callbacks.redownload_selected,
        icon=icon_loader("play"),
    )
    batch_new = _create_action(
        parent,
        translator.t("menu.file.batch_new"),
        callbacks.batch_new,
        icon=icon_loader("new"),
    )
    start_all = _create_action(
        parent,
        translator.t("menu.file.start_all"),
        callbacks.start_all,
        icon=icon_loader("start"),
        shortcut="F8",
    )
    pause_all = _create_action(
        parent,
        translator.t("menu.file.pause_all"),
        callbacks.pause_all,
        icon=icon_loader("pause"),
        shortcut="F9",
    )
    remove_all = _create_action(
        parent,
        translator.t("menu.file.remove_all"),
        callbacks.remove_all,
        icon=icon_loader("remove"),
        shortcut="F10",
    )
    clear_trash = _create_action(
        parent,
        translator.t("menu.file.clear_trash"),
        callbacks.clear_trash,
        icon=icon_loader("remove"),
    )
    import_unfinished = _create_action(
        parent,
        translator.t("menu.file.import_unfinished"),
        callbacks.import_unfinished,
        icon=icon_loader("browse"),
    )
    import_list = _create_action(
        parent,
        translator.t("menu.file.import_list"),
        callbacks.import_list,
        icon=icon_loader("browse"),
    )
    export_list = _create_action(
        parent,
        translator.t("menu.file.export_list"),
        callbacks.export_list,
        icon=icon_loader("copy"),
    )
    quit_app = _create_action(
        parent,
        translator.t("menu.file.exit"),
        callbacks.quit_app,
        icon=icon_loader("remove"),
        shortcut=QKeySequence.StandardKey.Quit,
    )

    menu.addAction(new_task)
    menu.addAction(open_torrent)
    menu.addAction(move_to)
    menu.addSeparator()
    menu.addAction(start_selected)
    menu.addAction(pause_selected)
    menu.addAction(remove_selected)
    menu.addAction(redownload_selected)
    menu.addSeparator()
    menu.addAction(batch_new)
    menu.addSeparator()
    menu.addAction(start_all)
    menu.addAction(pause_all)
    menu.addAction(remove_all)
    menu.addSeparator()
    menu.addAction(clear_trash)
    menu.addSeparator()
    menu.addAction(import_unfinished)
    menu.addAction(import_list)
    menu.addAction(export_list)
    menu.addSeparator()
    menu.addAction(quit_app)

    return FileMenuActions(
        menu=menu,
        new_task=new_task,
        open_torrent=open_torrent,
        move_to=move_to,
        start_selected=start_selected,
        pause_selected=pause_selected,
        remove_selected=remove_selected,
        redownload_selected=redownload_selected,
        batch_new=batch_new,
        start_all=start_all,
        pause_all=pause_all,
        remove_all=remove_all,
        clear_trash=clear_trash,
        import_unfinished=import_unfinished,
        import_list=import_list,
        export_list=export_list,
        quit_app=quit_app,
    )


def _create_action(
    parent: QWidget,
    text: str,
    callback: Callable[[], None],
    *,
    icon: QIcon | None = None,
    shortcut: str | QKeySequence.StandardKey | None = None,
) -> QAction:
    action = QAction(text, parent)
    if icon is not None:
        action.setIcon(icon)
    if shortcut is not None:
        action.setShortcut(shortcut)
    action.triggered.connect(callback)
    return action
