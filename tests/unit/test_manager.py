from __future__ import annotations

from dataclasses import replace

import pytest

from agent_sandbox.config import Settings
from agent_sandbox.errors import (
    BackendError,
    ForbiddenError,
    InvalidRequestError,
    LimitExceededError,
    NotFoundError,
    PayloadTooLargeError,
)
from agent_sandbox.manager import CreateOptions, SandboxManager
from tests.conftest import FakeClock
from tests.fakes import FakeBackend


def test_create_applies_defaults(manager: SandboxManager, settings: Settings, clock: FakeClock) -> None:
    record = manager.create(CreateOptions())
    assert record.id.startswith("sb_")
    assert record.spec.image == settings.default_image
    assert record.spec.cpus == settings.default_cpus
    assert record.spec.network is False
    assert record.spec.read_only_rootfs is True
    assert record.expires_at == clock.now + settings.default_timeout_seconds
    assert manager.status(record.id) == "running"


@pytest.mark.parametrize(
    ("opts", "error"),
    [
        (CreateOptions(cpus=100), InvalidRequestError),
        (CreateOptions(memory_mb=8), InvalidRequestError),
        (CreateOptions(memory_mb=10**6), InvalidRequestError),
        (CreateOptions(pids_limit=2), InvalidRequestError),
        (CreateOptions(timeout_seconds=0), InvalidRequestError),
        (CreateOptions(env={"A=B": "c"}), InvalidRequestError),
    ],
)
def test_create_validates_limits(manager: SandboxManager, opts: CreateOptions, error: type[Exception]) -> None:
    with pytest.raises(error):
        manager.create(opts)


def test_image_allowlist(settings: Settings, backend: FakeBackend) -> None:
    mgr = SandboxManager(replace(settings, allowed_images=("python:*", "docker.io/library/*")), backend)
    mgr.start()
    assert mgr.create(CreateOptions(image="python:3.12-slim")).spec.image == "python:3.12-slim"
    with pytest.raises(ForbiddenError):
        mgr.create(CreateOptions(image="evil/miner:latest"))


def test_network_can_be_disallowed(settings: Settings, backend: FakeBackend) -> None:
    mgr = SandboxManager(replace(settings, allow_network=False), backend)
    mgr.start()
    with pytest.raises(ForbiddenError):
        mgr.create(CreateOptions(network=True))


def test_quota(manager: SandboxManager) -> None:
    for _ in range(3):
        manager.create(CreateOptions())
    with pytest.raises(LimitExceededError):
        manager.create(CreateOptions())


def test_failed_create_releases_slot(manager: SandboxManager, backend: FakeBackend) -> None:
    backend.fail_create = True
    for _ in range(5):
        with pytest.raises(BackendError):
            manager.create(CreateOptions())
    backend.fail_create = False
    assert manager.create(CreateOptions())


def test_destroy(manager: SandboxManager, backend: FakeBackend) -> None:
    record = manager.create(CreateOptions())
    manager.destroy(record.id)
    assert record.id not in backend.sandboxes
    with pytest.raises(NotFoundError):
        manager.get(record.id)
    with pytest.raises(NotFoundError):
        manager.destroy(record.id)


def test_reaper_destroys_only_expired(manager: SandboxManager, clock: FakeClock) -> None:
    short = manager.create(CreateOptions(timeout_seconds=10))
    long = manager.create(CreateOptions(timeout_seconds=1000))
    clock.advance(11)
    assert manager.reap_expired() == [short.id]
    assert [r.id for r in manager.list_sandboxes()] == [long.id]


def test_set_timeout_extends_life(manager: SandboxManager, clock: FakeClock) -> None:
    record = manager.create(CreateOptions(timeout_seconds=10))
    clock.advance(9)
    manager.set_timeout(record.id, 100)
    clock.advance(50)
    assert manager.reap_expired() == []


def test_exec_wraps_string_commands(manager: SandboxManager, backend: FakeBackend) -> None:
    record = manager.create(CreateOptions())
    result = manager.exec(record.id, "echo hello", env={"X": "1"}, workdir="src")
    assert result.stdout == "hello\n"
    assert result.exit_code == 0
    call = backend.exec_calls[-1]
    assert call.command == ["/bin/sh", "-c", "echo hello"]
    assert call.workdir == "/workspace/src"
    assert call.env == {"X": "1"}
    assert call.timeout_seconds == manager.settings.default_exec_timeout_seconds


def test_exec_argv_and_errors(manager: SandboxManager, backend: FakeBackend) -> None:
    record = manager.create(CreateOptions())
    result = manager.exec(record.id, ["fail", "3"])
    assert (result.exit_code, result.stderr) == (3, "boom\n")
    assert backend.exec_calls[-1].command == ["fail", "3"]
    assert manager.exec(record.id, "hang").timed_out
    bad: str | list[str]
    for bad in ("", "   ", []):
        with pytest.raises(InvalidRequestError):
            manager.exec(record.id, bad)
    with pytest.raises(InvalidRequestError):
        manager.exec(record.id, "echo x", timeout_seconds=10**9)
    with pytest.raises(NotFoundError):
        manager.exec("sb_missing", "echo x")


def test_exec_truncates_output(settings: Settings, backend: FakeBackend) -> None:
    mgr = SandboxManager(replace(settings, max_exec_output_bytes=100), backend)
    mgr.start()
    record = mgr.create(CreateOptions())
    result = mgr.exec(record.id, "bytes 80")
    assert result.truncated
    assert len(result.stdout) + len(result.stderr) == 100


def test_files_round_trip(manager: SandboxManager) -> None:
    record = manager.create(CreateOptions())
    assert manager.write_file(record.id, "pkg/mod.py", b"x = 1\n") == "/workspace/pkg/mod.py"
    assert manager.read_file(record.id, "/workspace/pkg/mod.py") == b"x = 1\n"
    assert [e.name for e in manager.list_files(record.id)] == ["pkg"]
    with pytest.raises(InvalidRequestError):
        manager.write_file(record.id, "/etc/passwd", b"")
    with pytest.raises(InvalidRequestError):
        manager.write_file(record.id, "a.txt", b"", mode=0o7777)


def test_write_file_size_limit(settings: Settings, backend: FakeBackend) -> None:
    mgr = SandboxManager(replace(settings, max_file_bytes=4), backend)
    mgr.start()
    record = mgr.create(CreateOptions())
    with pytest.raises(PayloadTooLargeError):
        mgr.write_file(record.id, "a.txt", b"12345")


def test_snapshot_rollback_fork(manager: SandboxManager, backend: FakeBackend) -> None:
    record = manager.create(CreateOptions(env={"MODE": "test"}))
    manager.write_file(record.id, "app.py", b"v1")
    snap = manager.snapshot(record.id, name="v1")
    assert snap.size_bytes > 0
    assert manager.list_snapshots(record.id) == [snap]

    manager.write_file(record.id, "app.py", b"broken")
    manager.write_file(record.id, "junk.txt", b"junk")
    manager.rollback(record.id, snap.id)
    assert backend.sandboxes[record.id].files == {"/workspace/app.py": b"v1"}
    assert manager.get(record.id).source_snapshot_id == snap.id

    fork = manager.fork(snap.id, cpus=0.5)
    assert fork.id != record.id
    assert fork.spec.cpus == 0.5
    assert fork.spec.env == {"MODE": "test"}
    assert backend.sandboxes[fork.id].files == {"/workspace/app.py": b"v1"}


def test_snapshots_outlive_their_sandbox(manager: SandboxManager) -> None:
    record = manager.create(CreateOptions())
    snap = manager.snapshot(record.id)
    manager.destroy(record.id)
    assert manager.get_snapshot(snap.id) == snap
    manager.delete_snapshot(snap.id)
    with pytest.raises(NotFoundError):
        manager.get_snapshot(snap.id)
    with pytest.raises(NotFoundError):
        manager.get_snapshot("../sandboxes/x")


def test_failed_fork_cleans_up(manager: SandboxManager, backend: FakeBackend) -> None:
    record = manager.create(CreateOptions())
    snap = manager.snapshot(record.id)
    backend.fail_import = True
    with pytest.raises(BackendError):
        manager.fork(snap.id)
    assert list(backend.sandboxes) == [record.id]
    assert len(manager.list_sandboxes()) == 1


def test_restart_reconciles_state(settings: Settings, backend: FakeBackend, manager: SandboxManager) -> None:
    kept = manager.create(CreateOptions())
    stopped = manager.create(CreateOptions())
    backend.sandboxes[stopped.id].running = False
    backend.create("sb_orphan", kept.spec)

    restarted = SandboxManager(settings, backend)
    restarted.start()
    assert [r.id for r in restarted.list_sandboxes()] == [kept.id]
    assert "sb_orphan" not in backend.sandboxes
    assert restarted.get(kept.id).expires_at == kept.expires_at
