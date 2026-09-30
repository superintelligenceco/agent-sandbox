"""End-to-end tests: HTTP client -> FastAPI app -> Docker."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_sandbox.api import create_app
from agent_sandbox.client import SandboxClient
from agent_sandbox.manager import SandboxManager

pytestmark = pytest.mark.docker


@pytest.fixture
def client(docker_manager: SandboxManager) -> Iterator[SandboxClient]:
    app = create_app(docker_manager.settings, manager=docker_manager)
    with TestClient(app) as http:
        yield SandboxClient(http_client=cast("httpx.Client", http))


def test_agent_workflow(client: SandboxClient) -> None:
    assert client.health()["backend"] == "docker"
    with client.create() as sandbox:
        sandbox.write_file("counter.txt", "1")
        good = sandbox.snapshot("counter=1")

        sandbox.exec("rm -rf /workspace/*")
        assert sandbox.exec("cat counter.txt").exit_code != 0

        sandbox.rollback(good)
        assert sandbox.read_text("counter.txt") == "1"

        events = list(sandbox.exec_stream("for i in 1 2 3; do echo $i; done"))
        assert "".join(e.data for e in events if e.type == "stdout") == "1\n2\n3\n"
        assert events[-1].type == "exit"
        assert events[-1].exit_code == 0

        with client.fork(good) as fork:
            assert fork.read_text("counter.txt") == "1"
        client.delete_snapshot(good.id)
    assert client.list_sandboxes() == []
