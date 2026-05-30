from __future__ import annotations

import base64
import uuid
from pathlib import Path

import requests


class Aria2RPCError(RuntimeError):
    pass


class Aria2ConnectionError(Aria2RPCError):
    pass


class Aria2Client:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6800,
        rpc_secret: str = "",
        timeout: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.rpc_secret = rpc_secret
        self.timeout = timeout
        self.endpoint = f"http://{host}:{port}/jsonrpc"
        self.session = requests.Session()

    def call(self, method: str, params: list | None = None):
        rpc_method = method if method.startswith("aria2.") else f"aria2.{method}"
        rpc_params = [f"token:{self.rpc_secret}"]
        if params:
            rpc_params.extend(params)

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": rpc_method,
            "params": rpc_params,
        }

        try:
            response = self.session.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise Aria2ConnectionError(
                f"Failed to reach aria2 RPC at {self.endpoint}: {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise Aria2ConnectionError(
                "aria2 RPC returned an invalid JSON response."
            ) from exc

        if "error" in data:
            error = data["error"]
            message = error.get("message", "Unknown aria2 RPC error")
            raise Aria2RPCError(message)

        if not response.ok:
            raise Aria2ConnectionError(
                f"aria2 RPC returned HTTP {response.status_code} without an error payload."
            )

        return data.get("result")

    def add_uri(self, urls: list[str], options: dict | None = None):
        params: list = [urls]
        if options:
            params.append(options)
        return self.call("addUri", params)

    def add_torrent(
        self,
        torrent_path: str,
        options: dict | None = None,
        uris: list[str] | None = None,
    ):
        torrent_data = base64.b64encode(
            Path(torrent_path).read_bytes()
        ).decode("ascii")
        params: list = [torrent_data]
        if uris is not None or options is not None:
            params.append(uris or [])
        if options:
            params.append(options)
        return self.call("addTorrent", params)

    def pause(self, gid: str):
        return self.call("pause", [gid])

    def force_pause(self, gid: str):
        return self.call("forcePause", [gid])

    def unpause(self, gid: str):
        return self.call("unpause", [gid])

    def remove(self, gid: str):
        try:
            return self.call("remove", [gid])
        except Aria2RPCError as exc:
            try:
                return self.call("removeDownloadResult", [gid])
            except Aria2RPCError:
                raise exc

    def tell_status(self, gid: str, keys: list[str] | None = None):
        params: list = [gid]
        if keys:
            params.append(keys)
        return self.call("tellStatus", params)

    def tell_active(self):
        return self.call("tellActive")

    def tell_waiting(self, offset: int = 0, num: int = 100):
        return self.call("tellWaiting", [offset, num])

    def tell_stopped(self, offset: int = 0, num: int = 100):
        return self.call("tellStopped", [offset, num])

    def get_option(self, gid: str):
        return self.call("getOption", [gid])

    def get_servers(self, gid: str):
        return self.call("getServers", [gid])

    def get_peers(self, gid: str):
        return self.call("getPeers", [gid])
