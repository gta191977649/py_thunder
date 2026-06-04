from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PyThunder"


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_resources_dir() -> Path:
    return get_project_root() / "resources"


def get_icons_dir() -> Path:
    return get_resources_dir() / "icons"


def get_thunder5_icons_dir() -> Path:
    return get_icons_dir() / "thunder5"


def get_sfx_dir() -> Path:
    return get_resources_dir() / "sfx"


def get_default_notification_sound_path() -> Path:
    return get_sfx_dir() / "notification.wav"


def get_platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def get_aria2_binary_path() -> Path:
    platform_key = get_platform_key()
    binary_name = "aria2c.exe" if platform_key == "win" else "aria2c"
    return get_resources_dir() / "aria2" / platform_key / binary_name


def get_app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"

    app_data_dir = base / APP_NAME
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return app_data_dir


def get_config_path() -> Path:
    return get_app_data_dir() / "config.json"


def get_theme_path() -> Path:
    return get_app_data_dir() / "theme.json"


def get_theme_presets_dir() -> Path:
    return get_project_root() / "resources" / "themes"


def get_database_path() -> Path:
    return get_app_data_dir() / "app.db"


def get_aria2_session_path() -> Path:
    return get_app_data_dir() / "aria2.session"


def get_default_download_dir() -> Path:
    download_dir = Path.home() / "Downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir
