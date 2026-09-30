"""Integration tests that run real containers. They need a working Docker daemon."""

from __future__ import annotations

import time
from typing import Any

import pytest

from agent_sandbox.backends.base import ExecExit, ExecOutput
from agent_sandbox.backends.docker import DockerBackend
from agent_sandbox.errors import InvalidRequestError, NotFoundError, PayloadTooLargeError
from agent_sandbox.manager import CreateOptions, SandboxManager
from tests.integration.conftest import NETWORK

pytestmark = pytest.mark.docker

# Prints one command line per process without needing ps, which slim images lack.
PROCESSES = "for p in /proc/[0-9]*; do tr '\\0' ' ' < $p/cmdline 2>/dev/null; echo; done"


def _inspect(backend: DockerBackend, sandbox_id: str) -> dict[str, Any]:
    attrs: dict[str, Any] = backend.client.containers.get(backend.container_name(sandbox_id)).attrs
    return attrs


def test_hardened_defaults(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    sandbox = docker_manager.create(CreateOptions(cpus=0.5, memory_mb=128, pids_limit=64))
    host = _inspect(docker_backend, sandbox.id)["HostConfig"]
    assert host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"]
    assert not host.get("CapAdd")
    assert "no-new-privileges:true" in host["SecurityOpt"]
    assert host["PidsLimit"] == 64
    assert host["Memory"] == 128 * 1024 * 1024
    assert host["MemorySwap"] == host["Memory"]
    assert host["NanoCpus"] == 500_000_000
    assert host["NetworkMode"] == "none"
    assert host["Privileged"] is False
    assert host["IpcMode"] == "private"
    assert host["Init"] is True
    assert host["Tmpfs"]["/tmp"].startswith("rw,nosuid,nodev,size=")
    assert host["Binds"] is None

    probe = docker_manager.exec(
        sandbox.id,
        "id -u; grep -E '^(CapEff|NoNewPrivs)' /proc/self/status; "
        "touch /etc/pwned 2>/dev/null && echo rootfs-writable || echo rootfs-readonly; "
        "ls /sys/class/net",
    )
    lines = probe.stdout.split()
    assert lines[0] == "1000"
    assert "0000000000000000" in lines
    assert lines[lines.index("NoNewPrivs:") + 1] == "1"
    assert "rootfs-readonly" in lines
    assert lines[-1] == "lo"


def test_writable_rootfs_is_opt_in(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    sandbox = docker_manager.create(CreateOptions(read_only_rootfs=False))
    assert _inspect(docker_backend, sandbox.id)["HostConfig"]["ReadonlyRootfs"] is False
    assert docker_manager.exec(sandbox.id, "touch /var/tmp/ok && echo yes").stdout == "yes\n"


def test_network_is_opt_in(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    sandbox = docker_manager.create(CreateOptions(network=True))
    networks = _inspect(docker_backend, sandbox.id)["NetworkSettings"]["Networks"]
    assert list(networks) == [NETWORK]
    options = docker_backend.client.networks.get(NETWORK).attrs["Options"]
    assert options["com.docker.network.bridge.enable_icc"] == "false"


def test_exec_streams_output_and_exit_code(docker_manager: SandboxManager) -> None:
    sandbox = docker_manager.create(CreateOptions(env={"GREETING": "hello"}))
    events = list(
        docker_manager.exec_stream(sandbox.id, 'echo "$GREETING $EXTRA"; echo oops >&2; exit 7', env={"EXTRA": "x"})
    )
    stdout = b"".join(e.data for e in events if isinstance(e, ExecOutput) and e.stream == "stdout")
    stderr = b"".join(e.data for e in events if isinstance(e, ExecOutput) and e.stream == "stderr")
    assert stdout == b"hello x\n"
    assert stderr == b"oops\n"
    assert events[-1] == ExecExit(exit_code=7, timed_out=False)

    argv = docker_manager.exec(sandbox.id, ["printf", "%s|", "a b", "$HOME"])
    assert argv.stdout == "a b|$HOME|"
    assert docker_manager.exec(sandbox.id, "pwd", workdir="/tmp").stdout == "/tmp\n"


def test_exec_timeout_kills_the_process_group(docker_manager: SandboxManager) -> None:
    sandbox = docker_manager.create(CreateOptions())
    started = time.monotonic()
    result = docker_manager.exec(sandbox.id, "sleep 300 & sleep 300; echo never", timeout_seconds=1)
    assert result.timed_out
    assert result.exit_code != 0
    assert "never" not in result.stdout
    assert time.monotonic() - started < 15
    leftover = docker_manager.exec(sandbox.id, f"{PROCESSES} | grep -c '^sleep 300 $' || true")
    assert leftover.stdout.strip() == "0"


def test_pids_limit_stops_fork_bombs(docker_manager: SandboxManager) -> None:
    sandbox = docker_manager.create(CreateOptions(pids_limit=32))
    result = docker_manager.exec(sandbox.id, "for i in $(seq 1 100); do sleep 2 & done; wait", timeout_seconds=20)
    assert "fork" in result.stderr.lower() or "resource temporarily unavailable" in result.stderr.lower()


def test_files(docker_manager: SandboxManager) -> None:
    sandbox = docker_manager.create(CreateOptions())
    blob = bytes(range(256)) * 64
    assert docker_manager.write_file(sandbox.id, "data/blob.bin", blob) == "/workspace/data/blob.bin"
    docker_manager.write_file(sandbox.id, "run.sh", b"#!/bin/sh\necho ran\n", mode=0o755)
    assert docker_manager.read_file(sandbox.id, "data/blob.bin") == blob
    assert docker_manager.exec(sandbox.id, "./run.sh").stdout == "ran\n"
    assert docker_manager.exec(sandbox.id, "stat -c %u data/blob.bin").stdout == "1000\n"

    docker_manager.exec(sandbox.id, "ln -s data/blob.bin link && touch .hidden")
    assert docker_manager.read_file(sandbox.id, "link") == blob
    entries = {e.name: e for e in docker_manager.list_files(sandbox.id)}
    assert set(entries) == {".hidden", "data", "link", "run.sh"}
    assert entries["data"].type == "directory"
    assert entries["link"].type == "symlink"
    assert entries["run.sh"].type == "file"
    assert entries["run.sh"].size == 19

    assert docker_manager.read_file(sandbox.id, "/etc/hostname") == b"sandbox\n"
    with pytest.raises(NotFoundError):
        docker_manager.read_file(sandbox.id, "missing.txt")
    with pytest.raises(InvalidRequestError):
        docker_manager.read_file(sandbox.id, "data")
    with pytest.raises(NotFoundError):
        docker_manager.list_files(sandbox.id, "nope")
    with pytest.raises(InvalidRequestError):
        docker_manager.list_files(sandbox.id, "run.sh")


def test_read_file_limit(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    sandbox = docker_manager.create(CreateOptions())
    docker_manager.write_file(sandbox.id, "big", b"x" * 2048)
    with pytest.raises(PayloadTooLargeError):
        docker_backend.read_file(sandbox.id, "/workspace/big", max_bytes=1024)


def test_snapshot_rollback_and_fork(docker_manager: SandboxManager) -> None:
    sandbox = docker_manager.create(CreateOptions())
    docker_manager.exec(sandbox.id, "mkdir -p app/lib && echo v1 > app/lib/core.txt && chmod 600 app/lib/core.txt")
    snap = docker_manager.snapshot(sandbox.id, name="v1")
    assert snap.size_bytes > 0

    docker_manager.exec(sandbox.id, "rm -rf app && echo junk > junk.txt && (sleep 300 &) && echo tmp > /tmp/t")
    docker_manager.rollback(sandbox.id, snap.id)
    state = docker_manager.exec(
        sandbox.id,
        "find . | sort; stat -c %a app/lib/core.txt; cat app/lib/core.txt; ls /tmp; "
        f"{PROCESSES} | grep '^sleep 300 $' || true",
    )
    assert state.stdout.split() == [".", "./app", "./app/lib", "./app/lib/core.txt", "600", "v1"]

    fork = docker_manager.fork(snap.id)
    docker_manager.exec(fork.id, "echo v2 > app/lib/core.txt")
    assert docker_manager.read_file(fork.id, "app/lib/core.txt") == b"v2\n"
    assert docker_manager.read_file(sandbox.id, "app/lib/core.txt") == b"v1\n"


def test_destroy_removes_container_and_volume(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    sandbox = docker_manager.create(CreateOptions())
    assert sandbox.id in docker_backend.list_ids()
    docker_manager.destroy(sandbox.id)
    assert sandbox.id not in docker_backend.list_ids()
    assert not docker_backend.client.volumes.list(filters={"name": docker_backend.volume_name(sandbox.id)})
    docker_backend.destroy(sandbox.id)  # idempotent


def test_ttl_reaper(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    sandbox = docker_manager.create(CreateOptions(timeout_seconds=1))
    time.sleep(1.2)
    assert docker_manager.reap_expired() == [sandbox.id]
    assert not docker_backend.is_running(sandbox.id)


def test_restart_removes_orphans(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    kept = docker_manager.create(CreateOptions())
    orphan = docker_manager.create(CreateOptions())
    (docker_manager.settings.data_dir / "sandboxes" / f"{orphan.id}.json").unlink()

    restarted = SandboxManager(docker_manager.settings, docker_backend)
    restarted.start()
    assert [r.id for r in restarted.list_sandboxes()] == [kept.id]
    assert orphan.id not in docker_backend.list_ids()
    docker_manager.reconcile()


def test_unknown_image_is_a_client_error(docker_manager: SandboxManager, docker_backend: DockerBackend) -> None:
    with pytest.raises(InvalidRequestError):
        docker_manager.create(CreateOptions(image="agent-sandbox-test/does-not-exist:never"))
    assert docker_backend.list_ids() == [r.id for r in docker_manager.list_sandboxes()]
