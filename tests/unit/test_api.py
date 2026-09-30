from __future__ import annotations

import json
from dataclasses import replace

from fastapi.testclient import TestClient

from agent_sandbox.api import create_app
from agent_sandbox.config import Settings
from agent_sandbox.manager import SandboxManager
from tests.conftest import API_KEY
from tests.fakes import FakeBackend


def _create(api: TestClient, **body: object) -> dict[str, object]:
    response = api.post("/v1/sandboxes", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()
    return data


def test_sandbox_lifecycle(api: TestClient) -> None:
    sandbox = _create(api, cpus=0.5, memory_mb=256, timeout_seconds=60)
    assert sandbox["status"] == "running"
    assert sandbox["network"] is False
    sid = sandbox["id"]

    assert api.get(f"/v1/sandboxes/{sid}").json()["cpus"] == 0.5
    assert [s["id"] for s in api.get("/v1/sandboxes").json()["sandboxes"]] == [sid]
    assert api.post(f"/v1/sandboxes/{sid}/timeout", json={"timeout_seconds": 600}).status_code == 200
    assert api.delete(f"/v1/sandboxes/{sid}").status_code == 204

    missing = api.get(f"/v1/sandboxes/{sid}")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": f"sandbox {sid} not found"}}


def test_validation_errors(api: TestClient) -> None:
    assert api.post("/v1/sandboxes", json={"cpus": -1}).status_code == 422
    assert api.post("/v1/sandboxes", json={"unknown": 1}).status_code == 422
    too_big = api.post("/v1/sandboxes", json={"cpus": 64})
    assert too_big.status_code == 400
    assert too_big.json()["error"]["code"] == "invalid_request"


def test_quota_maps_to_429(api: TestClient) -> None:
    for _ in range(3):
        _create(api)
    response = api.post("/v1/sandboxes", json={})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "limit_exceeded"


def test_exec(api: TestClient) -> None:
    sid = _create(api)["id"]
    body = api.post(f"/v1/sandboxes/{sid}/exec", json={"command": "echo hi"}).json()
    assert body["stdout"] == "hi\n"
    assert body["exit_code"] == 0
    assert body["timed_out"] is False
    failed = api.post(f"/v1/sandboxes/{sid}/exec", json={"command": ["fail", "2"]}).json()
    assert failed["exit_code"] == 2


def test_exec_stream_is_ndjson(api: TestClient) -> None:
    sid = _create(api)["id"]
    with api.stream("POST", f"/v1/sandboxes/{sid}/exec/stream", json={"command": "fail 4"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.iter_lines() if line]
    assert events[0] == {"type": "stderr", "data": "boom\n"}
    assert events[-1]["type"] == "exit"
    assert events[-1]["exit_code"] == 4


def test_exec_stream_joins_split_utf8(api: TestClient) -> None:
    sid = _create(api)["id"]
    response = api.post(f"/v1/sandboxes/{sid}/exec/stream", json={"command": "utf8split"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert "".join(e["data"] for e in events if e["type"] == "stdout") == "é"


def test_exec_stream_unknown_sandbox_is_404(api: TestClient) -> None:
    assert api.post("/v1/sandboxes/sb_nope/exec/stream", json={"command": "echo"}).status_code == 404


def test_files(api: TestClient, backend: FakeBackend) -> None:
    sid = str(_create(api)["id"])
    put = api.put(
        f"/v1/sandboxes/{sid}/files",
        params={"path": "src/app.py", "mode": "755"},
        content=b"print(1)\n",
    )
    assert put.status_code == 200, put.text
    assert put.json()["path"] == "/workspace/src/app.py"
    assert backend.sandboxes[sid].files["/workspace/src/app.py"] == b"print(1)\n"

    got = api.get(f"/v1/sandboxes/{sid}/files", params={"path": "src/app.py"})
    assert got.content == b"print(1)\n"
    assert got.headers["content-type"] == "application/octet-stream"

    listing = api.get(f"/v1/sandboxes/{sid}/files/list").json()
    assert listing["path"] == "/workspace"
    assert [e["name"] for e in listing["entries"]] == ["src"]

    assert api.put(f"/v1/sandboxes/{sid}/files", params={"path": "/etc/x"}, content=b"").status_code == 400
    assert api.put(f"/v1/sandboxes/{sid}/files", params={"path": "a", "mode": "999"}, content=b"").status_code == 422
    assert api.get(f"/v1/sandboxes/{sid}/files", params={"path": "nope"}).status_code == 404


def test_upload_limit(settings: Settings, backend: FakeBackend) -> None:
    small = replace(settings, max_file_bytes=10)
    manager = SandboxManager(small, backend)
    with TestClient(create_app(small, manager=manager), headers={"X-API-Key": API_KEY}) as client:
        sid = _create(client)["id"]
        ok = client.put(f"/v1/sandboxes/{sid}/files", params={"path": "small"}, content=b"x" * 10)
        assert ok.status_code == 200
        response = client.put(f"/v1/sandboxes/{sid}/files", params={"path": "big"}, content=b"x" * 11)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"


def test_snapshot_rollback_fork(api: TestClient, backend: FakeBackend) -> None:
    sid = str(_create(api)["id"])
    api.put(f"/v1/sandboxes/{sid}/files", params={"path": "state.txt"}, content=b"good")
    snap = api.post(f"/v1/sandboxes/{sid}/snapshots", json={"name": "good"}).json()
    assert snap["name"] == "good"
    assert snap["sandbox_id"] == sid
    assert api.post(f"/v1/sandboxes/{sid}/snapshots").status_code == 201

    api.put(f"/v1/sandboxes/{sid}/files", params={"path": "state.txt"}, content=b"bad")
    rolled = api.post(f"/v1/sandboxes/{sid}/rollback", json={"snapshot_id": snap["id"]})
    assert rolled.status_code == 200
    assert rolled.json()["source_snapshot_id"] == snap["id"]
    assert backend.sandboxes[sid].files["/workspace/state.txt"] == b"good"

    forked = api.post(f"/v1/snapshots/{snap['id']}/fork", json={"timeout_seconds": 30})
    assert forked.status_code == 201
    assert backend.sandboxes[forked.json()["id"]].files["/workspace/state.txt"] == b"good"

    listed = api.get("/v1/snapshots", params={"sandbox_id": sid}).json()["snapshots"]
    assert len(listed) == 2
    assert api.get(f"/v1/snapshots/{snap['id']}").json()["id"] == snap["id"]
    assert api.delete(f"/v1/snapshots/{snap['id']}").status_code == 204
    assert api.post(f"/v1/sandboxes/{sid}/rollback", json={"snapshot_id": snap["id"]}).status_code == 404


def test_health_reports_backend_failure(api: TestClient, backend: FakeBackend) -> None:
    backend.reachable = False
    response = api.get("/healthz")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "backend_error"


def test_openapi_documents_every_route(api: TestClient) -> None:
    spec = api.get("/openapi.json").json()
    paths = spec["paths"]
    for path in (
        "/v1/sandboxes",
        "/v1/sandboxes/{sandbox_id}",
        "/v1/sandboxes/{sandbox_id}/exec",
        "/v1/sandboxes/{sandbox_id}/exec/stream",
        "/v1/sandboxes/{sandbox_id}/files",
        "/v1/sandboxes/{sandbox_id}/files/list",
        "/v1/sandboxes/{sandbox_id}/snapshots",
        "/v1/sandboxes/{sandbox_id}/rollback",
        "/v1/snapshots/{snapshot_id}/fork",
    ):
        assert path in paths
    assert {"HTTPBearer", "APIKeyHeader"} <= set(spec["components"]["securitySchemes"])
