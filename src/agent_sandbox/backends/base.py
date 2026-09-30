"""The backend interface every isolation technology implements.

A backend owns the low-level lifecycle of one isolated environment per sandbox.
The :class:`~agent_sandbox.manager.SandboxManager` handles IDs, quotas, TTLs, and
snapshot storage, so a backend only needs to translate these calls into its
runtime (Docker today; see the roadmap for Firecracker and gVisor).
"""

from __future__ import annotations

import abc
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import BinaryIO, Literal

WORKSPACE = "/workspace"


@dataclass(frozen=True)
class SandboxSpec:
    """Everything a backend needs to create a sandbox."""

    image: str
    cpus: float
    memory_mb: int
    pids_limit: int
    network: bool
    read_only_rootfs: bool
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecOutput:
    """A chunk of output from a running command."""

    stream: Literal["stdout", "stderr"]
    data: bytes


@dataclass(frozen=True)
class ExecExit:
    """The final event of a command."""

    exit_code: int
    timed_out: bool


ExecEvent = ExecOutput | ExecExit


@dataclass(frozen=True)
class FileEntry:
    """One entry in a directory listing."""

    name: str
    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size: int
    modified_at: int


class Backend(abc.ABC):
    """Abstract isolation backend."""

    name: str = "abstract"

    @abc.abstractmethod
    def ping(self) -> None:
        """Raise :class:`~agent_sandbox.errors.BackendError` if the runtime is unreachable."""

    @abc.abstractmethod
    def create(self, sandbox_id: str, spec: SandboxSpec) -> None:
        """Create and start a sandbox with an empty, writable workspace."""

    @abc.abstractmethod
    def destroy(self, sandbox_id: str) -> None:
        """Remove the sandbox and all of its storage. Must be idempotent."""

    @abc.abstractmethod
    def list_ids(self) -> list[str]:
        """Return the IDs of every sandbox this backend currently manages."""

    @abc.abstractmethod
    def is_running(self, sandbox_id: str) -> bool:
        """Return whether the sandbox exists and is running."""

    @abc.abstractmethod
    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str,
        timeout_seconds: float,
    ) -> Iterator[ExecEvent]:
        """Run ``command`` and yield output chunks followed by exactly one :class:`ExecExit`."""

    @abc.abstractmethod
    def read_file(self, sandbox_id: str, path: str, max_bytes: int) -> bytes:
        """Return the content of a regular file."""

    @abc.abstractmethod
    def write_file(self, sandbox_id: str, path: str, data: bytes, mode: int) -> None:
        """Create or replace a file inside the workspace, creating parent directories."""

    @abc.abstractmethod
    def list_files(self, sandbox_id: str, path: str) -> list[FileEntry]:
        """List the direct children of a directory."""

    @abc.abstractmethod
    def export_workspace(self, sandbox_id: str, dest: BinaryIO, max_bytes: int) -> int:
        """Write the workspace as a tar stream (paths relative to the workspace) and return its size."""

    @abc.abstractmethod
    def import_workspace(self, sandbox_id: str, src: BinaryIO) -> None:
        """Extract a tar stream produced by :meth:`export_workspace` into an empty workspace."""
