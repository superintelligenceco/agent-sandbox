from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_sandbox.backends.docker import LABEL_MANAGED, DockerBackend
from agent_sandbox.config import Settings
from agent_sandbox.manager import SandboxManager

IMAGE = os.environ.get("AGENT_SANDBOX_TEST_IMAGE", "alpine:3.20")
NETWORK = "agent-sandbox-test-net"


def _docker_client() -> Any:
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception:
        return None
    return client


@pytest.fixture(scope="session")
def docker_client() -> Iterator[Any]:
    client = _docker_client()
    if client is None:
        pytest.skip("Docker is not available")
    yield client
    _cleanup(client)


def _cleanup(client: Any) -> None:
    """Remove everything the tests created, even after failures."""
    filters = {"label": f"{LABEL_MANAGED}=true"}
    for container in client.containers.list(all=True, filters=filters):
        container.remove(force=True, v=True)
    for volume in client.volumes.list(filters=filters):
        volume.remove(force=True)
    for network in client.networks.list(names=[NETWORK]):
        network.remove()


@pytest.fixture
def docker_backend(docker_client: Any) -> DockerBackend:
    return DockerBackend(docker_client, network_name=NETWORK)


@pytest.fixture
def docker_settings(tmp_path: Path) -> Settings:
    return Settings(
        insecure_no_auth=True,
        data_dir=tmp_path / "data",
        default_image=IMAGE,
        default_memory_mb=128,
        default_exec_timeout_seconds=30,
    ).validate()


@pytest.fixture
def docker_manager(docker_settings: Settings, docker_backend: DockerBackend) -> Iterator[SandboxManager]:
    manager = SandboxManager(docker_settings, docker_backend)
    manager.start()
    yield manager
    for record in manager.list_sandboxes():
        manager.destroy(record.id)
