"""Python client for the agent-sandbox REST API.

The client depends only on ``httpx``::

    from agent_sandbox.client import SandboxClient

    with SandboxClient("http://localhost:8080", api_key="...") as client:
        with client.create(image="python:3.12-slim") as sandbox:
            print(sandbox.exec("python3 -c 'print(6 * 7)'").stdout)
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8080"


class SandboxAPIError(Exception):
    """An error response from the server."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    truncated: bool
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class ExecEvent:
    """One line of a streamed command: ``stdout``, ``stderr``, or ``exit``."""

    type: str
    data: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int | None = None


@dataclass(frozen=True)
class SnapshotInfo:
    id: str
    sandbox_id: str
    name: str | None
    image: str
    size_bytes: int
    created_at: str

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SnapshotInfo:
        return cls(
            id=data["id"],
            sandbox_id=data["sandbox_id"],
            name=data.get("name"),
            image=data["image"],
            size_bytes=int(data["size_bytes"]),
            created_at=data["created_at"],
        )


@dataclass(frozen=True)
class FileInfo:
    name: str
    path: str
    type: str
    size: int
    modified_at: str


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    if not response.is_stream_consumed:
        response.read()
    code, message = "http_error", response.text
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            code = body["error"].get("code", code)
            message = body["error"].get("message", message)
        elif isinstance(body, dict) and "detail" in body:
            code, message = "validation_error", json.dumps(body["detail"])
    except ValueError:
        pass
    raise SandboxAPIError(response.status_code, code, message)


class Sandbox:
    """A handle to one remote sandbox."""

    def __init__(self, client: SandboxClient, data: Mapping[str, Any]) -> None:
        self._client = client
        self._update(data)

    def _update(self, data: Mapping[str, Any]) -> None:
        self.data = dict(data)
        self.id: str = data["id"]
        self.status: str = data["status"]
        self.image: str = data["image"]
        self.expires_at: str = data["expires_at"]

    def __repr__(self) -> str:
        return f"Sandbox(id={self.id!r}, image={self.image!r}, status={self.status!r})"

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            self.destroy()
        except SandboxAPIError as err:
            if err.status_code != 404:
                raise

    def _path(self, suffix: str = "") -> str:
        return f"/v1/sandboxes/{self.id}{suffix}"

    def refresh(self) -> Sandbox:
        self._update(self._client._request("GET", self._path()).json())
        return self

    def exec(
        self,
        command: str | Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecResult:
        """Run a command to completion."""
        body = _exec_body(command, env, workdir, timeout_seconds)
        data = self._client._request("POST", self._path("/exec"), json=body).json()
        return ExecResult(**data)

    def exec_stream(
        self,
        command: str | Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ExecEvent]:
        """Run a command and yield output events as they arrive."""
        body = _exec_body(command, env, workdir, timeout_seconds)
        with self._client._http.stream("POST", self._path("/exec/stream"), json=body) as response:
            _raise_for_status(response)
            for line in response.iter_lines():
                if line.strip():
                    yield ExecEvent(**json.loads(line))

    def read_file(self, path: str) -> bytes:
        return self._client._request("GET", self._path("/files"), params={"path": path}).content

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read_file(path).decode(encoding)

    def write_file(self, path: str, data: bytes | str, *, mode: int = 0o644) -> FileInfo:
        content = data.encode() if isinstance(data, str) else data
        response = self._client._request(
            "PUT",
            self._path("/files"),
            params={"path": path, "mode": f"{mode:03o}"},
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        return FileInfo(**response.json())

    def list_files(self, path: str = "/workspace") -> list[FileInfo]:
        data = self._client._request("GET", self._path("/files/list"), params={"path": path}).json()
        return [FileInfo(**entry) for entry in data["entries"]]

    def snapshot(self, name: str | None = None) -> SnapshotInfo:
        data = self._client._request("POST", self._path("/snapshots"), json={"name": name}).json()
        return SnapshotInfo.from_json(data)

    def rollback(self, snapshot: SnapshotInfo | str) -> Sandbox:
        snapshot_id = snapshot.id if isinstance(snapshot, SnapshotInfo) else snapshot
        self._update(self._client._request("POST", self._path("/rollback"), json={"snapshot_id": snapshot_id}).json())
        return self

    def set_timeout(self, timeout_seconds: int) -> Sandbox:
        body = {"timeout_seconds": timeout_seconds}
        self._update(self._client._request("POST", self._path("/timeout"), json=body).json())
        return self

    def destroy(self) -> None:
        self._client._request("DELETE", self._path())


def _exec_body(
    command: str | Sequence[str],
    env: Mapping[str, str] | None,
    workdir: str | None,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"command": command if isinstance(command, str) else list(command)}
    if env:
        body["env"] = dict(env)
    if workdir is not None:
        body["workdir"] = workdir
    if timeout_seconds is not None:
        body["timeout_seconds"] = timeout_seconds
    return body


class SandboxClient:
    """Synchronous client.

    ``base_url`` and ``api_key`` default to the ``AGENT_SANDBOX_URL`` and
    ``AGENT_SANDBOX_API_KEY`` environment variables.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = 300.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        base_url = base_url or os.environ.get("AGENT_SANDBOX_URL", DEFAULT_URL)
        api_key = api_key or os.environ.get("AGENT_SANDBOX_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if http_client is None:
            self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        else:
            self._http = http_client
            self._http.headers.update(headers)

    def __enter__(self) -> SandboxClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = self._http.request(method, url, **kwargs)
        _raise_for_status(response)
        return response

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", "/healthz").json()
        return result

    def create(
        self,
        image: str | None = None,
        *,
        cpus: float | None = None,
        memory_mb: int | None = None,
        pids_limit: int | None = None,
        network: bool = False,
        read_only_rootfs: bool = True,
        timeout_seconds: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Sandbox:
        """Create a sandbox. Unset limits use the server defaults."""
        body: dict[str, Any] = {"network": network, "read_only_rootfs": read_only_rootfs, "env": dict(env or {})}
        for key, value in (
            ("image", image),
            ("cpus", cpus),
            ("memory_mb", memory_mb),
            ("pids_limit", pids_limit),
            ("timeout_seconds", timeout_seconds),
        ):
            if value is not None:
                body[key] = value
        return Sandbox(self, self._request("POST", "/v1/sandboxes", json=body).json())

    def get(self, sandbox_id: str) -> Sandbox:
        return Sandbox(self, self._request("GET", f"/v1/sandboxes/{sandbox_id}").json())

    def list_sandboxes(self) -> list[Sandbox]:
        data = self._request("GET", "/v1/sandboxes").json()
        return [Sandbox(self, item) for item in data["sandboxes"]]

    def list_snapshots(self, sandbox_id: str | None = None) -> list[SnapshotInfo]:
        params = {"sandbox_id": sandbox_id} if sandbox_id else None
        data = self._request("GET", "/v1/snapshots", params=params).json()
        return [SnapshotInfo.from_json(item) for item in data["snapshots"]]

    def get_snapshot(self, snapshot_id: str) -> SnapshotInfo:
        return SnapshotInfo.from_json(self._request("GET", f"/v1/snapshots/{snapshot_id}").json())

    def delete_snapshot(self, snapshot_id: str) -> None:
        self._request("DELETE", f"/v1/snapshots/{snapshot_id}")

    def fork(
        self,
        snapshot: SnapshotInfo | str,
        *,
        timeout_seconds: int | None = None,
        network: bool | None = None,
        cpus: float | None = None,
        memory_mb: int | None = None,
    ) -> Sandbox:
        """Start a new sandbox from a snapshot."""
        snapshot_id = snapshot.id if isinstance(snapshot, SnapshotInfo) else snapshot
        body = {
            key: value
            for key, value in (
                ("timeout_seconds", timeout_seconds),
                ("network", network),
                ("cpus", cpus),
                ("memory_mb", memory_mb),
            )
            if value is not None
        }
        return Sandbox(self, self._request("POST", f"/v1/snapshots/{snapshot_id}/fork", json=body).json())


__all__ = [
    "ExecEvent",
    "ExecResult",
    "FileInfo",
    "Sandbox",
    "SandboxAPIError",
    "SandboxClient",
    "SnapshotInfo",
]
