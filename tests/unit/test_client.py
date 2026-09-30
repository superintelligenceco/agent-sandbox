from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_sandbox.client import SandboxAPIError, SandboxClient, SnapshotInfo
from tests.conftest import API_KEY


@pytest.fixture
def client(api: TestClient) -> SandboxClient:
    return SandboxClient(api_key=API_KEY, http_client=cast("httpx.Client", api))


def test_full_flow(client: SandboxClient) -> None:
    assert client.health()["status"] == "ok"
    with client.create(cpus=0.5, env={"A": "1"}) as sandbox:
        assert sandbox.status == "running"
        assert repr(sandbox).startswith("Sandbox(id='sb_")
        assert sandbox.exec("echo hi").stdout == "hi\n"
        assert sandbox.exec(["echo", "argv"]).ok
        assert not sandbox.exec("fail 1").ok

        events = list(sandbox.exec_stream("echo streamed"))
        assert events[0].type == "stdout"
        assert events[0].data == "streamed\n"
        assert events[-1].exit_code == 0

        info = sandbox.write_file("notes.md", "draft")
        assert info.path == "/workspace/notes.md"
        assert sandbox.read_text("notes.md") == "draft"
        assert [f.name for f in sandbox.list_files()] == ["notes.md"]

        snap = sandbox.snapshot("draft")
        assert isinstance(snap, SnapshotInfo)
        sandbox.write_file("notes.md", "oops")
        sandbox.rollback(snap)
        assert sandbox.read_text("notes.md") == "draft"
        assert sandbox.set_timeout(120).refresh().status == "running"

        with client.fork(snap.id) as fork:
            assert fork.read_text("notes.md") == "draft"
            assert {s.id for s in client.list_sandboxes()} == {sandbox.id, fork.id}
        assert client.get_snapshot(snap.id) == snap
        assert client.list_snapshots(sandbox.id) == [snap]
        client.delete_snapshot(snap.id)
    assert client.list_sandboxes() == []


def test_errors_are_typed(client: SandboxClient) -> None:
    with pytest.raises(SandboxAPIError) as info:
        client.get("sb_missing")
    assert info.value.status_code == 404
    assert info.value.code == "not_found"

    with pytest.raises(SandboxAPIError) as info:
        client.create(cpus=-1)
    assert info.value.status_code == 422
    assert info.value.code == "validation_error"


def test_stream_errors_are_typed(client: SandboxClient) -> None:
    sandbox = client.create()
    sandbox.destroy()
    with pytest.raises(SandboxAPIError) as info:
        list(sandbox.exec_stream("echo x"))
    assert info.value.status_code == 404


def test_context_manager_tolerates_already_destroyed(client: SandboxClient) -> None:
    with client.create() as sandbox:
        sandbox.destroy()


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_SANDBOX_URL", "http://sandbox.test:9000")
    monkeypatch.setenv("AGENT_SANDBOX_API_KEY", "env-key")
    with SandboxClient() as client:
        assert str(client._http.base_url) == "http://sandbox.test:9000"
        assert client._http.headers["authorization"] == "Bearer env-key"
