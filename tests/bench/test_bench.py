"""Benchmarks for the server's in-process hot paths.

Each exec request goes through path normalization, the manager's output
collector, and the FastAPI route. These benchmarks run against the in-memory
backend, so they measure this project's code, not Docker.

Run them with ``make bench``. CI fails when a mean gets more than 2x slower than
the baseline in ``benchmarks/``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_benchmark.fixture import BenchmarkFixture

from agent_sandbox.api import create_app
from agent_sandbox.backends.base import ExecEvent, ExecExit, ExecOutput
from agent_sandbox.config import Settings
from agent_sandbox.manager import CreateOptions, SandboxManager, normalize_path, require_in_workspace
from tests.conftest import API_KEY
from tests.fakes import FakeBackend

CHUNK = b"x" * 4096
CHUNKS = 2048  # 8 MiB of output, just under the default 10 MiB exec cap


class ChattyBackend(FakeBackend):
    """A backend whose commands print many chunks, like a verbose build."""

    def exec(
        self,
        sandbox_id: str,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str,
        timeout_seconds: float,
    ) -> Iterator[ExecEvent]:
        self._box(sandbox_id)
        return self._chunks()

    @staticmethod
    def _chunks() -> Iterator[ExecEvent]:
        for i in range(CHUNKS):
            yield ExecOutput("stderr" if i % 8 == 0 else "stdout", CHUNK)
        yield ExecExit(0, False)


@pytest.fixture
def chatty(tmp_path: Path) -> tuple[SandboxManager, str]:
    settings = Settings(api_keys=(API_KEY,), data_dir=tmp_path / "data").validate()
    manager = SandboxManager(settings, ChattyBackend())
    manager.start()
    return manager, manager.create(CreateOptions()).id


def test_bench_normalize_paths(benchmark: BenchmarkFixture) -> None:
    paths = [f"src/pkg{i}/../mod{i}.py" for i in range(200)] + [f"/workspace/a/{i}//b/./c" for i in range(200)]

    def run() -> None:
        for path in paths:
            require_in_workspace(normalize_path(path))

    benchmark(run)


def test_bench_exec_collects_output(benchmark: BenchmarkFixture, chatty: tuple[SandboxManager, str]) -> None:
    manager, sandbox_id = chatty
    result = benchmark(manager.exec, sandbox_id, "make")
    assert len(result.stdout) + len(result.stderr) == CHUNKS * len(CHUNK)


def test_bench_exec_route(benchmark: BenchmarkFixture, tmp_path: Path) -> None:
    settings = Settings(api_keys=(API_KEY,), data_dir=tmp_path / "data").validate()
    manager = SandboxManager(settings, FakeBackend())
    manager.start()
    with TestClient(create_app(settings, manager=manager), headers={"Authorization": f"Bearer {API_KEY}"}) as client:
        sandbox_id = client.post("/v1/sandboxes", json={}).json()["id"]

        def run() -> int:
            response = client.post(f"/v1/sandboxes/{sandbox_id}/exec", json={"command": "echo hi"})
            return response.status_code

        assert benchmark(run) == 200
