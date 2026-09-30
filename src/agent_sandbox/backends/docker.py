"""Docker Engine backend.

Each sandbox is one long-lived container plus one named volume mounted at
``/workspace``. Containers run as a non-root user with every capability dropped,
``no-new-privileges``, a pids limit, memory and CPU limits, a read-only root
filesystem, and no network unless the caller asks for one.
"""

from __future__ import annotations

import io
import logging
import posixpath
import tarfile
import threading
import time
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, BinaryIO, cast

import docker
import docker.errors
from docker.models.containers import Container
from docker.types import Mount

from agent_sandbox.backends.base import (
    WORKSPACE,
    Backend,
    ExecEvent,
    ExecExit,
    ExecOutput,
    FileEntry,
    SandboxSpec,
)
from agent_sandbox.errors import (
    BackendError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
    SandboxError,
)

log = logging.getLogger(__name__)

LABEL_MANAGED = "io.agent-sandbox.managed"
LABEL_ID = "io.agent-sandbox.id"
PID_DIR = "/tmp/.agent-sandbox"  # noqa: S108 - path inside the sandbox, not on the host

# Keeps the container alive and exits promptly on SIGTERM so stops are fast.
KEEPALIVE = "trap 'exit 0' TERM INT; while :; do sleep 86400 & wait $!; done"

# Records the PID of the wrapper shell so a timeout can kill its process group.
# Docker starts every exec in its own session, so the wrapper is a group leader.
EXEC_WRAPPER = (
    'mkdir -p "${0%/*}" 2>/dev/null; echo $$ > "$0" 2>/dev/null; "$@"; rc=$?; rm -f "$0" 2>/dev/null; exit $rc'
)

KILL_SCRIPT = (
    'i=0; while [ ! -s "$0" ] && [ $i -lt 20 ]; do sleep 0.1; i=$((i+1)); done; '
    'p=$(cat "$0" 2>/dev/null) || exit 0; '
    'kill -KILL -"$p" 2>/dev/null; kill -KILL "$p" 2>/dev/null; rm -f "$0"; exit 0'
)

LIST_SCRIPT = (
    'cd -- "$0" 2>/dev/null || { if [ -e "$0" ]; then exit 3; else exit 2; fi; }; '
    'for f in * .[!.]* ..?*; do if [ -e "$f" ] || [ -L "$f" ]; then '
    "stat -c '%f %s %Y %n' -- \"$f\" 2>/dev/null; fi; done; exit 0"
)

# Go's os.FileMode bits, as reported by the Docker archive API.
_GO_MODE_DIR = 1 << 31
_GO_MODE_SYMLINK = 1 << 27


def _translate(exc: docker.errors.DockerException, what: str) -> SandboxError:
    if isinstance(exc, docker.errors.NotFound):
        return NotFoundError(f"{what}: not found")
    if isinstance(exc, docker.errors.APIError):
        detail = exc.explanation or str(exc)
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            return InvalidRequestError(f"{what}: {detail}")
        return BackendError(f"{what}: {detail}")
    return BackendError(f"{what}: {exc}")


class _IterReader(io.RawIOBase):
    """Adapts an iterator of byte chunks to a readable file object."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        view = memoryview(b).cast("B")
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(view), len(self._buffer))
        view[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return n


class _CountingWriter(io.RawIOBase):
    """Counts bytes written and enforces a size limit."""

    def __init__(self, dest: BinaryIO, limit: int) -> None:
        self._dest = dest
        self._limit = limit
        self.count = 0

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        data = bytes(b)
        self.count += len(data)
        if self.count > self._limit:
            raise PayloadTooLargeError(f"workspace exceeds the snapshot limit of {self._limit} bytes")
        self._dest.write(data)
        return len(data)


class DockerBackend(Backend):
    """Runs each sandbox as a hardened Docker container."""

    name = "docker"

    def __init__(
        self,
        client: docker.DockerClient | None = None,
        *,
        user: str = "1000:1000",
        runtime: str = "",
        network_name: str = "agent-sandbox-net",
        tmp_size_mb: int = 256,
    ) -> None:
        self._client = client
        self._user = user
        uid, _, gid = user.partition(":")
        self._uid = int(uid)
        self._gid = int(gid or uid)
        self._runtime = runtime or None
        self._network_name = network_name
        self._tmp_size_mb = tmp_size_mb
        self._network_lock = threading.Lock()

    # -- helpers ---------------------------------------------------------

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            try:
                self._client = docker.from_env()
            except docker.errors.DockerException as exc:
                raise BackendError(f"cannot connect to Docker: {exc}") from exc
        return self._client

    @staticmethod
    def container_name(sandbox_id: str) -> str:
        return f"agent-sandbox-{sandbox_id}"

    @staticmethod
    def volume_name(sandbox_id: str) -> str:
        return f"agent-sandbox-{sandbox_id}-workspace"

    def _labels(self, sandbox_id: str) -> dict[str, str]:
        return {LABEL_MANAGED: "true", LABEL_ID: sandbox_id}

    def _container(self, sandbox_id: str) -> Container:
        try:
            return self.client.containers.get(self.container_name(sandbox_id))
        except docker.errors.DockerException as exc:
            raise _translate(exc, f"sandbox {sandbox_id}") from exc

    def _ensure_image(self, image: str) -> None:
        try:
            self.client.images.get(image)
            return
        except docker.errors.ImageNotFound:
            pass
        except docker.errors.DockerException as exc:
            raise _translate(exc, f"image {image}") from exc
        repository, tag = image, None
        last = image.rsplit("/", 1)[-1]
        if "@" not in image and ":" in last:
            repository, tag = image.rsplit(":", 1)
        log.info("pulling image %s", image)
        try:
            self.client.images.pull(repository, tag=tag or "latest")
        except docker.errors.DockerException as exc:
            raise InvalidRequestError(f"cannot pull image {image}: {exc}") from exc

    def _ensure_network(self) -> str:
        with self._network_lock:
            try:
                self.client.networks.get(self._network_name)
            except docker.errors.NotFound:
                self.client.networks.create(
                    self._network_name,
                    driver="bridge",
                    options={"com.docker.network.bridge.enable_icc": "false"},
                    labels={LABEL_MANAGED: "true"},
                )
            except docker.errors.DockerException as exc:
                raise _translate(exc, "network") from exc
        return self._network_name

    def _run_simple(
        self, container: Container, command: Sequence[str], user: str | None = None
    ) -> tuple[int, bytes, bytes]:
        result = container.exec_run(list(command), user=user or self._user, demux=True)
        out, err = cast("tuple[bytes | None, bytes | None]", result.output)
        return int(result.exit_code or 0), out or b"", err or b""

    # -- lifecycle -------------------------------------------------------

    def ping(self) -> None:
        try:
            self.client.ping()
        except docker.errors.DockerException as exc:
            raise BackendError(f"Docker is unreachable: {exc}") from exc

    def create(self, sandbox_id: str, spec: SandboxSpec) -> None:
        self._ensure_image(spec.image)
        labels = self._labels(sandbox_id)
        volume = self.volume_name(sandbox_id)
        try:
            self.client.volumes.create(volume, labels=labels)
            self._chown_workspace(spec.image, volume, labels)
            network_mode = self._ensure_network() if spec.network else "none"
            env = {"HOME": WORKSPACE, **spec.env}
            container = self.client.containers.create(
                spec.image,
                entrypoint=["/bin/sh", "-c", KEEPALIVE],
                command=[],
                name=self.container_name(sandbox_id),
                hostname="sandbox",
                user=self._user,
                working_dir=WORKSPACE,
                environment=env,
                labels=labels,
                mounts=[_workspace_mount(volume)],
                tmpfs={"/tmp": f"rw,nosuid,nodev,size={self._tmp_size_mb}m,mode=1777"},  # noqa: S108 - mount point inside the sandbox
                read_only=spec.read_only_rootfs,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=spec.pids_limit,
                mem_limit=f"{spec.memory_mb}m",
                memswap_limit=f"{spec.memory_mb}m",
                nano_cpus=int(spec.cpus * 1_000_000_000),
                ipc_mode="private",
                init=True,
                network_mode=network_mode,
                runtime=self._runtime,
            )
            container.start()
        except BaseException as exc:
            try:
                self.destroy(sandbox_id)
            except SandboxError:
                log.warning("cleanup after failed create of %s failed", sandbox_id, exc_info=True)
            if isinstance(exc, docker.errors.DockerException):
                raise _translate(exc, f"create sandbox from {spec.image}") from exc
            raise

    def _chown_workspace(self, image: str, volume: str, labels: dict[str, str]) -> None:
        """Hand the fresh volume to the sandbox user.

        A short-lived helper container holds only ``CAP_CHOWN``; the sandbox
        itself never runs with any capability.
        """
        helper = self.client.containers.create(
            image,
            entrypoint=["chown", f"{self._uid}:{self._gid}", WORKSPACE],
            command=[],
            user="0:0",
            labels={**labels, "io.agent-sandbox.role": "init"},
            mounts=[_workspace_mount(volume)],
            cap_drop=["ALL"],
            cap_add=["CHOWN"],
            security_opt=["no-new-privileges:true"],
            network_mode="none",
            read_only=True,
            runtime=self._runtime,
        )
        try:
            helper.start()
            status = helper.wait(timeout=60)
            if status.get("StatusCode") != 0:
                logs = helper.logs().decode(errors="replace").strip()
                raise InvalidRequestError(f"image {image} cannot prepare the workspace: {logs}")
        finally:
            helper.remove(force=True)

    def destroy(self, sandbox_id: str) -> None:
        try:
            self.client.containers.get(self.container_name(sandbox_id)).remove(force=True, v=True)
        except docker.errors.NotFound:
            pass
        except docker.errors.DockerException as exc:
            raise _translate(exc, f"destroy sandbox {sandbox_id}") from exc
        for attempt in range(10):
            try:
                self.client.volumes.get(self.volume_name(sandbox_id)).remove(force=True)
                return
            except docker.errors.NotFound:
                return
            except docker.errors.APIError as exc:
                # The daemon can report the volume as in use for a moment after removal.
                if exc.status_code == 409 and attempt < 9:
                    time.sleep(0.2)
                    continue
                raise _translate(exc, f"remove workspace of {sandbox_id}") from exc

    def list_ids(self) -> list[str]:
        filters = {"label": f"{LABEL_MANAGED}=true"}
        try:
            ids = {
                c.labels[LABEL_ID]
                for c in self.client.containers.list(all=True, filters=filters)
                if LABEL_ID in c.labels and c.labels.get("io.agent-sandbox.role") != "init"
            }
            ids.update(
                v.attrs["Labels"][LABEL_ID]
                for v in self.client.volumes.list(filters=filters)
                if LABEL_ID in (v.attrs.get("Labels") or {})
            )
        except docker.errors.DockerException as exc:
            raise _translate(exc, "list sandboxes") from exc
        return sorted(ids)

    def is_running(self, sandbox_id: str) -> bool:
        try:
            container = self.client.containers.get(self.container_name(sandbox_id))
        except docker.errors.NotFound:
            return False
        except docker.errors.DockerException as exc:
            raise _translate(exc, f"sandbox {sandbox_id}") from exc
        return bool(container.status == "running")

    # -- exec ------------------------------------------------------------

    def exec(
        self,
        sandbox_id: str,
        command: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str,
        timeout_seconds: float,
    ) -> Iterator[ExecEvent]:
        container = self._container(sandbox_id)
        if container.status != "running":
            raise InvalidRequestError(f"sandbox {sandbox_id} is not running")
        pid_file = f"{PID_DIR}/{uuid.uuid4().hex}"
        api = self.client.api
        try:
            exec_id = api.exec_create(
                container.id,
                ["/bin/sh", "-c", EXEC_WRAPPER, pid_file, *command],
                user=self._user,
                workdir=workdir,
                environment=dict(env),
                stdout=True,
                stderr=True,
                tty=False,
            )["Id"]
            stream = api.exec_start(exec_id, stream=True, demux=True)
        except docker.errors.DockerException as exc:
            raise _translate(exc, "exec") from exc

        timed_out = threading.Event()

        def kill() -> None:
            timed_out.set()
            try:
                self._run_simple(container, ["/bin/sh", "-c", KILL_SCRIPT, pid_file])
            except docker.errors.DockerException:
                log.warning("failed to kill timed-out command in %s", sandbox_id, exc_info=True)

        timer = threading.Timer(timeout_seconds, kill)
        timer.daemon = True
        timer.start()
        return self._pump(exec_id, stream, timer, timed_out)

    def _pump(
        self,
        exec_id: str,
        stream: Iterator[tuple[bytes | None, bytes | None]],
        timer: threading.Timer,
        timed_out: threading.Event,
    ) -> Iterator[ExecEvent]:
        api = self.client.api
        try:
            for stdout, stderr in stream:
                if stdout:
                    yield ExecOutput("stdout", stdout)
                if stderr:
                    yield ExecOutput("stderr", stderr)
        finally:
            timer.cancel()
            if hasattr(stream, "close"):
                stream.close()

        exit_code = -1
        for _ in range(50):
            info = api.exec_inspect(exec_id)
            if not info.get("Running") and info.get("ExitCode") is not None:
                exit_code = int(info["ExitCode"])
                break
            time.sleep(0.05)
        yield ExecExit(exit_code=exit_code, timed_out=timed_out.is_set())

    # -- files -----------------------------------------------------------

    def read_file(self, sandbox_id: str, path: str, max_bytes: int) -> bytes:
        container = self._container(sandbox_id)
        for _ in range(8):  # follow a bounded number of symlinks
            try:
                chunks, stat = container.get_archive(path)
            except docker.errors.DockerException as exc:
                raise _translate(exc, path) from exc
            mode = int(stat.get("mode", 0))
            if mode & _GO_MODE_SYMLINK and stat.get("linkTarget"):
                target = str(stat["linkTarget"])
                path = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
                _drain(chunks)
                continue
            if mode & _GO_MODE_DIR:
                _drain(chunks)
                raise InvalidRequestError(f"{path} is a directory")
            if int(stat.get("size", 0)) > max_bytes:
                _drain(chunks)
                raise PayloadTooLargeError(f"{path} is larger than {max_bytes} bytes")
            with tarfile.open(fileobj=_IterReader(chunks), mode="r|") as archive:
                for member in archive:
                    if member.isfile():
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            break
                        return extracted.read(max_bytes + 1)[:max_bytes]
            raise InvalidRequestError(f"{path} is not a regular file")
        raise InvalidRequestError(f"{path}: too many levels of symbolic links")

    def write_file(self, sandbox_id: str, path: str, data: bytes, mode: int) -> None:
        container = self._container(sandbox_id)
        parent, name = posixpath.split(path)
        code, _, err = self._run_simple(container, ["mkdir", "-p", "--", parent])
        if code != 0:
            raise InvalidRequestError(f"cannot create {parent}: {err.decode(errors='replace').strip()}")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as archive:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            info.uid, info.gid = self._uid, self._gid
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(data))
        try:
            container.put_archive(parent, buf.getvalue())
        except docker.errors.DockerException as exc:
            raise _translate(exc, path) from exc

    def list_files(self, sandbox_id: str, path: str) -> list[FileEntry]:
        container = self._container(sandbox_id)
        code, out, err = self._run_simple(container, ["/bin/sh", "-c", LIST_SCRIPT, path])
        if code == 2:
            raise NotFoundError(f"{path}: not found")
        if code == 3:
            raise InvalidRequestError(f"{path} is not a directory")
        if code != 0:
            raise BackendError(f"cannot list {path}: {err.decode(errors='replace').strip()}")
        entries = []
        for line in out.decode(errors="replace").splitlines():
            parts = line.split(" ", 3)
            if len(parts) != 4:
                continue
            raw_mode, size, mtime, name = parts
            file_type = int(raw_mode, 16) & 0o170000
            kind = {0o040000: "directory", 0o100000: "file", 0o120000: "symlink"}.get(file_type, "other")
            entries.append(
                FileEntry(
                    name=name,
                    path=posixpath.join(path, name),
                    type=kind,  # type: ignore[arg-type]
                    size=int(size),
                    modified_at=int(mtime),
                )
            )
        return sorted(entries, key=lambda e: e.name)

    # -- snapshots -------------------------------------------------------

    def export_workspace(self, sandbox_id: str, dest: BinaryIO, max_bytes: int) -> int:
        container = self._container(sandbox_id)
        try:
            chunks, _ = container.get_archive(WORKSPACE)
        except docker.errors.DockerException as exc:
            raise _translate(exc, "export workspace") from exc
        counter = _CountingWriter(dest, max_bytes)
        prefix = posixpath.basename(WORKSPACE) + "/"
        with (
            tarfile.open(fileobj=_IterReader(chunks), mode="r|") as src,
            tarfile.open(fileobj=counter, mode="w|") as out,
        ):
            for member in src:
                if not member.name.startswith(prefix):
                    continue  # the workspace directory itself
                member.name = member.name[len(prefix) :]
                if member.isfile():
                    out.addfile(member, src.extractfile(member))
                else:
                    out.addfile(member)
        return counter.count

    def import_workspace(self, sandbox_id: str, src: BinaryIO) -> None:
        container = self._container(sandbox_id)
        try:
            container.put_archive(WORKSPACE, src)
        except docker.errors.DockerException as exc:
            raise _translate(exc, "import workspace") from exc


def _workspace_mount(volume: str) -> Mount:
    # no_copy stops Docker from copying the image's mount point (and its root
    # ownership) into the volume, which would undo the chown below.
    return Mount(target=WORKSPACE, source=volume, type="volume", no_copy=True)


def _drain(chunks: Iterable[bytes]) -> None:
    for _ in chunks:
        pass
