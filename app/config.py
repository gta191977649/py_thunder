from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from app.paths import (
    get_config_path,
    get_default_download_dir,
    get_default_notification_sound_path,
)


@dataclass(slots=True)
class AppConfig:
    rpc_host: str = "127.0.0.1"
    rpc_port: int = 6800
    rpc_secret: str = ""
    refresh_interval_ms: int = 1000
    max_concurrent_downloads: int = 5
    max_connection_per_server: int = 16
    default_download_dir: str = ""
    language: str = "zh_CN"
    floating_window_enabled: bool = False
    floating_window_x: int | None = None
    floating_window_y: int | None = None
    notification_sound_enabled: bool = True
    notification_sound_path: str = ""

    @classmethod
    def default(cls) -> "AppConfig":
        return cls(
            rpc_secret=secrets.token_hex(16),
            default_download_dir=str(get_default_download_dir()),
            language="zh_CN",
            notification_sound_path=str(get_default_notification_sound_path()),
        )

    @classmethod
    def load(cls) -> "AppConfig":
        config_path = get_config_path()
        if not config_path.exists():
            config = cls.default()
            config.save()
            return config

        data = json.loads(config_path.read_text(encoding="utf-8"))
        config = cls(
            rpc_host=data.get("rpc_host", "127.0.0.1"),
            rpc_port=int(data.get("rpc_port", 6800)),
            rpc_secret=data.get("rpc_secret") or secrets.token_hex(16),
            refresh_interval_ms=int(data.get("refresh_interval_ms", 1000)),
            max_concurrent_downloads=int(data.get("max_concurrent_downloads", 5)),
            max_connection_per_server=int(data.get("max_connection_per_server", 16)),
            default_download_dir=data.get("default_download_dir")
            or str(get_default_download_dir()),
            language=data.get("language", "zh_CN"),
            floating_window_enabled=bool(data.get("floating_window_enabled", False)),
            floating_window_x=(
                int(data["floating_window_x"])
                if data.get("floating_window_x") is not None
                else None
            ),
            floating_window_y=(
                int(data["floating_window_y"])
                if data.get("floating_window_y") is not None
                else None
            ),
            notification_sound_enabled=bool(data.get("notification_sound_enabled", True)),
            notification_sound_path=(
                str(data.get("notification_sound_path") or get_default_notification_sound_path())
            ),
        )
        Path(config.default_download_dir).mkdir(parents=True, exist_ok=True)
        config.save()
        return config

    def save(self) -> None:
        config_path = get_config_path()
        config_path.write_text(
            json.dumps(asdict(self), indent=2),
            encoding="utf-8",
        )
