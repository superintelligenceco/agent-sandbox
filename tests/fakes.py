"""An in-memory backend for unit tests."""

from __future__ import annotations

import io
import posixpath
import tarfile
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import BinaryIO, Literal

from agent_sandbox.backends.base import WORKSPACE, Backend, ExecEvent, ExecExit, ExecOutput, FileEntry, SandboxSpec
from agent_sandbox.errors import BackendError, InvalidRequestError, NotFoundError, PayloadTooLargeError


@dataclass
class FakeSandbox:
    spec: SandboxSpec
    files: dict[str, bytes] = field(default_factory=dict)
    running: bool = True


@dataclass
class ExecCall:
    sandbox_id: str
    command: list[str]
    env: dict[str, str]
    workdir: str
    timeout_seconds: float


class FakeBackend(Backend):
    """Stores each workspace as a dict of absolute path to bytes.

    ``exec`` understands a tiny command language, enough to test the layers above:
    ``echo <text>`` writes to stdout, ``fail <code>`` exits with a code after
    writing to stderr, and ``hang`` reports a timeout.
    """

    name = "fake"

    def __init__(self) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.exec_calls: list[ExecCall] = []
        self.fail_create = False
        self.fail_import = False
        self.reachable = True

    def ping(self) -> None:
        if not self.reachable:
            raise BackendError("fake backend is down")

    def create(self, sandbox_id: str, spec: SandboxSpec) -> None:
        if self.fail_create:
            raise BackendError("create failed")
        self.sandboxes[sandbox_id] = FakeSandbox(spec=spec)

    def destroy(self, sandbox_id: str) -> None:
        self.sandboxes.pop(sandbox_id, None)

    def list_ids(self) -> list[str]:
        return sorted(self.sandboxes)

    def is_running(self, sandbox_id: str) -> bool:
        box = self.sandboxes.get(sandbox_id)
        return bool(box and box.running)

    def _box(self, sandbox_id: str) -> FakeSandbox:
        try:
            return self.sandboxes[sandbox_id]
        except KeyError:
            raise NotFoundError(f"sandbox {sandbox_id}: not found") from None

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str,
        timeout_seconds: float,
    ) -> Iterator[ExecEvent]:
        self._box(sandbox_id)
        argv = list(command)
        self.exec_calls.append(ExecCall(sandbox_id, argv, dict(env), workdir, timeout_seconds))
        script = argv[2] if argv[:2] == ["/bin/sh", "-c"] else " ".join(argv)
        return self._run(script)

    @staticmethod
    def _run(script: str) -> Iterator[ExecEvent]:
        verb, _, rest = script.partition(" ")
        if verb == "echo":
            yield ExecOutput("stdout", rest.encode() + b"\n")
            yield ExecExit(0, False)
        elif verb == "fail":
            yield ExecOutput("stderr", b"boom\n")
            yield ExecExit(int(rest or 1), False)
        elif verb == "hang":
            yield ExecExit(137, True)
        elif verb == "bytes":
            yield ExecOutput("stdout", b"x" * int(rest))
            yield ExecOutput("stderr", b"y" * int(rest))
            yield ExecExit(0, False)
        elif verb == "utf8split":
            data = "é".encode()
            yield ExecOutput("stdout", data[:1])
            yield ExecOutput("stdout", data[1:])
            yield ExecExit(0, False)
        else:
            yield ExecOutput("stderr", f"sh: {verb}: not found\n".encode())
            yield ExecExit(127, False)

    def read_file(self, sandbox_id: str, path: str, max_bytes: int) -> bytes:
        box = self._box(sandbox_id)
        if path not in box.files:
            raise NotFoundError(f"{path}: not found")
        data = box.files[path]
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"{path} is larger than {max_bytes} bytes")
        return data

    def write_file(self, sandbox_id: str, path: str, data: bytes, mode: int) -> None:
        self._box(sandbox_id).files[path] = data

    def list_files(self, sandbox_id: str, path: str) -> list[FileEntry]:
        box = self._box(sandbox_id)
        prefix = path.rstrip("/") + "/"
        children: dict[str, FileEntry] = {}
        for name, data in box.files.items():
            if not name.startswith(prefix):
                continue
            head, _, tail = name[len(prefix) :].partition("/")
            kind: Literal["file", "directory"] = "directory" if tail else "file"
            children[head] = FileEntry(head, posixpath.join(path, head), kind, len(data), int(time.time()))
        if not children and path != WORKSPACE:
            if path in box.files:
                raise InvalidRequestError(f"{path} is not a directory")
            raise NotFoundError(f"{path}: not found")
        return sorted(children.values(), key=lambda e: e.name)

    def export_workspace(self, sandbox_id: str, dest: BinaryIO, max_bytes: int) -> int:
        box = self._box(sandbox_id)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as archive:
            for name, data in sorted(box.files.items()):
                info = tarfile.TarInfo(posixpath.relpath(name, WORKSPACE))
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        payload = buf.getvalue()
        if len(payload) > max_bytes:
            raise PayloadTooLargeError("workspace exceeds the snapshot limit")
        dest.write(payload)
        return len(payload)

    def import_workspace(self, sandbox_id: str, src: BinaryIO) -> None:
        if self.fail_import:
            raise BackendError("import failed")
        box = self._box(sandbox_id)
        with tarfile.open(fileobj=src, mode="r") as archive:
            for member in archive:
                extracted = archive.extractfile(member)
                if extracted is not None:
                    box.files[posixpath.join(WORKSPACE, member.name)] = extracted.read()
