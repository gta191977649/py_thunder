from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from app.config import AppConfig
from app.i18n import Translator
from app.paths import get_project_root
from app.theme import build_stylesheet, load_theme
from core.aria2_client import Aria2Client
from core.aria2_process import Aria2ProcessManager
from core.download_manager import DownloadManager
from storage.task_repository import TaskRepository
from ui.main_window import MainWindow


def configure_app_font(app: QApplication, base_font_size: int = 9) -> None:
    font_path = get_project_root() / "resources" / "font" / "default.ttf"
    if not font_path.exists():
        raise FileNotFoundError(f"Required font file was not found: {font_path}")

    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        raise RuntimeError(f"Failed to load required font file: {font_path}")

    font_families = QFontDatabase.applicationFontFamilies(font_id)
    if not font_families:
        raise RuntimeError(f"No font family was registered from: {font_path}")

    font = QFont(font_families[0], base_font_size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)


def main() -> int:
    app = QApplication(sys.argv)
    config = AppConfig.load()
    theme = load_theme()
    translator = Translator(config.language)

    app.setApplicationName(translator.t("app.title"))
    configure_app_font(app, int(theme["metrics"].get("base_font_size", 9)))
    app.setStyleSheet(build_stylesheet(theme, app.font().family()))

    repository = TaskRepository()

    aria2_process = Aria2ProcessManager(config)
    aria2_warning: str | None = None

    if aria2_process.is_available():
        if not aria2_process.start():
            aria2_warning = (
                aria2_process.last_error
                or translator.t("warn.aria2_start_failed")
            )
    else:
        aria2_warning = translator.t(
            "warn.aria2_missing",
            path=aria2_process.binary_path,
        )

    aria2_client = Aria2Client(
        host=config.rpc_host,
        port=config.rpc_port,
        rpc_secret=config.rpc_secret,
    )
    download_manager = DownloadManager(
        client=aria2_client,
        repository=repository,
        refresh_interval_ms=config.refresh_interval_ms,
    )

    window = MainWindow(
        config=config,
        theme=theme,
        translator=translator,
        download_manager=download_manager,
        initial_tasks=repository.list_all(),
    )
    window.show()

    if aria2_warning:
        window.show_aria2_warning(aria2_warning)

    QTimer.singleShot(0, download_manager.start)
    app.aboutToQuit.connect(download_manager.stop)
    app.aboutToQuit.connect(aria2_process.stop)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
