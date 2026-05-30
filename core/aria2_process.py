from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

from app.config import AppConfig
from app.paths import get_aria2_binary_path


class Aria2ProcessManager:
    STARTUP_TIMEOUT_SECONDS = 3.0
    STARTUP_POLL_INTERVAL_SECONDS = 0.05

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.binary_path = get_aria2_binary_path()
        self.process: subprocess.Popen[str] | None = None
        self.last_error: str | None = None
        self.was_started_by_app = False

    def is_available(self) -> bool:
        return self.binary_path.exists()

    def start(self) -> bool:
        if self.process and self.process.poll() is None:
            return True

        if not self.is_available():
            self.last_error = f"aria2c was not found at {self.binary_path}"
            return False

        download_dir = Path(self.config.default_download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        command = [
            str(self.binary_path),
            "--enable-rpc=true",
            "--rpc-listen-all=false",
            f"--rpc-listen-port={self.config.rpc_port}",
            f"--rpc-secret={self.config.rpc_secret}",
            "--continue=true",
            f"--max-concurrent-downloads={self.config.max_concurrent_downloads}",
            "--split=16",
            f"--max-connection-per-server={self.config.max_connection_per_server}",
            f"--dir={download_dir}",
        ]

        popen_kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "text": True,
        }
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            popen_kwargs["creationflags"] = create_no_window

        try:
            self.process = subprocess.Popen(command, **popen_kwargs)
        except OSError as exc:
            self.last_error = f"Failed to start aria2c: {exc}"
            self.process = None
            self.was_started_by_app = False
            return False

        deadline = time.monotonic() + self.STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self.process:
                break
            return_code = self.process.poll()
            if return_code is not None:
                self.last_error = f"aria2c exited early with code {return_code}."
                self.process = None
                self.was_started_by_app = False
                return False
            if self._is_rpc_ready():
                self.was_started_by_app = True
                self.last_error = None
                return True
            time.sleep(self.STARTUP_POLL_INTERVAL_SECONDS)

        self.was_started_by_app = True
        self.last_error = None
        return True

    def _is_rpc_ready(self) -> bool:
        try:
            with socket.create_connection(
                (self.config.rpc_host, int(self.config.rpc_port)),
                timeout=self.STARTUP_POLL_INTERVAL_SECONDS,
            ):
                return True
        except OSError:
            return False

    def stop(self) -> None:
        if not self.was_started_by_app or not self.process:
            return
        if self.process.poll() is not None:
            return

        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
