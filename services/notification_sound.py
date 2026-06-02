from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QUrl

from app.config import AppConfig
from app.paths import get_default_notification_sound_path

try:
    from PyQt6.QtMultimedia import QSoundEffect
except ImportError:  # pragma: no cover - optional runtime dependency fallback
    QSoundEffect = None  # type: ignore[assignment]

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows fallback
    winsound = None  # type: ignore[assignment]


class NotificationSoundPlayer(QObject):
    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._sound_effect = None

        if QSoundEffect is not None:
            self._sound_effect = QSoundEffect(self)
            self._sound_effect.setLoopCount(1)
            self._sound_effect.setVolume(0.9)
            self._refresh_source()

    def play_download_complete(self) -> None:
        if not self.config.notification_sound_enabled:
            return

        sound_path = self._resolve_sound_path()
        if sound_path is None or not sound_path.exists():
            return

        if self._sound_effect is not None:
            sound_url = QUrl.fromLocalFile(str(sound_path.resolve()))
            if self._sound_effect.source() != sound_url:
                self._sound_effect.setSource(sound_url)
            self._sound_effect.play()
            return

        if winsound is not None:
            winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def _refresh_source(self) -> None:
        if self._sound_effect is None:
            return
        sound_path = self._resolve_sound_path()
        if sound_path is None or not sound_path.exists():
            self._sound_effect.setSource(QUrl())
            return
        self._sound_effect.setSource(QUrl.fromLocalFile(str(sound_path.resolve())))

    def _resolve_sound_path(self) -> Path | None:
        configured_path = (self.config.notification_sound_path or "").strip()
        if configured_path:
            return Path(configured_path).expanduser()
        return get_default_notification_sound_path()
