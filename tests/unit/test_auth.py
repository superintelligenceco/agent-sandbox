from __future__ import annotations

from fastapi.testclient import TestClient

from agent_sandbox.api import create_app
from agent_sandbox.auth import key_is_valid
from agent_sandbox.config import Settings
from agent_sandbox.manager import SandboxManager
from tests.conftest import API_KEY


def test_key_is_valid() -> None:
    keys = ("a" * 16, "b" * 16)
    assert key_is_valid("b" * 16, keys)
    assert not key_is_valid("c" * 16, keys)
    assert not key_is_valid("", keys)


def test_rejects_missing_and_wrong_keys(api: TestClient) -> None:
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer wrong-key-000000000"}):
        response = api.get("/v1/sandboxes", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"


def test_accepts_bearer_and_x_api_key(api: TestClient) -> None:
    assert api.get("/v1/sandboxes").status_code == 200
    response = api.get("/v1/sandboxes", headers={"Authorization": "", "X-API-Key": API_KEY})
    assert response.status_code == 200


def test_health_needs_no_key(api: TestClient) -> None:
    response = api.get("/healthz", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.json()["backend"] == "fake"


def test_insecure_mode_skips_auth(settings: Settings, manager: SandboxManager) -> None:
    open_settings = Settings(insecure_no_auth=True, data_dir=settings.data_dir)
    with TestClient(create_app(open_settings, manager=manager)) as client:
        assert client.get("/v1/sandboxes").status_code == 200
