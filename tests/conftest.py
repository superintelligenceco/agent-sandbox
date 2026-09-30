from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_sandbox.api import create_app
from agent_sandbox.config import Settings
from agent_sandbox.manager import SandboxManager
from tests.fakes import FakeBackend

API_KEY = "test-key-0123456789abcdef"


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(api_keys=(API_KEY,), data_dir=tmp_path / "data", max_sandboxes=3).validate()


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def manager(settings: Settings, backend: FakeBackend, clock: FakeClock) -> SandboxManager:
    mgr = SandboxManager(settings, backend, clock=clock)
    mgr.start()
    return mgr


@pytest.fixture
def api(settings: Settings, manager: SandboxManager) -> Iterator[TestClient]:
    app = create_app(settings, manager=manager)
    with TestClient(app, headers={"Authorization": f"Bearer {API_KEY}"}) as client:
        yield client
