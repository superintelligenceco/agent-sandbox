"""Pydantic models that define the public REST API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_sandbox.backends.base import FileEntry
from agent_sandbox.manager import ExecResult, SandboxRecord, SnapshotRecord


def _ts(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: Literal["ok"]
    backend: str
    version: str


class SandboxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str | None = Field(default=None, description="OCI image. Defaults to the server's default image.")
    cpus: float | None = Field(default=None, gt=0, description="CPU limit in cores.")
    memory_mb: int | None = Field(default=None, ge=16, description="Memory limit in MiB. Swap is disabled.")
    pids_limit: int | None = Field(default=None, ge=8, description="Maximum number of processes.")
    network: bool = Field(default=False, description="Attach the sandbox to an isolated bridge network.")
    read_only_rootfs: bool = Field(default=True, description="Mount the image filesystem read-only.")
    timeout_seconds: int | None = Field(default=None, ge=1, description="Time to live before automatic deletion.")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for every command.")


class Sandbox(BaseModel):
    id: str = Field(examples=["sb_4f1c2a9e0b7d6c31"])
    status: Literal["running", "stopped"]
    image: str
    cpus: float
    memory_mb: int
    pids_limit: int
    network: bool
    read_only_rootfs: bool
    created_at: datetime
    expires_at: datetime
    source_snapshot_id: str | None = None

    @classmethod
    def from_record(cls, record: SandboxRecord, status: str) -> Sandbox:
        spec = record.spec
        return cls(
            id=record.id,
            status="running" if status == "running" else "stopped",
            image=spec.image,
            cpus=spec.cpus,
            memory_mb=spec.memory_mb,
            pids_limit=spec.pids_limit,
            network=spec.network,
            read_only_rootfs=spec.read_only_rootfs,
            created_at=_ts(record.created_at),
            expires_at=_ts(record.expires_at),
            source_snapshot_id=record.source_snapshot_id,
        )


class SandboxList(BaseModel):
    sandboxes: list[Sandbox]


class TimeoutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(ge=1, description="New time to live, counted from now.")


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str | list[str] = Field(
        description="A shell command string (run with /bin/sh -c) or an argv list.",
        examples=["python3 -c 'print(2 + 2)'"],
    )
    env: dict[str, str] = Field(default_factory=dict)
    workdir: str | None = Field(default=None, description="Working directory. Defaults to /workspace.")
    timeout_seconds: float | None = Field(default=None, gt=0, description="Kill the command after this many seconds.")


class ExecResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    truncated: bool = Field(description="True when output exceeded the server's capture limit.")
    duration_ms: int

    @classmethod
    def from_result(cls, result: ExecResult) -> ExecResponse:
        return cls(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
        )


class FileInfo(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size: int
    modified_at: datetime

    @classmethod
    def from_entry(cls, entry: FileEntry) -> FileInfo:
        return cls(
            name=entry.name,
            path=entry.path,
            type=entry.type,
            size=entry.size,
            modified_at=_ts(entry.modified_at),
        )


class FileList(BaseModel):
    path: str
    entries: list[FileInfo]


class SnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=128, description="Optional human-readable label.")


class Snapshot(BaseModel):
    id: str = Field(examples=["snap_9a8b7c6d5e4f3a2b"])
    sandbox_id: str
    name: str | None
    image: str
    size_bytes: int
    created_at: datetime

    @classmethod
    def from_record(cls, record: SnapshotRecord) -> Snapshot:
        return cls(
            id=record.id,
            sandbox_id=record.sandbox_id,
            name=record.name,
            image=record.spec.image,
            size_bytes=record.size_bytes,
            created_at=_ts(record.created_at),
        )


class SnapshotList(BaseModel):
    snapshots: list[Snapshot]


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int | None = Field(default=None, ge=1)
    network: bool | None = None
    cpus: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, ge=16)
