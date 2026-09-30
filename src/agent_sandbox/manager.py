"""Sandbox lifecycle, quotas, TTL reaping, and snapshot storage."""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import posixpath
import secrets
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_sandbox.backends.base import (
    WORKSPACE,
    Backend,
    ExecEvent,
    ExecExit,
    ExecOutput,
    FileEntry,
    SandboxSpec,
)
from agent_sandbox.config import Settings
from agent_sandbox.errors import (
    ForbiddenError,
    InvalidRequestError,
    LimitExceededError,
    NotFoundError,
    PayloadTooLargeError,
    SandboxError,
)

log = logging.getLogger(__name__)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


@dataclass
class SandboxRecord:
    id: str
    spec: SandboxSpec
    created_at: float
    expires_at: float
    source_snapshot_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["spec"]["env"] = dict(self.spec.env)
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SandboxRecord:
        return cls(
            id=data["id"],
            spec=SandboxSpec(**data["spec"]),
            created_at=float(data["created_at"]),
            expires_at=float(data["expires_at"]),
            source_snapshot_id=data.get("source_snapshot_id"),
        )


@dataclass
class SnapshotRecord:
    id: str
    sandbox_id: str
    created_at: float
    size_bytes: int
    spec: SandboxSpec
    name: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["spec"]["env"] = dict(self.spec.env)
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SnapshotRecord:
        return cls(
            id=data["id"],
            sandbox_id=data["sandbox_id"],
            created_at=float(data["created_at"]),
            size_bytes=int(data["size_bytes"]),
            spec=SandboxSpec(**data["spec"]),
            name=data.get("name"),
        )


@dataclass(frozen=True)
class CreateOptions:
    """Caller-supplied sandbox options. ``None`` means "use the server default"."""

    image: str | None = None
    cpus: float | None = None
    memory_mb: int | None = None
    pids_limit: int | None = None
    network: bool = False
    read_only_rootfs: bool = True
    timeout_seconds: int | None = None
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    truncated: bool
    duration_ms: int


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, path)


def normalize_path(path: str) -> str:
    """Return a normalized absolute POSIX path or raise ``InvalidRequestError``."""
    if not path or "\x00" in path:
        raise InvalidRequestError("path must be a non-empty string")
    if not path.startswith("/"):
        path = posixpath.join(WORKSPACE, path)
    return posixpath.normpath(path)


def require_in_workspace(path: str) -> str:
    """Normalize ``path`` and require it to be strictly inside the workspace."""
    normalized = normalize_path(path)
    if not normalized.startswith(WORKSPACE + "/"):
        raise InvalidRequestError(f"writes are limited to files under {WORKSPACE}")
    return normalized


def _validate_env(env: Mapping[str, str]) -> dict[str, str]:
    clean = {}
    for key, value in env.items():
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise InvalidRequestError(f"invalid environment variable name {key!r}")
        clean[key] = value
    return clean


class SandboxManager:
    """Coordinates a backend with persistent metadata and quotas."""

    def __init__(
        self,
        settings: Settings,
        backend: Backend,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self._clock = clock
        self._lock = threading.RLock()
        self._sandbox_locks: dict[str, threading.RLock] = {}
        self._sandboxes: dict[str, SandboxRecord] = {}
        self._pending = 0
        self._sandbox_dir = settings.data_dir / "sandboxes"
        self._snapshot_dir = settings.data_dir / "snapshots"

    # -- startup ---------------------------------------------------------

    def start(self) -> None:
        """Create storage directories and reconcile state with the backend."""
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.reconcile()

    def reconcile(self) -> None:
        """Load persisted sandboxes and remove anything that no longer lines up.

        Sandboxes whose container is gone or stopped are forgotten, and backend
        resources without a matching record (orphans) are destroyed.
        """
        live = set(self.backend.list_ids())
        with self._lock:
            self._sandboxes.clear()
            for path in sorted(self._sandbox_dir.glob("*.json")):
                try:
                    record = SandboxRecord.from_json(json.loads(path.read_text()))
                except (ValueError, KeyError, TypeError):
                    log.warning("ignoring unreadable sandbox record %s", path)
                    path.unlink(missing_ok=True)
                    continue
                if record.id in live and self.backend.is_running(record.id):
                    self._sandboxes[record.id] = record
                else:
                    log.info("dropping sandbox %s: no longer running", record.id)
                    self._forget(record.id)
            for orphan in live - set(self._sandboxes):
                log.info("removing orphaned sandbox resources for %s", orphan)
                self.backend.destroy(orphan)
            for tmp in self._snapshot_dir.glob("*.tmp"):
                tmp.unlink(missing_ok=True)

    # -- helpers ---------------------------------------------------------

    def _sandbox_lock(self, sandbox_id: str) -> threading.RLock:
        with self._lock:
            return self._sandbox_locks.setdefault(sandbox_id, threading.RLock())

    def _persist(self, record: SandboxRecord) -> None:
        _atomic_write_json(self._sandbox_dir / f"{record.id}.json", record.to_json())

    def _forget(self, sandbox_id: str) -> None:
        with self._lock:
            self._sandboxes.pop(sandbox_id, None)
            self._sandbox_locks.pop(sandbox_id, None)
        (self._sandbox_dir / f"{sandbox_id}.json").unlink(missing_ok=True)

    def _build_spec(self, opts: CreateOptions) -> SandboxSpec:
        s = self.settings
        image = opts.image or s.default_image
        if not any(fnmatch.fnmatchcase(image, pattern) for pattern in s.allowed_images):
            raise ForbiddenError(f"image {image!r} is not in the server's allowed_images list")
        cpus = s.default_cpus if opts.cpus is None else opts.cpus
        memory_mb = s.default_memory_mb if opts.memory_mb is None else opts.memory_mb
        pids = s.default_pids_limit if opts.pids_limit is None else opts.pids_limit
        if not 0 < cpus <= s.max_cpus:
            raise InvalidRequestError(f"cpus must be in (0, {s.max_cpus}]")
        if not 16 <= memory_mb <= s.max_memory_mb:
            raise InvalidRequestError(f"memory_mb must be in [16, {s.max_memory_mb}]")
        if not 8 <= pids <= s.max_pids_limit:
            raise InvalidRequestError(f"pids_limit must be in [8, {s.max_pids_limit}]")
        if opts.network and not s.allow_network:
            raise ForbiddenError("this server does not allow sandboxes with network access")
        return SandboxSpec(
            image=image,
            cpus=cpus,
            memory_mb=memory_mb,
            pids_limit=pids,
            network=opts.network,
            read_only_rootfs=opts.read_only_rootfs,
            env=_validate_env(opts.env),
        )

    def _ttl(self, timeout_seconds: int | None) -> int:
        ttl = self.settings.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        if not 1 <= ttl <= self.settings.max_timeout_seconds:
            raise InvalidRequestError(f"timeout_seconds must be in [1, {self.settings.max_timeout_seconds}]")
        return ttl

    def _reserve_slot(self) -> None:
        with self._lock:
            if len(self._sandboxes) + self._pending >= self.settings.max_sandboxes:
                raise LimitExceededError(
                    f"the server already runs the maximum of {self.settings.max_sandboxes} sandboxes"
                )
            self._pending += 1

    def _release_slot(self) -> None:
        with self._lock:
            self._pending -= 1

    def _launch(self, spec: SandboxSpec, ttl: int, snapshot: SnapshotRecord | None) -> SandboxRecord:
        self._reserve_slot()
        sandbox_id = new_id("sb")
        try:
            self.backend.create(sandbox_id, spec)
            try:
                if snapshot is not None:
                    self._restore(sandbox_id, snapshot)
            except BaseException:
                self.backend.destroy(sandbox_id)
                raise
            now = self._clock()
            record = SandboxRecord(
                id=sandbox_id,
                spec=spec,
                created_at=now,
                expires_at=now + ttl,
                source_snapshot_id=snapshot.id if snapshot else None,
            )
            with self._lock:
                self._sandboxes[sandbox_id] = record
            self._persist(record)
            return record
        finally:
            self._release_slot()

    def _restore(self, sandbox_id: str, snapshot: SnapshotRecord) -> None:
        with self.snapshot_path(snapshot.id).open("rb") as src:
            self.backend.import_workspace(sandbox_id, src)

    # -- sandboxes -------------------------------------------------------

    def create(self, opts: CreateOptions) -> SandboxRecord:
        spec = self._build_spec(opts)
        return self._launch(spec, self._ttl(opts.timeout_seconds), None)

    def get(self, sandbox_id: str) -> SandboxRecord:
        with self._lock:
            record = self._sandboxes.get(sandbox_id)
        if record is None:
            raise NotFoundError(f"sandbox {sandbox_id} not found")
        return record

    def list_sandboxes(self) -> list[SandboxRecord]:
        with self._lock:
            return sorted(self._sandboxes.values(), key=lambda r: r.created_at)

    def status(self, sandbox_id: str) -> str:
        return "running" if self.backend.is_running(sandbox_id) else "stopped"

    def destroy(self, sandbox_id: str) -> None:
        self.get(sandbox_id)
        with self._sandbox_lock(sandbox_id):
            self.backend.destroy(sandbox_id)
            self._forget(sandbox_id)

    def set_timeout(self, sandbox_id: str, timeout_seconds: int) -> SandboxRecord:
        ttl = self._ttl(timeout_seconds)
        with self._sandbox_lock(sandbox_id):
            record = self.get(sandbox_id)
            record.expires_at = self._clock() + ttl
            self._persist(record)
            return record

    def reap_expired(self) -> list[str]:
        """Destroy every sandbox whose TTL has passed and return their IDs."""
        now = self._clock()
        expired = [r.id for r in self.list_sandboxes() if r.expires_at <= now]
        reaped = []
        for sandbox_id in expired:
            try:
                self.destroy(sandbox_id)
                reaped.append(sandbox_id)
                log.info("reaped expired sandbox %s", sandbox_id)
            except NotFoundError:
                continue
            except SandboxError:
                log.warning("failed to reap sandbox %s", sandbox_id, exc_info=True)
        return reaped

    # -- exec ------------------------------------------------------------

    def exec_stream(
        self,
        sandbox_id: str,
        command: str | Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[ExecEvent]:
        self.get(sandbox_id)
        if isinstance(command, str):
            if not command.strip():
                raise InvalidRequestError("command must not be empty")
            argv = ["/bin/sh", "-c", command]
        else:
            argv = list(command)
            if not argv or not all(isinstance(a, str) for a in argv):
                raise InvalidRequestError("command must be a non-empty string or list of strings")
        s = self.settings
        timeout = s.default_exec_timeout_seconds if timeout_seconds is None else timeout_seconds
        if not 0 < timeout <= s.max_exec_timeout_seconds:
            raise InvalidRequestError(f"timeout_seconds must be in (0, {s.max_exec_timeout_seconds}]")
        return self.backend.exec(
            sandbox_id,
            argv,
            env=_validate_env(env or {}),
            workdir=normalize_path(workdir or WORKSPACE),
            timeout_seconds=timeout,
        )

    def exec(
        self,
        sandbox_id: str,
        command: str | Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        workdir: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecResult:
        """Run a command to completion and collect its output."""
        started = time.monotonic()
        limit = self.settings.max_exec_output_bytes
        buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        truncated = False
        final = ExecExit(exit_code=-1, timed_out=False)
        for event in self.exec_stream(sandbox_id, command, env=env, workdir=workdir, timeout_seconds=timeout_seconds):
            if isinstance(event, ExecOutput):
                buf = buffers[event.stream]
                room = limit - len(buffers["stdout"]) - len(buffers["stderr"])
                if len(event.data) > room:
                    truncated = True
                buf.extend(event.data[: max(room, 0)])
            else:
                final = event
        return ExecResult(
            stdout=buffers["stdout"].decode(errors="replace"),
            stderr=buffers["stderr"].decode(errors="replace"),
            exit_code=final.exit_code,
            timed_out=final.timed_out,
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # -- files -----------------------------------------------------------

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        self.get(sandbox_id)
        return self.backend.read_file(sandbox_id, normalize_path(path), self.settings.max_file_bytes)

    def write_file(self, sandbox_id: str, path: str, data: bytes, mode: int = 0o644) -> str:
        self.get(sandbox_id)
        target = require_in_workspace(path)
        if len(data) > self.settings.max_file_bytes:
            raise PayloadTooLargeError(f"file exceeds {self.settings.max_file_bytes} bytes")
        if not 0 <= mode <= 0o777:
            raise InvalidRequestError("mode must be between 0 and 0o777")
        self.backend.write_file(sandbox_id, target, data, mode)
        return target

    def list_files(self, sandbox_id: str, path: str = WORKSPACE) -> list[FileEntry]:
        self.get(sandbox_id)
        return self.backend.list_files(sandbox_id, normalize_path(path))

    # -- snapshots -------------------------------------------------------

    def snapshot_path(self, snapshot_id: str) -> Path:
        return self._snapshot_dir / f"{snapshot_id}.tar"

    def snapshot(self, sandbox_id: str, name: str | None = None) -> SnapshotRecord:
        with self._sandbox_lock(sandbox_id):
            record = self.get(sandbox_id)
            snapshot_id = new_id("snap")
            final = self.snapshot_path(snapshot_id)
            tmp = final.with_suffix(".tmp")
            try:
                with tmp.open("wb") as dest:
                    size = self.backend.export_workspace(sandbox_id, dest, self.settings.max_snapshot_bytes)
                os.replace(tmp, final)
            finally:
                tmp.unlink(missing_ok=True)
            snap = SnapshotRecord(
                id=snapshot_id,
                sandbox_id=sandbox_id,
                created_at=self._clock(),
                size_bytes=size,
                spec=record.spec,
                name=name,
            )
            _atomic_write_json(self._snapshot_dir / f"{snapshot_id}.json", snap.to_json())
            return snap

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord:
        meta = self._snapshot_dir / f"{snapshot_id}.json"
        if "/" in snapshot_id or not meta.is_file() or not self.snapshot_path(snapshot_id).is_file():
            raise NotFoundError(f"snapshot {snapshot_id} not found")
        return SnapshotRecord.from_json(json.loads(meta.read_text()))

    def list_snapshots(self, sandbox_id: str | None = None) -> list[SnapshotRecord]:
        snaps = []
        for meta in self._snapshot_dir.glob("*.json"):
            try:
                snap = self.get_snapshot(meta.stem)
            except (NotFoundError, ValueError, KeyError):
                continue
            if sandbox_id is None or snap.sandbox_id == sandbox_id:
                snaps.append(snap)
        return sorted(snaps, key=lambda s: s.created_at)

    def delete_snapshot(self, snapshot_id: str) -> None:
        self.get_snapshot(snapshot_id)
        self.snapshot_path(snapshot_id).unlink(missing_ok=True)
        (self._snapshot_dir / f"{snapshot_id}.json").unlink(missing_ok=True)

    def rollback(self, sandbox_id: str, snapshot_id: str) -> SandboxRecord:
        """Replace the sandbox with a fresh one holding the snapshot's workspace.

        The sandbox keeps its ID, spec, and expiry. Running processes stop and
        ``/tmp`` is cleared, so the sandbox state matches the snapshot exactly.
        """
        snapshot = self.get_snapshot(snapshot_id)
        with self._sandbox_lock(sandbox_id):
            record = self.get(sandbox_id)
            self.backend.destroy(sandbox_id)
            try:
                self.backend.create(sandbox_id, record.spec)
                self._restore(sandbox_id, snapshot)
            except BaseException:
                self.backend.destroy(sandbox_id)
                self._forget(sandbox_id)
                raise
            record.source_snapshot_id = snapshot.id
            self._persist(record)
            return record

    def fork(
        self,
        snapshot_id: str,
        *,
        timeout_seconds: int | None = None,
        network: bool | None = None,
        cpus: float | None = None,
        memory_mb: int | None = None,
    ) -> SandboxRecord:
        """Create a new sandbox from a snapshot, optionally overriding its limits."""
        snapshot = self.get_snapshot(snapshot_id)
        base = snapshot.spec
        opts = CreateOptions(
            image=base.image,
            cpus=base.cpus if cpus is None else cpus,
            memory_mb=base.memory_mb if memory_mb is None else memory_mb,
            pids_limit=base.pids_limit,
            network=base.network if network is None else network,
            read_only_rootfs=base.read_only_rootfs,
            env=base.env,
        )
        spec = self._build_spec(opts)
        return self._launch(spec, self._ttl(timeout_seconds), snapshot)
